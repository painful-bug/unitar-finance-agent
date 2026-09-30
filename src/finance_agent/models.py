from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from .finance import FinanceData


class ContextReport(BaseModel):
    strategy: Literal["none", "jev", "summary"] = "none"
    before_tokens: int = 0
    after_tokens: int = 0
    fallback_reason: str | None = None
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    before_messages: list[dict[str, Any]] = Field(default_factory=list)
    after_messages: list[dict[str, Any]] = Field(default_factory=list)


class TraceEvent(BaseModel):
    step: int
    tool: str
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class ExecutionTraceEvent(BaseModel):
    sequence: int = Field(ge=1)
    timestamp: datetime
    operation_id: str
    stage: Literal["prompt", "context", "model", "tool", "outcome"]
    state: Literal["started", "completed", "failed", "warning"]
    step: int | None = None
    tool_call_id: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset().total_seconds() != 0:
            raise ValueError("trace timestamps must use UTC")
        return value


class AgentResult(BaseModel):
    answer: str
    status: Literal["ok", "max_steps", "error", "context_error"]
    steps: int
    trace: list[TraceEvent] = Field(default_factory=list)
    context: ContextReport = Field(default_factory=ContextReport)


class ContextManagementError(RuntimeError):
    """Raised when no selected context strategy can produce a safe model input."""


@dataclass
class Session:
    session_id: str
    data: FinanceData
    as_of_date: date
    context_mode: Literal["auto", "jev", "summary"] = "auto"
    compaction_turns: int = 15
    max_agent_steps: int = 15
    messages: list[dict[str, Any]] = field(default_factory=list)
