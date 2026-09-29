from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import streamlit as st

from finance_agent.context import ContextManager, estimate_tokens
from finance_agent.finance import FinanceData, load_csv
from finance_agent.jev import JevClient
from finance_agent.models import Session


ROOT = Path(__file__).resolve().parents[1]
SYSTEM = {
    "role": "system",
    "content": "You are a grounded finance assistant. Use ledger tools for every financial value.",
}


class DeterministicDemoJev:
    """Clearly labeled offline scores for a reliable presentation fallback."""

    def noul_scores(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for name in questions:
            call_id = name.split("_", 1)[1]
            index = int(call_id.split("-")[-1])
            pattern = index % 3
            scores[name] = (
                0.1
                if pattern == 0
                else 0.9
                if pattern == 1 and name.startswith("call_")
                else 0.2
                if pattern == 1
                else 0.9
            )
        return scores


class UnusedProvider:
    def chat(self, messages, tools=None, response_model=None):
        raise RuntimeError("summary generation is not used by this Jev-only demo")


def _large_ledger() -> FinanceData:
    rows = ["date,kind,category,amount,merchant"]
    for month in range(1, 13):
        rows.append(f"2026-{month:02d}-01,income,salary,8000.00,Employer")
        for index in range(100):
            category = "groceries" if index % 2 == 0 else "dining"
            merchant = "Market" if category == "groceries" else "Cafe"
            amount = Decimal("10.00") + Decimal(index) / 10
            rows.append(
                f"2026-{month:02d}-{index % 28 + 1:02d},expense,{category},{amount:.2f},{merchant}-{index:03d}"
            )
    return FinanceData(load_csv("\n".join(rows)), date(2026, 12, 31))


def _scenario_prompts() -> list[str]:
    cases = json.loads((ROOT / "evals/golden.json").read_text(encoding="utf-8"))
    return next(case["prompts"] for case in cases if case["id"] == "twelve_turn_context")


def build_demo_session() -> Session:
    data = _large_ledger()
    session = Session("context-demo", data, date(2026, 12, 31), context_mode="jev")
    actions = [
        ("lookup_transactions", {"month": "2026-06", "category": "groceries", "kind": "expense"}),
        ("lookup_transactions", {"month": "2026-06", "category": "dining", "kind": "expense"}),
        ("check_budget_rule", {"rule_id": "groceries_monthly_cap", "month": "2026-06"}),
        ("calculate_savings_rate", {"month": "2026-06"}),
        ("lookup_transactions", {"month": "2026-07", "category": "groceries", "kind": "expense"}),
        ("lookup_transactions", {"month": "2026-07", "category": "dining", "kind": "expense"}),
        ("check_budget_rule", {"rule_id": "dining_monthly_cap", "month": "2026-07"}),
        ("check_budget_rule", {"rule_id": "groceries_monthly_cap", "month": "2026-07"}),
        ("calculate_savings_rate", {"month": "2026-07"}),
        ("lookup_transactions", {"month": "2026-08", "category": "dining", "kind": "expense"}),
        ("calculate_savings_rate", {"month": "2026-08"}),
    ]
    prompts = _scenario_prompts()
    for index, (prompt, (tool, arguments)) in enumerate(zip(prompts[:-1], actions, strict=True)):
        call_id = f"demo-{index:02d}"
        result = getattr(data, tool)(**arguments).model_dump_json()
        session.messages.extend(
            [
                {"role": "user", "content": prompt},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": tool, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": call_id, "content": result},
                {"role": "assistant", "content": f"Grounded result recorded for turn {index + 1}."},
            ]
        )
    session.messages.append({"role": "user", "content": prompts[-1]})
    return session


def compact_demo(session: Session, live: bool) -> tuple[list[dict[str, Any]], Any, bool]:
    original = copy.deepcopy(session.messages)
    judge = JevClient() if live else DeterministicDemoJev()
    manager = ContextManager(judge, trigger_tokens=8_000, preserve_recent=6)
    compacted, report = manager.prepare(SYSTEM, session, UnusedProvider(), mode="jev")
    return compacted, report, session.messages == original


def main() -> None:
    st.set_page_config(page_title="Context Compaction Inspector", page_icon="🔎", layout="wide")
    st.title("Context Compaction Inspector")
    st.warning("Presentation harness only — this is not part of the finance application.")
    live = st.radio(
        "Decision source",
        ("Live Jev", "Deterministic fallback"),
        help="The fallback is intentionally labeled and never presented as a live model result.",
    ) == "Live Jev"

    if st.button("Load 12-turn scenario", type="primary"):
        st.session_state.demo_session = build_demo_session()
        st.session_state.pop("demo_result", None)

    session = st.session_state.get("demo_session")
    if not session:
        st.info("Load the scenario to generate a large ledger-backed canonical conversation.")
        return

    before = [SYSTEM, *session.messages]
    before_tokens = estimate_tokens(before)
    st.metric("Canonical context before compaction", f"{before_tokens:,} estimated tokens")
    with st.expander("Presentation prompt sequence"):
        for number, prompt in enumerate(_scenario_prompts(), start=1):
            st.write(f"{number}. {prompt}")

    if st.button("Compact model context", disabled=before_tokens < 8_000):
        try:
            compacted, report, unchanged = compact_demo(session, live)
            st.session_state.demo_result = {
                "compacted": compacted,
                "report": report.model_dump(mode="json"),
                "unchanged": unchanged,
                "source": "Live Jev" if live else "Deterministic fallback",
            }
        except Exception as exc:
            st.error(f"Live compaction failed: {exc}")
            st.info("Select Deterministic fallback to continue the presentation without network access.")

    result = st.session_state.get("demo_result")
    if not result:
        return
    report = result["report"]
    reduction = 1 - report["after_tokens"] / max(1, report["before_tokens"])
    st.subheader(f"Result source: {result['source']}")
    first, second, third = st.columns(3)
    first.metric("Before", f"{report['before_tokens']:,} tokens")
    second.metric("After", f"{report['after_tokens']:,} tokens")
    third.metric("Reduction", f"{reduction:.1%}")
    if result["unchanged"]:
        st.success("Canonical session history is unchanged; only the model-facing copy was compacted.")
    else:
        st.error("Canonical history changed unexpectedly.")
    st.dataframe(report["decisions"], use_container_width=True, hide_index=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Before: canonical context")
        st.json(before, expanded=False)
    with right:
        st.subheader("After: model-facing context")
        st.json(result["compacted"], expanded=False)


if __name__ == "__main__":
    main()
