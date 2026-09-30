from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Iterator

from .models import ExecutionTraceEvent

MilestoneCallback = Callable[[dict[str, Any]], None]
EventCallback = Callable[[ExecutionTraceEvent], None]


class TraceRecorder:
    def __init__(self, callback: EventCallback | None):
        self.callback = callback
        self.sequence = 0

    def emit(self, milestone: dict[str, Any]) -> None:
        self.sequence += 1
        event = ExecutionTraceEvent(
            sequence=self.sequence,
            timestamp=datetime.now(timezone.utc),
            **milestone,
        )
        if self.callback:
            self.callback(event)


@contextmanager
def operation(
    emit: MilestoneCallback | None,
    stage: str,
    operation_id: str,
    *,
    step: int | None = None,
    tool_call_id: str | None = None,
    **payload: Any,
) -> Iterator[dict[str, Any]]:
    started = monotonic()
    base = dict(stage=stage, operation_id=operation_id, step=step, tool_call_id=tool_call_id)
    if emit:
        emit({**base, "state": "started", "payload": dict(payload)})
    try:
        yield payload
    except Exception as exc:
        if emit:
            emit({**base, "state": "failed", "duration_ms": (monotonic() - started) * 1000,
                  "payload": {**payload, "error": str(exc)}})
        raise
    else:
        if emit:
            emit({**base, "state": "failed" if payload.get("error") else "completed",
                  "duration_ms": (monotonic() - started) * 1000, "payload": payload})
