import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from finance_agent.budget import BudgetRule, Operand, default_budget_rules
import finance_agent.ui as ui
from finance_agent.ui import DEFAULT_RULES_TEXT, _call_tool, _context_panel_html


def test_rule_editor_starts_with_every_default_rule_comma_separated() -> None:
    assert DEFAULT_RULES_TEXT == ", ".join(
        rule.source_text for rule in default_budget_rules()
    )


def test_stale_server_error_tells_user_to_restart_mcp() -> None:
    class OldServerClient:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def call_tool(self, name, arguments):
            return SimpleNamespace(
                is_error=True,
                structured_content=None,
                content=[SimpleNamespace(text=f"Unknown tool: {name}")],
            )

    with patch("finance_agent.ui.Client", OldServerClient):
        with pytest.raises(RuntimeError, match="Restart the MCP server"):
            asyncio.run(_call_tool("parse_budget_rules", {"rules_text": "Save 20%."}))


def test_settings_can_add_or_remove_defaults_then_confirm_session_rules() -> None:
    custom = BudgetRule(
        rule_id="savings_target",
        source_text="Save at least 25% of income.",
        left=Operand(metric="savings", unit="RM"),
        operator="gte",
        right=Operand(metric="income", unit="RM", multiplier="0.25"),
    ).model_dump(mode="json")
    defaults = [rule.model_dump(mode="json") for rule in default_budget_rules()]
    calls: list[tuple[str, dict]] = []

    def fake_call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "parse_budget_rules":
            rules = defaults + [custom] if arguments["rules_text"].startswith(DEFAULT_RULES_TEXT) else [custom]
            return {"rules": rules, "warnings": []}
        if name == "create_finance_session":
            rules = arguments.get("budget_rules") or defaults
            return {
                "session_id": "test-session",
                "as_of_date": "2026-08-15",
                "context_mode": arguments["context_mode"],
                "transaction_count": 1,
                "budget_rules": rules,
            }
        if name == "close_finance_session":
            return {"session_id": arguments["session_id"], "closed": True}
        raise AssertionError(name)

    def button(app, label):
        return next(item for item in app.button if item.label == label)

    with patch.object(ui, "call_tool", fake_call_tool):
        app = AppTest.from_string("from finance_agent.ui import render\nrender()").run(timeout=10)
        app.radio[0].set_value("Settings").run(timeout=10)
        assert app.text_area[0].value == DEFAULT_RULES_TEXT

        app.text_area[0].set_value(
            f"{DEFAULT_RULES_TEXT}\nSave at least 25% of income."
        ).run(timeout=10)
        button(app, "Parse rules").click().run(timeout=10)
        button(app, "Confirm these rules").click().run(timeout=10)
        button(app, "Start new session").click().run(timeout=10)
        assert len([call for call in calls if call[0] == "create_finance_session"][-1][1]["budget_rules"]) == 4

        app.text_area[0].set_value("Save at least 25% of income.").run(timeout=10)
        button(app, "Parse rules").click().run(timeout=10)
        button(app, "Confirm these rules").click().run(timeout=10)
        button(app, "Start new session").click().run(timeout=10)
        assert [
            rule["rule_id"]
            for rule in [call for call in calls if call[0] == "create_finance_session"][-1][1]["budget_rules"]
        ] == ["savings_target"]

        button(app, "Use built-in defaults").click().run(timeout=10)
        assert app.text_area[0].value == DEFAULT_RULES_TEXT


def test_context_panel_is_color_coded_safe_and_fullscreen_capable() -> None:
    panel = _context_panel_html(
        {
            "strategy": "jev",
            "before_tokens": 100,
            "after_tokens": 60,
            "decisions": [
                {"tool_call_id": "call-1", "action": "trim"},
            ],
            "before_messages": [
                {"role": "user", "content": "<script>bad()</script>"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {"name": "lookup_transactions", "arguments": "{}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call-1", "content": "result"},
            ],
            "after_messages": [
                {"role": "system", "content": "Lossy summary of earlier session history"}
            ],
        }
    )

    assert "&lt;script&gt;bad()&lt;/script&gt;" in panel
    assert "<script>bad()</script>" not in panel
    assert "lookup_transactions" in panel
    assert "trim" in panel
    assert "requestFullscreen" in panel
    assert "Before · canonical" in panel and "After · model input" in panel


def test_live_context_setting_survives_chat_answer_reruns() -> None:
    context = {
        "strategy": "summary",
        "before_tokens": 100,
        "after_tokens": 60,
        "decisions": [],
        "before_messages": [{"role": "user", "content": "How much did I spend?"}],
        "after_messages": [{"role": "user", "content": "How much did I spend?"}],
    }
    calls: list[tuple[str, dict]] = []
    rendered_contexts: list[dict | None] = []

    def fake_call_tool(name, arguments):
        calls.append((name, arguments))
        if name == "create_finance_session":
            return {
                "session_id": "test-session",
                "as_of_date": "2026-08-15",
                "context_mode": arguments["context_mode"],
                "transaction_count": 1,
                "budget_rules": [],
            }
        if name == "ask_finance_agent":
            return {
                "answer": "RM42",
                "status": "complete",
                "steps": 1,
                "trace": [],
                "context": context,
            }
        raise AssertionError(name)

    with (
        patch.object(ui, "call_tool", fake_call_tool),
        patch.object(
            ui,
            "_render_context_panel",
            lambda: rendered_contexts.append(ui.st.session_state.get("live_context")),
        ),
    ):
        app = AppTest.from_string("from finance_agent.ui import render\nrender()")
        app.run(timeout=10)
        app.radio[0].set_value("Settings").run(timeout=10)
        app.toggle[0].set_value(True).run(timeout=10)
        app.radio[0].set_value("Chat").run(timeout=10)
        assert app.session_state["show_context_live"] is True
        app.chat_input[0].set_value("How much did I spend?").run(timeout=10)

        ask = next(arguments for name, arguments in calls if name == "ask_finance_agent")
        assert ask["include_context"] is True
        assert app.session_state["show_context_live"] is True
        assert app.session_state["live_context"] == context
        assert rendered_contexts[-1] == context

        app.radio[0].set_value("Settings").run(timeout=10)
        assert app.toggle[0].value is True
