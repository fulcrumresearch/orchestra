from .sessions import Session
from .logger import get_logger

from dataclasses import dataclass, field
from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
from textwrap import dedent
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json
import time

logger = get_logger(__name__)

ALLOWED_TOOLS = ["Read", "Write"]
PERMISSION_MODE = "acceptEdits"

SYSTEM_PROMPT = dedent(
    """
    You are a monitoring subagent receiving structured HOOK events from Claude Code instances.
    Your job:

    - Understand the instructions given to the agent in instructions.md and how they interact with the codebase.
    - Output information in realtime about the agent's progress, given the various hooks and codebase access.
    - Do not execute commands. Do not run Bash or WebFetch unless explicitly asked. Only write to the monitor.md file.

    Kinds of information in your report:

    - Deviations from given spec
    - Additional choices made by the agent in its implementation that were not defined in the spec
    - Summary of changes
    """
).strip()

def format_event_for_agent(evt: Dict[str, Any]) -> str:
    event_type = evt.get("event") or evt.get("hook_event_name") or "UnknownEvent"
    payload = evt.get("payload", evt)
    session_id = payload.get("session_id") or payload.get("session") or "?"
    tool_name = payload.get("tool_name") or payload.get("tool") or "-"
    cwd = payload.get("cwd") or payload.get("working_dir") or "-"
    transcript_path = payload.get("transcript_path", "-")
    ts = evt.get("receivedAt") or evt.get("received_at") or datetime.now(timezone.utc).isoformat()
    pretty_json = json.dumps(payload, indent=2, ensure_ascii=False)
    return (
        f"HOOK EVENT: {event_type}\n"
        f"time: {ts}\n"
        f"session_id: {session_id}\n"
        f"tool: {tool_name}\n"
        f"cwd: {cwd}\n"
        f"transcript_path: {transcript_path}\n\n"
        f"payload (JSON):\n```json\n{pretty_json}\n```\n\n"
        "Please:\n"
        "- Summarize significance.\n"
        "- Flag risk & sensitive args.\n"
        "- Append a one-line audit record to monitor.md (if Write is allowed).\n"
    )

@dataclass
class SessionMonitor:
    session: Session
    allowed_tools: List[str] = field(default_factory=lambda: ALLOWED_TOOLS)
    permission_mode: str = PERMISSION_MODE
    system_prompt: str = SYSTEM_PROMPT

    client: Optional[ClaudeSDKClient] = None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    task: Optional[asyncio.Task] = None
    last_touch: float = field(default_factory=lambda: time.time())

    async def start(self) -> None:
        if self.client is not None:
            return

        options = ClaudeCodeOptions(
            cwd=self.session.work_path,
            system_prompt=self.system_prompt,
            allowed_tools=self.allowed_tools,
            permission_mode=self.permission_mode,
            hooks={}
        )

        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except Exception:
                pass
            self.task = None
        if self.client:
            await self.client.__aexit__(None, None, None)
            self.client = None

    async def enqueue(self, evt: Dict[str, Any]) -> None:
        self.last_touch = time.time()
        self.queue.put_nowait(evt)

    async def _run(self) -> None:

        await self.client.query(f"[monitor:{self.session.session_id}] session online; awaiting hook events.")

        async for chunk in self.client.receive_response():
            logger.info("[%s] startup> %s", self.session.session_id, chunk)

        while True:
            evt = await self.queue.get()
            try:
                prompt = format_event_for_agent(evt)
                await self.client.query(prompt)
                async for chunk in self.client.receive_response():
                    logger.info("[%s] agent> %s", self.session.session_id, chunk)
            finally:
                self.queue.task_done()


@dataclass
class SessionMonitorWatcher:
    """Watches monitor.md files for a session and its children"""
    session: Session

    def get_monitor_files(self) -> Dict[str, Dict[str, Any]]:
        """
        Get monitor.md files for this session and all its children.
        Returns dict: {session_id: {"path": path, "content": content, "mtime": mtime}}
        """
        monitors = {}
        self._collect_from_session(self.session, monitors)
        return monitors

    def _collect_from_session(self, sess: Session, monitors: Dict[str, Dict[str, Any]]) -> None:
        """Recursively collect monitor files from a session and its children"""
        if not sess.work_path:
            return

        monitor_file = Path(sess.work_path) / "monitor.md"

        if monitor_file.exists():
            try:
                content = monitor_file.read_text()
                mtime = monitor_file.stat().st_mtime

                monitors[sess.session_id] = {
                    "path": str(monitor_file),
                    "content": content,
                    "mtime": mtime,
                    "last_updated": datetime.fromtimestamp(mtime).isoformat(),
                    "agent_type": sess.agent_type.value
                }
            except Exception as e:
                logger.error(f"Error reading {monitor_file}: {e}")
                monitors[sess.session_id] = {
                    "path": str(monitor_file),
                    "content": f"Error reading file: {e}",
                    "mtime": 0,
                    "last_updated": "Error",
                    "agent_type": sess.agent_type.value
                }

        # Process children
        for child in sess.children:
            self._collect_from_session(child, monitors)