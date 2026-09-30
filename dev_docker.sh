#!/usr/bin/env bash

set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ui_url="http://127.0.0.1:8501"
docker_desktop_bin="/Applications/Docker.app/Contents/Resources/bin"
probe_dir="$(mktemp -d)"
compose=(docker compose)

cleanup() {
  rm -rf "$probe_dir"
}

fail() {
  echo "$*" >&2
  "${compose[@]}" logs --tail=50 mcp ui >&2 || true
  exit 1
}

trap cleanup EXIT

if [[ -d "$docker_desktop_bin" && ":$PATH:" != *":$docker_desktop_bin:"* ]]; then
  export PATH="$docker_desktop_bin:$PATH"
fi

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 is required." >&2; exit 1; }

cd "$repo_dir"
if [[ -f .env ]]; then
  compose+=(--env-file .env)
fi

"${compose[@]}" up --build -d

probe_mcp() {
  local session_id
  curl --fail --silent --max-time 5 \
    -D "$probe_dir/headers" \
    -o "$probe_dir/initialize.json" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"dev-docker","version":"1.0"}}}' \
    "$ui_url/mcp" >/dev/null || return 1
  grep -q '"result"' "$probe_dir/initialize.json" || return 1
  session_id="$(awk 'BEGIN { IGNORECASE = 1 } /^mcp-session-id:/ { print $2 }' "$probe_dir/headers" | tr -d '\r')"
  [[ -n "$session_id" ]] || return 1
  curl --fail --silent --max-time 5 \
    -o "$probe_dir/tools.json" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H "Mcp-Session-Id: $session_id" \
    --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
    "$ui_url/mcp" >/dev/null
  grep -q '"create_finance_session"' "$probe_dir/tools.json"
}

for ((attempt = 0; attempt < 120; attempt += 1)); do
  if curl --fail --silent --max-time 2 "$ui_url" >/dev/null && probe_mcp; then
    if command -v open >/dev/null 2>&1; then
      open "$ui_url"
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$ui_url" >/dev/null 2>&1
    else
      echo "Open $ui_url in your browser."
    fi
    echo "UI ready at $ui_url; MCP tools are reachable through /mcp."
    exit 0
  fi
  sleep 1
done

fail "UI or proxied MCP did not become ready within 120 seconds."
