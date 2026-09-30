# File-by-file migration plan

> Historical plan: the later full-screen/thread-persistence overhaul supersedes component names and memory-only assumptions here. See [`../chat-thread-persistence.md`](../chat-thread-persistence.md) and the current source tree.

## Status definitions

- **KEEP**: no migration edit.
- **MODIFY**: edit in the named implementation phase.
- **DELETE**: remove only after React parity and cutover are verified.
- **NEW**: add as part of the migration.

The repository currently has 68 tracked files. Every current tracked file is listed below. The Graphify intermediates are deliberately retained because they are unrelated to the UI migration, even though they do not form a completed graph.

## Existing files

| File | Status | Phase | Exact action and reason |
|---|---|---:|---|
| `.dockerignore` | MODIFY | 4 | Exclude `web/`, frontend dependency/build outputs, and Playwright artifacts from the root MCP image build context. Keep existing secret, Git, virtualenv, cache, and evaluation-result exclusions. |
| `.env.example` | MODIFY | 4 | Preserve all provider settings and add `MCP_UPSTREAM=http://mcp:8000/mcp` for the UI container. Do not expose provider secrets to Vite/browser variables. |
| `.gitignore` | MODIFY | 4 | Add `web/node_modules/`, `web/dist/`, `web/coverage/`, `web/playwright-report/`, and `web/test-results/`. Preserve existing Python ignores. |
| `.python-version` | KEEP | — | Backend remains Python 3.12 as declared here and in [`pyproject.toml`](../../pyproject.toml). |
| `.streamlit/config.toml` | DELETE | 5 | Remove only after React is the verified default UI; it has no consumer after `finance-ui` is removed. |
| `Dockerfile` | KEEP | — | Remains the independently runnable Python MCP product. Frontend packaging uses `web/Dockerfile`. |
| `README.md` | MODIFY | 4, 5 | Phase 4 documents dual-product development, React URL, Compose, and one-time rule reconfirmation. Phase 5 removes Streamlit commands and references after rollback is no longer needed. |
| `docker-compose.yml` | MODIFY | 4 | Keep the MCP service configuration unchanged. Replace the `ui` service build/command with the React/Nginx image, pass `MCP_UPSTREAM`, and preserve `127.0.0.1:8501`. |
| `docs/context-compaction-demo.md` | MODIFY | 5 | Replace Streamlit-specific sidebar/navigation wording with the equivalent React session/settings/context controls. Keep prompts and expected Jev evidence unchanged. |
| `evals/golden.json` | KEEP | — | Agent evaluation inputs are unrelated to presentation. |
| `evals/results/.gitkeep` | KEEP | — | Preserve the generated evaluation-output directory. |
| `graphify-out/.graphify_ast.json` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/.graphify_chunk_01.json` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/.graphify_detect.json` | KEEP | — | Empty/incomplete Graphify artifact; document as untrusted but do not alter. |
| `graphify-out/.graphify_extract.json` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/.graphify_python` | KEEP | — | Empty/incomplete Graphify artifact; no migration edit. |
| `graphify-out/.graphify_root` | KEEP | — | Empty/incomplete Graphify artifact; no migration edit. |
| `graphify-out/.graphify_semantic.json` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/.graphify_semantic_new.json` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/.graphify_uncached.txt` | KEEP | — | Intermediate Graphify artifact; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/00afddc9875d12d649bfbcda099b66d29d044040a9a278811cb5541abe055f53.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/073a6871eb6a485ae72e314095bb7fdb3a4ea2ae873e4d2258ba370f0051227a.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/1d6938989579c522494295c366a8532ad89b54d87cd436d9a8f25ae555b94dd1.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/3f4e5e2b395adfc2767a8bb07aa21b72240aacd7d21eece5d111c22920bb323e.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/49463e31421f68df258670c92d15add0c3ff684f236ba1a3dc615a0770349bf7.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/4ad4f1f636a92a6ad5370c24024b91bc4c70e33070be4c19ce3c85f3ef506331.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/4b7711cf0c53d36c8648de4bc39a96d4af0a4b53a00656adfd62f38fddee3889.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/67d50e93945ae297bdd2a0c5e95d534bb53aad2f3290d942e11b50a6fce8fc6a.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/6fa6b722f908cd6b163d6f48551053adbb241e87d8581ae5f4e3badbabb2ac86.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/745483c4d27f7eccfa7ccd5334939f7e562ae6f2904753963ccaeb38edc607ae.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/77fe0aa852128f0b7d0273aea70a999aacde1f36e7b5ff6e49109f18e7546179.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/7d37b3cb96c00d0feada08ec9a44ea0163ac02257d43c3a2e324379e1067a0d0.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/863e9a3bca3bb0a41047b867d504081e6722bfecd9a4ef8d6f8e0d4c552e4571.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/9879322fd8375d2bd35487be4819edf824dd15f258d717658410fdaa1087b79c.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/99e1168ababd1131a47821624e6a91d5e2103bea4acd4fcac08a4f93a1f42764.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/c37fe69fd5128c5181eeefc05b4f4c252c9a8f71ea3147f7f426f28c530a53af.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/d5e9a8685e5510632a4c7a59251b6761a9191c0b925cf0f7bb13e462074534e1.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/e40edbb13ce4f1ab1fbedee0e794d6aea88860907acec225448be0cbc750c9ab.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/ef0b17b19cb2b7dd2cd569f2e50a6eb452aa6a23586ebc2e1e824464aaa0923b.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/f04ac07112122bbbebcead20a23ec9056a67c353a893f3ff065399330c225597.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/ast/v0.8.45/fe222634848fb661960b8c476d6e358288c5e6c226daa4a1ad76ffe93ced8774.json` | KEEP | — | Graphify AST cache; no migration edit. |
| `graphify-out/cache/semantic/5e11ea28f6104c59419efc1ed58a77b775975719753e682681f715128dcd96f6.json` | KEEP | — | Graphify semantic cache; no migration edit. |
| `graphify-out/cache/semantic/d634895ebd2db04510d1456a7218a304970bdf6a1623fc60714a1367cd510629.json` | KEEP | — | Graphify semantic cache; no migration edit. |
| `graphify-out/cache/stat-index.json` | KEEP | — | Graphify cache index; no migration edit. |
| `pyproject.toml` | MODIFY | 5 | Remove `streamlit` and the `finance-ui` console script only after cutover. Preserve Groq, MCP, Pydantic, TypeSafe SDK, evaluation script, build settings, and pytest config. |
| `src/finance_agent/__init__.py` | KEEP | — | Package identity remains unchanged. |
| `src/finance_agent/agent.py` | KEEP | — | Agent, Groq provider, system prompt, tools, errors, and six-step loop remain byte-for-byte unchanged. |
| `src/finance_agent/budget.py` | KEEP | — | Budget models, compiler prompt, validation, and deterministic rule semantics remain unchanged. |
| `src/finance_agent/context.py` | KEEP | — | Jev/summary selection, canonical-history handling, and context reporting remain unchanged. |
| `src/finance_agent/data/__init__.py` | KEEP | — | Package data marker remains unchanged. |
| `src/finance_agent/data/context_compaction_demo.csv` | KEEP | — | Generated context demo fixture remains unchanged. |
| `src/finance_agent/data/demo.csv` | KEEP | — | Bundled finance ledger remains unchanged. |
| `src/finance_agent/evaluation.py` | KEEP | — | Evaluation runner and report format remain unchanged. |
| `src/finance_agent/finance.py` | KEEP | — | CSV validation and deterministic finance calculations remain unchanged. |
| `src/finance_agent/jev.py` | KEEP | — | TypeSafe/Jev integration remains unchanged. |
| `src/finance_agent/models.py` | KEEP | — | Agent result, context report, trace, and session models remain unchanged. |
| `src/finance_agent/server.py` | KEEP | — | MCP tools, SessionStore, locking, transport, and server entrypoint remain byte-for-byte unchanged. |
| `src/finance_agent/ui.py` | DELETE | 5 | Delete only after React parity, Compose cutover, and rollback verification. No logic from this file moves into the backend. |
| `tests/test_agent.py` | KEEP | — | Preserve agent regression coverage unchanged. |
| `tests/test_budget.py` | KEEP | — | Preserve budget/compiler regression coverage unchanged. |
| `tests/test_context.py` | KEEP | — | Preserve context-management regression coverage unchanged. |
| `tests/test_evaluation.py` | KEEP | — | Preserve evaluation regression coverage unchanged. |
| `tests/test_finance.py` | KEEP | — | Preserve finance and CSV regression coverage unchanged. |
| `tests/test_jev.py` | KEEP | — | Preserve Jev regression coverage unchanged. |
| `tests/test_server.py` | KEEP | — | Preserve the MCP tool and lifecycle contract tests unchanged. |
| `tests/test_ui.py` | DELETE | 5 | Remove Streamlit-specific tests only after React unit/component/E2E parity coverage passes. |
| `tools/generate_context_compaction_csv.py` | KEEP | — | Preserve deterministic fixture generation. |
| `uv.lock` | MODIFY | 5 | Regenerate with `uv lock` after removing Streamlit; review that agent/MCP/provider versions do not change unexpectedly. |

