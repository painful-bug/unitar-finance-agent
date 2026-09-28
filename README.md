# Personal Finance Agent Beta

A framework-free personal finance assistant that answers from a validated ledger through a hand-written tool loop. Groq supplies the chat model, Jev selects old tool context, Groq summarization is the fallback, the agent is exposed over MCP, and Streamlit is only an MCP client.

## What is included

- Three Pydantic-validated finance tools: transaction lookup, budget checking, and savings-rate calculation.
- A six-step manual reason → act → observe loop with recoverable malformed tool calls.
- Canonical in-memory session history with runtime-selectable `auto`, `jev`, and `summary` context modes.
- MCP tools for creating, asking, and closing finance sessions.
- Bundled deterministic RM data plus per-session CSV uploads.
- Ten golden evaluation cases with literal checks and a separate structured LLM judge.

No agent framework, database, authentication, persistent uploads, or general financial advice is included.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are required.

```bash
cp .env.example .env
# Add GROQ_API_KEY and TYPESAFE_API_KEY to .env
uv sync --extra dev
```

Start the MCP server and UI in separate terminals:

```bash
uv run --env-file .env finance-mcp
uv run --env-file .env finance-ui
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). The MCP endpoint is `http://127.0.0.1:8000/mcp`.

Alternatively:

```bash
docker compose --env-file .env up --build
```

## CSV format

Uploads are UTF-8 CSV files up to 1 MB and 5,000 rows:

```csv
date,kind,category,amount,merchant
2026-07-01,income,salary,5000.00,Employer
2026-07-03,expense,groceries,120.40,Market
```

`kind` must be `income` or `expense`; amounts must be positive. Uploaded bytes and sessions remain in memory and disappear when the MCP process stops.

## Context modes

- `jev`: preserve human/assistant text, then keep, excerpt, or drop old complete tool-call/result pairs using two typed Jev decisions.
- `summary`: replace only an eligible old prefix with a clearly labeled Groq-generated summary while preserving the six newest messages exactly.
- `auto`: try Jev first and use summary when Jev fails or removes less than 5%.

The canonical history is never overwritten, so a running session can switch modes. If both strategies fail, the request returns an error rather than sending uncontrolled context.

## Tests and evaluation

```bash
uv run pytest
uv run --env-file .env finance-eval --version v1
uv run --env-file .env finance-eval --version final --context-mode auto
```

Evaluation reports are written to `evals/results/v1.json` and `evals/results/final.json`. The runner refuses to create reports without a Groq key; pass rates must come from real runs, not placeholders.

The application is a local single-user beta and is not financial advice.
