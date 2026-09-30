from __future__ import annotations

import asyncio
import copy
import os
from datetime import date
from importlib.resources import files
from typing import Annotated, Literal
from uuid import UUID, uuid4

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, Field

from .agent import ChatProvider, GroqProvider, run_agent
from .budget import BudgetRule, BudgetRulePreview, parse_budget_rules as compile_budget_rules
from .context import ContextManager
from .finance import FinanceData, load_csv
from .models import AgentResult, ContextReport, Session
from .threads import (
    ChatStore,
    ChatThreadDetail,
    ChatThreadList,
    ChatThreadRecord,
    ChatTurn,
    DeleteChatThreadResult,
    chat_title,
    thread_detail,
    utc_now,
)

ContextMode = Literal["auto", "jev", "summary"]
CompactionTurns = Annotated[int, Field(strict=True, ge=5, le=100)]
OptionalCompactionTurns = Annotated[int | None, Field(strict=True, ge=5, le=100)]


class SessionInfo(BaseModel):
    session_id: str
    as_of_date: date
    context_mode: ContextMode
    transaction_count: int
    budget_rules: list[BudgetRule]
    compaction_turns: CompactionTurns
    ledger_source: Literal["demo", "upload"]
    upload_name: str | None = None


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
        chat_store: ChatStore | None = None,
    ):
        self.sessions: dict[str, Session] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.records: dict[str, ChatThreadRecord] = {}
        self.provider = provider
        self.context_manager = context_manager or ContextManager()
        self.chat_store = chat_store or ChatStore()

    def create(
        self,
        csv_text: str | None = None,
        as_of_date: date | None = None,
        context_mode: ContextMode = "auto",
        budget_rules: list[BudgetRule] | None = None,
        compaction_turns: CompactionTurns = 15,
        upload_name: str | None = None,
    ) -> SessionInfo:
        using_demo = csv_text is None
        transactions = load_csv(_demo_csv() if using_demo else csv_text)
        anchor = as_of_date or (date(2026, 8, 15) if using_demo else max(row.date for row in transactions))
        session_id = str(uuid4())
        session = Session(
            session_id=session_id,
            data=FinanceData(transactions, anchor, budget_rules=budget_rules),
            as_of_date=anchor,
            context_mode=context_mode,
            compaction_turns=compaction_turns,
        )
        self.sessions[session_id] = session
        self.locks[session_id] = asyncio.Lock()
        now = utc_now()
        self.records[session_id] = ChatThreadRecord(
            thread_id=session_id,
            created_at=now,
            updated_at=now,
            ledger_source="demo" if using_demo else "upload",
            upload_name=upload_name if not using_demo else None,
            csv_text=None if using_demo else csv_text,
            as_of_date=anchor,
            context_mode=context_mode,
            transaction_count=len(transactions),
            budget_rules=session.data.budget_rules,
            compaction_turns=compaction_turns,
        )
        return SessionInfo(
            session_id=session_id,
            as_of_date=anchor,
            context_mode=context_mode,
            transaction_count=len(transactions),
            budget_rules=session.data.budget_rules,
            compaction_turns=compaction_turns,
            ledger_source="demo" if using_demo else "upload",
            upload_name=upload_name if not using_demo else None,
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
        compaction_turns: OptionalCompactionTurns = None,
    ) -> AgentResult:
        session = self._hydrate(session_id)
        if not session:
            return AgentResult(
                answer="Unknown or closed session.",
                status="error",
                steps=0,
                context=ContextReport(),
            )
        async with self.locks[session_id]:
            record = self.records[session_id]
            before_session_messages = copy.deepcopy(session.messages)
            before_record = record.model_copy(deep=True)
            if context_mode:
                session.context_mode = context_mode
                record.context_mode = context_mode
            if compaction_turns is not None:
                session.compaction_turns = compaction_turns
                record.compaction_turns = compaction_turns
            now = utc_now()
            if record.title_source == "auto" and not record.turns:
                record.title = chat_title(question)
            turn = ChatTurn(
                turn_id=str(uuid4()),
                created_at=now,
                question=question,
            )
            record.turns.append(turn)
            record.updated_at = now
            try:
                self.chat_store.save(record)
            except Exception:
                self.records[session_id] = before_record
                session.context_mode = before_record.context_mode
                session.compaction_turns = before_record.compaction_turns
                raise

            try:
                provider = self.provider or GroqProvider()
            except Exception as exc:
                result = AgentResult(
                    answer=f"The model provider is not configured: {exc}",
                    status="error",
                    steps=0,
                )
            else:
                result = await asyncio.to_thread(
                    run_agent,
                    session,
                    question,
                    provider,
                    self.context_manager,
                    include_context=include_context,
                )

            turn.state = "complete"
            turn.result = result
            record.messages = copy.deepcopy(session.messages)
            record.updated_at = utc_now()
            try:
                self.chat_store.save(record)
            except Exception:
                session.messages = before_session_messages
                persisted = self.chat_store.load(session_id)
                self.records[session_id] = persisted or before_record
                raise
            return result

    def list_chat_threads(self) -> ChatThreadList:
        return self.chat_store.list()

    async def get_chat_thread(self, thread_id: str) -> ChatThreadDetail:
        session = self._hydrate(thread_id)
        if not session:
            raise ValueError("Unknown chat thread.")
        async with self.locks[thread_id]:
            return thread_detail(self.records[thread_id])

    async def update_chat_thread(
        self,
        thread_id: str,
        title: str | None = None,
        context_mode: ContextMode | None = None,
        compaction_turns: OptionalCompactionTurns = None,
    ) -> ChatThreadDetail:
        session = self._hydrate(thread_id)
        if not session:
            raise ValueError("Unknown chat thread.")
        if title is None and context_mode is None and compaction_turns is None:
            raise ValueError("Provide a title, context mode, or compaction threshold.")
        async with self.locks[thread_id]:
            record = self.records[thread_id]
            before = record.model_copy(deep=True)
            if title is not None:
                title = title.strip()
                if not 1 <= len(title) <= 100:
                    raise ValueError("Title must contain 1 to 100 characters.")
                record.title = title
                record.title_source = "manual"
            if context_mode is not None:
                record.context_mode = context_mode
                session.context_mode = context_mode
            if compaction_turns is not None:
                record.compaction_turns = compaction_turns
                session.compaction_turns = compaction_turns
            record.updated_at = utc_now()
            try:
                self.chat_store.save(record)
            except Exception:
                self.records[thread_id] = before
                session.context_mode = before.context_mode
                session.compaction_turns = before.compaction_turns
                raise
            return thread_detail(record)

    async def delete_chat_thread(self, thread_id: str) -> DeleteChatThreadResult:
        UUID(thread_id)
        lock = self.locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            active = thread_id in self.sessions or thread_id in self.records
            deleted = self.chat_store.delete(thread_id) or active
            self.sessions.pop(thread_id, None)
            self.records.pop(thread_id, None)
        self.locks.pop(thread_id, None)
        return DeleteChatThreadResult(thread_id=thread_id, deleted=deleted)

    def close(self, session_id: str) -> CloseResult:
        closed = self.sessions.pop(session_id, None) is not None
        self.records.pop(session_id, None)
        self.locks.pop(session_id, None)
        return CloseResult(session_id=session_id, closed=closed)

    def _hydrate(self, thread_id: str) -> Session | None:
        if thread_id in self.sessions:
            return self.sessions[thread_id]
        record = self.chat_store.load(thread_id)
        if not record:
            return None
        recovered = False
        for turn in record.turns:
            if turn.state == "pending":
                turn.state = "interrupted"
                recovered = True
        if recovered:
            self.chat_store.save(record)
        csv_text = _demo_csv() if record.ledger_source == "demo" else record.csv_text
        assert csv_text is not None
        session = Session(
            session_id=record.thread_id,
            data=FinanceData(
                load_csv(csv_text),
                record.as_of_date,
                budget_rules=record.budget_rules,
            ),
            as_of_date=record.as_of_date,
            context_mode=record.context_mode,
            compaction_turns=record.compaction_turns,
            messages=copy.deepcopy(record.messages),
        )
        self.sessions[thread_id] = session
        self.records[thread_id] = record
        self.locks.setdefault(thread_id, asyncio.Lock())
        return session


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
        compaction_turns: CompactionTurns = 15,
        upload_name: str | None = None,
    ) -> SessionInfo:
        """Create an in-memory finance session from bundled data or validated ledger CSV."""
        return sessions.create(
            csv_text,
            as_of_date,
            context_mode,
            budget_rules,
            compaction_turns,
            upload_name,
        )

    @server.tool(structured_output=True)
    async def ask_finance_agent(
        session_id: str,
        question: str,
        context_mode: ContextMode | None = None,
        include_context: bool = False,
        compaction_turns: OptionalCompactionTurns = None,
    ) -> AgentResult:
        """Ask the hand-written finance agent a question in an existing session."""
        return await sessions.ask(
            session_id, question, context_mode, include_context, compaction_turns
        )

    @server.tool(structured_output=True)
    def close_finance_session(session_id: str) -> CloseResult:
        """Evict an in-memory finance session without deleting persisted chat history."""
        return sessions.close(session_id)

    @server.tool(structured_output=True)
    def list_chat_threads() -> ChatThreadList:
        """List persisted chat threads, newest first."""
        return sessions.list_chat_threads()

    @server.tool(structured_output=True)
    async def get_chat_thread(thread_id: str) -> ChatThreadDetail:
        """Load a persisted chat thread and make it available for continued conversation."""
        return await sessions.get_chat_thread(thread_id)

    @server.tool(structured_output=True)
    async def update_chat_thread(
        thread_id: str,
        title: str | None = None,
        context_mode: ContextMode | None = None,
        compaction_turns: OptionalCompactionTurns = None,
    ) -> ChatThreadDetail:
        """Rename a chat thread or update its mutable context settings."""
        return await sessions.update_chat_thread(
            thread_id, title, context_mode, compaction_turns
        )

    @server.tool(structured_output=True)
    async def delete_chat_thread(thread_id: str) -> DeleteChatThreadResult:
        """Permanently delete a persisted chat thread."""
        return await sessions.delete_chat_thread(thread_id)

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
