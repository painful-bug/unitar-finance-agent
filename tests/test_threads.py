import asyncio
import json
import stat
from pathlib import Path

import pytest

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore
from finance_agent.threads import AppSettings, ChatStore, ChatTurn, chat_title, utc_now


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


def test_retired_evaluation_setting_loads_in_settings_and_chat_snapshots(tmp_path):
    store = ChatStore(tmp_path / "chats")
    store.save_settings(AppSettings())
    path = store.path / "settings/app.json"
    saved = json.loads(path.read_text())
    saved.update(evaluation_judge="jev", compaction_turns=20)
    path.write_text(json.dumps(saved))
    assert store.load_settings().compaction_turns == 20
    assert "evaluation_judge" not in store.load_settings().model_dump()
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create()
    run(sessions.ask(created.session_id, "How much did I save?"))
    path = store.path / f"{created.session_id}.json"
    saved = json.loads(path.read_text())
    saved["turns"][0]["settings"]["evaluation_judge"] = "auto"
    path.write_text(json.dumps(saved))
    restored = store.load(created.session_id)
    assert restored.turns[0].question == "How much did I save?"
    assert "evaluation_judge" not in restored.turns[0].settings.model_dump()
    with pytest.raises(ValueError):
        AppSettings.model_validate({"unrelated_unknown_setting": True})


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
            max_agent_steps=25,
        )
    )
    updated = run(restarted.get_chat_thread(created.session_id))
    assert updated.summary.title == "August savings"
    assert updated.context_mode == "summary"
    assert updated.compaction_turns == 20
    assert updated.max_agent_steps == 25

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


def test_shared_settings_apply_to_all_chats_and_survive_restart(tmp_path: Path) -> None:
    from finance_agent.budget import default_budget_rules

    store = ChatStore(tmp_path / "chats")
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    first, second = sessions.create(), sessions.create()
    run(sessions.ask(first.session_id, "First answer"))
    run(sessions.ask(second.session_id, "Second answer"))
    custom = default_budget_rules()[:1]
    sessions.update_app_settings(context_mode="summary", compaction_turns=25, max_agent_steps=30,
                                 budget_rules=custom, rules_text=custom[0].source_text, rules_draft="A draft")
    for created in (first, second):
        detail = run(sessions.get_chat_thread(created.session_id))
        assert (detail.context_mode, detail.compaction_turns, detail.max_agent_steps) == ("summary", 25, 30)
        assert detail.budget_rules == custom
        assert detail.turns[0].settings.max_agent_steps == 15
    restarted = SessionStore(chat_store=ChatStore(store.path))
    assert restarted.get_app_settings() == sessions.get_app_settings()
    assert restarted.get_app_settings().rules_draft == "A draft"
    assert run(restarted.get_chat_thread(first.session_id)).max_agent_steps == 30
    assert sessions.create().max_agent_steps == 30
    assert store.list().skipped_files == 0
    assert stat.S_IMODE((store.path / "settings").stat().st_mode) == 0o700
    assert stat.S_IMODE((store.path / "settings" / "app.json").stat().st_mode) == 0o600


