#!/usr/bin/env bash

set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_port="${MCP_PORT:-8000}"
frontend_port="${WEB_PORT:-5173}"
frontend_url="http://127.0.0.1:${frontend_port}"
backend_url="http://127.0.0.1:${backend_port}/mcp"
backend_pid=""
frontend_pid=""

cleanup() {
  trap - EXIT INT TERM
  [[ -n "$frontend_pid" ]] && kill "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && kill "$backend_pid" 2>/dev/null || true
  [[ -n "$frontend_pid" ]] && wait "$frontend_pid" 2>/dev/null || true
  [[ -n "$backend_pid" ]] && wait "$backend_pid" 2>/dev/null || true
}

open_browser() {
  if command -v open >/dev/null 2>&1; then
    open "$frontend_url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$frontend_url" >/dev/null 2>&1
  else
    echo "Open $frontend_url in your browser."
  fi
}

trap cleanup EXIT
trap 'exit 130' INT TERM

command -v uv >/dev/null 2>&1 || { echo "uv is required." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }
[[ -x "$repo_dir/web/node_modules/.bin/vite" ]] || { echo "Run 'cd web && npm ci' first." >&2; exit 1; }

echo "Starting finance MCP service on $backend_url"
(
  cd "$repo_dir"
  if [[ -f .env ]]; then
    exec env MCP_HOST=127.0.0.1 MCP_PORT="$backend_port" uv run --env-file .env finance-mcp
  else
    exec env MCP_HOST=127.0.0.1 MCP_PORT="$backend_port" uv run finance-mcp
  fi
) &
backend_pid=$!

echo "Starting React UI on $frontend_url"
(
  cd "$repo_dir/web"
  exec env MCP_UPSTREAM="$backend_url" npm run dev -- --host 127.0.0.1 --port "$frontend_port" --strictPort
) &
frontend_pid=$!

ready=false
for ((attempt = 0; attempt < 120; attempt += 1)); do
  kill -0 "$backend_pid" 2>/dev/null || { wait "$backend_pid"; exit $?; }
  kill -0 "$frontend_pid" 2>/dev/null || { wait "$frontend_pid"; exit $?; }
  if curl --fail --silent --max-time 1 "$frontend_url" >/dev/null; then
    ready=true
    break
  fi
  sleep 0.25
done

if [[ "$ready" != true ]]; then
  echo "The development UI did not become ready at $frontend_url." >&2
  exit 1
fi

echo "Opening $frontend_url"
open_browser
echo "Press Ctrl+C to stop both servers."

while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 1
done

status=0
if ! kill -0 "$backend_pid" 2>/dev/null; then
  wait "$backend_pid" || status=$?
else
  wait "$frontend_pid" || status=$?
fi
exit "$status"
