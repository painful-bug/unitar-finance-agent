# Durable chat threads

## Current architecture

The React client remains a direct MCP client. The Python product adds a small `ChatStore` beside `SessionStore`; there is still no REST layer, database, authentication system, or agent framework.

Each saved chat is one versioned JSON file under `FINANCE_CHAT_STORE_PATH` or `~/.finance-agent/chats/`. The directory is mode `0700`, records are mode `0600`, and writes replace a same-directory temporary file atomically. Docker Compose mounts the `finance_chat_data` volume at `/data/chats`.

A record contains the ledger source, optional uploaded CSV text and filename, as-of date, confirmed budget rules, context settings, canonical agent messages, and visible turns. Public MCP results omit the CSV text and canonical record internals. Local files are unencrypted and may contain financial data.

## MCP surface

The current server exposes eight structured tools:

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

Titles are generated deterministically from the normalized first question and capped at 48 characters. Manual titles are trimmed and limited to 100 characters. Ledger, date, and rule snapshots are immutable after the first message; context mode and compaction threshold remain mutable.

## Browser behavior

Saved chats use `/chat/<thread-id>` routes backed by the browser History API and the existing Nginx SPA fallback. Reloading that route calls `get_chat_thread`, restores the transcript, and rehydrates the canonical agent session. Chat data is never duplicated into `localStorage`; only theme, new-chat compaction defaults, and rule-editor preferences remain browser-local.

The UI disables thread switching and destructive actions while an uncancellable question is in flight. It never automatically retries a failed MCP mutation.
