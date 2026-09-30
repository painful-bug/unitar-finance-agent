# Streamlit-to-React migration: overview and inventory

> Historical inventory: this file records the pre-React/pre-thread baseline. Durable JSON chat storage and the current eight-tool MCP surface are documented in [`../chat-thread-persistence.md`](../chat-thread-persistence.md).

## Purpose and scope

This document records the current application before replacing its Streamlit presentation layer with React. The migration must preserve the Python finance agent, finance calculations, context management, Jev integration, Pydantic models, and MCP tool behavior. The current architecture already keeps the UI outside the agent: Streamlit calls MCP instead of importing the agent core ([`src/finance_agent/ui.py:35-50`](../../src/finance_agent/ui.py#L35-L50)), while the MCP server owns sessions and invokes the agent ([`src/finance_agent/server.py:39-127`](../../src/finance_agent/server.py#L39-L127)).

The target remains a local, single-user beta. The current project explicitly excludes authentication, a database, persistent uploads, and general financial advice ([`README.md:15`](../../README.md#L15)).

## Knowledge-graph status

The checked-in `graphify-out/` directory is not a completed knowledge graph:

- `graphify-out/graph.json` is absent.
- `graphify-out/GRAPH_REPORT.md` is absent.
- The directory contains intermediate extraction files and caches, including `graphify-out/.graphify_ast.json`, `graphify-out/.graphify_extract.json`, and `graphify-out/cache/`.
- `graphify-out/.graphify_detect.json`, `graphify-out/.graphify_python`, and `graphify-out/.graphify_root` are empty in this checkout.

There are therefore no graph communities, god nodes, or ranked dependencies that can be treated as authoritative. The inventory below comes from full reads of the crucial UI, MCP, agent, finance, context, model, configuration, deployment, and test files. The intermediate Graphify files stay untouched because they are unrelated to the UI migration.

## Current system map

```text
Browser
  -> Streamlit UI
       -> MCP Python client over Streamable HTTP
            -> personal-finance-agent MCP server
                 -> in-memory SessionStore + per-session lock
                      -> handwritten six-step agent loop
                           -> Groq chat/tool calls
                           -> deterministic finance tools
                           -> Jev context selection / Groq summary fallback
```

- Streamlit is an MCP client and opens a client connection for each tool call ([`src/finance_agent/ui.py:35-50`](../../src/finance_agent/ui.py#L35-L50)).
- `SessionStore` owns an in-memory `sessions` dictionary and one `asyncio.Lock` per finance session ([`src/finance_agent/server.py:39-48`](../../src/finance_agent/server.py#L39-L48)).
- The MCP server exposes four structured tools over Streamable HTTP at `/mcp` ([`src/finance_agent/server.py:130-184`](../../src/finance_agent/server.py#L130-L184)).
- The agent exposes three internal Groq function tools and runs at most six reasoning/tool steps ([`src/finance_agent/agent.py:48-70`](../../src/finance_agent/agent.py#L48-L70), [`src/finance_agent/agent.py:180-246`](../../src/finance_agent/agent.py#L180-L246)).
- Context preparation preserves canonical history and produces a temporary model-facing context using Jev or summary compaction ([`src/finance_agent/context.py:142-280`](../../src/finance_agent/context.py#L142-L280)).

## Complete feature and interaction inventory

| Current feature or interaction | Current behavior | React mapping | Source |
|---|---|---|---|
| Page shell | Sets finance title/icon, centered layout, heading, and local-beta disclaimer | `App` header inside a centered responsive layout | [`src/finance_agent/ui.py:398-401`](../../src/finance_agent/ui.py#L398-L401) |
| View navigation | Horizontal Chat/Settings radio control | Two-button accessible tab list | [`src/finance_agent/ui.py:411-412`](../../src/finance_agent/ui.py#L411-L412) |
| Ledger source | Select bundled demo or uploaded CSV | Native radio group | [`src/finance_agent/ui.py:413-415`](../../src/finance_agent/ui.py#L413-L415) |
| CSV upload | Shows a CSV-only file uploader for the upload source | Native file input with `.csv,text/csv` accept hint and fatal UTF-8 decoding | [`src/finance_agent/ui.py:414-415`](../../src/finance_agent/ui.py#L414-L415), [`src/finance_agent/ui.py:66-71`](../../src/finance_agent/ui.py#L66-L71) |
| Context strategy | Selects `auto`, `jev`, or `summary` | Native select using the same values | [`src/finance_agent/ui.py:416`](../../src/finance_agent/ui.py#L416) |
| As-of override | Checkbox conditionally reveals a date input | Native checkbox and date input | [`src/finance_agent/ui.py:417-418`](../../src/finance_agent/ui.py#L417-L418) |
| Start new session | Best-effort closes the current session, creates another, then clears transcript and live context | `SessionPanel` calls `close_finance_session`, then `create_finance_session`, and resets client state | [`src/finance_agent/ui.py:53-64`](../../src/finance_agent/ui.py#L53-L64), [`src/finance_agent/ui.py:164-184`](../../src/finance_agent/ui.py#L164-L184), [`src/finance_agent/ui.py:425-430`](../../src/finance_agent/ui.py#L425-L430) |
| Session summary | Shows transaction count, as-of date, selected context mode, and active-rule count | Compact status card | [`src/finance_agent/ui.py:434-439`](../../src/finance_agent/ui.py#L434-L439) |
| Live-context toggle | Controls whether exact context messages are requested and displayed | Native checkbox styled as a switch | [`src/finance_agent/ui.py:313-320`](../../src/finance_agent/ui.py#L313-L320) |
| Rule editor | Edits one or more natural-language rules in a textarea | Controlled textarea | [`src/finance_agent/ui.py:321-331`](../../src/finance_agent/ui.py#L321-L331) |
| Parse rules | Calls MCP with rules plus the active uploaded ledger when present | `SettingsPanel` mutation through `parse_budget_rules` | [`src/finance_agent/ui.py:336-349`](../../src/finance_agent/ui.py#L336-L349) |
| Compiled preview | Shows rule ID, support state, source rule, and comparison | Semantic table | [`src/finance_agent/ui.py:353-378`](../../src/finance_agent/ui.py#L353-L378) |
| Validated JSON | Shows the complete parsed rules in an expander | Native `<details>` containing formatted JSON | [`src/finance_agent/ui.py:379-380`](../../src/finance_agent/ui.py#L379-L380) |
| Rule warnings | Displays one warning per unsupported or invalid compiled rule | Inline warning list with `role="status"` | [`src/finance_agent/ui.py:381-382`](../../src/finance_agent/ui.py#L381-L382) |
| Confirm rules | Saves the current parsed rule set and its ledger/rule signature | Confirm button plus versioned browser preferences | [`src/finance_agent/ui.py:383-387`](../../src/finance_agent/ui.py#L383-L387) |
| Stale-rule detection | Requires reparsing if rule text or ledger content changed | Compare current SHA-256 signature with parsed/confirmed signatures | [`src/finance_agent/ui.py:332-334`](../../src/finance_agent/ui.py#L332-L334), [`src/finance_agent/ui.py:388-394`](../../src/finance_agent/ui.py#L388-L394) |
| Built-in defaults | Restores the default three-rule text and clears parsed/confirmed state | Secondary reset button | [`src/finance_agent/ui.py:144-156`](../../src/finance_agent/ui.py#L144-L156), [`src/finance_agent/ui.py:395`](../../src/finance_agent/ui.py#L395) |
| Transcript | Renders every user and assistant message | `ChatPanel` message list | [`src/finance_agent/ui.py:445-455`](../../src/finance_agent/ui.py#L445-L455) |
| Markdown answers | Renders message content as Markdown | `react-markdown` with raw HTML disabled | [`src/finance_agent/ui.py:445-447`](../../src/finance_agent/ui.py#L445-L447), [`src/finance_agent/ui.py:481`](../../src/finance_agent/ui.py#L481) |
| Chat submission | Reads one prompt, automatically creates a session if absent, then calls the agent | Native form; the submit handler ensures a session before `ask_finance_agent` | [`src/finance_agent/ui.py:456-480`](../../src/finance_agent/ui.py#L456-L480) |
| Pending state | Shows “Checking the ledger…” while waiting | Disabled form controls and an `aria-live` loading message | [`src/finance_agent/ui.py:469-470`](../../src/finance_agent/ui.py#L469-L470) |
| Agent trace | Shows result status, step count, and JSON trace per answer | Native `<details>` section | [`src/finance_agent/ui.py:448-454`](../../src/finance_agent/ui.py#L448-L454), [`src/finance_agent/ui.py:482-486`](../../src/finance_agent/ui.py#L482-L486) |
| Context report | Shows the complete context report JSON per answer | Native `<details>` section | [`src/finance_agent/ui.py:453-454`](../../src/finance_agent/ui.py#L453-L454), [`src/finance_agent/ui.py:485-486`](../../src/finance_agent/ui.py#L485-L486) |
| Live context metrics | Shows strategy, before/after token counts, reduction, and fallback reason | `ContextPanel` summary header | [`src/finance_agent/ui.py:222-243`](../../src/finance_agent/ui.py#L222-L243), [`src/finance_agent/ui.py:278-287`](../../src/finance_agent/ui.py#L278-L287) |
| Context tabs | Switches between canonical context and model input | Accessible two-tab control | [`src/finance_agent/ui.py:282-299`](../../src/finance_agent/ui.py#L282-L299) |
| Context message cards | Color-codes roles and displays tool calls, arguments, call IDs, and keep/trim/drop actions | React message cards; React text escaping replaces manual HTML escaping | [`src/finance_agent/ui.py:186-219`](../../src/finance_agent/ui.py#L186-L219) |
| Context fullscreen | Double-click enters or leaves fullscreen | Fullscreen API on the React context panel | [`src/finance_agent/ui.py:278-293`](../../src/finance_agent/ui.py#L278-L293) |
| Feedback messages | Displays inline error, warning, info, and success notices | Semantic status banners | [`src/finance_agent/ui.py:350-395`](../../src/finance_agent/ui.py#L350-L395), [`src/finance_agent/ui.py:429-430`](../../src/finance_agent/ui.py#L429-L430) |

## Streamlit primitive inventory and migration

| Streamlit primitive | Current use | Target behavior | Source |
|---|---|---|---|
| `st.session_state` | Stores transcript, session data, live context, and rule workflow state | React state plus `localStorage` only for rule preferences | [`src/finance_agent/ui.py:53-64`](../../src/finance_agent/ui.py#L53-L64), [`src/finance_agent/ui.py:403-409`](../../src/finance_agent/ui.py#L403-L409) |
| `st.rerun` | Used after parsing, confirming, and receiving live context | No direct replacement; React state updates rerender | [`src/finance_agent/ui.py:349`](../../src/finance_agent/ui.py#L349), [`src/finance_agent/ui.py:387`](../../src/finance_agent/ui.py#L387), [`src/finance_agent/ui.py:492`](../../src/finance_agent/ui.py#L492) |
| `st.file_uploader` | Accepts ledger CSV | Native file input and `TextDecoder("utf-8", { fatal: true })` | [`src/finance_agent/ui.py:415`](../../src/finance_agent/ui.py#L415) |
| `st.chat_input` | Collects a question | Chat form with text input | [`src/finance_agent/ui.py:456`](../../src/finance_agent/ui.py#L456) |
| `st.chat_message` | Groups user and assistant messages | Semantic message articles | [`src/finance_agent/ui.py:445-447`](../../src/finance_agent/ui.py#L445-L447), [`src/finance_agent/ui.py:467-469`](../../src/finance_agent/ui.py#L467-L469) |
| `st.iframe` | Hosts the custom context inspector | Native React DOM tree | [`src/finance_agent/ui.py:305-310`](../../src/finance_agent/ui.py#L305-L310) |
| `st.dataframe` | Displays compiled rules | Semantic table | [`src/finance_agent/ui.py:366-378`](../../src/finance_agent/ui.py#L366-L378) |
| `st.expander` | Hides validated JSON, trace, and context details | `<details>/<summary>` | [`src/finance_agent/ui.py:379-380`](../../src/finance_agent/ui.py#L379-L380), [`src/finance_agent/ui.py:450-454`](../../src/finance_agent/ui.py#L450-L454) |
| `st.spinner` | Marks an in-flight agent request | Disabled controls plus live status text | [`src/finance_agent/ui.py:470`](../../src/finance_agent/ui.py#L470) |
| `st.radio`, `st.selectbox`, `st.checkbox`, `st.toggle`, `st.date_input`, `st.text_area`, `st.button` | Implements all settings and session controls | Labelled native HTML controls | [`src/finance_agent/ui.py:313-395`](../../src/finance_agent/ui.py#L313-L395), [`src/finance_agent/ui.py:411-425`](../../src/finance_agent/ui.py#L411-L425) |
| `st.cache_data`, `st.cache_resource`, `st.form` | Not used anywhere in the UI module | No replacement and no new cache/form abstraction | [`src/finance_agent/ui.py`](../../src/finance_agent/ui.py) |

## State inventory

| Current state | Meaning | Target owner | Persistence | Source |
|---|---|---|---|---|
| `messages` | UI transcript and attached result metadata | `App` chat reducer | Memory only | [`src/finance_agent/ui.py:63`](../../src/finance_agent/ui.py#L63), [`src/finance_agent/ui.py:403-404`](../../src/finance_agent/ui.py#L403-L404), [`src/finance_agent/ui.py:466-489`](../../src/finance_agent/ui.py#L466-L489) |
| `finance_session_id` | Current server-side finance session | `App` session state | Memory only | [`src/finance_agent/ui.py:54-60`](../../src/finance_agent/ui.py#L54-L60), [`src/finance_agent/ui.py:180`](../../src/finance_agent/ui.py#L180) |
| `session_info` | Date, count, context mode, and active rules | `App` session state | Memory only | [`src/finance_agent/ui.py:61`](../../src/finance_agent/ui.py#L61), [`src/finance_agent/ui.py:181`](../../src/finance_agent/ui.py#L181) |
| `live_context` | Most recent exact context report | `App` state | Memory only | [`src/finance_agent/ui.py:62`](../../src/finance_agent/ui.py#L62), [`src/finance_agent/ui.py:490-492`](../../src/finance_agent/ui.py#L490-L492) |
| `show_context_live` | Requests and shows full before/after messages | `App` state | Memory only | [`src/finance_agent/ui.py:315-320`](../../src/finance_agent/ui.py#L315-L320) |
| `budget_rules_text` | Editable natural-language rules | Preferences state | `localStorage` | [`src/finance_agent/ui.py:96`](../../src/finance_agent/ui.py#L96), [`src/finance_agent/ui.py:126`](../../src/finance_agent/ui.py#L126) |
| `budget_rules_editor_version` | Invalidates old stored editor state | Preference schema version | Stored with preference record | [`src/finance_agent/ui.py:23`](../../src/finance_agent/ui.py#L23), [`src/finance_agent/ui.py:127`](../../src/finance_agent/ui.py#L127) |
| `_budget_rules_text` | Streamlit widget mirror of the rule text | Removed | Controlled textarea replaces it | [`src/finance_agent/ui.py:146`](../../src/finance_agent/ui.py#L146), [`src/finance_agent/ui.py:159-161`](../../src/finance_agent/ui.py#L159-L161) |
| `parsed_rules` | Last compiled preview | `SettingsPanel` state | Memory; rehydrated from confirmed rules | [`src/finance_agent/ui.py:137`](../../src/finance_agent/ui.py#L137), [`src/finance_agent/ui.py:343`](../../src/finance_agent/ui.py#L343) |
| `rule_warnings` | Warnings returned with the preview | `SettingsPanel` state | Memory | [`src/finance_agent/ui.py:139`](../../src/finance_agent/ui.py#L139), [`src/finance_agent/ui.py:344`](../../src/finance_agent/ui.py#L344) |
| `parsed_rules_signature` | Ledger/rule fingerprint used for preview freshness | `SettingsPanel` state | Memory | [`src/finance_agent/ui.py:138`](../../src/finance_agent/ui.py#L138), [`src/finance_agent/ui.py:345`](../../src/finance_agent/ui.py#L345) |
| `confirmed_rules` | Rules eligible for the next session | Preferences state | `localStorage` | [`src/finance_agent/ui.py:97`](../../src/finance_agent/ui.py#L97), [`src/finance_agent/ui.py:384`](../../src/finance_agent/ui.py#L384) |
| `confirmed_rules_signature` | Ledger/rule fingerprint for confirmed rules | Preferences state | `localStorage` | [`src/finance_agent/ui.py:98`](../../src/finance_agent/ui.py#L98), [`src/finance_agent/ui.py:385`](../../src/finance_agent/ui.py#L385) |

Implicit widget state also includes the active view, ledger source, selected file, context mode, date-override flag, date value, prompt text, pending state, and current error. These become explicit React state owned by `App` or the relevant child component ([`src/finance_agent/ui.py:411-425`](../../src/finance_agent/ui.py#L411-L425), [`src/finance_agent/ui.py:456-494`](../../src/finance_agent/ui.py#L456-L494)).

The browser signature must remain SHA-256 over `csvBytes + NUL + UTF8(rulesText)`. The demo source uses the literal bytes `demo` ([`src/finance_agent/ui.py:74-76`](../../src/finance_agent/ui.py#L74-L76)). Existing `~/.finance-agent/rules.json` data is not browser-readable and will require one-time rule reconfirmation after cutover ([`src/finance_agent/ui.py:79-107`](../../src/finance_agent/ui.py#L79-L107)).

## MCP inventory

### Server

The single server is named `personal-finance-agent`, reports version `0.1.0`, and is served over Streamable HTTP at `/mcp` with JSON responses enabled ([`src/finance_agent/server.py:130-184`](../../src/finance_agent/server.py#L130-L184)).

### Exposed MCP tools

| Tool | Purpose | Server implementation | Current UI caller |
|---|---|---|---|
| `parse_budget_rules` | Compile natural-language rules against ledger categories | [`src/finance_agent/server.py:138-144`](../../src/finance_agent/server.py#L138-L144) | [`src/finance_agent/ui.py:336-348`](../../src/finance_agent/ui.py#L336-L348) |
| `create_finance_session` | Load demo/uploaded data and create an in-memory session | [`src/finance_agent/server.py:146-154`](../../src/finance_agent/server.py#L146-L154) | [`src/finance_agent/ui.py:164-184`](../../src/finance_agent/ui.py#L164-L184) |
| `ask_finance_agent` | Run the unchanged finance agent in a session | [`src/finance_agent/server.py:156-164`](../../src/finance_agent/server.py#L156-L164) | [`src/finance_agent/ui.py:472-480`](../../src/finance_agent/ui.py#L472-L480) |
| `close_finance_session` | Remove an in-memory finance session | [`src/finance_agent/server.py:166-169`](../../src/finance_agent/server.py#L166-L169) | [`src/finance_agent/ui.py:53-59`](../../src/finance_agent/ui.py#L53-L59) |

The pre-thread migration integration test asserted this original four-tool set. The current eight-tool contract is covered in [`../chat-thread-persistence.md`](../chat-thread-persistence.md). No `@server.resource` or `@server.prompt` registrations exist in the server module; therefore the server exposes no MCP resources and no MCP prompts.

### Internal agent tools

The following are Groq function tools executed inside the agent and are not MCP tools: `lookup_transactions`, `check_budget_rule`, and `calculate_savings_rate` ([`src/finance_agent/agent.py:48-70`](../../src/finance_agent/agent.py#L48-L70)). Their implementations stay in `FinanceData` ([`src/finance_agent/finance.py:94-283`](../../src/finance_agent/finance.py#L94-L283)).

## External services and configuration

| Concern | Current behavior | Source |
|---|---|---|
| Groq agent model | `GROQ_MODEL`, default `openai/gpt-oss-20b` | [`src/finance_agent/agent.py:93-117`](../../src/finance_agent/agent.py#L93-L117) |
| Groq summary model | Optional `GROQ_SUMMARY_MODEL`, otherwise reuse the agent provider | [`src/finance_agent/context.py:251-267`](../../src/finance_agent/context.py#L251-L267) |
| Groq evaluation judge | `GROQ_JUDGE_MODEL`, default `openai/gpt-oss-120b` | [`src/finance_agent/evaluation.py:63-73`](../../src/finance_agent/evaluation.py#L63-L73) |
| Groq credential | `GROQ_API_KEY` | [`src/finance_agent/agent.py:96`](../../src/finance_agent/agent.py#L96), [`.env.example:1`](../../.env.example#L1) |
| TypeSafe/Jev | `TYPESAFE_API_KEY`, `TYPESAFE_MODEL`, ten-second client timeout | [`src/finance_agent/jev.py:10-29`](../../src/finance_agent/jev.py#L10-L29), [`.env.example:2-6`](../../.env.example#L2-L6) |
| Evaluation trigger | `EVAL_CONTEXT_TRIGGER_TOKENS`, default `1500` | [`src/finance_agent/evaluation.py:71-73`](../../src/finance_agent/evaluation.py#L71-L73) |
| MCP bind | `MCP_HOST`, `MCP_PORT` | [`src/finance_agent/server.py:177-184`](../../src/finance_agent/server.py#L177-L184) |
| Streamlit MCP target | `MCP_URL` | [`src/finance_agent/ui.py:35-37`](../../src/finance_agent/ui.py#L35-L37) |
| Streamlit bind | `UI_HOST`, `UI_PORT` | [`src/finance_agent/ui.py:497-513`](../../src/finance_agent/ui.py#L497-L513) |
| Rule preference file | `FINANCE_UI_RULES_PATH`, otherwise `~/.finance-agent/rules.json` | [`src/finance_agent/ui.py:79-86`](../../src/finance_agent/ui.py#L79-L86) |

The current direct dependencies are Groq, MCP, Pydantic, Streamlit, and TypeSafe SDK; pytest is the dev dependency ([`pyproject.toml:1-16`](../../pyproject.toml#L1-L16)). The current checkout does **not** declare or import the `instructor` package: structured Groq responses are implemented with `response_format: json_schema` and Pydantic validation ([`src/finance_agent/agent.py:73-125`](../../src/finance_agent/agent.py#L73-L125), [`pyproject.toml:7-13`](../../pyproject.toml#L7-L13)). The migration must not alter that provider path.

## Persistence, concurrency, and streaming

- Finance sessions, locks, ledgers, messages, and uploaded CSV contents are process memory owned by `SessionStore` and `Session` ([`src/finance_agent/server.py:39-74`](../../src/finance_agent/server.py#L39-L74), [`src/finance_agent/models.py:43-49`](../../src/finance_agent/models.py#L43-L49)).
- Uploaded bytes and sessions disappear on MCP restart ([`README.md:42-52`](../../README.md#L42-L52)).
- Built-in data is packaged as `src/finance_agent/data/demo.csv`, with a separate generated 5,000-row compaction fixture ([`src/finance_agent/server.py:35-36`](../../src/finance_agent/server.py#L35-L36), [`tools/generate_context_compaction_csv.py:8-33`](../../tools/generate_context_compaction_csv.py#L8-L33)).
- Rule preferences persist in a local JSON file using a temporary file and atomic replacement ([`src/finance_agent/ui.py:89-107`](../../src/finance_agent/ui.py#L89-L107)).
- Evaluation reports are written beneath `evals/results/` ([`src/finance_agent/evaluation.py:129-144`](../../src/finance_agent/evaluation.py#L129-L144)).
- No database or vector store is configured in the dependencies or source ([`pyproject.toml:7-13`](../../pyproject.toml#L7-L13), [`src/finance_agent`](../../src/finance_agent)).
- Each finance session is serialized by its own `asyncio.Lock`; the blocking agent loop runs in a worker thread ([`src/finance_agent/server.py:89-122`](../../src/finance_agent/server.py#L89-L122)).
- Chat is complete-response, not token-streaming: `run_agent` returns one `AgentResult` and the server waits for it ([`src/finance_agent/agent.py:180-246`](../../src/finance_agent/agent.py#L180-L246), [`src/finance_agent/server.py:114-122`](../../src/finance_agent/server.py#L114-L122)).

## Tests, evaluation, and deployment inventory

| Area | Existing coverage | Source |
|---|---|---|
| Agent | Tool execution, malformed calls, max steps, unknown tools, provider errors | [`tests/test_agent.py`](../../tests/test_agent.py) |
| Budget rules | Structured compilation, hallucinated values, schema compatibility, deterministic evaluation | [`tests/test_budget.py`](../../tests/test_budget.py) |
| Finance | Totals, budgets, CSV validation, zero-income behavior | [`tests/test_finance.py`](../../tests/test_finance.py) |
| Context | Jev keep/trim/drop, summary fallback, canonical-history preservation, failure behavior | [`tests/test_context.py`](../../tests/test_context.py) |
| Jev | Generic decisions, Noul extraction, missing-answer validation | [`tests/test_jev.py`](../../tests/test_jev.py) |
| MCP | Exact tools, structured outputs, lifecycle, custom-rule confirmation | [`tests/test_server.py`](../../tests/test_server.py) |
| Streamlit UI | Rule persistence, navigation, stale-server error, context rendering, live-context reruns | [`tests/test_ui.py`](../../tests/test_ui.py) |
| Evaluation | Twelve-case notebook-style golden set with literal checks and independent LLM/Jev judges | [`tests/test_evaluation.py`](../../tests/test_evaluation.py), [`evals/golden.json`](../../evals/golden.json) |

The existing suite contains 30 tests and passed before this plan was written. Live-provider evaluation still requires real credentials because the runner rejects execution without `GROQ_API_KEY` ([`src/finance_agent/evaluation.py:63-65`](../../src/finance_agent/evaluation.py#L63-L65)).

The Python `Dockerfile` builds one image used by both current Compose services ([`Dockerfile`](../../Dockerfile), [`docker-compose.yml:1-25`](../../docker-compose.yml#L1-L25)). Compose exposes MCP on `127.0.0.1:8000` and Streamlit on `127.0.0.1:8501` ([`docker-compose.yml:11-24`](../../docker-compose.yml#L11-L24)). No `.github/workflows/` directory or CI definition exists in the current tracked tree.
