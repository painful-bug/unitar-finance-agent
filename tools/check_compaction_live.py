"""Live Groq/Jev regression on synthetic demo data; writes full evidence locally.

Run with GROQ_API_KEY and TYPESAFE_API_KEY exported:
    python tools/check_compaction_live.py --output /tmp/compaction-live.json
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import date
from importlib.resources import files
from pathlib import Path

from finance_agent.agent import AssistantTurn, GroqProvider, ToolCall, _assistant_message, _execute_tool, run_agent
from finance_agent.context import ContextManager
from finance_agent.finance import FinanceData, load_csv
from finance_agent.models import Session


def seeded_session(mode):
    data = FinanceData(load_csv(files("finance_agent.data").joinpath("demo.csv").read_text()), date(2026, 8, 15))
    session = Session("live-compaction-check", data, data.as_of_date, context_mode=mode, compaction_turns=5)
    for index, month in enumerate(["2026-07", "2026-08", "2026-07", "2026-06"]):
        args = {"month": month, **({"category": "groceries"} if index == 0 else {})}
        call = ToolCall(id=f"seed-{index}", name="lookup_transactions", arguments=json.dumps(args))
        content, _ = _execute_tool(session, call, 1)
        result = json.loads(content)
        session.messages.extend([
            {"role": "user", "content": f"Look up {args}; report count, total and returned transactions."},
            _assistant_message(AssistantTurn(tool_calls=[call])),
            {"role": "tool", "tool_call_id": call.id, "content": content},
            {"role": "assistant", "content": f"{result['count']} recorded transactions; RM{result['total']}. Rows: {json.dumps(result['transactions'])}"},
        ])
    return session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--modes", nargs="+", choices=("auto", "jev", "summary"), default=["auto", "jev", "summary"])
    parser.add_argument("--temperature", type=float, default=None, help="Omit to use the application's provider default")
    args = parser.parse_args()
    evidence = []
    with GroqProvider().client as client:
        provider = GroqProvider(client=client, temperature=args.temperature)
        for mode in args.modes:
            session = seeded_session(mode)
            manager = ContextManager()
            questions = [
                "Use lookup_transactions for 2026-05 with no category or kind filter. Report the exact count and total, then list the returned transactions.",
                "What were my June and July 2026 grocery expenses, and was each month within my grocery budget? Verify both months with the ledger tools.",
            ]
            for index, question in enumerate(questions):
                print(f"Checking {mode}: {question}", flush=True)
                original = copy.deepcopy(session.messages)
                events = []
                result = run_agent(session, question, provider, manager, include_context=True, event_callback=events.append)
                checks = {
                    "answer_completed": result.status == "ok",
                    "canonical_history_unchanged": session.messages[:len(original)] == original,
                    "current_request_preserved": any(m.get("content") == question for m in result.context.after_messages),
                    "no_context_expansion": result.context.after_tokens <= result.context.before_tokens,
                    "at_most_one_summary": sum(e.operation_id.endswith("-summary-model") and e.state == "started" for e in events) <= 1,
                }
                successful = [t for t in result.trace if t.result and not t.error]
                if index == 0:
                    checks["exact_empty_may_lookup"] = any(t.tool == "lookup_transactions" and t.arguments == {"month": "2026-05", "category": None, "kind": None} and t.result["count"] == 0 and t.result["total"] == "0.00" for t in successful)
                    checks["answer_reports_zero"] = "0.00" in result.answer
                else:
                    checks["both_budget_months_verified"] = {t.arguments["month"] for t in successful if t.tool == "check_budget_rule" and t.arguments["rule_id"] == "groceries_monthly_cap"} == {"2026-06", "2026-07"}
                    checks["exact_grocery_values_reported"] = all(value in result.answer.replace(",", "") for value in ("820", "690.65", "800"))
                row = {"mode": mode, "temperature": args.temperature, "question": question, "checks": checks, "result": result.model_dump(mode="json"), "events": [e.model_dump(mode="json") for e in events]}
                evidence.append(row)
                args.output.write_text(json.dumps(evidence, indent=2))
                print(json.dumps({"mode": mode, "strategy": result.context.strategy, "checks": checks}), flush=True)
    assert all(all(row["checks"].values()) for row in evidence), f"Live regression failed; see {args.output}"
    print(f"All {len(evidence)} live scenarios passed; evidence: {args.output}")


if __name__ == "__main__":
    main()
