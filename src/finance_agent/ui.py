from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from mcp import Client


DEFAULT_RULES_TEXT = """Keep monthly dining expenses at or below RM500.
Keep monthly groceries expenses at or below RM800.
Save at least 20% of monthly income."""


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error or result.structured_content is None:
        detail = " ".join(getattr(item, "text", "") for item in result.content)
        raise RuntimeError(detail or f"MCP tool {name} failed")
    return result.structured_content


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(_call_tool(name, arguments))


def _close_current_session() -> None:
    session_id = st.session_state.get("finance_session_id")
    if session_id:
        try:
            call_tool("close_finance_session", {"session_id": session_id})
        except Exception:
            pass
    st.session_state.pop("finance_session_id", None)
    st.session_state.pop("session_info", None)
    st.session_state.messages = []


def _csv_text(source: str, upload: Any) -> str | None:
    if source != "Upload CSV":
        return None
    if upload is None:
        raise ValueError("Choose a CSV file first.")
    return upload.getvalue().decode("utf-8")


def _rules_signature(source: str, upload: Any, rules_text: str) -> str:
    csv_bytes = upload.getvalue() if source == "Upload CSV" and upload is not None else b"demo"
    return hashlib.sha256(csv_bytes + b"\0" + rules_text.encode("utf-8")).hexdigest()


def _create_session(
    source: str,
    upload: Any,
    mode: str,
    override_date: Any,
    budget_rules: list[dict[str, Any]] | None,
) -> None:
    arguments: dict[str, Any] = {"context_mode": mode}
    csv_text = _csv_text(source, upload)
    if csv_text is not None:
        arguments["csv_text"] = csv_text
    if override_date is not None:
        arguments["as_of_date"] = override_date.isoformat()
    if budget_rules is not None:
        arguments["budget_rules"] = budget_rules
    info = call_tool("create_finance_session", arguments)
    st.session_state.finance_session_id = info["session_id"]
    st.session_state.session_info = info
    st.session_state.messages = []


def _render_settings(source: str, upload: Any) -> None:
    st.header("Budget rule settings")
    st.caption(
        "Write one or more monthly rules in plain English. The model only compiles them; "
        "validated code evaluates the ledger."
    )
    rules_text = st.text_area("Natural-language rules", key="budget_rules_text", height=180)
    signature = _rules_signature(source, upload, rules_text)
    parsed_signature = st.session_state.get("parsed_rules_signature")
    confirmed_signature = st.session_state.get("confirmed_rules_signature")

    if st.button("Parse rules", type="primary"):
        try:
            arguments: dict[str, Any] = {"rules_text": rules_text}
            csv_text = _csv_text(source, upload)
            if csv_text is not None:
                arguments["csv_text"] = csv_text
            preview = call_tool("parse_budget_rules", arguments)
            st.session_state.parsed_rules = preview["rules"]
            st.session_state.rule_warnings = preview.get("warnings", [])
            st.session_state.parsed_rules_signature = signature
            st.session_state.pop("confirmed_rules", None)
            st.session_state.pop("confirmed_rules_signature", None)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

    parsed = st.session_state.get("parsed_rules")
    if parsed and parsed_signature == signature:
        st.subheader("Compiled preview")
        def comparison(rule: dict[str, Any]) -> str:
            if not rule["supported"]:
                return rule["unsupported_reason"]
            left = rule.get("left") or {}
            right = rule.get("right") or {}
            return (
                f"{left.get('metric') or left.get('value')} {rule['operator']} "
                f"{right.get('metric') or right.get('value')}"
            )

        st.dataframe(
            [
                {
                    "id": rule["rule_id"],
                    "supported": rule["supported"],
                    "rule": rule["source_text"],
                    "comparison": comparison(rule),
                }
                for rule in parsed
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Validated JSON"):
            st.json(parsed)
        for warning in st.session_state.get("rule_warnings", []):
            st.warning(warning)
        if st.button("Confirm these rules", use_container_width=True):
            st.session_state.confirmed_rules = parsed
            st.session_state.confirmed_rules_signature = signature
            st.rerun()
    elif parsed:
        st.warning("The rule text or ledger changed. Parse again before confirming.")

    if confirmed_signature == signature:
        st.success("Custom rules confirmed for the next session.")
    else:
        st.info("New sessions currently use the built-in default rules.")
    if st.button("Use built-in defaults"):
        st.session_state.pop("confirmed_rules", None)
        st.session_state.pop("confirmed_rules_signature", None)
        st.rerun()


def render() -> None:
    st.set_page_config(page_title="Personal Finance Agent", page_icon="💰", layout="centered")
    st.title("Personal Finance Agent")
    st.caption("Grounded in the active ledger. Local beta — not financial advice.")

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "budget_rules_text" not in st.session_state:
        st.session_state.budget_rules_text = DEFAULT_RULES_TEXT

    with st.sidebar:
        view = st.radio("View", ("Chat", "Settings"), horizontal=True)
        st.header("Session")
        source = st.radio("Ledger", ("Bundled demo", "Upload CSV"))
        upload = st.file_uploader("Ledger CSV", type="csv") if source == "Upload CSV" else None
        mode = st.selectbox("Context strategy", ("auto", "jev", "summary"))
        override = st.checkbox("Override as-of date")
        override_date = st.date_input("As-of date", value=None) if override else None
        current_signature = _rules_signature(source, upload, st.session_state.budget_rules_text)
        confirmed_rules = (
            st.session_state.get("confirmed_rules")
            if st.session_state.get("confirmed_rules_signature") == current_signature
            else None
        )
        if st.button("Start new session", type="primary", use_container_width=True):
            _close_current_session()
            try:
                _create_session(source, upload, mode, override_date, confirmed_rules)
            except Exception as exc:
                st.error(str(exc))
        info = st.session_state.get("session_info")
        if info:
            st.success(
                f"{info['transaction_count']} rows · as of {info['as_of_date']} · {mode}"
            )
            st.caption(f"{len(info['budget_rules'])} active budget rules")

    if view == "Settings":
        _render_settings(source, upload)
        return

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("result"):
                result = message["result"]
                with st.expander("Agent trace"):
                    st.write(f"Status: `{result['status']}` · Steps: `{result['steps']}`")
                    st.json(result["trace"])
                with st.expander("Context management"):
                    st.json(result["context"])

    question = st.chat_input("Ask about your spending, budget, or savings")
    if not question:
        return
    if not st.session_state.get("finance_session_id"):
        try:
            _create_session(source, upload, mode, override_date, confirmed_rules)
        except Exception as exc:
            st.error(str(exc))
            return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Checking the ledger…"):
            try:
                result = call_tool(
                    "ask_finance_agent",
                    {
                        "session_id": st.session_state.finance_session_id,
                        "question": question,
                        "context_mode": mode,
                    },
                )
                st.markdown(result["answer"])
                with st.expander("Agent trace"):
                    st.write(f"Status: `{result['status']}` · Steps: `{result['steps']}`")
                    st.json(result["trace"])
                with st.expander("Context management"):
                    st.json(result["context"])
                st.session_state.messages.append(
                    {"role": "assistant", "content": result["answer"], "result": result}
                )
            except Exception as exc:
                st.error(str(exc))


def main() -> None:
    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.address",
        os.getenv("UI_HOST", "127.0.0.1"),
        "--server.port",
        os.getenv("UI_PORT", "8501"),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    render()
