from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .budget import BudgetRule, default_budget_rules
from .models import AgentResult, ExecutionTraceEvent


ContextMode = Literal["auto", "jev", "summary"]
TurnState = Literal["pending", "complete", "interrupted"]


class AppSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    rules_text: str = Field(default_factory=lambda: "\n".join(rule.source_text for rule in default_budget_rules()), max_length=10_000)
    rules_draft: str = Field(default_factory=lambda: "\n".join(rule.source_text for rule in default_budget_rules()), max_length=10_000)
    budget_rules: list[BudgetRule] = Field(default_factory=default_budget_rules, min_length=1, max_length=50)
    context_mode: ContextMode = "auto"
    evaluation_judge: Literal["auto", "jev", "llm"] = "auto"
    compaction_turns: int = Field(default=15, strict=True, ge=5, le=100)
    max_agent_steps: int = Field(default=15, strict=True, ge=1, le=100)

    @field_validator("budget_rules")
    @classmethod
    def unique_rules(cls, rules: list[BudgetRule]) -> list[BudgetRule]:
        if len({rule.rule_id for rule in rules}) != len(rules):
            raise ValueError("Budget rule IDs must be unique")
        return rules


class LedgerMetadata(BaseModel):
    ledger_source: Literal["demo", "upload"]
    upload_name: str | None = None
    as_of_date: date
    transaction_count: int


class TurnSettings(AppSettings):
    # Old chat snapshots could intentionally contain no budget rules.
    budget_rules: list[BudgetRule] = Field(default_factory=list)


class LedgerChange(LedgerMetadata):
    after_turn_count: int
    changed_at: datetime


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
    execution_trace_version: Literal[1] | None = None
    execution_trace: list[ExecutionTraceEvent] = Field(default_factory=list)
    ledger: LedgerMetadata | None = None
    settings: TurnSettings | None = None

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
    max_agent_steps: int = Field(default=15, ge=1, le=100)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    turns: list[ChatTurn] = Field(default_factory=list)
    ledger_changes: list[LedgerChange] = Field(default_factory=list)

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
    max_agent_steps: int
    turns: list[ChatTurn]
    ledger_changes: list[LedgerChange] = Field(default_factory=list)


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
        max_agent_steps=record.max_agent_steps,
        turns=record.turns,
        ledger_changes=record.ledger_changes,
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
        destination = self._record_path(record.thread_id)
        self._write_json(destination, record.model_dump_json(indent=2))

    def load_settings(self) -> AppSettings:
        try:
            return AppSettings.model_validate_json((self.path / "settings" / "app.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        self._write_json(self.path / "settings" / "app.json", settings.model_dump_json(indent=2))

    def _write_json(self, destination: Path, content: str) -> None:
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.chmod(0o700)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.parent.chmod(0o700)
        temporary = destination.parent / f".{destination.stem}.{uuid4()}.tmp"
        try:
            with open(temporary, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
                handle.write(content)
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
