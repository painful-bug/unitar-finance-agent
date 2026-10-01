# Budget parsing and chat verification

Verified on 1 October 2026 using synthetic demo transactions.

The saved failure occurred on model step 3, after two successful `lookup_transactions` calls. Groq returned HTTP 400 with `code=output_parse_failed` and an empty `failed_generation`. The confirmed rules were still the three defaults; context compaction had not run. The server's rule parser creates a preview, and only confirmation updates shared rules. There was no evidence that clicking **Parse rules** corrupted the session.

The application defect was that `GroqProvider.chat` recovered from empty responses but immediately propagated this failed-generation response. The exact malformed model output cannot be reconstructed because Groq returned no generation text. Groq's [tool-calling documentation](https://console.groq.com/docs/tool-use/local-tool-calling) describes the generated tool requests and the application's responsibility for validating and executing them.

The shared provider now retries `output_parse_failed` once, using the same messages, tools, and strict output schema. Empty responses share that retry budget. Other bad requests and repeated generation failures still return errors. Recovery is recorded in the execution trace, and failed generations do not enter canonical history.

Broader verification exposed repeated summarization within one answer. The agent now reuses its compacted prefix across tool steps and appends new calls/results without rewriting saved history. Its prompt also explicitly requires `check_budget_rule` for each budget judgment: one live run had otherwise compared lookup totals itself. Browser test setup now returns summaries for summary requests, and its assertions use the current system-summary role and UI heading.

## Automated checks

| Check | Result |
| --- | --- |
| Python, including evaluation tests | 77 passed |
| React/MCP frontend tests | 51 passed |
| Chromium browser tests, retries disabled | 14 passed |
| ESLint, TypeScript, production build | Passed |
| `git diff --check` | Passed |

The regression tests first failed on the original implementation. They cover recovery after a ledger result, the real Groq SDK's structured-parser error, repeated failure bounds, unrelated errors, mixed empty/parse errors, one summary across multiple tool steps, and visible parsing errors that preserve confirmed rules.

## Live checks

- Parsing the existing defaults left confirmed settings and the session history unchanged. The next chat returned July expenses of RM3150.65.
- A new **monthly transport cap of RM100** compiled without warnings, remained inactive until confirmation, and was then used through `check_budget_rule`: July's RM150 expenses were over budget.
- After restarting the session store, both the existing chat and a new chat used that same confirmed rule and returned the same result.
- Six live compaction scenarios passed across `auto`, `jev`, and `summary`: empty-month lookup and two-month grocery compliance in each mode. Checks covered exact totals, both budget-tool calls, preserved canonical history, the current question in model input, and at most one summary per answer. Jev exercised the documented summary fallback when it removed less than 5%.
- The running UI's `http://127.0.0.1:8501/mcp` completed MCP initialization and advertised all 10 tools. A real expense-summary chat through that proxy completed in two steps with the correct total. Its disposable test chat was removed and settings were preserved.
- The local backend was rebuilt. Its final `agent.py` SHA-256 matched the workspace: `7821873337e9e5fc1a38606805087e6705009c3af8631807f9206f8c33078cb3`.

Initial burst testing hit Groq's 8000-token-per-minute quota. The affected Jev and summary checks were rerun with 60-second pauses; all four passed. This patch does not remove provider quotas or guarantee that a provider will never fail again.

## Reproduce

```sh
uv run --extra dev --extra eval pytest
cd web
npm run test -- --run
npm run lint
npm run build
CI=1 npm run test:e2e -- --retries=0
cd ..
uv run --env-file .env python tools/check_budget_chat_live.py --output /tmp/budget-chat-live.json
uv run --env-file .env python tools/check_compaction_live.py --pause-seconds 60 --output /tmp/compaction-live.json
```

The live budget check uses a temporary chat store; it does not edit the user's settings or replay uploaded financial records. The compaction check seeds only the bundled synthetic ledger.

## Confirmation feedback follow-up

The live **Confirm these rules** click successfully wrote settings (the backend file's save timestamp advanced), but left the compiled preview and button visible. When the text already matched the active defaults, every visible label stayed the same.

Confirmation now shows **Saving…** while pending, dismisses the preview only after a successful write, and shows **Rules confirmed and saved for every chat** beside the budget controls. Failed writes keep the preview available for retry. Editing the draft during a save cannot dismiss a newer preview. The local UI container was rebuilt, and regression coverage includes unchanged text, delayed save, failure/retry, and rules restored after browser reload.

Live verification also exposed a separate `json_validate_failed` response: the model exhausted Groq's default completion budget while writing the third rule. Groq's [reasoning documentation](https://console.groq.com/docs/reasoning) specifies a 1024-token default, shared by reasoning and visible output. Structured requests now explicitly allow 4096 completion tokens while retaining strict schema validation. The full Python suite passed again, the backend was rebuilt, and the running UI successfully parsed all three defaults, confirmed them with visible feedback, and restored the active rules after reload. Screenshot evidence: `/tmp/budget-rules-confirmed.jpg`.

An additional live chat batch after this follow-up successfully parsed both the default and four-rule drafts and returned the correct expense total. Its next chat hit Groq's 8000-token-per-minute quota (HTTP 429), so that extra batch did not complete its transport/restart scenarios. The earlier complete live batch remains recorded above; the new confirmation/reload check completed successfully.
