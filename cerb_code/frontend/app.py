#!/usr/bin/env python3
"""Unified UI - Session picker and monitor combined (refactored)"""

from __future__ import annotations
import asyncio
import subprocess
import shutil
from pathlib import Path
import threading

from textual.app import App, ComposeResult
from textual.widgets import (
    Static,
    Label,
    TabbedContent,
    TabPane,
    ListView,
    ListItem,
    Tabs,
    RichLog,
)
from textual.containers import Container, Horizontal
from textual.binding import Binding

# Import widgets from new locations
from cerb_code.frontend.widgets.hud import HUD
from cerb_code.frontend.widgets.diff_tab import DiffTab
from cerb_code.frontend.widgets.monitor_tab import ModelMonitorTab
from cerb_code.frontend.state import AppState

# Import from lib
from cerb_code.lib.sessions import (
    Session,
    AgentType,
    save_session,
    SESSIONS_FILE,
)
from cerb_code.lib.tmux_agent import TmuxProtocol
from cerb_code.lib.file_watcher import watch_designer_file
from cerb_code.lib.logger import get_logger
from cerb_code.lib.config import load_config
from cerb_code.lib.helpers import (
    get_current_branch,
    ensure_stable_git_location,
    respawn_pane_with_vim,
    respawn_pane_with_terminal,
    PANE_AGENT,
)

logger = get_logger(__name__)


