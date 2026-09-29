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

3. Start the MCP server and UI in separate terminals:

   ```bash
   uv run --env-file .env finance-mcp
   uv run --env-file .env finance-ui
   ```

4. Open `http://127.0.0.1:8501`. In the sidebar select **Upload CSV**, upload
   `src/finance_agent/data/context_compaction_demo.csv`, select **jev**, and
   click **Start new session**.

5. Open **Settings** and enable **Show context live**. Return to **Chat**.

## Prompts to paste, in order

Send each as a separate message and wait for its answer.

1. `Use lookup_transactions for 2026-05 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
2. `Use lookup_transactions for 2026-06 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
3. `Use lookup_transactions for 2026-07 with no category or kind filter. Report the exact count and total, then list the returned transactions.`
4. `Use lookup_transactions for 2026-08 with no category or kind filter. This is now the active question; the earlier month lookups are completed audit evidence.`
5. `The only active goal is the August 2026 savings rate. Treat every earlier monthly lookup as obsolete for this answer. Use the savings-rate tool and give the exact result.`

## What to show judges

The 5,000-row CSV is intentionally valid under the upload limits. A broad lookup returns its first 50 matching rows, about 1,920 estimated tokens. The four broad lookups therefore cross the 8,000-token compaction trigger while preserving normal agent behavior.

In the **Context window**, show both tabs after prompt 5:

- **Before · canonical**: the original history remains intact, including the old tool outputs.
- **After · model input**: the Jev-selected context. Old tool-call/result pairs carry a **keep**, **trim**, or **drop** badge; dropped pairs are absent and trimmed tool results show an omission marker.

Also open the response's **Context management** expander. Capture the `strategy: "jev"`, before/after token counts, and `decisions` with both Noul probabilities. This is the audit receipt: Jev supplied relevance scores and the deterministic code mapped them to keep/trim/drop. It did not mutate the session's canonical history.

If the response says `strategy: "summary"`, the app fell back because Jev removed less than 5% (or was unavailable). Restart the session, confirm the **jev** strategy and `TYPESAFE_API_KEY`, then repeat the five prompts. Do not present a summary fallback as a Jev compaction result.
