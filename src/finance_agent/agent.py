from __future__ import annotations

import json
import os
from time import monotonic
from typing import Any, Literal, Protocol

from groq import Groq
from pydantic import BaseModel, Field, ValidationError

from .models import AgentResult, ContextManagementError, ContextReport, Session, TraceEvent
from .tracing import EventCallback, MilestoneCallback, TraceRecorder, operation


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str


class AssistantTurn(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ChatProvider(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> AssistantTurn: ...


class LookupArgs(BaseModel):
    month: str
    category: str | None = None
    kind: Literal["income", "expense"] | None = None


class BudgetArgs(BaseModel):
    rule_id: str
    month: str


class SavingsArgs(BaseModel):
    month: str


ARGUMENT_MODELS = {
    "lookup_transactions": LookupArgs,
    "check_budget_rule": BudgetArgs,
    "calculate_savings_rate": SavingsArgs,
}

TOOL_DESCRIPTIONS = {
    "lookup_transactions": "Look up ledger rows and their exact total for a month.",
    "check_budget_rule": "Check a named budget rule against the ledger for a month.",
    "calculate_savings_rate": "Calculate income, expenses, savings, and savings rate for a month.",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": model.model_json_schema(),
        },
    }
    for name, model in ARGUMENT_MODELS.items()
]


def _groq_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def clean(value: Any) -> None:
        if isinstance(value, dict):
            pattern = value.get("pattern")
            if isinstance(pattern, str) and "(?" in pattern:
                value.pop("pattern")
            if value.get("type") == "object" and "properties" in value:
                value["required"] = list(value["properties"])
            for child in value.values():
                clean(child)
        elif isinstance(value, list):
            for child in value:
                clean(child)

    clean(schema)
    return schema


class GroqProvider:
    def __init__(self, model: str | None = None, client: Groq | None = None, temperature: float | None = None):
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.client = client or Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.temperature = temperature

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: type[BaseModel] | None = None,
        event_callback: MilestoneCallback | None = None,
    ) -> AssistantTurn:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if response_model:
            kwargs["temperature"] = 0
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": _groq_schema(response_model),
                },
            }
        choice = self.client.chat.completions.create(**kwargs).choices[0]
        message = choice.message
        if not message.tool_calls and not (message.content or "").strip():
            if event_callback:
                event_callback(dict(stage="model", state="warning", operation_id="empty-response",
                                    payload={"message": "Empty model response; retrying once."}))
            kwargs["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Your previous response was empty. Continue with a ledger tool call "
                        "or a non-empty answer. If the requested information is unavailable, "
                        "explain the limitation."
                    ),
                },
            ]
            with operation(event_callback, "model", "retry", model=self.model, message_count=len(kwargs["messages"]), tool_count=len(tools or [])) as retry:
                choice = self.client.chat.completions.create(**kwargs).choices[0]
                message = choice.message
                retry.update(content=message.content, tool_calls=[{"id": call.id, "name": call.function.name, "arguments": call.function.arguments} for call in (message.tool_calls or [])])
            if not message.tool_calls and not (message.content or "").strip():
                raise ValueError(
                    f"Model returned no answer or tool calls after one retry "
                    f"(finish_reason={choice.finish_reason})."
                )
        calls = [
            ToolCall(id=call.id, name=call.function.name, arguments=call.function.arguments)
            for call in (message.tool_calls or [])
        ]
        content = message.content
        if response_model and content:
            content = response_model.model_validate_json(content).model_dump_json()
        return AssistantTurn(content=content, tool_calls=calls)


def _system_prompt(session: Session) -> str:
    categories = sorted({item.category for item in session.data.transactions})
    budget_rules = "; ".join(
        f"{rule.rule_id}: {rule.source_text}" for rule in session.data.budget_rules
    )
    return (
        "You are a personal finance assistant. Answer only from the supplied ledger tools; "
        "never guess or do arithmetic yourself. Use tools for every financial value. "
        f"The session as-of date is {session.as_of_date.isoformat()}. "
        f"Known categories: {', '.join(categories)}. "
        f"Budget rules: {budget_rules or 'none configured'}."
    )


def _assistant_message(turn: AssistantTurn) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": turn.content}
    if turn.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in turn.tool_calls
        ]
    return message


