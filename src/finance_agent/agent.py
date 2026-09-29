from __future__ import annotations

import json
import os
from typing import Any, Literal, Protocol

from groq import Groq
from pydantic import BaseModel, Field, ValidationError

from .models import AgentResult, ContextManagementError, ContextReport, Session, TraceEvent


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
    def __init__(self, model: str | None = None, client: Groq | None = None):
        self.model = model or os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
        self.client = client or Groq(api_key=os.getenv("GROQ_API_KEY"))

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> AssistantTurn:
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        if response_model:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": _groq_schema(response_model),
                },
            }
        message = self.client.chat.completions.create(**kwargs).choices[0].message
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
            step=step, tool=call.name, arguments=raw_args, error=error
        )
    dumped = result.model_dump(mode="json")
    return result.model_dump_json(), TraceEvent(
        step=step, tool=call.name, arguments=args.model_dump(mode="json"), result=dumped
    )


def run_agent(
    session: Session,
    user_question: str,
    provider: ChatProvider,
    context_manager: Any | None = None,
    max_steps: int = 6,
    include_context: bool = False,
) -> AgentResult:
    session.messages.append({"role": "user", "content": user_question})
    trace: list[TraceEvent] = []
    context_report = ContextReport()

    for step in range(1, max_steps + 1):
        system = {"role": "system", "content": _system_prompt(session)}
        try:
            if context_manager:
                messages, context_report = context_manager.prepare(
                    system,
                    session,
                    provider,
                    include_messages=include_context,
                )
            else:
                messages = [system, *session.messages]
        except ContextManagementError as exc:
            return AgentResult(
                answer=f"Context management failed: {exc}",
                status="context_error",
                steps=step,
                trace=trace,
                context=context_report,
            )
        try:
            turn = provider.chat(messages, tools=TOOLS)
        except Exception as exc:
            return AgentResult(
                answer=f"The model request failed: {exc}",
                status="error",
                steps=step,
                trace=trace,
                context=context_report,
            )

        session.messages.append(_assistant_message(turn))
        if not turn.tool_calls:
            return AgentResult(
                answer=turn.content or "The model returned no answer.",
                status="ok",
                steps=step,
                trace=trace,
                context=context_report,
            )

        for call in turn.tool_calls:
            content, event = _execute_tool(session, call, step)
            trace.append(event)
            session.messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": content}
            )

    return AgentResult(
        answer="Reached the maximum of 6 agent steps without a final answer.",
        status="max_steps",
        steps=max_steps,
        trace=trace,
        context=context_report,
    )
