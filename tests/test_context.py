import copy
from datetime import date

from finance_agent.agent import AssistantTurn
from finance_agent.context import ContextManager
from finance_agent.finance import FinanceData, load_csv
from finance_agent.models import ContextManagementError, Session


class FakeJev:
    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error

    def noul_scores(self, state, questions):
        if self.error:
            raise self.error
        return {name: self.answers[name] for name in questions}


class SummaryProvider:
    def chat(self, messages, tools=None, response_model=None):
        return AssistantTurn(content="July groceries were RM120.40; the user asked to retain exact amounts.")


class DropAllJev:
    def noul_scores(self, state, questions):
        return {name: 0.0 for name in questions}


def make_session() -> Session:
    data = FinanceData(
        load_csv("date,kind,category,amount\n2026-07-01,expense,groceries,120.40"),
        date(2026, 8, 15),
    )
    messages = [
        {"role": "user", "content": "Start"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "keep", "type": "function", "function": {"name": "lookup_transactions", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "keep", "content": "exact result"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "trim", "type": "function", "function": {"name": "lookup_transactions", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "trim", "content": "A" * 400 + "Z" * 400},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "drop", "type": "function", "function": {"name": "lookup_transactions", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "drop", "content": "irrelevant"},
        {"role": "user", "content": "Newest message"},
    ]
    return Session("test", data, date(2026, 8, 15), messages=messages)


def make_turn_session(turns: int) -> Session:
    session = make_session()
    session.messages = []
    session.compaction_turns = 5
    for turn in range(1, turns + 1):
        call_id = f"turn-{turn}"
        session.messages.extend(
            [
                {"role": "user", "content": f"Question {turn}"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "lookup_transactions", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": call_id, "content": "X" * 800},
                {"role": "assistant", "content": f"Answer {turn}"},
            ]
        )
    return session


def test_turn_threshold_compacts_from_the_fifth_user_message_without_mutating_history() -> None:
    manager = ContextManager(DropAllJev())
    system = {"role": "system", "content": "system"}

    for turns in range(1, 5):
        session = make_turn_session(turns)
        full, report = manager.prepare(system, session, SummaryProvider(), include_messages=True)
        assert report.strategy == "none"
        assert report.after_messages == full

    session = make_turn_session(5)
    original = copy.deepcopy(session.messages)
    compacted, report = manager.prepare(system, session, SummaryProvider(), include_messages=True)

    assert report.strategy == "jev"
    assert report.after_tokens < report.before_tokens
    assert report.after_messages == compacted
    assert any(message.get("content") == "Question 5" for message in compacted)
    assert session.messages == original

    session.messages.extend(
        [{"role": "user", "content": "Question 6"}, {"role": "assistant", "content": "Answer 6"}]
    )
    _, later_report = manager.prepare(system, session, SummaryProvider())
    assert later_report.strategy == "jev"


def test_turn_threshold_uses_summary_when_jev_fails() -> None:
    session = make_turn_session(5)
    manager = ContextManager(FakeJev(error=RuntimeError("Jev unavailable")))

    compacted, report = manager.prepare(
        {"role": "system", "content": "system"},
        session,
        SummaryProvider(),
        mode="auto",
        include_messages=True,
    )

    assert report.strategy == "summary"
    assert report.fallback_reason == "Jev unavailable"
    assert report.after_messages == compacted


def test_jev_keeps_trims_and_drops_complete_tool_pairs() -> None:
    answers = {
        "call_keep": 0.9,
        "result_keep": 0.9,
        "call_trim": 0.2,
        "result_trim": 0.9,
        "call_drop": 0.1,
        "result_drop": 0.1,
    }
    session = make_session()
    original = copy.deepcopy(session.messages)
    manager = ContextManager(FakeJev(answers), trigger_tokens=1, preserve_recent=1)

    compacted, report = manager.prepare(
        {"role": "system", "content": "system"}, session, SummaryProvider(), mode="jev"
    )

    serialized = str(compacted)
    call_ids = {
        call["id"]
        for message in compacted
        for call in message.get("tool_calls", [])
    }
    result_ids = {
        message["tool_call_id"] for message in compacted if message.get("role") == "tool"
    }
    assert "exact result" in serialized
    assert "A" * 300 in serialized and "Z" * 300 in serialized
    assert "irrelevant" not in serialized and "'id': 'drop'" not in serialized
    assert result_ids <= call_ids
    assert report.strategy == "jev"
    assert {item["action"] for item in report.decisions} == {"keep", "trim", "drop"}
    assert session.messages == original


def test_jev_falls_back_when_all_keep_would_not_compact() -> None:
    session = make_session()
    manager = ContextManager(
        FakeJev(
            {
                "call_keep": 1.0,
                "result_keep": 1.0,
                "call_trim": 1.0,
                "result_trim": 1.0,
                "call_drop": 1.0,
                "result_drop": 1.0,
            }
        ),
        trigger_tokens=1,
        preserve_recent=1,
    )

    compacted, report = manager.prepare(
        {"role": "system", "content": "system"},
        session,
        SummaryProvider(),
        mode="jev",
        include_messages=True,
    )

    assert report.strategy == "summary"
    assert report.after_tokens < report.before_tokens
    assert report.fallback_reason == "Jev removed less than 5%"
    assert report.before_messages[1:] == session.messages
    assert report.after_messages == compacted


def test_auto_falls_back_to_groq_summary_without_splitting_recent_history() -> None:
    session = make_session()
    manager = ContextManager(
        FakeJev(error=RuntimeError("Jev unavailable")), trigger_tokens=1, preserve_recent=2
    )

    compacted, report = manager.prepare(
        {"role": "system", "content": "system"}, session, SummaryProvider(), mode="auto"
    )

    assert report.strategy == "summary"
    assert report.fallback_reason == "Jev unavailable"
    assert compacted[-1] == session.messages[-1]
    assert "Lossy summary" in compacted[1]["content"]


def test_context_mode_can_change_without_mutating_canonical_history() -> None:
    session = make_session()
    original = copy.deepcopy(session.messages)
    manager = ContextManager(FakeJev({
        "call_keep": 1.0,
        "result_keep": 1.0,
        "call_trim": 1.0,
        "result_trim": 1.0,
        "call_drop": 1.0,
        "result_drop": 1.0,
    }), trigger_tokens=1, preserve_recent=1)

    manager.prepare({"role": "system", "content": "system"}, session, SummaryProvider(), mode="summary")
    manager.prepare({"role": "system", "content": "system"}, session, SummaryProvider(), mode="jev")

    assert session.messages == original


def test_auto_reports_context_error_when_both_strategies_fail() -> None:
    class EmptySummaryProvider:
        def chat(self, messages, tools=None, response_model=None):
            return AssistantTurn()

    manager = ContextManager(FakeJev(error=RuntimeError("Jev down")), trigger_tokens=1, preserve_recent=1)

    try:
        manager.prepare(
            {"role": "system", "content": "system"}, make_session(), EmptySummaryProvider(), mode="auto"
        )
    except ContextManagementError as exc:
        assert "Jev down" in str(exc)
        assert "summary model returned no content" in str(exc)
    else:
        raise AssertionError("expected context management failure")
