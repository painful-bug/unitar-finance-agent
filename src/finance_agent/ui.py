from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from mcp import Client


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


def _create_session(source: str, upload: Any, mode: str, override_date: Any) -> None:
    arguments: dict[str, Any] = {"context_mode": mode}
    if source == "Upload CSV":
        if upload is None:
            raise ValueError("Choose a CSV file first.")
        arguments["csv_text"] = upload.getvalue().decode("utf-8")
    if override_date is not None:
        arguments["as_of_date"] = override_date.isoformat()
    info = call_tool("create_finance_session", arguments)
    st.session_state.finance_session_id = info["session_id"]
    st.session_state.session_info = info
    st.session_state.messages = []


def render() -> None:
    st.set_page_config(page_title="Personal Finance Agent", page_icon="💰", layout="centered")
    st.title("Personal Finance Agent")
    st.caption("Grounded in the active ledger. Local beta — not financial advice.")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    with st.sidebar:
        st.header("Session")
        source = st.radio("Ledger", ("Bundled demo", "Upload CSV"))
        upload = st.file_uploader("Ledger CSV", type="csv") if source == "Upload CSV" else None
        mode = st.selectbox("Context strategy", ("auto", "jev", "summary"))
        override = st.checkbox("Override as-of date")
        override_date = st.date_input("As-of date", value=None) if override else None
        if st.button("Start new session", type="primary", use_container_width=True):
            _close_current_session()
            try:
                _create_session(source, upload, mode, override_date)
            except Exception as exc:
                st.error(str(exc))
        info = st.session_state.get("session_info")
        if info:
            st.success(
                f"{info['transaction_count']} rows · as of {info['as_of_date']} · {mode}"
            )

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
            _create_session(source, upload, mode, override_date)
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

