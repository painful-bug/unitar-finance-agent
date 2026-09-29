from __future__ import annotations

import copy
import json
import math
import os
from typing import Any, Protocol

from typesafe_sdk import Noul

from .agent import ChatProvider, GroqProvider
from .jev import JevClient
from .models import ContextManagementError, ContextReport, Session


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return math.ceil(len(json.dumps(messages, default=str, ensure_ascii=False)) / 4)


def _excerpt(text: str, size: int = 300) -> str:
    if len(text) <= size * 2:
        return text
    omitted = len(text) - size * 2
    return f"{text[:size]}\n[… {omitted} characters omitted …]\n{text[-size:]}"


class JevJudge(Protocol):
    def noul_scores(
        self, state: dict[str, Any], questions: dict[str, Noul]
    ) -> dict[str, float]: ...


def _tool_pairs(messages: list[dict[str, Any]], preserve_recent: int) -> dict[str, tuple[int, int]]:
    cut = max(0, len(messages) - preserve_recent)
    calls: dict[str, int] = {}
    results: dict[str, int] = {}
    for index, message in enumerate(messages):
        for call in message.get("tool_calls", []):
            calls[call["id"]] = index
        if message.get("role") == "tool" and message.get("tool_call_id"):
            results[message["tool_call_id"]] = index
    return {
        call_id: (call_index, results[call_id])
        for call_id, call_index in calls.items()
        if call_id in results and call_index < cut and results[call_id] < cut
    }


def _jev_state(session: Session) -> dict[str, Any]:
    conversation = copy.deepcopy(session.messages)
    for message in conversation:
        if message.get("role") == "tool":
            message["content"] = _excerpt(str(message.get("content", "")))
    recent_goals = [
        str(message.get("content", ""))
        for message in session.messages
        if message.get("role") == "user"
    ][-3:]
    return {"current_goals": recent_goals, "conversation": conversation}


def _questions(call_ids: list[str]) -> dict[str, Noul]:
    questions: dict[str, Noul] = {}
    for call_id in call_ids:
        questions[f"call_{call_id}"] = Noul(
            instructions=(
                f"Tool call {call_id} carries information the current goals still depend on: "
                "an input, constraint, decision, or action that was taken."
            )
        )
        questions[f"result_{call_id}"] = Noul(
            instructions=(
                f"The exact result of tool call {call_id} contains information needed to continue "
                "correctly, such as a date, amount, status, error, or user-relevant finding."
            )
        )
    return questions


