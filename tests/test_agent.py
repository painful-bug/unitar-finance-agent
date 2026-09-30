from datetime import date
from types import SimpleNamespace

import pytest

from finance_agent.agent import AssistantTurn, GroqProvider, ToolCall, run_agent
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
            for index in range(15)
        ]
    )

    result = run_agent(session(), "Keep calling tools", provider)

    assert result.status == "max_steps"
    assert result.steps == 15
    assert len(result.trace) == 15
    assert "15 agent steps" in result.answer


def test_agent_reports_the_configured_step_limit() -> None:
    provider = FakeProvider([
        AssistantTurn(tool_calls=[ToolCall(id=f"call-{index}", name="calculate_savings_rate", arguments='{"month":"2026-07"}')])
        for index in range(2)
    ])

    result = run_agent(session(), "Keep calling tools", provider, max_steps=2)

    assert result.status == "max_steps"
    assert result.answer == "Reached the maximum of 2 agent steps without a final answer."


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


@pytest.mark.parametrize("content", [None, "", " \n\t"])
def test_empty_final_turn_is_an_error_and_is_not_saved(content) -> None:
    current = session()
    result = run_agent(current, "Plan next month", FakeProvider([AssistantTurn(content=content)]))

    assert result.status == "error"
    assert current.messages == [{"role": "user", "content": "Plan next month"}]


@pytest.mark.parametrize("recovered", [AssistantTurn(content="Please confirm next month's income."), AssistantTurn(
    tool_calls=[ToolCall(id="salary", name="lookup_transactions", arguments='{"month":"2026-07"}')]
)])
def test_groq_retries_empty_response_without_mutating_history(recovered) -> None:
    requests = []
    turns = iter([AssistantTurn(content=" \n"), recovered])

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=(turn := next(turns)).content,
            tool_calls=[SimpleNamespace(id=call.id, function=SimpleNamespace(
                name=call.name, arguments=call.arguments
            )) for call in turn.tool_calls],
        ), finish_reason="stop")])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    messages = [{"role": "user", "content": "Plan next month"}]
    assert GroqProvider(client=client).chat(messages) == recovered
    assert len(requests) == 2
    assert len(messages) == 1
    assert "previous response was empty" in requests[1]["messages"][-1]["content"]


def test_groq_repeated_empty_response_is_bounded_and_keeps_tool_trace() -> None:
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id="salary", function=SimpleNamespace(
                    name="lookup_transactions", arguments='{"month":"2026-07","category":"salary"}'
                )
            )])
            reason = "tool_calls"
        else:
            message = SimpleNamespace(content="", tool_calls=[])
            reason = "length"
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=reason)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    current = session()
    result = run_agent(current, "Plan next month", GroqProvider(client=client))

    assert len(requests) == 3
    assert result.status == "error"
    assert "finish_reason=length" in result.answer
    assert result.trace[0].result["total"] == "5000.00"
    assert current.messages[-1]["role"] == "tool"
