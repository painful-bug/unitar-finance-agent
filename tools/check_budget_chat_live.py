"""Live parse/confirm/chat regression using only the bundled synthetic ledger.

Run: uv run --env-file .env python tools/check_budget_chat_live.py --output /tmp/budget-chat-live.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from mcp import Client

from finance_agent.agent import GroqProvider
from finance_agent.server import SessionStore, build_server
from finance_agent.threads import ChatStore


async def check(output: Path):
    evidence = []
    with TemporaryDirectory(prefix="finance-budget-live-") as directory, GroqProvider().client as groq:
        provider = GroqProvider(client=groq)
        store = SessionStore(provider=provider, chat_store=ChatStore(Path(directory)))
        async with Client(build_server(store)) as client:
            async def call(name, **arguments):
                response = await client.call_tool(name, arguments)
                assert not response.is_error, response.content
                return response.structured_content

            settings = await call("get_app_settings")
            created = await call("create_finance_session")
            session_id = created["session_id"]
            preview = await call("parse_budget_rules", rules_text=settings["rules_text"])
            assert not preview["warnings"] and len(preview["rules"]) == 3
            assert await call("get_app_settings") == settings

            async def ask(question, expected_tool, expected_result):
                result = await call("ask_finance_agent", session_id=session_id, question=question)
                evidence.append({"question": question, "result": result})
                output.write_text(json.dumps(evidence, indent=2))
                assert result["status"] == "ok", result["answer"]
                assert any(t["tool"] == expected_tool and t.get("result") and all(
                    Decimal(t["result"][k]) == Decimal(v) if k in {"limit", "observed", "total"} else t["result"].get(k) == v
                    for k, v in expected_result.items()) for t in result["trace"]), result
                print(json.dumps({"question": question, "status": result["status"], "tools": [t["tool"] for t in result["trace"]]}), flush=True)

            await ask("Give me a summary of last month's expenses, including the total.", "lookup_transactions", {"month": "2026-07", "total": "3150.65"})
            new_text = settings["rules_text"] + "\nKeep monthly transport expenses at or below RM100."
            preview = await call("parse_budget_rules", rules_text=new_text)
            assert not preview["warnings"], preview
            assert len(preview["rules"]) == 4
            new_rule = next(r for r in preview["rules"] if r["left"] and r["left"].get("category") == "transport")
            assert new_rule["right"]["value"] == "100" or new_rule["right"]["value"] == "100.00"
            assert await call("get_app_settings") == settings
            saved = await call("update_app_settings", rules_text=new_text, rules_draft=new_text, budget_rules=preview["rules"])
            assert saved["budget_rules"] == preview["rules"]
            await ask("Am I within my new transport budget for July 2026? Check the rule.", "check_budget_rule", {"rule_id": new_rule["rule_id"], "limit": "100.00", "observed": "150.00", "compliant": False})

        # Rehydration must retain the confirmed rule for existing and new chats.
        restarted = SessionStore(provider=provider, chat_store=ChatStore(Path(directory)))
        assert restarted.get_app_settings() == store.get_app_settings()
        async with Client(build_server(restarted)) as client:
            for arguments in ({"thread_id": session_id}, {}):
                tool = "get_chat_thread" if arguments else "create_finance_session"
                response = await client.call_tool(tool, arguments)
                detail = response.structured_content
                active_id = session_id if arguments else detail["session_id"]
                assert any(r["rule_id"] == new_rule["rule_id"] for r in detail["budget_rules"])
                response = await client.call_tool("ask_finance_agent", {"session_id": active_id, "question": "Check July 2026 against the transport budget."})
                result = response.structured_content
                evidence.append({"after_restart": True, "existing_chat": bool(arguments), "result": result})
                output.write_text(json.dumps(evidence, indent=2))
                assert result["status"] == "ok", result
                assert any(t["tool"] == "check_budget_rule" and t.get("result", {}).get("rule_id") == new_rule["rule_id"] and Decimal(t["result"]["limit"]) == 100 and t["result"]["compliant"] is False for t in result["trace"]), result
                print(f"Confirmed new transport rule used after restart (existing_chat={bool(arguments)}).", flush=True)
    print(f"All {len(evidence)} live chat scenarios passed; evidence: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(check(parser.parse_args().output))
