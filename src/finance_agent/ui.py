from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from mcp import Client


DEFAULT_RULES_TEXT = ", ".join(
    (
        "Keep monthly dining expenses at or below RM500.",
        "Keep monthly groceries expenses at or below RM800.",
        "Save at least 20% of monthly income.",
    )
)


async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")) as client:
        result = await client.call_tool(name, arguments)
    if result.is_error or result.structured_content is None:
        detail = " ".join(getattr(item, "text", "") for item in result.content)
        if detail.startswith("Unknown tool:"):
            raise RuntimeError(
                f"{detail}. The MCP server is running older code. Restart the MCP server "
                "with `uv run --env-file .env finance-mcp`, then try again."
            )
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
    st.session_state.pop("live_context", None)
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
    st.session_state.pop("live_context", None)
    st.session_state.messages = []


def _message_card(
    message: dict[str, Any],
    number: int,
    actions: dict[str, str],
) -> str:
    role = message.get("role", "unknown")
    safe_role = role if role in {"system", "user", "assistant", "tool"} else "unknown"
    content = message.get("content")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, indent=2) if content is not None else ""
    call_ids = [call.get("id", "") for call in message.get("tool_calls", [])]
    if message.get("tool_call_id"):
        call_ids.append(message["tool_call_id"])
    action = next((actions[item] for item in call_ids if item in actions), "")
    summary = role == "system" and content.startswith("Lossy summary")
    title = "summary" if summary else role
    badges = f'<span class="action {action}">{action}</span>' if action else ""
    tools = "".join(
        (
            f'<div class="tool-call"><strong>{html.escape(call["function"]["name"])}</strong>'
            f'<pre>{html.escape(call["function"].get("arguments", ""))}</pre></div>'
        )
        for call in message.get("tool_calls", [])
    )
    tool_id = (
        f'<span class="call-id">{html.escape(str(message["tool_call_id"]))}</span>'
        if message.get("tool_call_id")
        else ""
    )
    return (
        f'<article class="message {safe_role}"><header><span>{number:02d} · '
        f'{html.escape(title)}</span>{tool_id}{badges}</header>'
        f'<div class="content">{html.escape(content)}</div>{tools}</article>'
    )


