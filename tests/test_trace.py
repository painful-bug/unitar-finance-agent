import asyncio
import json
import threading
from datetime import date

import pytest
from mcp import Client

from finance_agent.agent import AssistantTurn, ToolCall, run_agent
from finance_agent.context import ContextManager
from finance_agent.finance import FinanceData, load_csv
from finance_agent.models import Session
from finance_agent.server import SessionStore, build_server
from finance_agent.threads import ChatStore


def session():
    return Session("test", FinanceData(load_csv("date,kind,category,amount\n2026-08-01,income,salary,1000"), date(2026, 8, 15)), date(2026, 8, 15))


class Provider:
    model = "test-model"

    def __init__(self, turns=None):
        self.turns = iter(turns or [AssistantTurn(content="Done")])

    def chat(self, messages, tools=None, response_model=None):
        return next(self.turns)


class GatedProvider(Provider):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def chat(self, messages, tools=None, response_model=None):
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("Test provider was not released")
        return AssistantTurn(content="Done")


@pytest.mark.parametrize("arguments,tool", [('{"month":"2026-08"}', "calculate_savings_rate"), ("broken-json", "lookup_transactions"), ("[]", "lookup_transactions"), ("{}", "unknown")])
def test_capture_multiple_tools_and_exact_raw_arguments(arguments, tool):
    events = []
    provider = Provider([AssistantTurn(tool_calls=[ToolCall(id="one", name=tool, arguments=arguments), ToolCall(id="two", name="calculate_savings_rate", arguments='{"month":"2026-08"}')]), AssistantTurn(content="Done")])
    result = run_agent(session(), "Check savings", provider, event_callback=events.append)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert all(event.timestamp.utcoffset().total_seconds() == 0 for event in events)
    assert all(event.duration_ms is None or event.duration_ms >= 0 for event in events)
    assert events[0].stage == "prompt" and events[-1].stage == "outcome"
    tools = [event for event in events if event.stage == "tool" and event.state != "started"]
    assert len(tools) == 2 and tools[0].tool_call_id == "one"
    assert tools[0].payload["raw_arguments"] == arguments
    assert tools[0].state == ("completed" if arguments.startswith('{"month"') else "failed")
    assert result.status == "ok" and len(result.trace) == 2


def test_provider_error_empty_response_and_step_limit_have_terminal_events():
    for provider, limit, status in [(Provider([AssistantTurn(content="")]), 1, "error"), (Provider([AssistantTurn(tool_calls=[ToolCall(id="one", name="unknown", arguments="{}")])]), 1, "max_steps"), (Provider([]), 0, "max_steps")]:
        events = []
        result = run_agent(session(), "Check", provider, max_steps=limit, event_callback=events.append)
        assert result.status == status
        assert events[-1].state == "failed" and events[-1].payload["status"] == status


