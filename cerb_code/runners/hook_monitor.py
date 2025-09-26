#!/usr/bin/env python3
# Read hook JSON from stdin and POST to /hook/<session_id>, where
# session_id = current git branch of the repo Claude is in.

import json
import os
import sys
import subprocess
from pathlib import Path
from urllib.parse import quote

import requests


def _run_git(args, cwd: Path) -> str | None:
    try:
        out = subprocess.check_output(["git", *args], cwd=str(cwd), stderr=subprocess.DEVNULL)
        return out.decode("utf-8", "replace").strip() or None
    except Exception:
        return None


def _detect_branch(payload: dict) -> str:
    """
    Resolve the session_id as the current git branch.

    Priority:
      1) payload["git_branch"] or payload["branch"] (if provided by the hook)
      2) env CLAUDE_BRANCH (manual override)
      3) `git rev-parse --abbrev-ref HEAD` in project_path/cwd
         - if detached HEAD, fall back to `git rev-parse --short HEAD`
      4) "unknown"
    """

    repo_dir = payload["cwd"]
    repo_path = Path(repo_dir)

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    # add error matching
    return branch


def main() -> int:
    base = os.getenv("CLAUDE_MONITOR_BASE", "http://127.0.0.1:8081")  # no /hook here
    event_name = sys.argv[1] if len(sys.argv) > 1 else "UnknownEvent"

    # Read hook JSON from stdin
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except Exception as e:
        print(f"[forward.py] invalid stdin JSON: {e}", file=sys.stderr)
        return 1

    # Determine session_id = branch name
    session_id = _detect_branch(payload)
    # URL-encode for safety (e.g., slashes in branch names like feature/foo)
    session_id_enc = quote(session_id, safe="")

    url = f"{base.rstrip('/')}/hook/{session_id_enc}"

    envelope = {
        "event": event_name,
        "receivedAt": payload.get("timestamp") or payload.get("time"),
        "payload": payload,
    }

    # Fire-and-forget POST (don’t block Claude if monitor is unreachable)
    try:
        requests.post(url, json=envelope, timeout=2)
    except Exception as e:
        print(f"[forward.py] POST failed to {url}: {e}", file=sys.stderr)
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
