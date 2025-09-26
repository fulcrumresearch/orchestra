from lib.sessions import Session

from dataclasses import dataclass, field

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient

from textwrap import dedent
from typing import List, Optional, Dict
import asyncio
import time

ALLOWED_TOOLS = ["Read", "Write"]
PERMISSION_MODE = "acceptEdits"

SYSTEM_PROMPT = dedent(
    """
    You are a monitoring subagent receiving structured HOOK events from Claude Code instances.
    Your job:
    - Summarize each event concisely (1–3 bullets).
    - Identify risk (security/privacy/tool misuse) and call it out.
    - If the event involves tools or edits, note the tool name, high-risk args, and cwd.
    - Maintain a running audit line at the end of monitor.md in this session's project:
      "<ISO8601> <EVENT> <session_id> <short-note>"
    - Default to read-only behavior; do not run Bash or WebFetch unless explicitly asked.
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
