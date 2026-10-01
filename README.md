# Personal Finance Agent Beta

A framework-free personal finance assistant that answers from a validated ledger through a hand-written tool loop. Groq supplies the chat model, Jev selects old tool context, Groq summarization is the fallback, the agent is exposed over MCP, and a React UI connects through a same-origin proxy.

## What is included

- Three Pydantic-validated finance tools: transaction lookup, deterministic budget checking, and savings-rate calculation.
- Session-scoped natural-language budget rules compiled into a safe expression schema.
- A six-step manual reason → act → observe loop with recoverable malformed tool calls.
- Canonical session history with runtime-selectable `auto`, `jev`, and `summary` context modes.
- Eight typed MCP tools covering finance sessions, budget-rule parsing, and persistent chat-thread lifecycle.
- Bundled deterministic RM data plus per-chat CSV uploads stored with the local thread.
- Twelve golden evaluation cases using the instructor notebook method, comparing two finance prompts with keyword checks and an LLM judge.

No agent framework, database, authentication, cloud sync, or general financial advice is included.

## Setup

Python 3.12, [uv](https://docs.astral.sh/uv/), and Node.js 24 are required for local development.

```bash
cp .env.example .env
# Add GROQ_API_KEY and TYPESAFE_API_KEY to .env
uv sync --extra dev
```

Start the MCP server:

```bash
uv run --env-file .env finance-mcp
```

Then start the React development server in another terminal:

```bash
cd web
npm ci
MCP_UPSTREAM=http://127.0.0.1:8000/mcp npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The MCP endpoint is `http://127.0.0.1:8000/mcp`.

Or start both development servers and open the UI in your default browser:

```bash
./dev.sh
```

Press `Ctrl+C` to stop both processes. Set `MCP_PORT` or `WEB_PORT` before running the script when the default ports are occupied.

For the production-shaped two-container setup:

```bash
docker compose --env-file .env up --build
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Nginx serves the React app and proxies same-origin `/mcp` traffic to the independently runnable MCP container. Only the UI port and MCP port are bound to loopback.

The images can also be built separately:

```bash
docker build -t finance-mcp .
docker build -t finance-agent-ui ./web
```

Set `MCP_UPSTREAM` when running the UI image outside Compose. It must be an MCP URL reachable from that container; provider API keys belong only on the MCP process and are never included in the browser bundle.

## CSV format

Uploads are UTF-8 CSV files up to 10 MB and 50,000 rows:

```csv
date,kind,category,amount,merchant
2026-07-01,income,salary,5000.00,Employer
2026-07-03,expense,groceries,120.40,Market
```

`kind` must be `income` or `expense`; amounts must be positive. Choose or drop a CSV directly in the chat pane. Every **New chat** starts with the bundled demo unless you upload another CSV. Uploaded dates use the latest transaction date; bundled data uses `2026-08-15`.

After the first message, the uploaded CSV is retained in that chat's owner-readable JSON record. **Replace CSV** and **Use bundled data** remain available between answers. A successful replacement keeps the visible transcript and traces, adds a ledger-change marker, and starts fresh model context. Invalid files leave the previous ledger intact.

## Saved chats

The sidebar lists saved chats newest first. A blank **New chat** is not written until its first message. At that point the server snapshots the ledger, as-of date, confirmed rules, canonical agent context, visible turns, tool traces, and context reports. The first prompt becomes the title; use the thread menu to rename or permanently delete it.

Direct local runs store one validated JSON file per chat under `~/.finance-agent/chats/`. Set `FINANCE_CHAT_STORE_PATH` to use another directory. The directory is mode `0700`, files are mode `0600`, and writes use atomic replacement. These files are unencrypted and can contain uploaded financial data. Docker Compose stores them in the `finance_chat_data` named volume at `/data/chats`.

Saved routes use `/chat/<thread-id>`, so refreshing or reopening a URL restores the transcript and rehydrates its finance session. The ledger belongs to its chat. Budget rules, context strategy, compaction threshold, and agent step limit are shared by every chat and stored in `settings/app.json` inside the chat-store directory. Each answer records the settings and ledger metadata it used. Existing chat records remain readable; old per-chat settings do not override the shared configuration for new answers.

## Context modes

- `jev`: preserve human/assistant text, then keep, excerpt, or drop old complete tool-call/result pairs using two typed Jev decisions; use summary if Jev cannot reduce the context by at least 5%.
- `summary`: replace only an eligible old prefix with a clearly labeled Groq-generated summary while preserving the six newest messages exactly.
- `auto`: try Jev first and use summary when Jev fails or removes less than 5%.

The canonical history is never overwritten, so a running session can switch modes. If both strategies fail, the request returns an error rather than sending uncontrolled context.

The React product triggers compaction after 15 user turns (configurable from 5 to 100 in **Settings**) or an estimated 8,000 tokens, whichever comes first. Settings are saved on the backend and apply to existing and new chats. Compaction prepares a copy of the history once per answer; subsequent tool steps reuse that copy with their new calls and results. The saved history remains intact.

## Natural-language budget rules

Open the full-page **Settings** view from any chat, edit the built-in rules or add rules on new lines, and select **Parse rules**. Groq converts the text into a validated expression preview; **Confirm these rules** activates it for every chat. Draft editing or failed parsing keeps the previous confirmed rules active. The saved expression is evaluated with exact `Decimal` arithmetic over the ledger. Unsupported rules remain visible and return `insufficient_evidence` instead of a guessed result.

Rules and drafts persist on the backend. Previous browser-local agent preferences are ignored; a backend without shared settings starts with the built-in defaults. Category names are resolved against bundled, saved, and staged ledgers; a rule referring to a category absent from the active ledger returns `insufficient_evidence`.

**Settings** uses the full content pane with the conversation sidebar, budget editor, context controls, and execution controls. Strategy selections save immediately; valid numeric values save on blur. Settings remain editable during an answer, and the next answer uses the saved configuration. Theme remains browser-local.

For example, `Save at least 20% of monthly income` is stored as a comparison between savings and income multiplied by `0.20`. The actual income and target are resolved separately for every requested month.

## Context inspector and tool activity

Select **Context** in the chat header to open the inspector. Switch between canonical pre-compaction context and exact model input; compacted responses automatically select the model-input pane. The fullscreen button expands the panel, and tool calls retain their keep, trim, or drop decision.

Assistant Markdown supports headings, lists, tables, links, blockquotes, and fenced code while raw HTML remains disabled. Finance tool traces render as readable transaction, savings, and budget modules; original arguments and results remain available under collapsed **Technical details** disclosures.

The top-right theme control follows the operating-system theme on first use, then saves the explicit light or dark choice in the browser. Theme changes apply immediately without required motion.

## Tests and evaluation

```bash
uv run --extra dev --extra eval pytest
uv run --extra eval --env-file .env python tools/run_evaluation.py
```

Each evaluation compares the real finance agent under two system prompts, once per prompt, using twelve questions with keyword OR LLM-judge checks. All three finance tools are available in each fresh session. It prints questions, tool calls and results, answers, verdicts, and reasoning, then saves `report.md` and `results.json` in a new timestamped directory under `evals/results/`. The concise report shows pass rates, a measured winner or tie, and each case’s verdict. Both prompts use the bundled CSV and the same budget rules; no reference answers are sent to the agent. Only `GROQ_API_KEY` is required; evaluation is independent of app Settings and Jev. See [the evaluation operating guide](docs/evaluation-guide.md) and [the verified evaluation report](docs/evaluation-report.md).

CI runs the Python suite and package build, frontend lint/typecheck/unit/build checks, Playwright against a deterministic MCP fixture, and both container builds. It does not publish images or require provider credentials.

The application is a local single-user beta and is not financial advice.