def _context_panel_html(context: dict[str, Any] | None) -> str:
    context = context or {}
    before = context.get("before_messages", [])
    after = context.get("after_messages", [])
    actions = {
        decision["tool_call_id"]: decision["action"]
        for decision in context.get("decisions", [])
    }
    before_html = "".join(
        _message_card(message, index, actions) for index, message in enumerate(before, start=1)
    ) or '<div class="empty">Ask a question to capture the session context.</div>'
    after_html = "".join(
        _message_card(message, index, actions) for index, message in enumerate(after, start=1)
    ) or '<div class="empty">The model-facing context will appear here.</div>'
    before_tokens = int(context.get("before_tokens", 0))
    after_tokens = int(context.get("after_tokens", 0))
    reduction = 0 if not before_tokens else 1 - after_tokens / before_tokens
    strategy = html.escape(str(context.get("strategy", "none")))
    fallback = context.get("fallback_reason")
    fallback_html = (
        f'<div class="fallback">Fallback: {html.escape(str(fallback))}</div>' if fallback else ""
    )
    return f"""
<!doctype html>
<html><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: transparent; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
#context-root {{ width: 100%; aspect-ratio: 1; display: flex; flex-direction: column; color: #e7edf7; background: radial-gradient(circle at top right, #1d3150, #0b111c 55%); border: 1px solid #2c3d55; border-radius: 16px; overflow: hidden; box-shadow: 0 14px 35px rgba(0,0,0,.28); }}
#context-root:fullscreen {{ width: 100vw; height: 100vh; aspect-ratio: auto; border: 0; border-radius: 0; padding: 18px; background: #080d16; }}
.top {{ padding: 12px 12px 8px; border-bottom: 1px solid #26364c; background: rgba(8,13,22,.72); }}
.title {{ display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 750; letter-spacing: .02em; }}
.hint {{ color: #8293aa; font-size: 9px; font-weight: 500; }}
.metrics {{ display: flex; gap: 6px; margin-top: 8px; font-size: 9px; color: #aebbd0; }}
.metric {{ padding: 4px 7px; border-radius: 999px; background: #152238; border: 1px solid #263a58; }}
.tabs {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }}
.tabs button {{ cursor: pointer; color: #9facc0; background: transparent; border: 0; border-bottom: 2px solid transparent; padding: 5px; font-size: 10px; font-weight: 700; }}
.tabs button.active {{ color: #fff; border-color: #6da8ff; }}
.fallback {{ margin-top: 6px; color: #fbbf24; font-size: 9px; line-height: 1.25; }}
.feed {{ flex: 1; min-height: 0; overflow-y: auto; padding: 9px; scroll-behavior: smooth; }}
.feed[hidden] {{ display: none; }}
#context-root:fullscreen .feed {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); align-content: start; gap: 10px; }}
.message {{ margin-bottom: 8px; border-radius: 10px; border-left: 4px solid; padding: 8px; background: rgba(255,255,255,.045); }}
.message header {{ display: flex; gap: 6px; align-items: center; margin-bottom: 5px; text-transform: uppercase; font-size: 8px; font-weight: 800; letter-spacing: .1em; }}
.message .content {{ white-space: pre-wrap; overflow-wrap: anywhere; font: 10px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; color: #dce6f4; }}
.system {{ border-color: #a78bfa; }} .system header {{ color: #c4b5fd; }}
.user {{ border-color: #60a5fa; }} .user header {{ color: #93c5fd; }}
.assistant {{ border-color: #34d399; }} .assistant header {{ color: #6ee7b7; }}
.tool {{ border-color: #f59e0b; }} .tool header {{ color: #fbbf24; }}
.unknown {{ border-color: #94a3b8; }}
.tool-call {{ margin-top: 7px; padding: 6px; border: 1px solid #36506f; border-radius: 7px; color: #93c5fd; font-size: 9px; }}
pre {{ margin: 4px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; color: #cbd5e1; font-size: 9px; }}
.call-id {{ color: #7890ac; text-transform: none; letter-spacing: 0; overflow: hidden; text-overflow: ellipsis; }}
.action {{ margin-left: auto; padding: 2px 5px; border-radius: 999px; letter-spacing: .04em; }}
.keep {{ color: #6ee7b7; background: #123c32; }} .trim {{ color: #fde68a; background: #47360e; }} .drop {{ color: #fca5a5; background: #481c24; }}
.empty {{ color: #8293aa; font-size: 11px; line-height: 1.5; padding: 16px 8px; text-align: center; }}
</style></head>
<body><section id="context-root" title="Double-click to enter or leave fullscreen">
  <div class="top">
    <div class="title"><span>Live context · {strategy}</span><span class="hint">double-click to expand</span></div>
    <div class="metrics"><span class="metric">{before_tokens:,} → {after_tokens:,} tokens</span><span class="metric">{reduction:.0%} smaller</span></div>
    <div class="tabs"><button id="before-button" class="active" onclick="showFeed(event, 'before')">Before · canonical</button><button id="after-button" onclick="showFeed(event, 'after')">After · model input</button></div>
    {fallback_html}
  </div>
  <div id="before" class="feed">{before_html}</div>
  <div id="after" class="feed" hidden>{after_html}</div>
</section>
<script>
const root = document.getElementById('context-root');
root.addEventListener('dblclick', async () => {{
  if (document.fullscreenElement) await document.exitFullscreen();
  else if (root.requestFullscreen) await root.requestFullscreen();
}});
function showFeed(event, name) {{
  event.stopPropagation();
  document.getElementById('before').hidden = name !== 'before';
  document.getElementById('after').hidden = name !== 'after';
  document.getElementById('before-button').classList.toggle('active', name === 'before');
  document.getElementById('after-button').classList.toggle('active', name === 'after');
}}
</script></body></html>
"""


def _render_context_panel() -> None:
    st.iframe(
        _context_panel_html(st.session_state.get("live_context")),
        height=330,
        tab_index=0,
    )


def _render_settings(source: str, upload: Any) -> None:
    st.header("Budget rule settings")
    st.toggle(
        "Show context live",
        key="show_context_live",
        help="Shows the canonical session and the context sent to the model after each answer.",
    )
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
        if st.session_state.get("show_context_live"):
            st.markdown("#### Context window")
            _render_context_panel()
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
                        "include_context": st.session_state.get("show_context_live", False),
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
                if st.session_state.get("show_context_live"):
                    st.session_state.live_context = result["context"]
                    st.rerun()
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
