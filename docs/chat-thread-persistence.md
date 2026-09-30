# Durable chat threads

## Current architecture

The React client remains a direct MCP client. The Python product adds a small `ChatStore` beside `SessionStore`; there is still no REST layer, database, authentication system, or agent framework.

Each saved chat is one versioned JSON file under `FINANCE_CHAT_STORE_PATH` or `~/.finance-agent/chats/`. The directory is mode `0700`, records are mode `0600`, and writes replace a same-directory temporary file atomically. Docker Compose mounts the `finance_chat_data` volume at `/data/chats`.

A record contains the ledger source, optional uploaded CSV text and filename, as-of date, confirmed budget rules, context settings, canonical agent messages, and visible turns. Public MCP results omit the CSV text and canonical record internals. Local files are unencrypted and may contain financial data.

## MCP surface

The current server exposes ten structured tools:

- `get_app_settings`
- `update_app_settings`
- `parse_budget_rules`
- `create_finance_session`
- `ask_finance_agent`
- `close_finance_session`
- `list_chat_threads`
- `get_chat_thread`
- `update_chat_thread`
- `delete_chat_thread`

`create_finance_session` creates an unsaved in-memory draft. The first `ask_finance_agent` call writes a pending turn before invoking the provider, then atomically finalizes the result and canonical messages. A pending turn found after process restart is exposed as interrupted rather than silently dropped.

`close_finance_session` evicts only the in-memory copy. `get_chat_thread` rehydrates a finance session from JSON, and `delete_chat_thread` is the only operation that permanently removes the record.

## Public records

- `ChatThreadSummary` contains thread ID, title, timestamps, turn count, ledger source, and optional upload filename.
- `ChatTurn` contains its ID, timestamp, question, state, and optional `AgentResult`.
- `ChatThreadDetail` adds safe session metadata, rules, context settings, and turns.
- `ChatThreadList` returns newest-first summaries plus the number of invalid files skipped.

Titles are generated deterministically from the normalized first question and capped at 48 characters. Manual titles are trimmed and limited to 100 characters. Ledger replacement is available between answers. The replacement is validated and atomically saved before the live session changes. Earlier turns and their traces remain intact, a `ledger_changes` entry records the boundary, and canonical `messages` are cleared. The public detail includes change markers but never CSV content. New turns contain `ledger` and `settings` snapshots; legacy turns are backfilled before their old metadata could be overwritten.

## Browser behavior

Saved chats use `/chat/<thread-id>` routes backed by the browser History API and the existing Nginx SPA fallback. Reloading that route calls `get_chat_thread`, restores the transcript, and rehydrates the canonical agent session. Chat data is never duplicated into `localStorage`; only theme remains authoritative in browser-local storage. `/settings` is a full-page route using the same shell and sidebar, and preserves the composer draft and active stream while navigating back to chat.

The UI disables thread switching and destructive actions while an uncancellable question is in flight. It never automatically retries a failed MCP mutation.

## Shared settings

`settings/app.json` under the chat-store directory stores a versioned `AppSettings` record. It is excluded from the thread listing, uses atomic replacement, and has directory mode `0700` / file mode `0600`. Missing settings use built-in budget rules, context mode `auto`, 15 compaction turns, and 15 agent steps. Invalid persisted settings raise an error rather than silently overwriting confirmed rules.

`get_app_settings` returns the confirmed rules and source text, editable rule draft, context strategy, compaction threshold, and maximum agent steps. `update_app_settings` accepts partial updates. Compaction turns must be strict integers from 5 to 100; agent steps must be strict integers from 1 to 100. Rules are validated with the existing schema and have unique IDs. `reset_rules: true` restores built-in rules and draft text without changing other settings.

The parser uses category names from bundled and saved ledgers plus an optional staged CSV. Editing or saving `rules_draft` never activates it; confirmation sends `rules_text` and `budget_rules` together. Switching ledgers does not invalidate confirmed rules. Missing ledger categories evaluate as insufficient evidence.

Each answer captures shared settings once when it starts. Settings updates persist immediately without mutating sessions that are running. Thread details expose current shared configuration, while each turn retains its historical snapshot. Legacy configuration arguments on create, ask, and thread update now change shared settings; omitted arguments inherit them. Browser-local defaults are not imported. Local settings writes are serialized within one backend process; the product does not support multiple server processes writing the same store.

`update_chat_thread` accepts `csv_text` / `upload_name` for replacement, or `use_bundled_data: true` for reset. These options are mutually exclusive. CSV changes are rejected during a running answer. Replacing a ledger uses its latest transaction date (or the bundled anchor) and clears only future model context. The previous CSV is not archived; historical answers, traces, dates, and ledger labels remain available.
