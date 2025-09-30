from .sessions import Session
from .logger import get_logger

from dataclasses import dataclass, field
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
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

# Batch processing configuration
BATCH_WAIT_TIME = 10  # Wait 2 seconds after first event before processing
MAX_BATCH_SIZE = 10    # Process immediately if 10 events accumulate
MAX_BATCH_WAIT = 20   # Never wait more than 5 seconds total

SYSTEM_PROMPT = dedent(
    """
    You are a monitoring subagent receiving structured HOOK events from Claude Code instances.
    Your job:

    - Understand the instructions given to the agent in instructions.md and how they interact with the codebase.
    - Output information in realtime about the agent's progress, given the various hooks and codebase access.
    - Do not execute commands. Do not run Bash or WebFetch unless explicitly asked. Only write to the monitor.md file.

    Structure of report:

    - **Current Status**: Describe what the agent is currently trying to do.
    - **Summary of changes**: For each file, what did the agent do, what choices were made, how did they do it, how does the whole thing get structured.
    - **Deviations from spec**: Detail potential choices the agent made that were not defined or were deviations from the spec given by the designer in the instructions file.

    Don't make it too verbose, it should be definitely less than a page.
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

        options = ClaudeAgentOptions(
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

        await self.client.query(f"Session online. Understand and update the monitor.md in the given format. Do NOT log every event, the whole point is to make this easier for the a human to understand what is going on.")

        async for chunk in self.client.receive_response():
            logger.info("[%s] startup> %s", self.session.session_id, chunk)

        while True:
            # Collect batch of events
            batch = []

            # Get first event (blocking)
            first_event = await self.queue.get()
            batch.append(first_event)
            batch_start = time.time()

            # Collect more events with timeout
            while True:
                batch_age = time.time() - batch_start

                # Stop if batch is full or too old
                if batch_age >= MAX_BATCH_WAIT:
                    break

                # Try to get more events (with timeout)
                try:
                    evt = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=BATCH_WAIT_TIME
                    )
                    batch.append(evt)
                except asyncio.TimeoutError:
                    break

            # Format all events and send as one message
            try:
                prompts = [format_event_for_agent(evt) for evt in batch]
                combined_prompt = "\n\n---\n\n".join(prompts)

                await self.client.query(combined_prompt)
                async for chunk in self.client.receive_response():
                    logger.info("[%s] batch[%d]> %s", self.session.session_id, len(batch), chunk)
            finally:
                # Mark all events as done
                for _ in batch:
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
                }
            except Exception as e:
                logger.error(f"Error reading {monitor_file}: {e}")

        # Process children
        for child in sess.children:
            self._collect_from_session(child, monitors)
