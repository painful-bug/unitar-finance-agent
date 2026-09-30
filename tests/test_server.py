import asyncio
import json
from decimal import Decimal

from mcp import Client

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.budget import BudgetRule, Operand, default_budget_rules
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore, build_server
from finance_agent.threads import ChatStore


DEFAULT_RULES_TEXT = ", ".join(rule.source_text for rule in default_budget_rules())


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


def test_mcp_session_lifecycle_and_structured_results(tmp_path) -> None:
    async def scenario() -> None:
        store = SessionStore(
            provider=FakeProvider(),
            context_manager=ContextManager(trigger_tokens=100_000),
            chat_store=ChatStore(tmp_path / "chats"),
        )
        server = build_server(store)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "parse_budget_rules",
                "create_finance_session",
                "ask_finance_agent",
                "close_finance_session",
                "list_chat_threads",
                "get_chat_thread",
                "update_chat_thread",
                "delete_chat_thread",
            }

            created = await client.call_tool("create_finance_session", {})
            session_id = created.structured_content["session_id"]
            assert created.structured_content["transaction_count"] > 0
            assert created.structured_content["compaction_turns"] == 15
            assert created.structured_content["max_agent_steps"] == 15
            assert created.structured_content["ledger_source"] == "demo"

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

            listed = await client.call_tool("list_chat_threads", {})
            assert listed.structured_content["threads"][0]["thread_id"] == session_id

            renamed = await client.call_tool(
                "update_chat_thread",
                {"thread_id": session_id, "title": "July review", "compaction_turns": 20, "max_agent_steps": 25},
            )
            assert renamed.structured_content["summary"]["title"] == "July review"
            assert renamed.structured_content["compaction_turns"] == 20
            assert renamed.structured_content["max_agent_steps"] == 25

            closed = await client.call_tool("close_finance_session", {"session_id": session_id})
            assert closed.structured_content == {"session_id": session_id, "closed": True}

            restored = await client.call_tool("get_chat_thread", {"thread_id": session_id})
            assert restored.structured_content["turns"][0]["question"] == "July groceries?"

            deleted = await client.call_tool("delete_chat_thread", {"thread_id": session_id})
            assert deleted.structured_content == {"thread_id": session_id, "deleted": True}

    asyncio.run(scenario())


def test_mcp_compaction_turn_contract_is_bounded_and_configurable() -> None:
    async def scenario() -> None:
        server = build_server(SessionStore(provider=FakeProvider()))
        async with Client(server) as client:
            tools = await client.list_tools()
            schemas = {tool.name: tool.input_schema for tool in tools.tools}
            create_turns = schemas["create_finance_session"]["properties"]["compaction_turns"]
            ask_turns = schemas["ask_finance_agent"]["properties"]["compaction_turns"]
            assert create_turns["default"] == 15
            assert create_turns["minimum"] == 5
            assert create_turns["maximum"] == 100
            ask_integer = next(item for item in ask_turns["anyOf"] if item.get("type") == "integer")
            assert ask_integer["minimum"] == 5
            assert ask_integer["maximum"] == 100

            for invalid in (4, 101, 5.5, "5"):
                rejected = await client.call_tool(
                    "create_finance_session", {"compaction_turns": invalid}
                )
                assert rejected.is_error

            created = await client.call_tool(
                "create_finance_session", {"compaction_turns": 5}
            )
            assert created.structured_content["compaction_turns"] == 5

            max_steps = schemas["create_finance_session"]["properties"]["max_agent_steps"]
            assert max_steps["default"] == 15
            assert max_steps["minimum"] == 1
            assert max_steps["maximum"] == 100
            assert "max_agent_steps" not in schemas["ask_finance_agent"]["properties"]

            configured = await client.call_tool("create_finance_session", {"max_agent_steps": 1})
            assert configured.structured_content["max_agent_steps"] == 1

    asyncio.run(scenario())


def test_saved_agent_step_limit_controls_execution() -> None:
    async def scenario() -> None:
        server = build_server(SessionStore(provider=FakeProvider()))
        async with Client(server) as client:
            created = await client.call_tool("create_finance_session", {"max_agent_steps": 1})
            result = await client.call_tool(
                "ask_finance_agent",
                {"session_id": created.structured_content["session_id"], "question": "July groceries?"},
            )
            assert result.structured_content["status"] == "max_steps"
            assert result.structured_content["steps"] == 1
            assert result.structured_content["answer"] == "Reached the maximum of 1 agent steps without a final answer."

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
