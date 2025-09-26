#!/usr/bin/env bash
# Forward a Claude Code hook payload (read from stdin) to your monitor.
# Requires: curl, jq (hooks quickstart suggests jq).  chmod +x this file.
# You can set URL/token in the environment or edit the defaults.
#
# Env:
#   CLAUDE_MONITOR_URL       default http://127.0.0.1:8080/hook
#   CLAUDE_MONITOR_TOKEN     optional bearer-style shared secret
#   CLAUDE_MONITOR_HMAC_SECRET optional HMAC secret (if set, we send X-Hub-Signature-256)
#   HOSTNAME                 auto-injected by most shells/OSes
#
# Usage (from settings.json):
#   "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh PreToolUse"

set -euo pipefail

EVENT="${1:-UnknownEvent}"
URL="${CLAUDE_MONITOR_URL:-http://127.0.0.1:8080/hook}"

# Read entire stdin (hook JSON)
body="$(cat)"

# Construct an envelope for the monitor
payload="$(
  jq -c --arg event "$EVENT" \
        --arg host "${HOSTNAME:-}" \
        --arg ts "$(date -Is)" \
        '{event:$event, source:{host:$host}, receivedAt:$ts, payload:.}' \
        <<<"$body"
)"

headers=(-H "Content-Type: application/json" -H "X-CLAUDE-HOOK: v1")
if [ -n "$TOKEN" ]; then
  headers+=(-H "X-CLAUDE-HOOK-TOKEN: $TOKEN")
fi
# Fire-and-forget; do not block Claude Code if monitor is down
curl -sS -X POST "$URL" "${headers[@]}" --data-raw "$payload" >/dev/null || true
