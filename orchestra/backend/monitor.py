#!/usr/bin/env python3
"""
Orchestra monitoring server - receives hook events and routes them to monitoring agents.

Supports two monitor types:
- SessionMonitor: Orchestra-integrated, uses MCP to communicate with sessions
- IndependentMonitor: Standalone, writes feedback to .orchestra-monitor.txt

Required environment:
  ANTHROPIC_API_KEY=...  # Required by Claude SDK

Run:
  orchestra-monitor-server [--mode session|independent] [port]

  --mode session: Load Session objects and use SessionMonitor (default)
  --mode independent: Use simple IndependentMonitor

  Default port: 8081 for both modes
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from orchestra.lib.monitor import BaseMonitor, SessionMonitor, IndependentMonitor
from orchestra.lib.sessions import Session, load_sessions

# Prevent the monitor agent itself from triggering hooks (would create infinite loop)
os.environ["CLAUDE_MONITOR_SKIP_FORWARD"] = "1"

app = FastAPI(title="Orchestra Monitor Server", version="1.0")

logger = logging.getLogger("monitor_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

# session_id -> Monitor
_monitors: Dict[str, BaseMonitor] = {}

# Server mode: "session" or "independent"
_mode: str = "session"


def get_session(session_id: str, source_path: str) -> Session:
    """Load and return a session by ID from the specified project"""
    sessions = load_sessions(flat=True, project_dir=Path(source_path))

    for sess in sessions:
        if sess.session_id == session_id:
            return sess

    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found in {source_path}")


async def get_or_create_monitor(session_id: str, source_path: str) -> BaseMonitor:
    """Get or create a monitor based on server mode"""
    monitor = _monitors.get(session_id)

    if monitor is None:
        if _mode == "session":
            # Session mode: load Session object and create SessionMonitor
            session = get_session(session_id, source_path)
            monitor = SessionMonitor(session=session)
        else:
            # Independent mode: create IndependentMonitor directly
            monitor = IndependentMonitor(session_id=session_id, source_path=source_path)

        await monitor.start()
        _monitors[session_id] = monitor
        logger.info("started %s monitor for session_id=%s in %s", _mode, session_id, source_path)

    return monitor


@app.on_event("shutdown")
async def _shutdown() -> None:
    for sid, m in list(_monitors.items()):
        await m.stop()
        _monitors.pop(sid, None)


@app.post("/hook/{session_id}")
async def hook(request: Request, session_id: str) -> Dict[str, str]:
    """Receive hook events and route to appropriate monitor"""
    body = await request.body()
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    source_path = data.get("source_path")

    if not source_path:
        raise HTTPException(status_code=400, detail="source_path is required")

    # Create clean event with received timestamp
    evt = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    event_type = evt.get("event", "UnknownEvent")
    logger.info(f"Received event {event_type} for session {session_id} in {source_path}")

    monitor = await get_or_create_monitor(session_id, source_path)

    try:
        await monitor.enqueue(evt)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="queue full")

    return {"status": "ok", "session_id": session_id, "mode": _mode}


def main():
    """Entry point for the monitoring server"""
    global _mode

    # Parse arguments
    args = sys.argv[1:]
    port = None

    # Check for --mode flag
    if "--mode" in args:
        mode_idx = args.index("--mode")
        if mode_idx + 1 < len(args):
            _mode = args[mode_idx + 1]
            if _mode not in ["session", "independent"]:
                print(f"Error: Invalid mode '{_mode}'. Must be 'session' or 'independent'")
                sys.exit(1)
            # Remove --mode and its value
            args = args[:mode_idx] + args[mode_idx + 2:]

    # Parse port (remaining arg)
    if args:
        try:
            port = int(args[0])
        except ValueError:
            print(f"Error: Invalid port '{args[0]}'")
            sys.exit(1)

    # Set default port
    if port is None:
        port = 8081

    print(f"Starting Orchestra Monitor Server in {_mode} mode on port {port}")
    print(f"Hook endpoint: http://0.0.0.0:{port}/hook/{{session_id}}")
    if _mode == "session":
        print(f"Using SessionMonitor (MCP-based communication)")
    else:
        print(f"Using IndependentMonitor (file-based feedback to .orchestra-monitor.txt)")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
