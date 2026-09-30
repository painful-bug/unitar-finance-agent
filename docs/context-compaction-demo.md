# Jev context-compaction demo

## One-time setup

1. Generate the deterministic fixture (it is already generated in this checkout):

   ```bash
   uv run python tools/generate_context_compaction_csv.py
   ```

2. Add live provider credentials to `.env`:

   ```dotenv
   GROQ_API_KEY=...
   TYPESAFE_API_KEY=...
   ```

3. Start both products with Compose:

   ```bash
   docker compose --env-file .env up --build
   ```

4. Open `http://127.0.0.1:8501`, select **New chat**, then open **Settings**.
   Select **Upload CSV**, upload `src/finance_agent/data/context_compaction_demo.csv`,
   choose the **Auto** context strategy, and set **Compact after turns** to `5`.
   Close Settings; the first prompt creates the saved chat.

## Prompts to paste, in order

Send each as a separate message and wait for its answer.

1. `Use lookup_transactions for 2026-05 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
2. `Use lookup_transactions for 2026-06 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
3. `Use lookup_transactions for 2026-07 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
4. `Use lookup_transactions for 2026-08 with no category or kind filter. This is now the active question; the earlier month lookups are completed audit evidence.`
5. `The only active goal is the August 2026 savings rate. Treat every earlier monthly lookup as obsolete for this answer. Use the savings-rate tool and give the exact result.`

## What to show judges

The 5,000-row CSV is intentionally valid under the upload limits. The first four prompts build complete tool-call history without compacting. Prompt five reaches the configured five-user-turn threshold and starts the existing Jev-first compaction flow while preserving normal agent behavior.

Select **Context** in the chat header and show both tabs after prompt 5:

- **Before**: the original history remains intact, including the old tool outputs.
- **Model input**: the Jev-selected context. Old tool-call/result pairs carry a **keep**, **trim**, or **drop** badge; dropped pairs are absent and trimmed tool results show an omission marker.

Capture the `jev` strategy label, before/after token counts, and keep/trim/drop tool modules. Open a module's collapsed **Technical details** only when raw arguments or results are needed. This is the audit receipt: Jev supplied relevance scores and deterministic code mapped them to keep/trim/drop. It did not mutate the chat's canonical history.

If the inspector shows `summary`, the app used the configured Groq fallback because Jev removed less than 5% or was unavailable. Confirm `TYPESAFE_API_KEY`, start a new chat, and repeat the five prompts when a specifically Jev-backed demonstration is required. Do not present a summary fallback as a Jev compaction result.
