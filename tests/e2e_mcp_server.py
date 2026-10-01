"""Deterministic MCP process for browser tests; never imported by production code."""

from __future__ import annotations

import json
import os
import shutil
import time
from decimal import Decimal
from pathlib import Path

from finance_agent.agent import AssistantTurn, ToolCall
from finance_agent.budget import BudgetRule, BudgetRuleSet, Operand, default_budget_rules
from finance_agent.context import ContextManager
from finance_agent.server import SessionStore, build_server
from finance_agent.threads import ChatStore


DEFAULT_RULES_TEXT = "\n".join(rule.source_text for rule in default_budget_rules())


class DeterministicProvider:
    def __init__(self):
        self.tool_calls = 0

    def chat(self, messages, tools=None, response_model=None):
        if response_model is BudgetRuleSet:
            rules_text = json.loads(messages[-1]["content"])["rules"]
            rules = default_budget_rules()
            if rules_text != DEFAULT_RULES_TEXT:
                custom = BudgetRule(
                    rule_id="savings_target",
                    source_text=rules_text,
                    left=Operand(metric="savings", unit="RM"),
                    operator="gte",
                    right=Operand(
                        metric="income",
                        unit="RM",
                        multiplier=Decimal("0.25"),
                    ),
                )
                rules = [*rules, custom] if rules_text.startswith(DEFAULT_RULES_TEXT) else [custom]
            return AssistantTurn(
                content=json.dumps({"rules": [rule.model_dump(mode="json") for rule in rules]})
            )

        if not tools:
            return AssistantTurn(content="Earlier finance questions were answered from the ledger tools.")

        question = next((message.get("content", "") for message in reversed(messages) if message["role"] == "user"), "")
        if "Trace slowly" in question:
            time.sleep(1.5)  # Expose running stages to browser tests before each deterministic response.
        if messages[-1]["role"] == "tool":
            return AssistantTurn(content="Deterministic finance answer from the active ledger.")
        self.tool_calls += 1
        if "Check savings target" in question:
            return AssistantTurn(tool_calls=[ToolCall(
                id=f"deterministic-budget-{self.tool_calls}", name="check_budget_rule",
                arguments='{"rule_id":"savings_target","month":"2026-07"}',
            )])
        return AssistantTurn(
            tool_calls=[
                ToolCall(
                    id=f"deterministic-savings-{self.tool_calls}",
                    name="calculate_savings_rate",
                    arguments='{"month":"2026-08"}',
                )
            ]
        )


class DeterministicJev:
    def noul_scores(self, state, questions):
        return {name: 0.0 for name in questions}


CHAT_STORE_PATH = Path(os.getenv("FINANCE_CHAT_STORE_PATH", "/tmp/finance-agent-e2e-chats"))
if os.getenv("FINANCE_E2E_RESET_CHAT_STORE") == "1":
    shutil.rmtree(CHAT_STORE_PATH, ignore_errors=True)


SERVER = build_server(
    SessionStore(
        provider=DeterministicProvider(),
        context_manager=ContextManager(DeterministicJev()),
        chat_store=ChatStore(CHAT_STORE_PATH),
    )
)


if __name__ == "__main__":
    try:
        SERVER.run(
            transport="streamable-http",
            host=os.getenv("MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("MCP_PORT", "8001")),
            streamable_http_path="/mcp",
            json_response=False,
        )
    except KeyboardInterrupt:
        pass
