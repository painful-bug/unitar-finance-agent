from datetime import date

from finance_agent.agent import AssistantTurn, ToolCall, run_agent
from finance_agent.finance import FinanceData, load_csv
from finance_agent.models import Session


LEDGER = """date,kind,category,amount,merchant
2026-07-01,income,salary,5000,Employer
2026-07-03,expense,groceries,120.40,Market
"""


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]):
        self.turns = iter(turns)
        self.seen_messages: list[list[dict]] = []

    def chat(self, messages, tools=None, response_model=None):
        self.seen_messages.append(messages)
        return next(self.turns)


def session() -> Session:
    return Session(
        session_id="test",
        data=FinanceData(load_csv(LEDGER), date(2026, 8, 15)),
        as_of_date=date(2026, 8, 15),
    )


def test_agent_executes_validated_tool_then_returns_answer() -> None:
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup_transactions",
                        arguments='{"month":"2026-07","category":"groceries","kind":"expense"}',
                    )
                ]
            ),
            AssistantTurn(content="You spent RM120.40 on groceries in July."),
        ]
    )

    result = run_agent(session(), "How much did I spend on groceries last month?", provider)

    assert result.status == "ok"
    assert result.steps == 2
    assert result.trace[0].result["total"] == "120.40"
    assert provider.seen_messages[1][-1]["tool_call_id"] == "call-1"


def test_malformed_tool_call_becomes_observation_instead_of_crash() -> None:
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[ToolCall(id="bad", name="lookup_transactions", arguments="not-json")]
            ),
            AssistantTurn(content="I could not validate that request."),
        ]
    )

    result = run_agent(session(), "Check July", provider)

    assert result.status == "ok"
    assert "invalid JSON" in result.trace[0].error
    assert "invalid JSON" in provider.seen_messages[1][-1]["content"]


def test_agent_stops_at_hard_step_limit() -> None:
    provider = FakeProvider(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(id=f"call-{index}", name="calculate_savings_rate", arguments='{"month":"2026-07"}')
                ]
            )
            for index in range(6)
        ]
    )

    result = run_agent(session(), "Keep calling tools", provider)

    assert result.status == "max_steps"
    assert result.steps == 6
    assert len(result.trace) == 6


def test_unknown_tool_and_provider_failure_are_typed_errors() -> None:
    provider = FakeProvider(
        [
            AssistantTurn(tool_calls=[ToolCall(id="unknown", name="invented", arguments="{}")]),
            AssistantTurn(content="That tool is unavailable."),
        ]
    )
    result = run_agent(session(), "Use an unknown tool", provider)
    assert result.trace[0].error == "unknown tool: invented"

    class BrokenProvider:
        def chat(self, messages, tools=None, response_model=None):
            raise RuntimeError("offline")

    failed = run_agent(session(), "Hello", BrokenProvider())
    assert failed.status == "error"
    assert "offline" in failed.answer
