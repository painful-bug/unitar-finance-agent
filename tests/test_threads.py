import asyncio
import json
import stat
from pathlib import Path

import pytest

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore
from finance_agent.threads import ChatStore, ChatTurn, chat_title, utc_now


class ThreadProvider:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, response_model=None):
        if messages[-1]["role"] == "tool":
            return AssistantTurn(content="Your savings rate is grounded in the ledger.")
        self.calls += 1
        return AssistantTurn(
            tool_calls=[
                ToolCall(
                    id=f"savings-{self.calls}",
                    name="calculate_savings_rate",
                    arguments='{"month":"2026-08"}',
                )
            ]
        )


def run(value):
    return asyncio.run(value)


def test_chat_title_is_deterministic_and_bounded() -> None:
    assert chat_title("  How   much did I save?\n") == "How much did I save?"
    assert chat_title("x" * 60) == f"{'x' * 47}…"


def test_store_permissions_validation_and_corrupt_file_isolation(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "chats")
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create()
    run(sessions.ask(created.session_id, "How much did I save?"))

    path = store.path / f"{created.session_id}.json"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1

    (store.path / "broken.json").write_text('{"version": 99}', encoding="utf-8")
    listed = store.list()
    assert [thread.thread_id for thread in listed.threads] == [created.session_id]
    assert listed.skipped_files == 1

    with pytest.raises(ValueError):
        store.load("../../not-a-thread")


def test_uploaded_thread_survives_restart_without_exposing_csv(tmp_path: Path) -> None:
    chat_store = ChatStore(tmp_path / "chats")
    csv_text = "date,kind,category,amount,merchant\n2026-08-01,income,salary,1000,Acme\n"
    first = SessionStore(
        provider=ThreadProvider(),
        context_manager=ContextManager(trigger_tokens=100_000),
        chat_store=chat_store,
    )
    created = first.create(csv_text=csv_text, upload_name="private.csv")
    result = run(first.ask(created.session_id, "Summarize my savings.", include_context=True))
    assert result.status == "ok"

    public = run(first.get_chat_thread(created.session_id))
    assert public.summary.upload_name == "private.csv"
    assert "csv_text" not in public.model_dump(mode="json")
    assert public.turns[0].result is not None
    assert public.turns[0].result.trace[0].tool == "calculate_savings_rate"

    restarted = SessionStore(
        provider=ThreadProvider(),
        context_manager=ContextManager(trigger_tokens=100_000),
        chat_store=ChatStore(chat_store.path),
    )
    restored = run(restarted.get_chat_thread(created.session_id))
    assert restored.turns[0].question == "Summarize my savings."
    assert restored.transaction_count == 1

    run(
        restarted.update_chat_thread(
            created.session_id,
            title="August savings",
            context_mode="summary",
            compaction_turns=20,
        )
    )
    updated = run(restarted.get_chat_thread(created.session_id))
    assert updated.summary.title == "August savings"
    assert updated.context_mode == "summary"
    assert updated.compaction_turns == 20

    continued = run(restarted.ask(created.session_id, "Check again."))
    assert continued.status == "ok"
    assert run(restarted.get_chat_thread(created.session_id)).summary.turn_count == 2

    restarted.close(created.session_id)
    assert run(restarted.get_chat_thread(created.session_id)).summary.turn_count == 2
    assert run(restarted.delete_chat_thread(created.session_id)).deleted is True
    assert chat_store.load(created.session_id) is None


def test_pending_turn_is_recovered_as_interrupted(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "chats")
    first = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = first.create()
    record = first.records[created.session_id]
    record.turns.append(
        ChatTurn(
            turn_id="8a68c223-7e5a-4adc-9f1a-9c18a8f87be0",
            created_at=utc_now(),
            question="Was this interrupted?",
        )
    )
    store.save(record)

    restarted = SessionStore(provider=ThreadProvider(), chat_store=ChatStore(store.path))
    detail = run(restarted.get_chat_thread(created.session_id))
    assert detail.turns[0].state == "interrupted"
    assert detail.turns[0].result is None


def test_failed_thread_update_rolls_back_in_memory_state(tmp_path: Path, monkeypatch) -> None:
    store = ChatStore(tmp_path / "chats")
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create()
    run(sessions.ask(created.session_id, "Keep the original title"))
    original = sessions.records[created.session_id].model_copy(deep=True)

    def fail_save(_record) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(store, "save", fail_save)
    with pytest.raises(OSError, match="disk full"):
        run(sessions.update_chat_thread(created.session_id, title="Do not retain this"))

    current = sessions.records[created.session_id]
    assert current.title == original.title
    assert current.title_source == original.title_source
