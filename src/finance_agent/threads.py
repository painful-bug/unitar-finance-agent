from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .budget import BudgetRule
from .models import AgentResult


ContextMode = Literal["auto", "jev", "summary"]
TurnState = Literal["pending", "complete", "interrupted"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("chat timestamps must use UTC")
    return value


def chat_title(question: str) -> str:
    normalized = " ".join(question.split())
    return normalized if len(normalized) <= 48 else f"{normalized[:47]}…"


class ChatTurn(BaseModel):
    turn_id: str
    created_at: datetime
    question: str
    state: TurnState = "pending"
    result: AgentResult | None = None

    @field_validator("turn_id")
    @classmethod
    def valid_turn_id(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        return _require_utc(value)


class ChatThreadRecord(BaseModel):
    version: Literal[1] = 1
    thread_id: str
    title: str = Field(default="New chat", min_length=1, max_length=100)
    title_source: Literal["auto", "manual"] = "auto"
    created_at: datetime
    updated_at: datetime
    ledger_source: Literal["demo", "upload"]
    upload_name: str | None = None
    csv_text: str | None = None
    as_of_date: date
    context_mode: ContextMode
    transaction_count: int
    budget_rules: list[BudgetRule]
    compaction_turns: int = Field(ge=5, le=100)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    turns: list[ChatTurn] = Field(default_factory=list)

    @field_validator("thread_id")
    @classmethod
    def valid_thread_id(cls, value: str) -> str:
        UUID(value)
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamps(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def valid_ledger(self) -> ChatThreadRecord:
        if self.ledger_source == "upload" and not self.csv_text:
            raise ValueError("uploaded chat threads require CSV data")
        if self.ledger_source == "demo" and self.csv_text is not None:
            raise ValueError("demo chat threads cannot contain CSV data")
        return self


class ChatThreadSummary(BaseModel):
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    turn_count: int
    ledger_source: Literal["demo", "upload"]
    upload_name: str | None = None


class ChatThreadList(BaseModel):
    threads: list[ChatThreadSummary]
    skipped_files: int = 0


class ChatThreadDetail(BaseModel):
    summary: ChatThreadSummary
    as_of_date: date
    context_mode: ContextMode
    transaction_count: int
    budget_rules: list[BudgetRule]
    compaction_turns: int
    turns: list[ChatTurn]


class DeleteChatThreadResult(BaseModel):
    thread_id: str
    deleted: bool


def thread_summary(record: ChatThreadRecord) -> ChatThreadSummary:
    return ChatThreadSummary(
        thread_id=record.thread_id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        turn_count=len(record.turns),
        ledger_source=record.ledger_source,
        upload_name=record.upload_name,
    )


def thread_detail(record: ChatThreadRecord) -> ChatThreadDetail:
    return ChatThreadDetail(
        summary=thread_summary(record),
        as_of_date=record.as_of_date,
        context_mode=record.context_mode,
        transaction_count=record.transaction_count,
        budget_rules=record.budget_rules,
        compaction_turns=record.compaction_turns,
        turns=record.turns,
    )


class ChatStore:
    def __init__(self, path: Path | None = None):
        configured = os.getenv("FINANCE_CHAT_STORE_PATH")
        self.path = path or (
            Path(configured).expanduser()
            if configured
            else Path.home() / ".finance-agent" / "chats"
        )

    def save(self, record: ChatThreadRecord) -> None:
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.chmod(0o700)
        destination = self._record_path(record.thread_id)
        temporary = self.path / f".{record.thread_id}.{uuid4()}.tmp"
        try:
            temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def load(self, thread_id: str) -> ChatThreadRecord | None:
        try:
            return ChatThreadRecord.model_validate_json(
                self._record_path(thread_id).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return None

    def list(self) -> ChatThreadList:
        if not self.path.exists():
            return ChatThreadList(threads=[])
        records: list[ChatThreadRecord] = []
        skipped = 0
        # ponytail: an O(n) scan is enough for a local beta; add an index only after measured pain.
        for path in self.path.glob("*.json"):
            try:
                records.append(ChatThreadRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                skipped += 1
        records.sort(key=lambda item: (item.updated_at, item.created_at), reverse=True)
        return ChatThreadList(
            threads=[thread_summary(record) for record in records],
            skipped_files=skipped,
        )

    def delete(self, thread_id: str) -> bool:
        path = self._record_path(thread_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _record_path(self, thread_id: str) -> Path:
        parsed = UUID(thread_id)
        return self.path / f"{parsed}.json"
