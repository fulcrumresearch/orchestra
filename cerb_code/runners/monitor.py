#!/usr/bin/env python3
"""
Multi-agent Claude Code monitor (asyncio, single process).

- FastAPI app exposes POST /hook (no auth/signatures).
- For each incoming event, we route by payload.session_id.
- Each unique session_id gets its own:
    * long-lived Claude Code SDK session
    * asyncio.Queue of events
    * forwarder task that feeds events to the agent
- Idle _sessions auto-close after an inactivity timeout.

ENV
  ANTHROPIC_API_KEY=...            # required by Claude Code CLI/SDK
  MONITOR_PROJECT_ROOT=/srv/mon    # optional: base dir for per-session subprojects
  MONITOR_DEFAULT_PROJECT=.        # used if no per-session subdir is found
  MONITOR_PROMPT="..."             # optional extra system guidance
  MONITOR_ALLOWED_TOOLS="Read"     # comma-separated, e.g. "Read,Write"
  MONITOR_PERMISSION_MODE=plan     # plan | ask | acceptEdits
  MONITOR_IDLE_SECS=900            # idle timeout (seconds) to close a session (default 15m)

Run (example):
  uvicorn monitor_multi:app --host 0.0.0.0 --port 8081
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

from cerb_code.lib.monitor import SessionMonitor
from cerb_code.lib.sessions import Session, load_sessions

import os

os.environ["CLAUDE_MONITOR_SKIP_FORWARD"] = "1"

app = FastAPI(title="Claude Code Multi-Monitor", version="1.0")

logger = logging.getLogger("multi_monitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

# session_id -> SessionWorker
_workers: Dict[str, SessionMonitor] = {}

_sessions = {sess.session_id: sess for sess in load_sessions(flat=True)}

def get_session(session_id: str) -> Session:
    global _sessions
    if session_id not in _sessions:
        _sessions = {sess.session_id: sess for sess in load_sessions(flat=True)}

    session = _sessions.get(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session

async def get_or_create_worker(session_id: str, payload: Dict[str, Any]) -> SessionMonitor:
    worker = _workers.get(session_id)

    session = get_session(session_id)
    print(session)

    if worker is None:
        worker = SessionMonitor(session=session)
        await worker.start()
        _workers[session_id] = worker
        logger.info("started worker for session_id=%s", session_id)
    return worker

@app.on_event("startup")
async def _startup() -> None:
    logger.info("multi-monitor starting")

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

    payload = data.get("payload") or {}

    evt = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    worker = await get_or_create_worker(session_id, payload)

    try:
        await worker.enqueue(evt)
    except asyncio.QueueFull:
        raise HTTPException(status_code=503, detail="queue full")

    return {"status": "ok", "session_id": session_id}


def main():
    """Entry point for the monitoring server"""
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081

    print(f"Starting Cerb Monitor Server on port {port}")
    print(f"Hook endpoint: http://127.0.0.1:{port}/hook/{{session_id}}")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
