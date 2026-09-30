# Migration phases and testing

> Historical migration sequence: the later durable-thread overhaul supersedes the original tool-surface and reload assumptions. See [`../chat-thread-persistence.md`](../chat-thread-persistence.md) for the current contract and restart behavior.

## Execution rule

Implementation uses five hard checkpoints. Complete and verify exactly one phase, report its evidence, then stop. The next phase begins only after the user compacts context and explicitly authorizes continuation.

The Python agent/backend implementation is protected throughout. The current server already separates UI calls from the agent and exposes the complete lifecycle through MCP ([`src/finance_agent/server.py:130-184`](../../src/finance_agent/server.py#L130-L184)); the migration must not alter that boundary.

## Baseline before Phase 1

Capture these results before implementation:

1. `git status --short` and current commit.
2. `uv run pytest` — currently expected to pass 30 tests.
3. `uv build` or the repository's existing package-build check.
4. In-process MCP discovery showing all eight finance and thread tools, as asserted by `tests/test_server.py`.
5. Checksums or a `git diff --exit-code` baseline for the protected Python files listed in [`03-file-by-file-plan.md`](03-file-by-file-plan.md).

Do not require live Groq or TypeSafe calls for ordinary migration phases. The evaluation runner explicitly requires `GROQ_API_KEY` ([`src/finance_agent/evaluation.py:63-65`](../../src/finance_agent/evaluation.py#L63-L65)); provider-backed evaluation is a separate optional verification when credentials are available.

## Phase 1 — Frontend and MCP transport foundation

### Goal

Create the smallest runnable React/Vite application, exact UI-facing TypeScript contracts, and an MCP client wrapper. Keep Streamlit fully runnable and make no existing-file changes.

### Files touched

New files only:

```text
web/package.json
web/package-lock.json
web/tsconfig.json
web/eslint.config.js
web/vite.config.ts
web/index.html
web/src/main.tsx
web/src/App.tsx
web/src/styles.css
web/src/types.ts
web/src/lib/mcp.ts
web/src/lib/mcp.test.ts
web/src/test/setup.ts
```

### Dependencies

Runtime:

- `react`
- `react-dom`
- `@modelcontextprotocol/client`

Development:

- Vite and the React plugin
- TypeScript
- Tailwind CSS and its Vite integration
- ESLint with React/TypeScript rules
- Vitest, jsdom, and Testing Library

Do not add React Router, Zustand, TanStack Query, shadcn/ui, a formatter, schema-codegen, or a second HTTP client.

### Implementation behavior

- `types.ts` mirrors the eight MCP tool inputs/outputs described in [`02-api-contract.md`](02-api-contract.md) and [`../chat-thread-persistence.md`](../chat-thread-persistence.md).
- `mcp.ts` constructs one `Client` plus `StreamableHTTPClientTransport` for same-origin `/mcp`.
- Connection performs discovery and validates the exact eight-tool surface.
- Tool calls validate `isError`, textual error content, `structuredContent`, and required top-level fields.
- No tool call is automatically retried.
- A transport failure invalidates the client; a later explicit action may reconnect.
- The shell renders title, disclaimer, connection state, and placeholder Chat/Settings navigation only.
- Vite's development proxy forwards `/mcp` to `MCP_UPSTREAM` or `http://127.0.0.1:8000/mcp` without changing the MCP server.

### Definition of done

- `npm ci` succeeds from `web/`.
- Lint, typecheck, unit tests, and production build pass.
- With `finance-mcp` running, the browser connects through the Vite proxy and discovers all eight tools.
- Tool-wrapper tests cover success, `isError`, absent structured content, malformed required fields, unknown-tool restart guidance, and no automatic retry.
- `finance-ui` still runs unchanged.
- `git diff --` reports no modifications under `src/finance_agent/`, `tests/`, root packaging, or deployment files.

### Verification

```bash
cd web
npm ci
npm run lint
npm run typecheck
npm test -- --run
npm run build
```

Manual:

1. Start `uv run --env-file .env finance-mcp`.
2. Start the Vite dev server.
3. Confirm the shell loads and reports an MCP connection.
4. Stop MCP and confirm the UI reports unavailability without looping or replaying a request.

### Checkpoint

Stop after reporting commands, results, files created, and the protected-file diff.

## Phase 2 — Session and settings parity

### Goal

Implement every session control and budget-rule settings behavior while Streamlit remains the default packaged UI.

### Files touched

```text
web/src/App.tsx
web/src/App.test.tsx
web/src/styles.css
web/src/components/SessionPanel.tsx
web/src/components/SettingsPanel.tsx
web/src/lib/preferences.ts
web/src/lib/preferences.test.ts
tests/e2e_mcp_server.py
```

### Dependencies

- Completed Phase 1 MCP wrapper and types.
- Existing `SessionStore(provider=...)` injection point for the deterministic test process ([`src/finance_agent/server.py:39-48`](../../src/finance_agent/server.py#L39-L48), [`src/finance_agent/server.py:130-131`](../../src/finance_agent/server.py#L130-L131)).
- Existing server-side CSV and rule validation remain authoritative ([`src/finance_agent/finance.py:60-91`](../../src/finance_agent/finance.py#L60-L91), [`src/finance_agent/budget.py:223-347`](../../src/finance_agent/budget.py#L223-L347)).

### Implementation behavior

#### Session controls

- Select bundled demo or uploaded CSV.
- Read uploads with `arrayBuffer` and fatal UTF-8 decoding; do not silently replace invalid bytes.
- Select `auto`, `jev`, or `summary`.
- Conditionally enable and display the date input.
- Compute current ledger/rules signature.
- Use confirmed custom rules only when their signature matches the current ledger and text.
- Starting a session best-effort closes the old finance session, creates a replacement, and clears transcript/live context after successful creation.
- Display transaction count, as-of date, mode, and active-rule count from `SessionInfo`.

#### Rule settings

- Preserve `DEFAULT_RULES_TEXT` exactly as the three current sentences ([`src/finance_agent/ui.py:16-22`](../../src/finance_agent/ui.py#L16-L22)).
- Store `{ version, rulesText, confirmedRules, confirmedSignature }` under one versioned localStorage key.
- Defensively reject malformed, incompatible, or incomplete stored data and use defaults.
- Compute SHA-256 over exact ledger bytes, one zero byte, and UTF-8 rule text; use literal `demo` bytes for the bundled ledger, matching [`src/finance_agent/ui.py:74-76`](../../src/finance_agent/ui.py#L74-L76).
- Parse through `parse_budget_rules`; preserve the previous preview when a call fails.
- Render the comparison table, formatted JSON, warnings, confirm action, stale warning, success/info status, and reset action.
- Reset clears parsed and confirmed state, restores defaults, and saves them.
- `localStorage` failure is non-fatal and leaves the in-memory UI usable.

#### Deterministic test MCP process

- Add only a test process; do not add a production environment switch.
- Reuse `build_server` and `SessionStore` with a fake provider.
- Provide deterministic structured rule compilation and deterministic agent turns sufficient for browser tests.
- Never import the test provider from production code.

### Definition of done

- All controls and conditional visibility match the current UI.
- Demo and uploaded sessions call `create_finance_session` with the correct arguments.
- A replacement session closes the prior session first but does not fail solely because close failed, matching [`src/finance_agent/ui.py:53-64`](../../src/finance_agent/ui.py#L53-L64).
- Rule draft, parse, confirmation, invalidation, and reset match Streamlit behavior.
- Confirmed rules survive a browser reload through localStorage.
- The old `~/.finance-agent/rules.json` is not read; README migration notes will require one-time reconfirmation.
- Streamlit remains runnable and remains the Compose `ui` service.
- Phase 1 checks and all 30 Python tests pass.

### Verification scenarios

1. Default rules appear on first load.
2. Edit rules, switch Chat/Settings, and confirm the text remains.
3. Parse and confirm a custom rule; reload and verify it is restored.
4. Change rule text and verify the preview/confirmation becomes stale.
5. Change uploaded ledger and verify the signature becomes stale.
6. Reset defaults and verify parsed/confirmed state clears.
7. Upload invalid UTF-8 and verify no MCP request is sent.
8. Upload a server-invalid CSV and verify the server error is displayed.
9. Start a demo session and verify the server-provided summary.
10. Start a second session and verify the first close is attempted.

### Checkpoint

Stop after reporting tests, manual evidence, and the protected-file diff.

## Phase 3 — Chat and context-inspector parity

### Goal

Complete chat submission, transcript rendering, trace/context details, and the full live context inspector without adding streaming or changing the agent.

### Files touched

```text
web/package.json
web/package-lock.json
web/playwright.config.ts
web/src/App.tsx
web/src/App.test.tsx
web/src/styles.css
web/src/components/ChatPanel.tsx
web/src/components/ContextPanel.tsx
web/src/components/ContextPanel.test.tsx
web/tests/app.spec.ts
tests/e2e_mcp_server.py
```

### Dependencies

- Add only `react-markdown` as the new runtime dependency.
- Add Playwright as the E2E dependency.
- Reuse Phase 2's deterministic MCP test process.

### Implementation behavior

#### Chat

- Render user and assistant messages in order.
- Render assistant content with `react-markdown`; do not enable raw HTML.
- Use one native form with the existing placeholder text.
- If no finance session exists, create it from the current controls before asking.
- Append the user message before the call, matching current behavior ([`src/finance_agent/ui.py:456-469`](../../src/finance_agent/ui.py#L456-L469)).
- Disable duplicate submissions while a call is pending.
- Call `ask_finance_agent` with session ID, question, current mode, and current live-context setting.
- Append the assistant answer and complete result after success.
- On a tool/transport failure, keep the submitted user message, show the error, and do not invent an assistant answer, matching [`src/finance_agent/ui.py:466-494`](../../src/finance_agent/ui.py#L466-L494).
- For typed `AgentResult.status` values other than `ok`, still render the returned answer and details.
- Expose status, steps, trace JSON, and context JSON in native details elements for every assistant result.

#### Live context

- Update the panel from the newest result only when `showContextLive` is enabled.
- Render strategy, token transition, percentage reduction, and fallback reason.
- Provide canonical and model-input tabs.
- Render system, user, assistant, tool, summary, and unknown roles with distinct but restrained styles.
- Show tool-call names and arguments, tool call IDs, and keep/trim/drop badges.
- Escape all content through normal React text rendering.
- Preserve whitespace and wrap long tool content.
- Double-click the panel to request/exit fullscreen; fullscreen failure must not break inline viewing.

### Definition of done

- First chat submission automatically creates a finance session.
- Only one question can be in flight.
- The deterministic E2E path returns and renders an answer.
- Markdown formatting works while raw HTML is rendered as text or ignored.
- Trace and context details are inspectable.
- Live context renders both tabs, metrics, fallback, roles, tool metadata, and decision badges.
- Starting a new session clears transcript and live context.
- No custom SSE/WebSocket code exists.
- No protected backend file changes exist.
- Python, frontend unit/component, and Playwright tests pass.

### Playwright scenarios

1. Load the app and verify accessible Chat/Settings navigation.
2. Start a demo session and verify its summary.
3. Enable live context, submit a question, and verify answer/trace/context details.
4. Switch context tabs and verify canonical/model content.
5. Edit, parse, confirm, and use a custom rule in a new session.
6. Upload a CSV and create a session.
7. Start another session and verify transcript/context reset.
8. Stop the upstream and verify the UI presents an error without duplicate calls.

### Checkpoint

Stop after reporting automated and manual parity results and the protected-file diff.

## Phase 4 — Container, Compose, documentation, and CI cutover

### Goal

Make React the default packaged UI while retaining the Streamlit source and command for one rollback phase.

### Files touched

```text
.dockerignore
.env.example
.gitignore
.github/workflows/ci.yml
README.md
docker-compose.yml
web/.dockerignore
web/Dockerfile
web/nginx/templates/default.conf.template
```

### Implementation behavior

#### UI image

- Build with a pinned Node 24 Alpine image using `npm ci` and `npm run build`.
- Copy only `dist/` into an Nginx Alpine runtime.
- Use the official Nginx template mechanism to substitute `MCP_UPSTREAM` at container start.
- Serve `index.html` as SPA fallback.
- Proxy `/mcp` to the exact configured upstream.
- Preserve method and response headers, use HTTP/1.1, disable request/response buffering where required, and set a read timeout long enough for model calls.
- Do not embed Groq or TypeSafe credentials in the UI image or JavaScript bundle.

#### Compose

- Keep the MCP service build, command, environment, and loopback port unchanged from [`docker-compose.yml:1-13`](../../docker-compose.yml#L1-L13).
- Change only the `ui` service to build `web/`, set `MCP_UPSTREAM=http://mcp:8000/mcp`, depend on MCP, and map `127.0.0.1:8501:80`.
- Retain the Streamlit `finance-ui` console command outside Compose for rollback during this phase.

#### CI

- Python job: install with the lockfile, run all tests, and build the Python package.
- Frontend job: Node 24, `npm ci`, lint, typecheck, unit/component tests, and production build.
- E2E job: install Chromium, start the deterministic MCP fixture and Vite server, and run Playwright.
- Container job: build both images or run `docker compose build` without requiring provider credentials.
- No deployment/publishing job is added.

### Definition of done

- MCP and UI images build independently.
- The UI image starts with only `MCP_UPSTREAM` as application configuration.
- Browser traffic to `/mcp` successfully initializes MCP, discovers tools, creates a session, asks, and closes.
- UI remains at `http://127.0.0.1:8501`; MCP remains at `http://127.0.0.1:8000/mcp`.
- Nginx does not buffer or truncate MCP traffic.
- `finance-ui` can still be started manually as rollback.
- CI passes from a clean checkout.
- Protected backend files remain unchanged.

### Verification

```bash
docker compose --env-file .env build
docker compose --env-file .env up -d
docker compose ps
curl --fail http://127.0.0.1:8501/
```

Then execute the manual session/settings/chat/context parity flow through the containerized UI. Live chat requires valid provider credentials; deterministic E2E remains the credential-free CI proof.

### Checkpoint

Stop after reporting image IDs/build results, Compose state, smoke results, CI-equivalent commands, and protected-file diff.

## Phase 5 — Remove Streamlit and perform final verification

### Goal

Remove the legacy Streamlit presentation only after React parity and container cutover are proven.

### Files touched

```text
.streamlit/config.toml                 DELETE
src/finance_agent/ui.py                DELETE
tests/test_ui.py                       DELETE
pyproject.toml                         MODIFY
uv.lock                                MODIFY
README.md                              MODIFY
docs/context-compaction-demo.md        MODIFY
```

### Implementation behavior

- Remove `streamlit` from Python dependencies.
- Remove the `finance-ui` console script.
- Regenerate `uv.lock` without opportunistically upgrading unrelated direct dependencies.
- Remove Streamlit-specific source, configuration, and tests.
- Update setup instructions to start MCP plus the React dev server, or use Compose.
- Update the context-compaction demo to use React labels while preserving its prompts and Jev evidence requirements ([`docs/context-compaction-demo.md:31-52`](../context-compaction-demo.md#L31-L52)).
- Document the one-time custom-rule reconfirmation caused by moving from a local JSON file to browser storage.

### Definition of done

- `rg -n 'streamlit|finance-ui|st\.'` returns only intentional historical references in `docs/migration/` and lockfile history is clean of the package.
- `uv sync --extra dev --frozen`, all backend tests, and package build pass.
- Frontend lint, typecheck, unit/component tests, build, and Playwright pass.
- Both images and Compose build from a clean checkout.
- Manual parity matrix has no missing interaction.
- `git diff --exit-code` is empty for all protected backend files.
- MCP discovery returns the four finance tools plus the four durable-thread tools.
- No FastAPI, Instructor, database, custom SSE/WebSocket, Zustand, TanStack Query, or component library was added.

### Final evidence report

Report separately:

- Python unit result.
- Frontend lint/typecheck/unit result.
- Playwright result.
- Python package build result.
- UI production build result.
- MCP discovery result.
- Docker image and Compose result.
- Live-provider result if credentials were available; otherwise state that it was not run.
- Protected-file diff result.

### Checkpoint

Stop. The migration is complete only when every definition-of-done item is satisfied; do not begin unrelated improvements.

## Test strategy by layer

### Python unit tests

Retain the existing tests for agent, finance, budgets, context, Jev, MCP, and evaluation. These protect the backend behavior that the migration must not change ([`tests/test_agent.py`](../../tests/test_agent.py), [`tests/test_finance.py`](../../tests/test_finance.py), [`tests/test_budget.py`](../../tests/test_budget.py), [`tests/test_context.py`](../../tests/test_context.py), [`tests/test_jev.py`](../../tests/test_jev.py), [`tests/test_server.py`](../../tests/test_server.py), [`tests/test_evaluation.py`](../../tests/test_evaluation.py)).

### Frontend unit tests

- Preference record validation, version mismatch, corruption, save/reset, and storage errors.
- Exact signature vector compatible with Python `hashlib.sha256` behavior from [`src/finance_agent/ui.py:74-76`](../../src/finance_agent/ui.py#L74-L76).
- Fatal invalid UTF-8 handling.
- MCP wrapper success and every error boundary.
- No automatic retry.
- Required-field narrowing for every tool result.

### Component tests

- Chat/Settings tabs and keyboard behavior.
- Conditional upload and date controls.
- Rule preview, warnings, confirmation, stale state, and defaults.
- Pending and error states.
- Markdown raw-HTML safety.
- Trace/context details.
- Context roles, tool calls, decision badges, tabs, metrics, and fallback.

### MCP integration tests

- Existing exact tool discovery.
- Existing session lifecycle and structured output.
- Existing rule preview to confirmed session flow.
- Browser E2E through the actual MCP protocol using the deterministic test process, not a mocked fetch shape.

### Playwright E2E

Use Chromium as the single required browser for v1 migration proof. Test user-visible behavior through the Vite same-origin proxy and real MCP SDK connection. Do not couple tests to internal React state.

### Container tests

- Build MCP and UI separately.
- Run Compose with no live-provider calls for startup and discovery.
- Verify UI HTTP 200.
- Verify MCP protocol initialization/tool discovery through Nginx.
- When credentials are available, run one end-to-end chat through Compose.

### Accessibility and manual checks

- Every input has a visible label.
- Keyboard focus order follows visual order.
- Tabs expose selected state.
- Pending and error text uses live regions without stealing focus.
- Color is not the only signal for statuses or keep/trim/drop actions.
- Context content remains readable without fullscreen.
- Narrow-screen layout avoids horizontal page scrolling.