@pytest.mark.parametrize("failure", [None, "jev", "both"])
def test_context_compaction_fallback_and_failure_are_captured(failure):
    current = session()
    current.messages = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "tool_calls": [{"id": "old", "function": {"name": "lookup_transactions", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "old", "content": "Long old result " * 200},
    ]
    class Jev:
        def noul_scores(self, state, questions):
            if failure:
                raise RuntimeError("Jev unavailable")
            return {name: 0.0 for name in questions}
    class Responses:
        def chat(self, messages, tools=None, response_model=None):
            if failure == "both":
                raise RuntimeError("Model offline")
            return AssistantTurn(content="Visible summary or answer")
    events = []
    original = list(current.messages)
    result = run_agent(current, "Newest question", Responses(), ContextManager(Jev(), trigger_tokens=1, preserve_recent=1), event_callback=events.append)
    assert current.messages[:3] == original
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert any(event.operation_id.endswith("-jev") for event in events)
    if failure:
        assert any(event.state == "warning" and event.payload.get("fallback_reason") == "Jev unavailable" for event in events)
        assert any(event.operation_id.endswith("summary-model") for event in events)
    assert result.status == ("context_error" if failure == "both" else "ok")
    assert events[-1].payload["status"] == result.status


def test_provider_setup_and_request_failure_have_saved_outcomes(tmp_path, monkeypatch):
    async def scenario():
        import finance_agent.server as server_module
        def unavailable():
            raise RuntimeError("Missing provider configuration")
        monkeypatch.setattr(server_module, "GroqProvider", unavailable)
        store = SessionStore(chat_store=ChatStore(tmp_path))
        created = store.create()
        result = await store.ask(created.session_id, "Hello")
        assert result.status == "error"
        saved = store.chat_store.load(created.session_id).turns[0]
        assert [event.stage for event in saved.execution_trace] == ["prompt", "outcome"]
        class Broken:
            def chat(self, *args, **kwargs):
                raise RuntimeError("Model offline")
        store.provider = Broken()
        assert (await store.ask(created.session_id, "Again")).status == "error"
        events = store.chat_store.load(created.session_id).turns[1].execution_trace
        assert any(event.stage == "model" and event.state == "failed" for event in events)
    asyncio.run(scenario())


def test_final_save_is_atomic_with_outcome_and_preserves_partial_trace(tmp_path, monkeypatch):
    async def scenario():
        store = SessionStore(provider=Provider(), chat_store=ChatStore(tmp_path))
        created = store.create()
        save = store.chat_store.save
        def fail_final(record):
            if record.turns[-1].state == "complete":
                raise OSError("final write failed")
            save(record)
        monkeypatch.setattr(store.chat_store, "save", fail_final)
        with pytest.raises(OSError, match="final write failed"):
            await store.ask(created.session_id, "Check")
        saved = store.chat_store.load(created.session_id)
        assert saved.turns[0].state == "pending" and saved.turns[0].result is None
        assert all(event.stage != "outcome" for event in saved.turns[0].execution_trace)
        assert store.sessions[created.session_id].messages == []
    asyncio.run(scenario())


def test_live_snapshot_disconnect_and_restart_preserve_trace(tmp_path):
    async def scenario():
        provider = GatedProvider()
        store = SessionStore(provider=provider, chat_store=ChatStore(tmp_path))
        created = store.create()
        published = []

        async def progress(envelope):
            saved = store.chat_store.load(created.session_id)
            assert saved.turns[0].execution_trace[-1].sequence >= envelope["event"]["sequence"]
            published.append(envelope)

        request = asyncio.create_task(store.ask(created.session_id, "Check", on_progress=progress))
        try:
            assert await asyncio.to_thread(provider.started.wait, 3)
            running = await asyncio.wait_for(store.get_chat_thread(created.session_id), 1)
            assert running.turns[0].state == "pending"
            assert running.turns[0].execution_trace[-1].stage == "model"
            assert running.turns[0].execution_trace[-1].state == "started"
            running.turns[0].execution_trace.clear()
            assert (await store.get_chat_thread(created.session_id)).turns[0].execution_trace
            with pytest.raises(ValueError, match="running"):
                store.close(created.session_id)
            with pytest.raises(ValueError, match="running"):
                await store.ask(created.session_id, "Duplicate")
            execution = store.running[created.session_id]
            request.cancel()
            await asyncio.gather(request, return_exceptions=True)
            assert not execution.cancelled()
            provider.release.set()
            assert (await asyncio.wait_for(asyncio.shield(execution), 3)).status == "ok"
            restored = await SessionStore(chat_store=ChatStore(tmp_path)).get_chat_thread(created.session_id)
            assert restored.turns[0].execution_trace[-1].stage == "outcome"
            assert restored.turns[0].result.answer == "Done"
            assert published
        finally:
            provider.release.set()
            await asyncio.gather(request, return_exceptions=True)
    asyncio.run(scenario())


def test_failed_trace_save_stops_provider_and_keeps_last_durable_event(tmp_path, monkeypatch):
    async def scenario():
        provider = GatedProvider()
        store = SessionStore(provider=provider, chat_store=ChatStore(tmp_path))
        created = store.create()
        save = store.chat_store.save
        published = []

        def fail_model(record):
            if record.turns[-1].execution_trace and record.turns[-1].execution_trace[-1].stage == "model":
                raise OSError("disk full")
            save(record)

        monkeypatch.setattr(store.chat_store, "save", fail_model)
        async def progress(envelope):
            published.append(envelope)
        with pytest.raises(OSError, match="disk full"):
            await asyncio.wait_for(store.ask(created.session_id, "Check", on_progress=progress), 3)
        assert not provider.started.is_set()
        saved = store.chat_store.load(created.session_id)
        assert saved.turns[0].execution_trace[-1].stage == "context"
        assert all(envelope["event"]["stage"] != "model" for envelope in published)
        assert (await store.get_chat_thread(created.session_id)).turns[0].state == "interrupted"
    asyncio.run(scenario())


def test_notification_failure_does_not_fail_execution(tmp_path):
    async def scenario():
        store = SessionStore(provider=Provider(), chat_store=ChatStore(tmp_path))
        async def offline(_):
            raise RuntimeError("disconnected")
        created = store.create()
        assert (await store.ask(created.session_id, "Check", on_progress=offline)).status == "ok"
        assert store.chat_store.load(created.session_id).turns[0].state == "complete"
    asyncio.run(scenario())


def test_mcp_progress_arrives_before_final_and_matches_saved_events(tmp_path):
    async def scenario():
        provider = GatedProvider()
        store = SessionStore(provider=provider, chat_store=ChatStore(tmp_path))
        async with Client(build_server(store)) as client:
            created = await client.call_tool("create_finance_session", {})
            thread_id = created.structured_content["session_id"]
            events = []
            first_model = asyncio.Event()
            async def progress(progress, total, message):
                envelope = json.loads(message)
                events.append(envelope["event"])
                if envelope["event"]["stage"] == "model":
                    first_model.set()
            request = asyncio.create_task(client.call_tool("ask_finance_agent", {"session_id": thread_id, "question": "Check"}, progress_callback=progress))
            try:
                await asyncio.wait_for(first_model.wait(), 3)
                assert not request.done()
                provider.release.set()
                answered = await asyncio.wait_for(request, 3)
                assert answered.structured_content["status"] == "ok"
                saved = await store.get_chat_thread(thread_id)
                assert events == [event.model_dump(mode="json") for event in saved.turns[0].execution_trace]
            finally:
                provider.release.set()
                await asyncio.gather(request, return_exceptions=True)
    asyncio.run(scenario())


def test_pending_legacy_and_partial_records_load_without_migration(tmp_path):
    async def scenario():
        store = SessionStore(provider=Provider(), chat_store=ChatStore(tmp_path))
        created = store.create()
        await store.ask(created.session_id, "Check")
        path = tmp_path / f"{created.session_id}.json"
        record = json.loads(path.read_text())
        turn = record["turns"][0]
        turn["state"] = "pending"
        turn["result"] = None
        path.write_text(json.dumps(record))
        recovered = await SessionStore(chat_store=ChatStore(tmp_path)).get_chat_thread(created.session_id)
        assert recovered.turns[0].state == "interrupted" and recovered.turns[0].execution_trace
        turn.pop("execution_trace")
        turn.pop("execution_trace_version")
        path.write_text(json.dumps(record))
        legacy = await SessionStore(chat_store=ChatStore(tmp_path)).get_chat_thread(created.session_id)
        assert legacy.turns[0].execution_trace == [] and legacy.turns[0].execution_trace_version is None
    asyncio.run(scenario())
