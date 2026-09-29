from __future__ import annotations

import asyncio
import os
from datetime import date
from importlib.resources import files
from typing import Literal
from uuid import uuid4

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from .agent import ChatProvider, GroqProvider, run_agent
from .budget import BudgetRule, BudgetRulePreview, parse_budget_rules as compile_budget_rules
from .context import ContextManager
from .finance import FinanceData, load_csv
from .models import AgentResult, ContextReport, Session

ContextMode = Literal["auto", "jev", "summary"]


class SessionInfo(BaseModel):
    session_id: str
    as_of_date: date
    context_mode: ContextMode
    transaction_count: int
    budget_rules: list[BudgetRule]


class CloseResult(BaseModel):
    session_id: str
    closed: bool


def _demo_csv() -> str:
    return files("finance_agent.data").joinpath("demo.csv").read_text(encoding="utf-8")


class SessionStore:
    def __init__(
        self,
        provider: ChatProvider | None = None,
        context_manager: ContextManager | None = None,
    ):
        self.sessions: dict[str, Session] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.provider = provider
        self.context_manager = context_manager or ContextManager()

    def create(
        self,
        csv_text: str | None = None,
        as_of_date: date | None = None,
        context_mode: ContextMode = "auto",
        budget_rules: list[BudgetRule] | None = None,
    ) -> SessionInfo:
        using_demo = csv_text is None
        transactions = load_csv(_demo_csv() if using_demo else csv_text)
        anchor = as_of_date or (date(2026, 8, 15) if using_demo else max(row.date for row in transactions))
        session_id = str(uuid4())
        self.sessions[session_id] = Session(
            session_id=session_id,
            data=FinanceData(transactions, anchor, budget_rules=budget_rules),
            as_of_date=anchor,
            context_mode=context_mode,
        )
        self.locks[session_id] = asyncio.Lock()
        return SessionInfo(
            session_id=session_id,
            as_of_date=anchor,
            context_mode=context_mode,
            transaction_count=len(transactions),
            budget_rules=self.sessions[session_id].data.budget_rules,
        )

    def parse_budget_rules(
        self,
        rules_text: str,
        csv_text: str | None = None,
    ) -> BudgetRulePreview:
        transactions = load_csv(_demo_csv() if csv_text is None else csv_text)
        provider = self.provider or GroqProvider()
        return compile_budget_rules(
            rules_text,
            (transaction.category for transaction in transactions),
            provider,
        )

    async def ask(
        self,
        session_id: str,
        question: str,
        context_mode: ContextMode | None = None,
        include_context: bool = False,
    ) -> AgentResult:
        session = self.sessions.get(session_id)
        if not session:
            return AgentResult(
                answer="Unknown or closed session.",
                status="error",
                steps=0,
                context=ContextReport(),
            )
        if context_mode:
            session.context_mode = context_mode
        try:
            provider = self.provider or GroqProvider()
        except Exception as exc:
            return AgentResult(
                answer=f"The model provider is not configured: {exc}",
                status="error",
                steps=0,
            )
        async with self.locks[session_id]:
            return await asyncio.to_thread(
                run_agent,
                session,
                question,
                provider,
                self.context_manager,
                include_context=include_context,
            )

    def close(self, session_id: str) -> CloseResult:
        closed = self.sessions.pop(session_id, None) is not None
        self.locks.pop(session_id, None)
        return CloseResult(session_id=session_id, closed=closed)


def build_server(store: SessionStore | None = None) -> MCPServer:
    sessions = store or SessionStore()
    server = MCPServer(
        "personal-finance-agent",
        description="Grounded personal finance agent with explicit session context management.",
        version="0.1.0",
    )

    @server.tool(structured_output=True)
    def parse_budget_rules(
        rules_text: str,
        csv_text: str | None = None,
    ) -> BudgetRulePreview:
        """Compile natural-language monthly budget rules into a validated expression schema."""
        return sessions.parse_budget_rules(rules_text, csv_text)

    @server.tool(structured_output=True)
    def create_finance_session(
        csv_text: str | None = None,
        as_of_date: date | None = None,
        context_mode: ContextMode = "auto",
        budget_rules: list[BudgetRule] | None = None,
    ) -> SessionInfo:
        """Create an in-memory finance session from bundled data or validated ledger CSV."""
        return sessions.create(csv_text, as_of_date, context_mode, budget_rules)

    @server.tool(structured_output=True)
    async def ask_finance_agent(
        session_id: str,
        question: str,
        context_mode: ContextMode | None = None,
        include_context: bool = False,
    ) -> AgentResult:
        """Ask the hand-written finance agent a question in an existing session."""
        return await sessions.ask(session_id, question, context_mode, include_context)

    @server.tool(structured_output=True)
    def close_finance_session(session_id: str) -> CloseResult:
        """Delete an in-memory finance session."""
        return sessions.close(session_id)

    return server


SERVER = build_server()


def main() -> None:
    SERVER.run(
        transport="streamable-http",
        host=os.getenv("MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("MCP_PORT", "8000")),
        streamable_http_path="/mcp",
        json_response=True,
    )


if __name__ == "__main__":
    main()
