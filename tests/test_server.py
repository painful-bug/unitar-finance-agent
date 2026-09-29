import asyncio
import json
from decimal import Decimal

from mcp import Client

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.budget import BudgetRule, Operand, default_budget_rules
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore, build_server
from finance_agent.ui import DEFAULT_RULES_TEXT


class FakeProvider:
    def __init__(self):
        self.turns = iter(
            [
                AssistantTurn(
                    tool_calls=[
                        ToolCall(
                            id="lookup",
                            name="lookup_transactions",
                            arguments='{"month":"2026-07","category":"groceries","kind":"expense"}',
                        )
                    ]
                ),
                AssistantTurn(content="July groceries were RM690.65."),
            ]
        )

    def chat(self, messages, tools=None, response_model=None):
        return next(self.turns)


def test_mcp_session_lifecycle_and_structured_results() -> None:
    async def scenario() -> None:
        store = SessionStore(
            provider=FakeProvider(),
            context_manager=ContextManager(trigger_tokens=100_000),
        )
        server = build_server(store)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "parse_budget_rules",
                "create_finance_session",
                "ask_finance_agent",
                "close_finance_session",
            }

            created = await client.call_tool("create_finance_session", {})
            session_id = created.structured_content["session_id"]
            assert created.structured_content["transaction_count"] > 0

            answered = await client.call_tool(
                "ask_finance_agent",
                {
                    "session_id": session_id,
                    "question": "July groceries?",
                    "context_mode": "summary",
                    "include_context": True,
                },
            )
            assert answered.structured_content["status"] == "ok"
            assert answered.structured_content["trace"][0]["tool"] == "lookup_transactions"
            context = answered.structured_content["context"]
            assert context["before_messages"][0]["role"] == "system"
            assert context["after_messages"] == context["before_messages"]

            closed = await client.call_tool("close_finance_session", {"session_id": session_id})
            assert closed.structured_content == {"session_id": session_id, "closed": True}

    asyncio.run(scenario())


def test_mcp_rule_preview_can_be_confirmed_into_a_session() -> None:
    class RuleParser:
        def chat(self, messages, tools=None, response_model=None):
            rules_text = json.loads(messages[-1]["content"])["rules"]
            custom = BudgetRule(
                rule_id="savings_target",
                source_text="Save at least 25% of income.",
                left=Operand(metric="savings", unit="RM"),
                operator="gte",
                right=Operand(metric="income", unit="RM", multiplier=Decimal("0.25")),
            )
            rules = default_budget_rules() + [custom] if rules_text.startswith(DEFAULT_RULES_TEXT) else [custom]
            return AssistantTurn(
                content=json.dumps({"rules": [rule.model_dump(mode="json") for rule in rules]})
            )

    async def scenario() -> None:
        server = build_server(SessionStore(provider=RuleParser()))
        async with Client(server) as client:
            preview = await client.call_tool(
                "parse_budget_rules",
                {"rules_text": f"{DEFAULT_RULES_TEXT}\nSave at least 25% of income."},
            )
            rules = preview.structured_content["rules"]
            with_defaults = await client.call_tool(
                "create_finance_session", {"budget_rules": rules},
            )
            assert len(with_defaults.structured_content["budget_rules"]) == 4

            custom_preview = await client.call_tool(
                "parse_budget_rules", {"rules_text": "Save at least 25% of income."}
            )
            custom_only = await client.call_tool(
                "create_finance_session",
                {"budget_rules": custom_preview.structured_content["rules"]},
            )

            assert [
                rule["rule_id"] for rule in custom_only.structured_content["budget_rules"]
            ] == ["savings_target"]

    asyncio.run(scenario())