def _apply_decisions(
    messages: list[dict[str, Any]],
    pairs: dict[str, tuple[int, int]],
    scores: dict[str, float],
    threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actions: dict[str, str] = {}
    decision_log: list[dict[str, Any]] = []
    for call_id in pairs:
        call_score = scores[f"call_{call_id}"]
        result_score = scores[f"result_{call_id}"]
        action = "keep" if result_score >= threshold else ("trim" if call_score >= threshold else "drop")
        actions[call_id] = action
        decision_log.append(
            {
                "tool_call_id": call_id,
                "call_probability": call_score,
                "result_probability": result_score,
                "action": action,
            }
        )

    rebuilt: list[dict[str, Any]] = []
    for original in messages:
        message = copy.deepcopy(original)
        if message.get("tool_calls"):
            message["tool_calls"] = [
                call for call in message["tool_calls"] if actions.get(call["id"]) != "drop"
            ]
            if not message["tool_calls"]:
                message.pop("tool_calls")
                if not message.get("content"):
                    continue
        if message.get("role") == "tool":
            action = actions.get(message.get("tool_call_id"))
            if action == "drop":
                continue
            if action == "trim":
                message["content"] = _excerpt(str(message.get("content", "")))
        rebuilt.append(message)
    return rebuilt, decision_log


def _safe_prefix_cut(messages: list[dict[str, Any]], desired: int) -> int:
    cut = desired
    pairs = _tool_pairs(messages, preserve_recent=0)
    changed = True
    while changed:
        changed = False
        for call_index, result_index in pairs.values():
            if call_index < cut <= result_index:
                cut = call_index
                changed = True
    return cut


class ContextManager:
    def __init__(
        self,
        jev: JevJudge | None = None,
        *,
        trigger_tokens: int = 8_000,
        preserve_recent: int = 6,
        keep_threshold: float = 0.5,
        min_reduction: float = 0.05,
    ):
        self.jev = jev or JevClient()
        self.trigger_tokens = trigger_tokens
        self.preserve_recent = preserve_recent
        self.keep_threshold = keep_threshold
        self.min_reduction = min_reduction

    def prepare(
        self,
        system: dict[str, Any],
        session: Session,
        provider: ChatProvider,
        mode: str | None = None,
    ) -> tuple[list[dict[str, Any]], ContextReport]:
        full = [system, *session.messages]
        before = estimate_tokens(full)
        if before < self.trigger_tokens:
            return full, ContextReport(before_tokens=before, after_tokens=before)

        selected = mode or session.context_mode
        if selected == "summary":
            try:
                return self._summarize(system, session, provider, before)
            except Exception as exc:
                raise ContextManagementError(f"Groq summary failed: {exc}") from exc
        if selected == "jev":
            try:
                return self._compact_with_jev(system, session, before)
            except Exception as exc:
                raise ContextManagementError(f"Jev compaction failed: {exc}") from exc
        if selected != "auto":
            raise ValueError(f"unknown context mode: {selected}")

        try:
            compacted, report = self._compact_with_jev(system, session, before)
            reduction = 1 - report.after_tokens / max(1, report.before_tokens)
            if reduction >= self.min_reduction:
                return compacted, report
            reason = f"Jev removed less than {self.min_reduction:.0%}"
        except Exception as exc:
            reason = str(exc)
        try:
            return self._summarize(system, session, provider, before, fallback_reason=reason)
        except Exception as exc:
            raise ContextManagementError(
                f"Jev failed ({reason}); Groq summary failed ({exc})"
            ) from exc

    def _compact_with_jev(
        self, system: dict[str, Any], session: Session, before: int
    ) -> tuple[list[dict[str, Any]], ContextReport]:
        pairs = _tool_pairs(session.messages, self.preserve_recent)
        if not pairs:
            raise ValueError("no old complete tool calls are eligible for Jev")
        questions = _questions(list(pairs))
        scores = self.jev.noul_scores(_jev_state(session), questions)
        compacted_history, decisions = _apply_decisions(
            session.messages, pairs, scores, self.keep_threshold
        )
        compacted = [system, *compacted_history]
        return compacted, ContextReport(
            strategy="jev",
            before_tokens=before,
            after_tokens=estimate_tokens(compacted),
            decisions=decisions,
        )

    def _summarize(
        self,
        system: dict[str, Any],
        session: Session,
        provider: ChatProvider,
        before: int,
        fallback_reason: str | None = None,
    ) -> tuple[list[dict[str, Any]], ContextReport]:
        desired = max(0, len(session.messages) - self.preserve_recent)
        cut = _safe_prefix_cut(session.messages, desired)
        if cut == 0:
            raise ValueError("no old history is eligible for summarization")
        prompt = (
            "Summarize only the eligible prefix of this finance session. Use the complete session "
            "for relevance. Preserve dates, RM amounts, budget outcomes, user constraints, unresolved "
            "questions, and tool findings. Do not add facts.\n\n"
            f"Eligible prefix message count: {cut}\n"
            f"Complete session:\n{json.dumps(session.messages, ensure_ascii=False, default=str)}"
        )
        summary_model = os.getenv("GROQ_SUMMARY_MODEL")
        summary_provider = GroqProvider(summary_model) if summary_model else provider
        turn = summary_provider.chat(
            [
                {"role": "system", "content": "You produce concise, factual conversation summaries."},
                {"role": "user", "content": prompt},
            ]
        )
        if not turn.content:
            raise ValueError("summary model returned no content")
        compacted = [
            system,
            {"role": "system", "content": f"Lossy summary of earlier session history:\n{turn.content}"},
            *copy.deepcopy(session.messages[cut:]),
        ]
        return compacted, ContextReport(
            strategy="summary",
            before_tokens=before,
            after_tokens=estimate_tokens(compacted),
            fallback_reason=fallback_reason,
        )
