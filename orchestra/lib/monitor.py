from .sessions import Session
from .logger import get_logger
from .config import load_config
from .prompts import get_monitor_prompt, get_independent_monitor_prompt

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pathlib import Path
import asyncio
import json
import time

logger = get_logger(__name__)

# Batch processing configuration
BATCH_WAIT_TIME = 10  # Wait 10 seconds after first event before processing
MAX_BATCH_SIZE = 10  # Process immediately if 10 events accumulate
MAX_BATCH_WAIT = 20  # Never wait more than 20 seconds total


def format_event_for_agent(evt: Dict[str, Any]) -> str:
    """Format event for the monitoring agent"""
    event_type = evt.get("event", "UnknownEvent")
    ts = evt.get("received_at", datetime.now(timezone.utc).isoformat())
    pretty_json = json.dumps(evt, indent=2, ensure_ascii=False)

    return f"HOOK EVENT: {event_type}\ntime: {ts}\n\n```json\n{pretty_json}\n```"


@dataclass
class BaseMonitor(ABC):
    """
    Base class for monitoring agents with shared batching and event processing.

    Subclasses must implement abstract methods to define monitor-specific behavior.
    """

    client: Optional[ClaudeSDKClient] = field(default=None, init=False)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000), init=False)
    task: Optional[asyncio.Task] = field(default=None, init=False)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this monitor"""
        pass

    @abstractmethod
    def get_allowed_tools(self) -> List[str]:
        """Return list of allowed tools for this monitor"""
        pass

    @abstractmethod
    def get_mcp_servers(self) -> Dict[str, Any]:
        """Return MCP server configuration dict (empty dict if none needed)"""
        pass

    @abstractmethod
    def get_working_directory(self) -> str:
        """Return the working directory for the Claude agent"""
        pass

    @abstractmethod
    def get_session_id(self) -> str:
        """Return the session ID being monitored"""
        pass

    async def start(self) -> None:
        """Start the monitor agent"""
        if self.client is not None:
            return

        options = ClaudeAgentOptions(
            cwd=self.get_working_directory(),
            system_prompt=self.get_system_prompt(),
            allowed_tools=self.get_allowed_tools(),
            permission_mode="acceptEdits",
            hooks={},
            mcp_servers=self.get_mcp_servers(),
        )

        self.client = ClaudeSDKClient(options=options)
        await self.client.__aenter__()
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop the monitor agent"""
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
        """Add an event to the processing queue"""
        self.queue.put_nowait(evt)

    async def _run(self) -> None:
        """Main monitoring loop - processes batched events"""
        # Send startup message
        await self.client.query(
            "Monitor session started. Watch the events and intervene when necessary. Build understanding in your head."
        )

        async for chunk in self.client.receive_response():
            logger.info("[%s] startup> %s", self.get_session_id(), chunk)

        # Process events in batches
        while True:
            # Collect batch of events
            batch = []

            # Get first event (blocking)
            first_event = await self.queue.get()
            batch.append(first_event)
            batch_start = asyncio.get_event_loop().time()

            # Collect more events with timeout
            while True:
                batch_age = asyncio.get_event_loop().time() - batch_start

                # Stop if batch is full or too old
                if len(batch) >= MAX_BATCH_SIZE or batch_age >= MAX_BATCH_WAIT:
                    break

                # Try to get more events (with timeout)
                try:
                    evt = await asyncio.wait_for(self.queue.get(), timeout=BATCH_WAIT_TIME)
                    batch.append(evt)
                except asyncio.TimeoutError:
                    break

            # Format all events and send as one message
            try:
                prompts = [format_event_for_agent(evt) for evt in batch]
                combined_prompt = "\n\n---\n\n".join(prompts)

                await self.client.query(combined_prompt)
                async for chunk in self.client.receive_response():
                    logger.info("[%s] batch[%d]> %s", self.get_session_id(), len(batch), chunk)
            finally:
                # Mark all events as done
                for _ in batch:
                    self.queue.task_done()


@dataclass
class SessionMonitor(BaseMonitor):
    """Orchestra session-based monitor that uses MCP to communicate with sessions"""

    session: Session
    last_touch: float = field(default_factory=lambda: time.time())

    def get_system_prompt(self) -> str:
        parent_session_id = getattr(self.session, 'parent_session_name', 'unknown')
        return get_monitor_prompt(
            session_id=self.session.session_id,
            agent_type=self.session.agent_type.value if self.session.agent_type else "unknown",
            parent_session_id=parent_session_id,
            source_path=self.session.source_path,
        )

    def get_allowed_tools(self) -> List[str]:
        return ["Read", "Write", "Edit", "mcp__orchestra-subagent__send_message_to_session"]

    def get_mcp_servers(self) -> Dict[str, Any]:
        config = load_config()
        mcp_port = config.get("mcp_port", 8765)
        return {
            "orchestra-subagent": {
                "type": "http",
                "url": f"http://127.0.0.1:{mcp_port}/mcp",
            }
        }

    def get_working_directory(self) -> str:
        return self.session.work_path

    def get_session_id(self) -> str:
        return self.session.session_id

    async def enqueue(self, evt: Dict[str, Any]) -> None:
        """Override to track last touch time"""
        self.last_touch = time.time()
        await super().enqueue(evt)


@dataclass
class IndependentMonitor(BaseMonitor):
    """Standalone monitor that writes feedback to .orchestra-monitor.txt (no MCP/sessions)"""

    session_id: str
    source_path: str

    def get_system_prompt(self) -> str:
        return get_independent_monitor_prompt(
            session_id=self.session_id,
            source_path=self.source_path,
        )

    def get_allowed_tools(self) -> List[str]:
        return ["Read", "Write"]

    def get_mcp_servers(self) -> Dict[str, Any]:
        return {}  # No MCP needed

    def get_working_directory(self) -> str:
        return self.source_path

    def get_session_id(self) -> str:
        return self.session_id


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

        monitor_file = Path(sess.work_path) / ".orchestra" / "monitor.md"

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