## New files

| File | Status | Phase | Responsibility |
|---|---|---:|---|
| `.github/workflows/ci.yml` | NEW | 4 | Run frozen Python install/tests, frontend install/lint/typecheck/unit/build/E2E, and image builds. |
| `docs/migration/00-overview-and-inventory.md` | NEW | Planning | Verified current architecture, features, Streamlit/state/MCP inventory, services, tests, and deployment. |
| `docs/migration/01-target-architecture.md` | NEW | Planning | MCP-only target, feature parity matrix, state ownership, and tradeoffs. |
| `docs/migration/02-api-contract.md` | NEW | Planning | HTTP transport and original finance-tool TypeScript contract; durable-thread additions are documented separately. |
| `docs/migration/03-file-by-file-plan.md` | NEW | Planning | Every existing and planned file disposition. |
| `docs/migration/04-phases-and-testing.md` | NEW | Planning | Ordered strangler phases, checkpoints, acceptance criteria, and tests. |
| `docs/migration/05-risks-and-open-questions.md` | NEW | Planning | Risks, edge cases, locked assumptions, and unresolved scope. |
| `tests/e2e_mcp_server.py` | NEW | 2 | Test-only MCP process using `build_server(SessionStore(provider=fake))`; enables deterministic browser E2E without provider keys or production backend edits. |
| `web/.dockerignore` | NEW | 4 | Exclude `node_modules`, build output, reports, and local caches from UI image context. |
| `web/Dockerfile` | NEW | 4 | Multi-stage Node 24 build and Nginx runtime image. |
| `web/package.json` | NEW | 1 | Define runtime dependencies and scripts for dev, build, lint, typecheck, unit tests, and E2E. |
| `web/package-lock.json` | NEW | 1 | Pin the frontend dependency graph for reproducible npm and container builds. |
| `web/tsconfig.json` | NEW | 1 | Strict browser TypeScript configuration. |
| `web/eslint.config.js` | NEW | 1 | Minimal React/TypeScript lint configuration without formatting rules. |
| `web/vite.config.ts` | NEW | 1 | React/Tailwind plugins, test setup, and development `/mcp` proxy to `MCP_UPSTREAM` or local port 8000. |
| `web/playwright.config.ts` | NEW | 3 | Start deterministic MCP fixture and Vite, then run Chromium E2E. |
| `web/index.html` | NEW | 1 | Vite document shell and finance page metadata. |
| `web/nginx/templates/default.conf.template` | NEW | 4 | Serve SPA fallback and proxy `/mcp` to runtime `MCP_UPSTREAM` with buffering disabled and long timeouts. |
| `web/src/main.tsx` | NEW | 1 | Mount the React application and global styles. |
| `web/src/App.tsx` | NEW | 1-3 | Own page state, MCP lifecycle, view switching, session replacement, error banners, and child coordination. |
| `web/src/App.test.tsx` | NEW | 2-3 | Test navigation, conditional controls, session reset, and cross-component state behavior. |
| `web/src/styles.css` | NEW | 1-3 | Tailwind import plus the small human-like responsive visual system. |
| `web/src/types.ts` | NEW | 1 | Exact UI-facing MCP/domain TypeScript types from the Python contracts. |
| `web/src/components/SessionPanel.tsx` | NEW | 2 | Ledger, upload, context mode, date override, new-session action, status, and optional context panel placement. |
| `web/src/components/SettingsPanel.tsx` | NEW | 2 | Context toggle and complete budget-rule parse/preview/confirm/reset flow. |
| `web/src/components/ChatPanel.tsx` | NEW | 3 | Transcript, Markdown answers, prompt form, pending state, trace, and context details. |
| `web/src/components/ContextPanel.tsx` | NEW | 3 | Before/after context tabs, metrics, fallback, message cards, action badges, and fullscreen behavior. |
| `web/src/components/ContextPanel.test.tsx` | NEW | 3 | Verify safe text rendering, roles, tool calls, action badges, tabs, metrics, and fallback. |
| `web/src/lib/mcp.ts` | NEW | 1 | Own the official MCP client/transport, tool discovery, typed calls, narrowing, error text, reconnect, and clean shutdown. |
| `web/src/lib/mcp.test.ts` | NEW | 1 | Verify exact discovery, typed narrowing, missing content, `isError`, unknown-tool guidance, and no automatic retry. |
| `web/src/lib/preferences.ts` | NEW | 2 | Built-in rule text, versioned localStorage record, defensive loading, save/reset, fatal CSV decoding, and SHA-256 signatures. |
| `web/src/lib/preferences.test.ts` | NEW | 2 | Verify defaults, corrupt/old storage fallback, save/reset, UTF-8 rejection, and signature vectors. |
| `web/src/test/setup.ts` | NEW | 1 | Configure DOM matchers and deterministic test cleanup. |
| `web/tests/app.spec.ts` | NEW | 3 | End-to-end parity flow against the deterministic MCP test process. |

