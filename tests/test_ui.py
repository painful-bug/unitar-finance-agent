from finance_agent.ui import _context_panel_html


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