def test_invalid_settings_and_failed_save_retain_confirmed_settings(tmp_path: Path, monkeypatch) -> None:
    from pydantic import ValidationError

    store = ChatStore(tmp_path)
    sessions = SessionStore(chat_store=store)
    original = sessions.get_app_settings()
    for invalid in (4, 101, 5.5, "5", True):
        with pytest.raises(ValidationError):
            sessions.update_app_settings(compaction_turns=invalid)
    for invalid in (0, 101, "10", True):
        with pytest.raises(ValidationError):
            sessions.update_app_settings(max_agent_steps=invalid)
    with pytest.raises(ValidationError):
        sessions.update_app_settings(budget_rules=[])
    with pytest.raises(ValueError, match="requires compiled"):
        sessions.update_app_settings(rules_text="Unconfirmed")
    sessions.update_app_settings(rules_draft="Edit without activating")
    assert sessions.get_app_settings().budget_rules == original.budget_rules
    before = sessions.get_app_settings()
    monkeypatch.setattr(store, "save_settings", lambda _settings: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        sessions.update_app_settings(max_agent_steps=25)
    assert sessions.get_app_settings() == before
    assert store.load_settings() == before


def test_replace_ledger_preserves_turns_resets_context_and_is_atomic(tmp_path: Path, monkeypatch) -> None:
    from datetime import date

    store = ChatStore(tmp_path)
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create()
    run(sessions.ask(created.session_id, "Remember the old ledger"))
    original = store.load(created.session_id)
    csv_text = "date,kind,category,amount\n2026-09-01,income,salary,2500\n"
    replaced = run(sessions.update_chat_thread(created.session_id, csv_text=csv_text, upload_name="september.csv"))
    assert replaced.as_of_date == date(2026, 9, 1)
    assert replaced.transaction_count == 1
    assert replaced.turns[0].ledger.as_of_date == original.as_of_date
    assert replaced.turns[0].result == original.turns[0].result
    assert replaced.ledger_changes[0].after_turn_count == 1
    assert sessions.sessions[created.session_id].messages == []
    persisted = store.load(created.session_id)
    assert persisted.messages == [] and persisted.csv_text == csv_text
    assert "csv_text" not in replaced.model_dump()

    for invalid in ("bad,data", "date,kind,category,amount\n2026-09-01,expense,dining,-10"):
        with pytest.raises(ValueError):
            run(sessions.update_chat_thread(created.session_id, csv_text=invalid, upload_name="bad.csv"))
        assert store.load(created.session_id) == persisted
    restarted = SessionStore(provider=ThreadProvider(), chat_store=ChatStore(store.path))
    assert run(restarted.get_chat_thread(created.session_id)).ledger_changes == replaced.ledger_changes
    assert restarted.sessions[created.session_id].messages == []
    run(restarted.ask(created.session_id, "Use the new ledger"))
    assert len(restarted.records[created.session_id].turns) == 2
    assert restarted.sessions[created.session_id].messages[0]["content"] == "Use the new ledger"
    reset = run(restarted.update_chat_thread(created.session_id, use_bundled_data=True))
    assert reset.summary.ledger_source == "demo" and reset.as_of_date == date(2026, 8, 15)
    assert reset.summary.upload_name is None and len(reset.ledger_changes) == 2
    assert restarted.create().ledger_source == "demo"

    before = restarted.records[created.session_id].model_copy(deep=True)
    old_data = restarted.sessions[created.session_id].data
    monkeypatch.setattr(restarted.chat_store, "save", lambda _record: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        run(restarted.update_chat_thread(created.session_id, csv_text=csv_text))
    assert restarted.records[created.session_id] == before
    assert restarted.sessions[created.session_id].data is old_data


def test_running_answer_keeps_settings_and_rejects_ledger_replacement(tmp_path: Path) -> None:
    import threading
    from finance_agent.budget import default_budget_rules

    class GatedProvider:
        def __init__(self):
            self.started, self.release = threading.Event(), threading.Event()
            self.inputs = []

        def chat(self, messages, tools=None, response_model=None):
            self.inputs.append(messages)
            self.started.set()
            assert self.release.wait(5)
            return AssistantTurn(content="Done")

    async def scenario():
        provider = GatedProvider()
        sessions = SessionStore(provider=provider, chat_store=ChatStore(tmp_path))
        created = sessions.create()
        task = asyncio.create_task(sessions.ask(created.session_id, "First question"))
        assert await asyncio.to_thread(provider.started.wait, 3)
        try:
            custom = default_budget_rules()[:1]
            sessions.update_app_settings(max_agent_steps=1, context_mode="summary", budget_rules=custom)
            assert sessions.sessions[created.session_id].max_agent_steps == 15
            with pytest.raises(ValueError, match="current answer"):
                await sessions.update_chat_thread(created.session_id, use_bundled_data=True)
        finally:
            provider.release.set()
        await task
        assert sessions.records[created.session_id].turns[0].settings.max_agent_steps == 15
        await sessions.ask(created.session_id, "Second question")
        assert sessions.records[created.session_id].turns[1].settings.max_agent_steps == 1
        assert sessions.records[created.session_id].turns[1].settings.budget_rules == custom
        assert "groceries_monthly_cap" in provider.inputs[0][0]["content"]
        assert "groceries_monthly_cap" not in provider.inputs[1][0]["content"]

    run(scenario())


def test_legacy_thread_replacement_keeps_historical_metadata(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create()
    run(sessions.ask(created.session_id, "Old answer"))
    path = store.path / f"{created.session_id}.json"
    raw = json.loads(path.read_text())
    raw.pop("ledger_changes")
    raw["budget_rules"] = []
    raw["turns"][0].pop("ledger")
    raw["turns"][0].pop("settings")
    path.write_text(json.dumps(raw))
    restarted = SessionStore(chat_store=ChatStore(store.path))
    changed = run(restarted.update_chat_thread(created.session_id, use_bundled_data=True))
    assert changed.turns[0].ledger.ledger_source == "demo"
    assert changed.turns[0].settings.budget_rules == []
    assert store.load(created.session_id).turns[0].settings.budget_rules == []


def test_new_answer_preserves_legacy_settings_before_applying_globals(tmp_path: Path):
    store = ChatStore(tmp_path)
    sessions = SessionStore(provider=ThreadProvider(), chat_store=store)
    created = sessions.create(max_agent_steps=25)
    run(sessions.ask(created.session_id, "Legacy answer"))
    path = store.path / f"{created.session_id}.json"
    raw = json.loads(path.read_text())
    raw["turns"][0].pop("settings")
    raw["turns"][0].pop("ledger")
    path.write_text(json.dumps(raw))
    restarted = SessionStore(provider=ThreadProvider(), chat_store=ChatStore(store.path))
    restarted.update_app_settings(max_agent_steps=30)
    run(restarted.ask(created.session_id, "New answer"))
    turns = store.load(created.session_id).turns
    assert turns[0].settings.max_agent_steps == 25
    assert turns[1].settings.max_agent_steps == 30
