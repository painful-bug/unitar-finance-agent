import copy
from datetime import date
from types import SimpleNamespace

import httpx
import pytest
from groq import BadRequestError

from finance_agent.agent import AssistantTurn, GroqProvider, ToolCall, run_agent
from finance_agent.context import ContextManager
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


@pytest.mark.parametrize("code,failures,expected_calls", [
    ("output_parse_failed", 1, 2),
    ("output_parse_failed", 2, 2),
    ("invalid_request_error", 1, 1),
])
def test_groq_parse_error_recovery_is_specific_and_bounded(code, failures, expected_calls):
    requests, events = [], []
    error = BadRequestError("Parsing failed", response=httpx.Response(
        400, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    ), body={"error": {"code": code, "failed_generation": ""}})

    def create(**kwargs):
        requests.append(kwargs)
        if len(requests) <= failures:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="Recovered answer", tool_calls=[]
        ))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    messages = [{"role": "user", "content": "Summarize expenses"}]
    provider = GroqProvider(client=client)
    if code == "output_parse_failed" and failures == 1:
        assert provider.chat(messages, event_callback=events.append).content == "Recovered answer"
        assert any(event["state"] == "warning" for event in events)
        assert any(event["state"] == "completed" for event in events)
    else:
        with pytest.raises(BadRequestError) as raised:
            provider.chat(messages, event_callback=events.append)
        assert raised.value is error
    assert len(requests) == expected_calls
    assert messages == [{"role": "user", "content": "Summarize expenses"}]
    assert all(request["messages"] == messages for request in requests)


@pytest.mark.parametrize("first", ["empty", "parse"])
def test_groq_empty_and_parse_failures_share_one_retry(first):
    requests = []
    error = BadRequestError("Parsing failed", response=httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com")),
                            body={"code": "output_parse_failed"})
    def create(**kwargs):
        requests.append(kwargs)
        if (len(requests) == 1) == (first == "parse"):
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[]), finish_reason="stop")])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises((BadRequestError, ValueError)):
        GroqProvider(client=client).chat([{"role": "user", "content": "Hello"}])
    assert len(requests) == 2


def test_agent_reuses_compacted_context_across_tool_steps_without_changing_history():
    current = session()
    current.context_mode = "summary"
    current.compaction_turns = 5
    current.messages = [message for _ in range(4) for message in [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]]
    original = copy.deepcopy(current.messages)
    class Provider:
        summaries = 0
        inputs = []
        def chat(self, messages, tools=None, response_model=None):
            if not tools:
                self.summaries += 1
                return AssistantTurn(content="Earlier questions answered.")
            self.inputs.append(copy.deepcopy(messages))
            if len(self.inputs) < 3:
                return AssistantTurn(tool_calls=[ToolCall(id=f"lookup-{len(self.inputs)}", name="lookup_transactions", arguments='{"month":"2026-07"}')])
            return AssistantTurn(content="Done")
    provider = Provider()
    result = run_agent(current, "Current question", provider, ContextManager(trigger_tokens=None, preserve_recent=2), include_context=True)
    assert result.status == "ok" and provider.summaries == 1
    assert current.messages[:len(original)] == original
    assert result.context.after_messages == provider.inputs[-1]
    assert len([m for m in provider.inputs[-1] if m["role"] == "tool"]) == 2
    assert sum((m.get("content") or "").startswith("Lossy summary") for m in provider.inputs[-1]) == 1