def _execute_tool(session: Session, call: ToolCall, step: int) -> tuple[str, TraceEvent]:
    model = ARGUMENT_MODELS.get(call.name)
    if model is None:
        error = f"unknown tool: {call.name}"
        return json.dumps({"error": error}), TraceEvent(step=step, tool=call.name, error=error)
    try:
        raw_args = json.loads(call.arguments)
    except json.JSONDecodeError:
        error = "invalid JSON tool arguments"
        return json.dumps({"error": error}), TraceEvent(step=step, tool=call.name, error=error)
    try:
        args = model.model_validate(raw_args)
        result = getattr(session.data, call.name)(**args.model_dump())
    except (ValidationError, ValueError) as exc:
        error = f"invalid tool arguments: {exc}"
        return json.dumps({"error": error}), TraceEvent(
            step=step, tool=call.name, arguments=raw_args if isinstance(raw_args, dict) else None, error=error
        )
    dumped = result.model_dump(mode="json")
    return result.model_dump_json(), TraceEvent(
        step=step, tool=call.name, arguments=args.model_dump(mode="json"), result=dumped
    )


def _run_agent(
    session: Session,
    user_question: str,
    provider: ChatProvider,
    context_manager: Any | None = None,
    max_steps: int = 15,
    include_context: bool = False,
    emit: MilestoneCallback | None = None,
    system_prompt: str | None = None,
) -> AgentResult:
    session.messages.append({"role": "user", "content": user_question})
    trace: list[TraceEvent] = []
    context_report = ContextReport()

    for step in range(1, max_steps + 1):
        system = {"role": "system", "content": _system_prompt(session)}
        if system_prompt:
            system["content"] += "\n\n" + system_prompt
        try:
            with operation(emit, "context", f"context-{step}", step=step, strategy=session.context_mode) as context_payload:
                if context_manager:
                    extra = {"event_callback": lambda event: emit({**event, "step": step, "operation_id": f"context-{step}-{event['operation_id']}"})} if emit else {}
                    messages, context_report = context_manager.prepare(
                        system, session, provider, include_messages=include_context, **extra,
                    )
                else:
                    messages = [system, *session.messages]
                context_payload.update(context_report.model_dump(mode="json", exclude={"before_messages", "after_messages"}))
        except ContextManagementError as exc:
            return AgentResult(
                answer=f"Context management failed: {exc}",
                status="context_error",
                steps=step,
                trace=trace,
                context=context_report,
            )
        try:
            with operation(emit, "model", f"model-{step}", step=step, model=getattr(provider, "model", None), message_count=len(messages), tool_count=len(TOOLS)) as model_payload:
                extra = {"event_callback": lambda event: emit({**event, "step": step, "operation_id": f"model-{step}-{event['operation_id']}"})} if emit and isinstance(provider, GroqProvider) else {}
                turn = provider.chat(messages, tools=TOOLS, **extra)
                model_payload.update(content=turn.content, tool_calls=[call.model_dump(mode="json") for call in turn.tool_calls])
                if not turn.tool_calls and not (turn.content or "").strip():
                    model_payload["error"] = "The model returned no answer or tool calls."
        except Exception as exc:
            return AgentResult(
                answer=f"The model request failed: {exc}",
                status="error",
                steps=step,
                trace=trace,
                context=context_report,
            )

        if not turn.tool_calls and not (turn.content or "").strip():
            return AgentResult(
                answer="The model returned no answer or tool calls. Please try again.",
                status="error",
                steps=step,
                trace=trace,
                context=context_report,
            )

        session.messages.append(_assistant_message(turn))
        if not turn.tool_calls:
            return AgentResult(
                answer=turn.content,
                status="ok",
                steps=step,
                trace=trace,
                context=context_report,
            )

        for index, call in enumerate(turn.tool_calls):
            with operation(emit, "tool", f"tool-{step}-{index}", step=step, tool_call_id=call.id, tool=call.name, raw_arguments=call.arguments) as tool_payload:
                content, event = _execute_tool(session, call, step)
                tool_payload.update(event.model_dump(mode="json"))
            trace.append(event)
            session.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": content}
            )

    return AgentResult(
        answer=f"Reached the maximum of {max_steps} agent steps without a final answer.",
        status="max_steps",
        steps=max_steps,
        trace=trace,
        context=context_report,
    )


def run_agent(
    session: Session,
    user_question: str,
    provider: ChatProvider,
    context_manager: Any | None = None,
    max_steps: int = 15,
    include_context: bool = False,
    event_callback: EventCallback | None = None,
    system_prompt: str | None = None,
) -> AgentResult:
    """Run the finance loop; optional instructions follow the standard tool prompt."""
    recorder = TraceRecorder(event_callback)
    started = monotonic()
    recorder.emit(dict(stage="prompt", state="completed", operation_id="prompt", payload={"question": user_question}))
    result = _run_agent(session, user_question, provider, context_manager, max_steps, include_context,
                        recorder.emit if event_callback else None, system_prompt)
    recorder.emit(dict(stage="outcome", state="completed" if result.status == "ok" else "failed",
                       operation_id="outcome", duration_ms=(monotonic() - started) * 1000,
                       payload={"answer": result.answer, "status": result.status, "steps": result.steps}))
    return result
