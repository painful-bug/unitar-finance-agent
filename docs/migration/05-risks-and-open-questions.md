# Risks, edge cases, assumptions, and open questions

> Current extension: persistent local JSON threads intentionally reopen the earlier memory-only boundary. Uploaded CSVs, canonical messages, and turns now survive restart with the security and lifecycle constraints in [`../chat-thread-persistence.md`](../chat-thread-persistence.md).

## Locked scope

The following decisions are fixed for this migration:

- Deployment stays local and single-user, matching the current explicit product boundary ([`README.md:15`](../../README.md#L15)).
- React reaches the unchanged MCP product through the UI container's same-origin reverse proxy.
- The repository remains a monorepo and produces separate MCP and UI images.
- Port `8501` remains the user-facing UI port; MCP remains on `8000` ([`docker-compose.yml:11-24`](../../docker-compose.yml#L11-L24)).
- Agent, finance, budget, context, Jev, models, evaluation, MCP server, and packaged data remain unchanged.
- Existing custom rules are reconfirmed once rather than imported from `~/.finance-agent/rules.json`.
- FastAPI, REST endpoints, OpenAPI, database persistence, authentication, Zustand, TanStack Query, shadcn/ui, custom SSE, and WebSockets are not added.
- Graphify intermediate files remain untouched.

## Risks and mitigations

| Risk or edge case | Why it exists | Mitigation | Verification |
|---|---|---|---|
| Streamlit reruns currently synchronize widget values implicitly | Streamlit re-executes `render` and stores widget/session state ([`src/finance_agent/ui.py:398-494`](../../src/finance_agent/ui.py#L398-L494)) | Use one explicit React state owner and controlled inputs; avoid duplicated state in children | Component tests across Chat/Settings changes and session resets |
| Rule signature completes after newer input is selected | Browser hashing is asynchronous, unlike current synchronous `hashlib.sha256` ([`src/finance_agent/ui.py:74-76`](../../src/finance_agent/ui.py#L74-L76)) | Tie each digest to the exact file/rules revision and discard stale completions | Rapidly change rule text/file in unit tests and assert only latest digest wins |
| Browser decoding can silently replace invalid UTF-8 | `File.text()` is not equivalent to Python's strict `.decode("utf-8")` ([`src/finance_agent/ui.py:66-71`](../../src/finance_agent/ui.py#L66-L71)) | Decode `arrayBuffer` with `TextDecoder("utf-8", { fatal: true })` | Invalid-byte unit and component test; assert no MCP call |
| Client-side CSV hints diverge from server validation | The server enforces exact size, row, column, enum, date, and amount rules ([`src/finance_agent/finance.py:13-91`](../../src/finance_agent/finance.py#L13-L91)) | Keep browser validation limited to file presence/decoding; display authoritative server error | Exercise oversized, empty, missing-column, and bad-row inputs through MCP integration |
| Duplicate non-idempotent operations after a timeout | Create and ask may have succeeded even if the response was lost | Never automatically retry tool calls; reconnect only for the next explicit action | MCP wrapper test asserts one call per user action |
| MCP connection loss leaves UI session identifiers stale | Finance sessions and MCP transport sessions have different lifecycles | Reconnect transport for the next action and let the server return typed unknown-session errors | Kill/restart test MCP between actions and verify visible failure |
| Abrupt tab closure leaves a finance session in memory | Reliable async cleanup during unload is not available; current Streamlit UI also lacks tab-close cleanup | Best-effort normal unmount cleanup only; document that MCP restart clears sessions | Manual close/unload test; do not make stronger lifecycle claims |
| Multiple MCP replicas cannot share sessions | Sessions and locks are process-local dictionaries ([`src/finance_agent/server.py:39-48`](../../src/finance_agent/server.py#L39-L48)) | Run one local MCP process; do not introduce horizontal scaling | Compose defines one MCP service instance |
| Nginx buffers or times out an MCP request | Model calls may take longer than ordinary HTTP responses; MCP also uses GET/DELETE transport operations | Disable proxy buffering, preserve methods/headers, and set a long read timeout | Initialize, list, call, and terminate through the production UI container |
| Cross-origin headers fail in a browser | MCP Streamable HTTP uses non-safelisted request/response headers | Use same-origin browser traffic and proxy server-side to MCP | Browser E2E connects only to `/mcp` on the UI origin |
| Assistant Markdown creates an XSS boundary | Model output is untrusted presentation data | Use `react-markdown` without raw HTML support; React escapes context text | Render script/HTML payloads in component tests |
| Context-panel output differs from the Streamlit iframe | Current panel hand-builds escaped HTML and JavaScript ([`src/finance_agent/ui.py:186-302`](../../src/finance_agent/ui.py#L186-L302)) | Render the same fields as React elements and test each role/tool/action state | `ContextPanel` tests plus Playwright tab interaction |
| Fullscreen is denied or unavailable | Browser fullscreen requires user activation and may be restricted | Keep the panel fully usable inline; silently retain inline mode on rejection | Manual desktop-browser check and component event test |
| Decimal values may be JSON strings or numbers | Pydantic's Decimal schema permits both representations | Accept `string | number` in UI types and never perform financial arithmetic in JavaScript | Contract fixture covers both representations |
| Rules confirmed for one ledger are used with another | Rule categories depend on the selected ledger ([`src/finance_agent/server.py:76-87`](../../src/finance_agent/server.py#L76-L87)) | Require the exact current ledger/rules signature before passing confirmed rules | Change ledger after confirmation and assert built-in rules are used |
| Parsed preview goes stale after text edits | Current UI preserves the preview but warns when signatures differ ([`src/finance_agent/ui.py:353-394`](../../src/finance_agent/ui.py#L353-L394)) | Preserve preview, mark it stale, and disable confirmation until reparsed | Component test |
| Context mode changes mid-session | The server mutates `session.context_mode` when a mode is supplied ([`src/finance_agent/server.py:89-105`](../../src/finance_agent/server.py#L89-L105)) | Always send the currently selected mode with `ask_finance_agent` | Integration test switches modes between questions |
| User submits multiple questions concurrently | Streamlit handles one script execution at a time | Disable prompt and session mutations during a chat request | Rapid-submit component/E2E test |
| New-session creation fails after old-session closure | Current behavior closes first, so failed replacement can leave no server session ([`src/finance_agent/ui.py:425-430`](../../src/finance_agent/ui.py#L425-L430)) | Preserve the exact ordering and show the creation error; clear client session state once the old close was attempted | Deterministic failure test documents parity rather than changing semantics |
| Typed agent errors are mistaken for transport failures | `ask` returns `AgentResult(status="error")` for unknown sessions/provider configuration ([`src/finance_agent/server.py:96-113`](../../src/finance_agent/server.py#L96-L113)) | Render valid `AgentResult` answers and details for all statuses | MCP wrapper and ChatPanel tests |
| Preference storage is corrupt or unavailable | Browser storage may contain stale JSON or throw in privacy/quota modes | Validate the version and required fields; fall back to defaults/in-memory state | Storage corruption and throwing-storage tests |
| Existing preferences appear lost at cutover | Browser code cannot read `~/.finance-agent/rules.json` without a new endpoint ([`src/finance_agent/ui.py:79-107`](../../src/finance_agent/ui.py#L79-L107)) | Document one-time reconfirmation; do not add import or filesystem APIs | README checklist and manual cutover test |
| Public exposure leaks unauthenticated finance operations | The current product deliberately has no auth ([`README.md:15`](../../README.md#L15)) | Keep Compose loopback binding and mark public hosting unsupported | Inspect Compose bindings; security note in README |
| Live-provider verification is unavailable in CI | Groq and Jev require real credentials; evaluation refuses to run without Groq ([`src/finance_agent/evaluation.py:63-65`](../../src/finance_agent/evaluation.py#L63-L65)) | Use a deterministic test-only MCP provider for E2E; report live evaluation separately | CI passes without secrets; optional credentialed run clearly labelled |
| Incomplete Graphify data is mistaken for a current architecture graph | Final `graph.json` and `GRAPH_REPORT.md` are absent | Cite source files, mark graph incomplete, and leave intermediates untouched | Documentation review |

## Streamlit conveniences that must be rebuilt

### Rerun and widget persistence

Streamlit reruns the module and reconnects widget/session values automatically. React must instead coordinate controlled inputs, derived signatures, parsed/confirmed state, and resets explicitly ([`src/finance_agent/ui.py:313-443`](../../src/finance_agent/ui.py#L313-L443)). The rule workflow is the highest-risk state machine and receives focused unit/component tests.

### Request serialization and feedback

Streamlit's synchronous script flow naturally blocks a second submission while the first call is in progress and provides spinner/error primitives ([`src/finance_agent/ui.py:469-494`](../../src/finance_agent/ui.py#L469-L494)). React must disable conflicting controls, expose pending state accessibly, and decide which existing state survives an error.

### File lifecycle

React retains an unsubmitted `File` in page memory, decodes it strictly when needed, and invalidates signatures when the file changes. Once the first question is submitted, the uploaded CSV is stored only in the owner-readable server-side thread JSON; refresh restores the chat without returning CSV contents to the browser.

### Markdown, tables, JSON, and expanders

Streamlit supplies Markdown rendering, dataframes, JSON viewers, and expanders ([`src/finance_agent/ui.py:353-380`](../../src/finance_agent/ui.py#L353-L380), [`src/finance_agent/ui.py:445-486`](../../src/finance_agent/ui.py#L445-L486)). React replaces them with one Markdown dependency and native semantic elements; it does not introduce a component system.

### Sidebar and responsive layout

Streamlit provides a collapsible sidebar automatically ([`src/finance_agent/ui.py:411-439`](../../src/finance_agent/ui.py#L411-L439)). The React layout must explicitly place session controls beside content on wide screens and above content on narrow screens without hiding functionality.

### Safe custom HTML

The iframe panel currently calls `html.escape` for roles, content, tool names, arguments, IDs, and fallback text ([`src/finance_agent/ui.py:186-243`](../../src/finance_agent/ui.py#L186-L243)). React text nodes provide the replacement escaping; no `dangerouslySetInnerHTML` is allowed.

## Failure-mode behavior to preserve

- Missing upload in upload mode: show “Choose a CSV file first.” and do not call MCP ([`src/finance_agent/ui.py:66-71`](../../src/finance_agent/ui.py#L66-L71)).
- Close failure while replacing a session: ignore the close error and attempt creation ([`src/finance_agent/ui.py:53-64`](../../src/finance_agent/ui.py#L53-L64)).
- Parse failure: show the error and keep the editor usable ([`src/finance_agent/ui.py:336-351`](../../src/finance_agent/ui.py#L336-L351)).
- Missing/old MCP tool: show explicit restart guidance ([`src/finance_agent/ui.py:38-45`](../../src/finance_agent/ui.py#L38-L45)).
- Agent/provider/context failures: render the typed result or returned tool error; never invent an answer ([`src/finance_agent/server.py:96-113`](../../src/finance_agent/server.py#L96-L113), [`src/finance_agent/agent.py:204-221`](../../src/finance_agent/agent.py#L204-L221)).
- Context disabled: send `include_context=false`; trace and summary metadata still render from the result ([`src/finance_agent/ui.py:472-489`](../../src/finance_agent/ui.py#L472-L489)).
- No prior context: show the existing empty-state meaning in the live context panel ([`src/finance_agent/ui.py:230-235`](../../src/finance_agent/ui.py#L230-L235)).

## Open questions

### Blocking questions

None for the selected local, single-user migration.

### Verified specification discrepancy: Instructor

The implementation request states that Instructor is already used and must remain intact. In this checkout:

- `instructor` is not declared in direct dependencies ([`pyproject.toml:7-13`](../../pyproject.toml#L7-L13)); and
- structured output is implemented directly through Groq `response_format: { type: "json_schema" }` followed by Pydantic validation ([`src/finance_agent/agent.py:73-125`](../../src/finance_agent/agent.py#L73-L125)).

This does not block the migration because the controlling requirement is to leave the agent/provider path unchanged. Implementation must neither add nor remove Instructor. If another branch contains an Instructor integration, that branch must be inspected and the plan refreshed before implementation there.

### Future questions that reopen architecture

These are deliberately out of scope. Any one of them requires a new design decision before work begins:

1. **Public hosting:** choose MCP OAuth or an authenticated edge, exact allowed origins/hosts, TLS termination, and secret/session ownership.
2. **Multi-user use:** define identity, tenant isolation, rule preference storage, session ownership, upload retention, quotas, and audit policy.
3. **Horizontal scaling:** introduce shared session state or sticky routing and decide how per-session locks work across processes.
4. **Persistent sessions/uploads:** define database/object storage, encryption, retention, deletion, migrations, and recovery.
5. **Token streaming:** change the provider/agent/MCP result contract and define partial-error/cancellation semantics.
6. **Static CDN-only UI:** enable direct browser MCP access with exact CORS and transport-security configuration.
7. **Schema generation:** add it only if contract drift becomes a demonstrated maintenance problem.

## Acceptance assumptions

- “Feature parity” means every current user-visible interaction and result field remains available; it does not require pixel-identical Streamlit styling.
- “Keep the agent unchanged” means no edits to `agent.py`, `budget.py`, `context.py`, `evaluation.py`, `finance.py`, `jev.py`, `models.py`, `server.py`, or packaged finance data.
- The test-only deterministic MCP process may import and configure the existing public construction points but may not add a production test mode.
- Rule preferences begin with built-in defaults in React; users manually re-enter and reconfirm custom rules once.
- Browser reload restores saved transcripts, safe configuration metadata, live context from completed turns, and the rehydrated finance session. Only unsubmitted draft text and an unsubmitted file selection are intentionally lost.
- Local deployment binds exposed ports to `127.0.0.1` and is not presented as safe for untrusted networks.
- The MCP tool names, inputs, outputs, and agent status values are compatibility contracts.
- The implementation stops after every phase and waits for explicit user authorization before proceeding.