## Target tree

```text
.
├── .github/
│   └── workflows/
│       └── ci.yml
├── docs/
│   ├── context-compaction-demo.md
│   └── migration/
│       ├── 00-overview-and-inventory.md
│       ├── 01-target-architecture.md
│       ├── 02-api-contract.md
│       ├── 03-file-by-file-plan.md
│       ├── 04-phases-and-testing.md
│       └── 05-risks-and-open-questions.md
├── evals/
├── graphify-out/                    # retained, incomplete intermediate output
├── src/
│   └── finance_agent/
│       ├── agent.py                 # unchanged
│       ├── budget.py                # unchanged
│       ├── context.py               # unchanged
│       ├── evaluation.py            # unchanged
│       ├── finance.py               # unchanged
│       ├── jev.py                   # unchanged
│       ├── models.py                # unchanged
│       ├── server.py                # unchanged
│       └── data/                    # unchanged
├── tests/
│   ├── e2e_mcp_server.py
│   └── test_*.py                    # existing backend tests; Streamlit test removed in phase 5
├── tools/
├── web/
│   ├── nginx/templates/default.conf.template
│   ├── src/
│   │   ├── components/
│   │   ├── lib/
│   │   ├── test/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── styles.css
│   │   └── types.ts
│   ├── tests/app.spec.ts
│   ├── Dockerfile
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── eslint.config.js
│   ├── vite.config.ts
│   └── playwright.config.ts
├── Dockerfile                       # MCP image
├── docker-compose.yml
├── pyproject.toml
└── uv.lock
```

## Files explicitly protected from migration edits

Implementation must check `git diff --` for the following files at the end of every phase and require an empty result:

```text
src/finance_agent/agent.py
src/finance_agent/budget.py
src/finance_agent/context.py
src/finance_agent/evaluation.py
src/finance_agent/finance.py
src/finance_agent/jev.py
src/finance_agent/models.py
src/finance_agent/server.py
src/finance_agent/data/
```

The final cleanup may modify packaging around those files, but never their implementation.
