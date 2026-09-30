# Target architecture

> Current extension: the completed UI now includes durable JSON chat threads. Where this original migration plan describes the earlier memory-only or four-tool baseline, [`../chat-thread-persistence.md`](../chat-thread-persistence.md) is authoritative.

## Decision

Use React as a browser MCP client and keep the current Python MCP server as the sole application backend. Do not add FastAPI, a REST translation layer, a database, or another agent framework.

```text
Browser
  ├─ GET / and assets ───────────────┐
  └─ MCP Streamable HTTP at /mcp ───┤
                                      v
                         React UI container
                         Nginx static server
                         and same-origin proxy
                                      |
                                      | MCP_UPSTREAM
                                      v
                       unchanged Python MCP product
                         ├─ SessionStore
                         ├─ finance agent
                         ├─ finance calculations
                         ├─ Groq
                         └─ TypeSafe/Jev
```

The MCP server already exposes the complete UI-facing capability as four typed tools ([`src/finance_agent/server.py:130-184`](../../src/finance_agent/server.py#L130-L184)). The current UI already communicates exclusively through those tools ([`src/finance_agent/ui.py:35-50`](../../src/finance_agent/ui.py#L35-L50)). A FastAPI adapter would therefore duplicate validation and transport contracts without removing any existing component.

## Selected stack

### Frontend

- React and TypeScript, built with Vite.
- Tailwind CSS for the small layout and color system.
- Native semantic controls rather than a component library.
- `react-markdown` for assistant answers, with raw HTML disabled.
- Official `@modelcontextprotocol/client` using `StreamableHTTPClientTransport`.
- React state and reducers for page-lifetime state.
- Versioned `localStorage` for confirmed rule preferences only.
- npm with a committed `package-lock.json`.
- Node.js 24 for local and container builds.

### Backend

- Existing Python 3.12 package and `uv` workflow ([`.python-version`](../../.python-version), [`pyproject.toml:1-16`](../../pyproject.toml#L1-L16)).
- Existing MCP server, Pydantic models, agent loop, finance code, context manager, Groq provider, and Jev client remain unchanged ([`src/finance_agent/server.py`](../../src/finance_agent/server.py), [`src/finance_agent/agent.py`](../../src/finance_agent/agent.py), [`src/finance_agent/finance.py`](../../src/finance_agent/finance.py), [`src/finance_agent/context.py`](../../src/finance_agent/context.py)).
- Existing Streamable HTTP `/mcp` endpoint remains the only application API ([`src/finance_agent/server.py:177-184`](../../src/finance_agent/server.py#L177-L184)).

### Packaging and deployment

- The root `Dockerfile` continues to build the MCP product ([`Dockerfile`](../../Dockerfile)).
- `web/Dockerfile` builds the React bundle with Node 24, then serves it from Nginx.
- The UI image accepts `MCP_UPSTREAM` at runtime and proxies same-origin `/mcp` requests to it.
- Docker Compose combines the two products while retaining the current user-facing ports: UI at `127.0.0.1:8501`, MCP at `127.0.0.1:8000` ([`docker-compose.yml:11-24`](../../docker-compose.yml#L11-L24)).

## Why FastAPI is not required

The MCP server already provides:

- Pydantic-derived input and output schemas through structured MCP tools ([`src/finance_agent/server.py:138-169`](../../src/finance_agent/server.py#L138-L169)).
- Request validation for dates, enums, nested budget rules, and structured results ([`src/finance_agent/budget.py:39-122`](../../src/finance_agent/budget.py#L39-L122), [`src/finance_agent/models.py:13-49`](../../src/finance_agent/models.py#L13-L49)).
- Streamable HTTP and Uvicorn hosting through the MCP SDK ([`src/finance_agent/server.py:177-184`](../../src/finance_agent/server.py#L177-L184)).
- Session creation, use, synchronization, and closure ([`src/finance_agent/server.py:39-127`](../../src/finance_agent/server.py#L39-L127)).
- Typed error results from the agent ([`src/finance_agent/agent.py:204-246`](../../src/finance_agent/agent.py#L204-L246)).

FastAPI would require four HTTP endpoints, duplicate request/response models, an MCP client inside FastAPI, another deployment boundary, and OpenAPI-to-TypeScript generation. None of those additions unlock current functionality. The frontend can use the MCP tool schemas directly and maintain small TypeScript domain types checked by integration tests.

## Browser-to-MCP topology

The browser connects to `/mcp` on the same origin that serves the React bundle. Nginx forwards that path to `MCP_UPSTREAM` without buffering and with long request timeouts. This design:

- keeps `src/finance_agent/server.py` unchanged;
- avoids browser CORS configuration on the MCP product;
- preserves MCP `POST`, `GET`, and `DELETE` methods and response headers;
- lets the UI and MCP remain separately built and runnable products; and
- keeps the upstream address out of browser build-time configuration.

Direct cross-origin browser-to-MCP communication remains a future alternative. It would require matching MCP transport-security and CORS allowlists, permission for MCP request headers, and exposure of `Mcp-Session-Id`; those server changes conflict with the current no-backend-change boundary.

## Streaming decision

Do not add custom SSE or WebSocket chat streaming. The current MCP transport may use HTTP streaming internally, but application answers are complete results: `run_agent` executes until it returns an `AgentResult`, and `ask_finance_agent` awaits that completed result ([`src/finance_agent/agent.py:180-246`](../../src/finance_agent/agent.py#L180-L246), [`src/finance_agent/server.py:89-122`](../../src/finance_agent/server.py#L89-L122)). The React UI will show a pending state until that result arrives.

Adding token streaming would require changing the Groq provider, agent loop, MCP tool contract, context-report timing, tests, and UI protocol. That is functionality change, not presentation migration.

## State ownership

```text
MCP process memory
  finance session, ledger, canonical agent messages, per-session lock

React page memory
  current session ID/info, transcript, controls, parsed preview,
  warnings, pending/error state, live context

Browser localStorage
  rule text, confirmed rules, confirmation signature, schema version
```

The React transcript remains a UI copy. The authoritative agent conversation continues to live in the MCP `Session.messages` list ([`src/finance_agent/models.py:43-49`](../../src/finance_agent/models.py#L43-L49), [`src/finance_agent/agent.py:188-239`](../../src/finance_agent/agent.py#L188-L239)). No server-session data is copied into `localStorage`.

## Architecture decisions and tradeoffs

| Decision | Selected approach | Tradeoff | Alternative considered |
|---|---|---|---|
| Backend | MCP server only | No REST/OpenAPI endpoint layer | FastAPI would duplicate all four tool contracts |
| Browser transport | Same-origin Nginx proxy | UI image includes a small runtime web server | Direct MCP needs backend CORS and transport-security changes |
| Chat delivery | Complete response | No token-by-token output | SSE/WebSocket requires agent changes |
| Server state | In-memory active sessions plus validated per-chat JSON | Local restart rehydrates chats; horizontal multi-writer scaling remains out of scope | A database is unnecessary for the local single-user product |
| Client state | React state/reducer | State transitions are explicit | Zustand is unnecessary for one page |
| Server calls | Small MCP wrapper | No generic cache/devtools | TanStack Query offers little for non-idempotent tool calls |
| Components | Native HTML plus Tailwind | Accessibility must be verified directly | shadcn/Radix adds generated files and dependencies |
| Contract | TypeScript domain types plus MCP discovery/contract tests | Types are mirrored | OpenAPI requires FastAPI; JSON-schema codegen adds a pipeline |
| Structured model output | Preserve Groq JSON schema plus Pydantic | No extra abstraction | Adding Instructor would modify the provider boundary |
| Authentication | None, loopback-only | Not safe for public exposure | MCP OAuth or an authenticated edge is future scope |
| Rule persistence | Versioned `localStorage` | Existing JSON preferences need one-time reconfirmation | Import UI or file-serving endpoint adds behavior |
| Markdown | `react-markdown`, raw HTML disabled | Small rendering differences from Streamlit are possible | Raw HTML rendering is an unnecessary XSS risk |
| Packaging | Two images in one repository | Releases share one repository | Splitting repositories adds coordination overhead |

## Feature parity matrix

`N/A — direct MCP` means there is intentionally no FastAPI endpoint.

| Streamlit behavior | React owner | FastAPI endpoint | MCP tool | Notes |
|---|---|---|---|---|
| Page shell and disclaimer | `App` | N/A | None | Preserve current wording from [`src/finance_agent/ui.py:398-401`](../../src/finance_agent/ui.py#L398-L401) |
| Chat/Settings navigation | `App` | N/A | None | Client-only view state |
| Demo/upload ledger selection | `SessionPanel` | N/A — direct MCP | `create_finance_session`; `parse_budget_rules` | Uploaded text is sent only when upload mode is active |
| CSV selection and decoding | `SessionPanel` | N/A | None until a tool call | Fatal UTF-8 decode; server retains authoritative size/row validation from [`src/finance_agent/finance.py:13-91`](../../src/finance_agent/finance.py#L13-L91) |
| Context strategy | `SessionPanel` | N/A — direct MCP | `create_finance_session`; `ask_finance_agent` | Mode may change during an existing session, matching [`src/finance_agent/server.py:89-105`](../../src/finance_agent/server.py#L89-L105) |
| Date override | `SessionPanel` | N/A — direct MCP | `create_finance_session` | Send ISO date only when enabled |
| Start new session | `App` + `SessionPanel` | N/A — direct MCP | `close_finance_session`, then `create_finance_session` | Clear transcript and live context only after successful creation |
| Session summary | `SessionPanel` | N/A — direct MCP | `create_finance_session` | Render `SessionInfo` |
| Show live context | `SettingsPanel` / `App` | N/A — direct MCP | `ask_finance_agent` | Controls `include_context` |
| Edit rules | `SettingsPanel` | N/A | None | Controlled text plus local preference save |
| Parse rules | `SettingsPanel` | N/A — direct MCP | `parse_budget_rules` | Include uploaded ledger text when active |
| Compiled preview | `SettingsPanel` | N/A | None | Render `BudgetRulePreview` already returned by MCP |
| Validated JSON | `SettingsPanel` | N/A | None | Native details element |
| Confirm rules | `SettingsPanel` | N/A | None | Save rules and current signature locally |
| Detect stale preview/confirmation | `SettingsPanel` | N/A | None | Compare signatures before confirming or creating |
| Restore defaults | `SettingsPanel` | N/A | None | Clear parsed and confirmed values |
| Existing transcript | `ChatPanel` | N/A | None | Page-memory copy only |
| Submit question | `ChatPanel` / `App` | N/A — direct MCP | `ask_finance_agent` | Auto-create a session when absent |
| Answer pending state | `ChatPanel` | N/A | None | Disable concurrent sends to match Streamlit serialization |
| Markdown answer | `ChatPanel` | N/A | None | Render `AgentResult.answer` safely |
| Agent trace | `ChatPanel` | N/A | None | Render `AgentResult.status`, `steps`, and `trace` |
| Context JSON | `ChatPanel` | N/A | None | Render `AgentResult.context` |
| Live context inspector | `ContextPanel` | N/A | None | Uses the same `ContextReport`; no extra server call |
| Context tabs and fullscreen | `ContextPanel` | N/A | None | Client-only controls |
| Error banners | `App` and panels | N/A | All called tools | Distinguish transport/tool errors from typed agent status |

## UI design rules

- Use a calm neutral palette, restrained accent color, generous spacing, and a single centered content column.
- Keep session controls visually compact and place them beside the main content on wide screens and above it on narrow screens.
- Use native labels, focus indicators, button elements, tab semantics, `aria-live` status text, and keyboard-operable details.
- Do not introduce dashboards, charts, animated decoration, onboarding flows, or unrelated navigation.
- Preserve every existing capability, but do not add features merely because React makes them possible.