class UnifiedApp(App):
    """Unified app combining session picker and monitor"""

    CSS = """
    Screen {
        background: #0a0a0a;
    }

    #header {
        height: 2;
        background: #111111;
        border-bottom: solid #333333;
        dock: top;
    }

    #hud {
        height: 2;
        padding: 0 1;
        color: #C0FFFD;
        text-align: center;
    }

    #main-content {
        height: 1fr;
    }

    #left-pane {
        width: 30%;
        background: #0a0a0a;
        border-right: solid #333333;
    }

    #right-pane {
        width: 70%;
        background: #000000;
    }

    TabbedContent {
        height: 1fr;
    }

    Tabs {
        background: #1a1a1a;
    }

    Tab {
        padding: 0 1;
    }

    Tab.-active {
        text-style: bold;
    }

    TabPane {
        padding: 1;
        background: #000000;
        layout: vertical;
    }

    #sidebar-title {
        color: #00ff9f;
        text-style: bold;
        margin-bottom: 0;
        height: 1;
    }

    #branch-info {
        color: #888888;
        text-style: italic;
        margin-bottom: 0;
        height: 1;
    }

    #status-indicator {
        color: #ffaa00;
        text-style: italic;
        margin-bottom: 1;
        height: 1;
    }

    ListView {
        height: 1fr;
    }

    ListItem {
        color: #cccccc;
        padding: 0 1;
    }

    ListItem:hover {
        background: #222222;
        color: #ffffff;
    }

    ListView > ListItem.--highlight {
        background: #1a1a1a;
        color: #00ff9f;
        text-style: bold;
        border-left: thick #00ff9f;
    }

    RichLog {
        background: #000000;
        color: #ffffff;
        overflow-x: hidden;
        overflow-y: auto;
        width: 100%;
        height: 1fr;
        text-wrap: wrap;
    }
"""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+d", "delete_session", "Delete", priority=True),
        Binding("p", "toggle_pairing", "Toggle Pairing", priority=True, show=True),
        Binding("s", "open_spec", "Open Spec", priority=True),
        Binding("t", "open_terminal", "Open Terminal", priority=True),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("k", "scroll_tab_up", "Scroll Tab Up", show=False),
        Binding("j", "scroll_tab_down", "Scroll Tab Down", show=False),
        Binding("left", "prev_tab", show=False),
        Binding("right", "next_tab", show=False),
        Binding("h", "prev_tab", show=False),
        Binding("l", "next_tab", show=False),
    ]

    def __init__(self):
        super().__init__()
        logger.info("KerberosApp initializing")

        # Store the original project directory (resolve now, before any pairing)
        project_dir = Path.cwd().resolve()

        # Initialize state
        self.state = AppState(project_dir)

        # Load config and create TmuxProtocol
        config = load_config()
        self.agent = TmuxProtocol(
            default_command="claude",
            mcp_port=config.get("mcp_port", 8765),
        )

        # File watcher state
        self._last_session_mtime = None
        self._watch_task = None

        logger.info(
            f"KerberosApp initialized (Docker: {config.get('use_docker', True)})"
        )

    def action_quit(self) -> None:
        """Quit the UI and kill the dedicated tmux server named 'orchestra'."""

        def kill_tmux_server():
            try:
                subprocess.run(
                    ["tmux", "-L", "orchestra", "kill-server"],
                    capture_output=True,
                    text=True,
                )
            except Exception:
                pass

        # Delay the kill slightly to allow the app to exit cleanly first
        threading.Timer(0.2, kill_tmux_server).start()
        self.exit()

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return

        # Global header with HUD
        with Container(id="header"):
            self.hud = HUD(
                "⌃D delete • ⌃R refresh • P pair • S spec • T terminal • ⌃Q quit",
                id="hud",
            )
            yield self.hud

        # Main content area - split horizontally
        with Horizontal(id="main-content"):
            # Left pane - session list
            with Container(id="left-pane"):
                yield Static("Orchestra", id="sidebar-title")
                self.branch_info = Static("", id="branch-info")
                yield self.branch_info
                self.status_indicator = Static("", id="status-indicator")
                yield self.status_indicator
                self.session_list = ListView(id="session-list")
                yield self.session_list

            # Right pane - tabbed monitor view
            with Container(id="right-pane"):
                with TabbedContent(initial="diff-tab"):
                    with TabPane("Diff", id="diff-tab"):
                        yield DiffTab()
                    with TabPane("Monitor", id="monitor-tab"):
                        yield ModelMonitorTab()

    async def on_ready(self) -> None:
        """Load sessions and refresh list"""
        # Detect current git branch and store as fixed root
        branch_name = get_current_branch()
        self.state.root_session_id = branch_name

        # Load sessions for current branch only
        self.state.load(root_session_id=self.state.root_session_id, protocol=self.agent)

        # Ensure branch session exists
        if not self.state.root_session:
            try:
                # Show status indicator
                self.status_indicator.update("⏳ Creating session...")

                # First time setup - ensure .git is in stable location
                await asyncio.to_thread(ensure_stable_git_location, Path.cwd())

                # Create designer session for this branch
                logger.info(f"Creating designer session for branch: {branch_name}")
                new_session = Session(
                    session_id=branch_name,
                    agent_type=AgentType.DESIGNER,
                    protocol=self.agent,
                    source_path=str(Path.cwd()),
                )
                await asyncio.to_thread(new_session.prepare)
                if await asyncio.to_thread(new_session.start):
                    self.state.root_session = new_session
                    await asyncio.to_thread(save_session, new_session, self.state.project_dir)
                    logger.info(f"Successfully created and saved session {branch_name}")
                else:
                    logger.error(f"Failed to start session {branch_name}")

                # Clear status indicator
                self.status_indicator.update("")
            except Exception as e:
                logger.exception(f"Error creating designer session: {e}")
                self.status_indicator.update("")

        # Update branch info display
        self.branch_info.update(f"Designer: {branch_name}")

        await self.action_refresh()

        # Auto-load branch session
        if self.state.root_session:
            self._attach_to_session(self.state.root_session)

        # Focus the session list by default
        self.set_focus(self.session_list)

        # Start watching sessions file for changes
        self._watch_task = asyncio.create_task(self._watch_sessions_file())

        # Start the file watcher
        await self.state.file_watcher.start()

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        # Save the current selection
        current_index = self.session_list.index
        selected_session_id = None
        if current_index == 0 and self.state.root_session:
            selected_session_id = self.state.root_session.session_id
        elif current_index is not None and current_index > 0 and self.state.root_session:
            child_index = current_index - 1
            if child_index < len(self.state.root_session.children):
                selected_session_id = self.state.root_session.children[child_index].session_id

        self.session_list.clear()

        # Check if we have a root session
        if not self.state.root_session:
            self.session_list.append(ListItem(Label("No sessions found")))
            return

        # Add designer session
        root = self.state.root_session
        status = self.agent.get_status(root.session_id, root.use_docker)
        is_active = status.get("attached", False)

        status_icon = "●" if is_active else "○"
        paired_indicator = "[P] " if self.state.paired_session_id == root.session_id else ""
        display_name = f"{status_icon} {paired_indicator}🎨 {root.session_id}"
        self.session_list.append(ListItem(Label(display_name)))

        # Add executor sessions
        for child in root.children:
            status = self.agent.get_status(child.session_id, child.use_docker)
            is_active = status.get("attached", False)

            status_icon = "●" if is_active else "○"
            paired_indicator = "[P] " if self.state.paired_session_id == child.session_id else ""
            display_name = f"{status_icon} {paired_indicator}👷 {child.session_id}"
            self.session_list.append(ListItem(Label(display_name)))

        # Restore the selection if the session still exists
        if selected_session_id:
            if self.state.root_session.session_id == selected_session_id:
                self.session_list.index = 0
            else:
                for i, child in enumerate(self.state.root_session.children):
                    if child.session_id == selected_session_id:
                        self.session_list.index = i + 1
                        break

    def action_cursor_up(self) -> None:
        """Move cursor up in the list"""
        self.session_list.action_cursor_up()

    def action_cursor_down(self) -> None:
        """Move cursor down in the list"""
        self.session_list.action_cursor_down()

    def action_scroll_tab_up(self) -> None:
        """Scroll up in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            for widget in active_pane.query(RichLog):
                widget.scroll_relative(y=-1)

    def action_scroll_tab_down(self) -> None:
        """Scroll down in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            for widget in active_pane.query(RichLog):
                widget.scroll_relative(y=1)

    def action_prev_tab(self) -> None:
        """Switch to previous tab"""
        tabs = self.query_one(Tabs)
        tabs.action_previous_tab()

    def action_next_tab(self) -> None:
        """Switch to next tab"""
        tabs = self.query_one(Tabs)
        tabs.action_next_tab()

    async def _delete_session_task(self, session_to_delete: Session) -> None:
        """Background task for deleting a session"""
        try:
            # Delete the session (handles Docker or local mode)
            await asyncio.to_thread(session_to_delete.delete)

            # Save the root session (if it still exists)
            if self.state.root_session and session_to_delete != self.state.root_session:
                await asyncio.to_thread(save_session, self.state.root_session, self.state.project_dir)
        finally:
            # Remove from state - simple: root or child
            if self.state.root_session and session_to_delete.session_id == self.state.root_session.session_id:
                # Deleting root - clear everything
                self.state.root_session = None
            else:
                # Deleting a child
                self.state.remove_child(session_to_delete.session_id)

            # Refresh the list
            await self.action_refresh()

            # Clear status indicator
            self.status_indicator.update("")

    def action_delete_session(self) -> None:
        """Delete the currently selected session"""
        index = self.session_list.index
        if index is None:
            return

        session_to_delete = self.state.get_session_by_index(index)
        if not session_to_delete:
            return

        # If deleting the active session, switch to designer first
        if self.state.active_session_id == session_to_delete.session_id:
            if self.state.root_session and session_to_delete != self.state.root_session:
                self._attach_to_session(self.state.root_session)
            else:
                self.hud.set_session("")

        # Show status indicator
        self.status_indicator.update("⏳ Deleting session...")

        # Run delete in background without waiting
        asyncio.create_task(self._delete_session_task(session_to_delete))

    async def _toggle_pairing_task(self, session: Session, is_paired: bool) -> None:
        """Background task for toggling pairing"""
        # Set session.paired temporarily for toggle_pairing to work
        session.paired = is_paired

        # Toggle pairing (this does I/O)
        success, error_msg = await asyncio.to_thread(session.toggle_pairing)

        if not success:
            self.hud.set_session(f"Error: {error_msg}")
            logger.error(f"Failed to toggle pairing: {error_msg}")
            self.status_indicator.update("")
            return

        # Update state based on new pairing status
        if is_paired:
            # Was paired, now unpaired
            self.state.paired_session_id = None
            paired_indicator = ""
        else:
            # Was unpaired, now paired
            self.state.paired_session_id = session.session_id
            paired_indicator = "[P] "

        self.hud.set_session(f"{paired_indicator}{session.session_id}")

        # Refresh the list to show pairing status
        await self.action_refresh()

        # Clear status indicator
        self.status_indicator.update("")

    def action_toggle_pairing(self) -> None:
        """Toggle pairing mode for the currently selected session"""
        index = self.session_list.index
        if index is None:
            return

        session = self.state.get_session_by_index(index)
        if not session:
            return

        # Check if this session is currently paired (from state)
        is_paired = (self.state.paired_session_id == session.session_id)

        # Show status indicators
        pairing_mode = "paired" if not is_paired else "unpaired"
        self.status_indicator.update(f"⏳ Switching to {pairing_mode}...")
        self.hud.set_session(f"Switching to {pairing_mode} mode...")

        # Run toggle in background without waiting
        asyncio.create_task(self._toggle_pairing_task(session, is_paired))

    def action_open_spec(self) -> None:
        """Open designer.md in vim in a split tmux pane"""
        index = self.session_list.index
        if index is None:
            return

        session = self.state.get_session_by_index(index)
        if not session:
            return
        work_path = Path(session.work_path)
        designer_md = work_path / "designer.md"

        # Create designer.md if it doesn't exist
        if not designer_md.exists():
            designer_md.touch()
            logger.info(f"Created {designer_md}")

        # Register file watcher for designer.md to notify session on changes
        watch_designer_file(self.state.file_watcher, designer_md, session)

        # Use helper to respawn pane with vim
        if respawn_pane_with_vim(designer_md):
            logger.info(f"Opened spec editor for {designer_md}")
        else:
            logger.error(f"Failed to open spec")

    def action_open_terminal(self) -> None:
        """Open bash terminal in the highlighted session's worktree in pane 1"""
        index = self.session_list.index
        if index is None:
            return

        session = self.state.get_session_by_index(index)
        if not session:
            return
        work_path = Path(session.work_path)

        # Use helper to respawn pane with terminal
        if respawn_pane_with_terminal(work_path):
            logger.info(f"Opened terminal for {work_path}")
        else:
            logger.error(f"Failed to open terminal")

    def _attach_to_session(self, session: Session) -> None:
        """Select a session and update monitors to show it"""
        # Update state
        self.state.set_active_session(session.session_id)

        # Check session status using the protocol
        status = self.agent.get_status(session.session_id, session.use_docker)

        if not status.get("exists", False):
            # Session doesn't exist, create it
            logger.info(f"Session {session.session_id} doesn't exist, creating it")
            if not session.work_path:
                session.prepare()

            if not session.start():
                # Failed to create session, show error in pane
                logger.error(f"Failed to start session {session.session_id}")
                error_cmd = f"bash -c 'echo \"Failed to start session {session.session_id}\"; exec bash'"
                subprocess.run(
                    ["tmux", "-L", "orchestra", "respawn-pane", "-t", PANE_AGENT, "-k", error_cmd],
                    capture_output=True,
                    text=True,
                )
                return

        # At this point, session exists - attach to it in pane 2
        self.agent.attach(
            session.session_id, target_pane=PANE_AGENT, use_docker=session.use_docker
        )

        # Update HUD with session name
        self.hud.set_session(session.session_id)

        # Immediately refresh monitor tab to show new session's monitor
        monitor_tab = self.query_one(ModelMonitorTab)
        monitor_tab.refresh_monitor()

    async def _watch_sessions_file(self) -> None:
        """Watch sessions.json for changes and refresh when modified"""
        while True:
            try:
                if SESSIONS_FILE.exists():
                    current_mtime = SESSIONS_FILE.stat().st_mtime
                    if (
                        self._last_session_mtime is not None
                        and current_mtime != self._last_session_mtime
                    ):
                        logger.info("Sessions file changed, refreshing...")
                        # Reload sessions from disk
                        self.state.load(root_session_id=self.state.root_session_id, protocol=self.agent)
                        await self.action_refresh()
                    self._last_session_mtime = current_mtime
            except Exception as e:
                logger.error(f"Error watching sessions file: {e}")

            # Check every second
            await asyncio.sleep(1)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list when clicked"""
        idx = event.list_view.index
        if idx is None:
            return

        session = self.state.get_session_by_index(idx)
        if not session:
            return

        self._attach_to_session(session)
