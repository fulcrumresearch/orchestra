#!/usr/bin/env python3
"""
Orchestra monitoring server - receives hook events and routes them to monitoring agents.

- FastAPI app exposes POST /hook/{session_id} endpoint
- Each session gets its own Claude SDK monitoring agent
- Events are batched and sent to the monitoring agent
- Monitor agent updates monitor.md in real-time

Configuration is in orchestra/lib/monitor.py (ALLOWED_TOOLS, PERMISSION_MODE, etc.)

Required environment:
  ANTHROPIC_API_KEY=...  # Required by Claude SDK

Run:
  orchestra-monitor-server [port]  # defaults to port 8081
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from orchestra.lib.monitor import SessionMonitor
from orchestra.lib.sessions import Session, load_sessions

import os

# Prevent the monitor agent itself from triggering hooks (would create infinite loop)
os.environ["CLAUDE_MONITOR_SKIP_FORWARD"] = "1"

app = FastAPI(title="Claude Code Multi-Monitor", version="1.0")

logger = logging.getLogger("multi_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

# session_id -> SessionWorker
_workers: Dict[str, SessionMonitor] = {}


def get_session(session_id: str, source_path: str) -> Session:
    """Load and return a session by ID from the specified project"""
    sessions = load_sessions(flat=True, project_dir=Path(source_path))

    for sess in sessions:
        if sess.session_id == session_id:
            return sess

    raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found in {source_path}")


async def get_or_create_worker(session_id: str, source_path: str, payload: Dict[str, Any]) -> SessionMonitor:
    worker = _workers.get(session_id)

    session = get_session(session_id, source_path)

    if worker is None:
        worker = SessionMonitor(session=session)
        await worker.start()
        _workers[session_id] = worker
        logger.info("started worker for session_id=%s in %s", session_id, source_path)
    return worker


@app.on_event("shutdown")
async def _shutdown() -> None:
    for sid, w in list(_workers.items()):
        await w.stop()
        _workers.pop(sid, None)


@app.post("/hook/{session_id}")
async def hook(request: Request, session_id: str) -> Dict[str, str]:
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

    worker = await get_or_create_worker(session_id, source_path, evt)

    try:
        await worker.enqueue(evt)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="queue full")

    return {"status": "ok", "session_id": session_id}


def main():
    """Entry point for the monitoring server"""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081

    print(f"Starting Orchestra Monitor Server on port {port}")
    print(f"Hook endpoint: http://0.0.0.0:{port}/hook/{{session_id}}")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
