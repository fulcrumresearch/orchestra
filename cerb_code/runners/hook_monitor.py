#!/usr/bin/env python3
# Read hook JSON from stdin and POST to /hook/<session_id>
# Session ID is passed as the first argument

import json
import os
import sys
from urllib.parse import quote

import requests


def main() -> int:
    if os.getenv("CLAUDE_MONITOR_SKIP_FORWARD") == "1":
        return 0

    if len(sys.argv) < 2:
        print("Usage: hook_monitor.py <session_id> [event_name]", file=sys.stderr)
        return 1

    session_id = sys.argv[1]
    event_name = sys.argv[2] if len(sys.argv) > 2 else "tool_use"

    base = os.getenv("CLAUDE_MONITOR_BASE", "http://127.0.0.1:8081")

    # Read hook JSON from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception as e:
        print(f"[hook_monitor] invalid stdin JSON: {e}", file=sys.stderr)
        return 1

    # URL-encode for safety
    session_id_enc = quote(session_id, safe="")

    url = f"{base.rstrip('/')}/hook/{session_id_enc}"

    envelope = {
        "event": event_name,
        "receivedAt": payload.get("timestamp") or payload.get("time"),
        "payload": payload,
    }

    # Fire-and-forget POST (don't block Claude if monitor is unreachable)
    try:
        requests.post(url, json=envelope, timeout=2)
    except Exception as e:
        print(f"[hook_monitor] POST failed to {url}: {e}", file=sys.stderr)
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
