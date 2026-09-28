import asyncio

from mcp import Client

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore, build_server


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
                "create_finance_session",
                "ask_finance_agent",
                "close_finance_session",
            }

            created = await client.call_tool("create_finance_session", {})
            session_id = created.structured_content["session_id"]
            assert created.structured_content["transaction_count"] > 0

            answered = await client.call_tool(
                "ask_finance_agent",
                {"session_id": session_id, "question": "July groceries?", "context_mode": "summary"},
            )
            assert answered.structured_content["status"] == "ok"
            assert answered.structured_content["trace"][0]["tool"] == "lookup_transactions"

            closed = await client.call_tool("close_finance_session", {"session_id": session_id})
            assert closed.structured_content == {"session_id": session_id, "closed": True}

    asyncio.run(scenario())
