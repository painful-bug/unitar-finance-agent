from __future__ import annotations

import asyncio
import copy
import json
import os
from concurrent.futures import Future
from datetime import date
from importlib.resources import files
from time import monotonic
from typing import Annotated, Awaitable, Callable, Literal
from uuid import UUID, uuid4

from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, Field

from .agent import ChatProvider, GroqProvider, run_agent
from .budget import BudgetRule, BudgetRulePreview, parse_budget_rules as compile_budget_rules
from .context import ContextManager
from .finance import FinanceData, load_csv
from .models import AgentResult, ContextReport, ExecutionTraceEvent, Session
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
AgentSteps = Annotated[int, Field(strict=True, ge=1, le=100)]
OptionalAgentSteps = Annotated[int | None, Field(strict=True, ge=1, le=100)]


class SessionInfo(BaseModel):
    session_id: str
    as_of_date: date
    context_mode: ContextMode
    transaction_count: int
    budget_rules: list[BudgetRule]
    compaction_turns: CompactionTurns
    max_agent_steps: AgentSteps
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
        self.running: dict[str, asyncio.Task[AgentResult]] = {}

    def create(
        self,
        csv_text: str | None = None,
        as_of_date: date | None = None,
        context_mode: ContextMode = "auto",
        budget_rules: list[BudgetRule] | None = None,
        compaction_turns: CompactionTurns = 15,
        max_agent_steps: AgentSteps = 15,
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
            max_agent_steps=max_agent_steps,
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
            max_agent_steps=max_agent_steps,
        )
        return SessionInfo(
            session_id=session_id,
            as_of_date=anchor,
            context_mode=context_mode,
            transaction_count=len(transactions),
            budget_rules=session.data.budget_rules,
            compaction_turns=compaction_turns,
            max_agent_steps=max_agent_steps,
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
        on_progress: Callable[[dict], Awaitable[None]] | None = None,
    ) -> AgentResult:
        if session_id in self.running:
            raise ValueError("This chat already has a running question.")
        notifications: asyncio.Queue[dict] = asyncio.Queue()
        task = asyncio.create_task(self._ask(session_id, question, context_mode, include_context, compaction_turns, notifications))
        self.running[session_id] = task

        def finished(completed: asyncio.Task) -> None:
            self.running.pop(session_id, None)
            if not completed.cancelled():
                completed.exception()  # Retrieve errors even when the requesting browser disconnected.

        task.add_done_callback(finished)

        async def deliver() -> None:
            enabled = on_progress is not None
            while True:
                envelope = await notifications.get()
                try:
                    if enabled and on_progress:
                        await asyncio.wait_for(on_progress(envelope), timeout=2)
                except Exception:
                    enabled = False  # Delivery failure never stops capture or execution.
                finally:
                    notifications.task_done()

        delivery = asyncio.create_task(deliver())
        try:
            result = await asyncio.shield(task)
            # Let the final saved event reach the requesting client before its result.
            try:
                await asyncio.wait_for(notifications.join(), timeout=2.5)
            except TimeoutError:
                pass  # A slow subscriber cannot turn a saved successful answer into an error.
            return result
        finally:
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)

    async def _ask(
        self,
        session_id: str,
        question: str,
        context_mode: ContextMode | None,
        include_context: bool,
        compaction_turns: OptionalCompactionTurns,
        notifications: asyncio.Queue[dict],
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
                execution_trace_version=1,
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

            loop = asyncio.get_running_loop()
            milestones: asyncio.Queue[tuple[ExecutionTraceEvent, Future] | None] = asyncio.Queue()
            storage_error: Exception | None = None
            terminal: ExecutionTraceEvent | None = None
            started = monotonic()

            def capture(event: ExecutionTraceEvent) -> None:
                acknowledgement: Future = Future()
                loop.call_soon_threadsafe(milestones.put_nowait, (event, acknowledgement))
                acknowledgement.result()  # Do not start another stage before its trace is durable.

            def execute() -> AgentResult:
                try:
                    try:
                        provider = self.provider or GroqProvider()
                    except Exception as exc:
                        capture(ExecutionTraceEvent(sequence=1, timestamp=utc_now(), stage="prompt", state="completed", operation_id="prompt", payload={"question": question}))
                        return AgentResult(answer=f"The model provider is not configured: {exc}", status="error", steps=0)
                    return run_agent(session, question, provider, self.context_manager,
                                     max_steps=session.max_agent_steps,
                                     include_context=include_context, event_callback=capture)
                finally:
                    loop.call_soon_threadsafe(milestones.put_nowait, None)

            worker = asyncio.create_task(asyncio.to_thread(execute))
            while (item := await milestones.get()) is not None:
                event, acknowledgement = item
                if storage_error:
                    acknowledgement.set_exception(storage_error)
                    continue
                if event.stage == "outcome":
                    terminal = event
                    acknowledgement.set_result(None)
                    continue
                turn.execution_trace.append(event)
                record.updated_at = utc_now()
                try:
                    # ponytail: rewrite the local thread per milestone; add an event journal only after measured I/O pain.
                    self.chat_store.save(record)
                except Exception as exc:
                    turn.execution_trace.pop()
                    storage_error = exc
                    acknowledgement.set_exception(exc)
                else:
                    notifications.put_nowait(dict(version=1, thread_id=session_id, turn_id=turn.turn_id, event=event.model_dump(mode="json")))
                    acknowledgement.set_result(None)
            try:
                try:
                    result = await worker
                except Exception as exc:
                    if storage_error:
                        raise storage_error
                    result = AgentResult(answer=f"Agent execution failed: {exc}", status="error", steps=max((event.step or 0 for event in turn.execution_trace), default=0))
                if not terminal:
                    terminal = ExecutionTraceEvent(sequence=len(turn.execution_trace) + 1, timestamp=utc_now(), stage="outcome", state="failed", operation_id="outcome", duration_ms=(monotonic() - started) * 1000, payload={"answer": result.answer, "status": result.status, "steps": result.steps})
                turn.execution_trace.append(terminal)
                turn.state = "complete"
                turn.result = result
                record.messages = copy.deepcopy(session.messages)
                record.updated_at = utc_now()
                self.chat_store.save(record)
            except Exception:
                session.messages = before_session_messages
                persisted = self.chat_store.load(session_id)
                self.records[session_id] = persisted or before_record
                for saved_turn in self.records[session_id].turns:
                    if saved_turn.turn_id == turn.turn_id:
                        saved_turn.state = "interrupted"
                raise
            notifications.put_nowait(dict(version=1, thread_id=session_id, turn_id=turn.turn_id, event=terminal.model_dump(mode="json")))
            return result

    def list_chat_threads(self) -> ChatThreadList:
        return self.chat_store.list()

    async def get_chat_thread(self, thread_id: str) -> ChatThreadDetail:
        session = self._hydrate(thread_id)
        if not session:
            raise ValueError("Unknown chat thread.")
        return thread_detail(self.records[thread_id]).model_copy(deep=True)

    async def update_chat_thread(
        self,
        thread_id: str,
        title: str | None = None,
        context_mode: ContextMode | None = None,
        compaction_turns: OptionalCompactionTurns = None,
        max_agent_steps: OptionalAgentSteps = None,
    ) -> ChatThreadDetail:
        session = self._hydrate(thread_id)
        if not session:
            raise ValueError("Unknown chat thread.")
        if title is None and context_mode is None and compaction_turns is None and max_agent_steps is None:
            raise ValueError("Provide a title, context mode, compaction threshold, or agent step limit.")
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
            if max_agent_steps is not None:
                record.max_agent_steps = max_agent_steps
                session.max_agent_steps = max_agent_steps
            record.updated_at = utc_now()
            try:
                self.chat_store.save(record)
            except Exception:
                self.records[thread_id] = before
                session.context_mode = before.context_mode
                session.compaction_turns = before.compaction_turns
                session.max_agent_steps = before.max_agent_steps
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
        if session_id in self.running:
            raise ValueError("Cannot close a session while its question is running.")
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
            max_agent_steps=record.max_agent_steps,
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
        max_agent_steps: AgentSteps = 15,
        upload_name: str | None = None,
    ) -> SessionInfo:
        """Create an in-memory finance session from bundled data or validated ledger CSV."""
        return sessions.create(
            csv_text,
            as_of_date,
            context_mode,
            budget_rules,
            compaction_turns,
            max_agent_steps,
            upload_name,
        )

    @server.tool(structured_output=True)
    async def ask_finance_agent(
        session_id: str,
        question: str,
        ctx: Context,
        context_mode: ContextMode | None = None,
        include_context: bool = False,
        compaction_turns: OptionalCompactionTurns = None,
    ) -> AgentResult:
        """Ask the hand-written finance agent a question in an existing session."""
        async def progress(envelope: dict) -> None:
            await ctx.report_progress(envelope["event"]["sequence"], message=json.dumps(envelope))
        return await sessions.ask(
            session_id, question, context_mode, include_context, compaction_turns, progress,
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
        max_agent_steps: OptionalAgentSteps = None,
    ) -> ChatThreadDetail:
        """Rename a chat thread or update its mutable context settings."""
        return await sessions.update_chat_thread(
            thread_id, title, context_mode, compaction_turns, max_agent_steps
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
        json_response=False,
    )


if __name__ == "__main__":
    main()
