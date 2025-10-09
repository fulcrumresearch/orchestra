#!/usr/bin/env python3
"""Unified UI - Session picker and monitor combined"""

from __future__ import annotations
import asyncio
import subprocess
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Sequence, Tuple
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
from rich.markup import escape

from cerb_code.lib.sessions import (
    Session,
    AgentType,
    load_sessions,
    save_session,
    SESSIONS_FILE,
)
from cerb_code.lib.tmux_agent import TmuxProtocol
from cerb_code.lib.monitor import SessionMonitorWatcher
from cerb_code.lib.file_watcher import FileWatcher, watch_designer_file
from cerb_code.lib.logger import get_logger
from cerb_code.lib.config import load_config
from cerb_code.lib.helpers import get_current_branch, ensure_stable_git_location
import re

logger = get_logger(__name__)


class HUD(Static):
    can_focus = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_text = (
            "⌃D delete • ⌃R refresh • P pair • S spec • T terminal • ⌃Q quit"
        )
        self.current_session = ""

    def set_session(self, session_name: str):
        """Update the current session display"""
        self.current_session = session_name
        self.update(f"[{session_name}] • {self.default_text}")


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
        Binding("enter", "select_session", "Select Session", show=False),
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
        self.sessions: list[Session] = []
        self.flat_sessions: list[Session] = []  # Flattened list for selection
        self.current_session: Session | None = None
        self.root_session_id: str | None = None  # Fixed root, doesn't change even when pairing
        # Store the original project directory (resolve now, before any pairing)
        self.project_dir: Path = Path.cwd().resolve()
        # Track which session is currently paired (UI state only, not persisted)
        self.paired_session_id: str | None = None
        # Load config and create TmuxProtocol
        config = load_config()
        self.agent = TmuxProtocol(
            default_command="claude",
            mcp_port=config.get("mcp_port", 8765),
        )
        self._last_session_mtime = None
        self._watch_task = None
        # Create a shared FileWatcher for monitoring files
        self.file_watcher = FileWatcher()
        logger.info(
            f"KerberosApp initialized (Docker: {config.get('use_docker', True)})"
        )

    def action_quit(self) -> None:
        """Quit the UI and kill the dedicated tmux server named 'orchestra'.

        We schedule the tmux kill to occur shortly after exit so that the UI
        can clean up normally while ensuring Docker containers, sessions, and
        worktrees remain untouched.
        """

        def kill_tmux_server():
            try:
                subprocess.run(
                    ["tmux", "-L", "orchestra", "kill-server"],
                    capture_output=True,
                    text=True,
                )
            except Exception:
                # Ignore any errors while attempting to kill the tmux server
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
        self.root_session_id = branch_name

        # Load sessions for current branch only
        self.sessions = load_sessions(protocol=self.agent, root=self.root_session_id, project_dir=self.project_dir)

        # Ensure branch session exists
        if not self.sessions:
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
                    active=False,
                )
                await asyncio.to_thread(new_session.prepare)
                if await asyncio.to_thread(new_session.start):
                    self.sessions = [new_session]
                    await asyncio.to_thread(save_session, new_session, self.project_dir)
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
        if self.sessions:
            self._attach_to_session(self.sessions[0])

        # Focus the session list by default
        self.set_focus(self.session_list)

        # Start watching sessions file for changes
        self._watch_task = asyncio.create_task(self._watch_sessions_file())

        # Start the file watcher
        await self.file_watcher.start()

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        # Save the current selection
        current_index = self.session_list.index
        selected_session_id = None
        if current_index is not None and 0 <= current_index < len(self.flat_sessions):
            selected_session_id = self.flat_sessions[current_index].session_id

        self.session_list.clear()
        self.flat_sessions = []  # Keep flat list for selection

        if not self.sessions:
            self.session_list.append(ListItem(Label("No sessions found")))
            return

        # Add sessions to list with hierarchy
        def add_session_tree(session, indent=0):
            # Update status for this session
            status = self.agent.get_status(session.session_id, session.use_docker)
            session.active = status.get("attached", False)

            # Keep track in flat list for selection
            self.flat_sessions.append(session)

            # Display with indentation
            prefix = "  " * indent
            status_icon = "●" if session.active else "○"
            paired_indicator = "[P] " if self.paired_session_id == session.session_id else ""
            display_name = f"{status_icon} {paired_indicator}{session.session_id}"
            item = ListItem(Label(f"{prefix}{display_name}"))
            self.session_list.append(item)

            # Add children recursively
            for child in session.children:
                add_session_tree(child, indent + 1)

        for session in self.sessions:
            add_session_tree(session)

        # Restore the selection if the session still exists
        if selected_session_id:
            for i, session in enumerate(self.flat_sessions):
                if session.session_id == selected_session_id:
                    self.session_list.index = i
                    break

        # Don't save here - this causes an infinite loop with the file watcher!

    def _invoke_widget_action(
        self,
        widget: Any,
        candidate_methods: Sequence[str],
        action_description: str,
        args: Tuple[Any, ...] | None = None,
        kwargs: Dict[str, Any] | None = None,
    ) -> None:
        """Safely invoke widget actions, falling back to alternative names."""

        args = args or ()
        kwargs = kwargs or {}

        for method_name in candidate_methods:
            method = getattr(widget, method_name, None)
            if callable(method):
                try:
                    method(*args, **kwargs)
                    return
                except TypeError:
                    logger.debug(
                        "Signature mismatch performing %s using %s on %r; trying next candidate",
                        action_description,
                        method_name,
                        widget,
                    )
                except Exception:
                    logger.exception(
                        "Failed to perform %s using %s on %r",
                        action_description,
                        method_name,
                        widget,
                    )
                    return

        logger.warning(
            "No action handler available for %s on %r (tried: %s)",
            action_description,
            widget,
            ", ".join(candidate_methods),
        )

    def action_cursor_up(self) -> None:
        """Move cursor up in the list"""
        self._invoke_widget_action(
            self.session_list,
            ("action_cursor_up", "action_up", "cursor_up"),
            "session list cursor up",
        )

    def action_cursor_down(self) -> None:
        """Move cursor down in the list"""
        self._invoke_widget_action(
            self.session_list,
            ("action_cursor_down", "action_down", "cursor_down"),
            "session list cursor down",
        )

    def action_scroll_tab_up(self) -> None:
        """Scroll up in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            # Find and scroll the RichLog widget directly
            for widget in active_pane.query(RichLog):
                self._invoke_widget_action(
                    widget,
                    ("action_scroll_up", "scroll_relative"),
                    "scroll log up",
                    kwargs={"y": -1},
                )

    def action_scroll_tab_down(self) -> None:
        """Scroll down in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            # Find and scroll the RichLog widget directly
            for widget in active_pane.query(RichLog):
                self._invoke_widget_action(
                    widget,
                    ("action_scroll_down", "scroll_relative"),
                    "scroll log down",
                    kwargs={"y": 1},
                )

    def action_prev_tab(self) -> None:
        """Switch to previous tab"""
        tabs = self.query_one(Tabs)
        self._invoke_widget_action(
            tabs,
            ("action_previous_tab", "action_prev_tab", "action_scroll_left"),
            "previous tab",
        )

    def action_next_tab(self) -> None:
        """Switch to next tab"""
        tabs = self.query_one(Tabs)
        self._invoke_widget_action(
            tabs,
            ("action_next_tab", "action_scroll_right"),
            "next tab",
        )

    def action_select_session(self) -> None:
        """Select the highlighted session"""
        index = self.session_list.index
        if index is not None and 0 <= index < len(self.flat_sessions):
            session = self.flat_sessions[index]
            self._attach_to_session(session)

    def _remove_session_from_tree(self, sessions: list[Session], session_id: str) -> bool:
        """Recursively remove a session from the tree. Returns True if found and removed."""
        for i, session in enumerate(sessions):
            if session.session_id == session_id:
                sessions.pop(i)
                return True
            # Recursively check children
            if self._remove_session_from_tree(session.children, session_id):
                return True
        return False

    async def _delete_session_task(self, session_to_delete: Session) -> None:
        """Background task for deleting a session"""
        try:
            # Delete the session (handles Docker or local mode)
            await asyncio.to_thread(session_to_delete.delete)

            # Remove from sessions tree (handles both top-level and child sessions)
            self._remove_session_from_tree(self.sessions, session_to_delete.session_id)

            # Save the root session (if any remain)
            if self.sessions:
                await asyncio.to_thread(save_session, self.sessions[0], self.project_dir)

            # Refresh the list
            await self.action_refresh()
        finally:
            # Clear status indicator
            self.status_indicator.update("")

    def action_delete_session(self) -> None:
        """Delete the currently selected session"""
        # Get the currently highlighted session from the list
        index = self.session_list.index
        if index is None or index >= len(self.flat_sessions):
            return

        session_to_delete = self.flat_sessions[index]

        # If deleting the current session, switch to designer first (before background deletion)
        if (
            self.current_session
            and self.current_session.session_id == session_to_delete.session_id
        ):
            # Switch to designer immediately
            if self.sessions:
                self._attach_to_session(self.sessions[0])
            else:
                self.hud.set_session("")
                # Clear pane 2 (claude pane) with a message
                msg_cmd = "echo 'No active sessions.'"
                subprocess.run(
                    [
                        "tmux",
                        "-L",
                        "orchestra",
                        "respawn-pane",
                        "-t",
                        "2",
                        "-k",
                        msg_cmd,
                    ],
                  )

        # Show status indicator
        self.status_indicator.update("⏳ Deleting session...")

        # Run delete in background without waiting
        asyncio.create_task(self._delete_session_task(session_to_delete))

    async def _toggle_pairing_task(self, session: Session, is_paired: bool) -> None:
        """Background task for toggling pairing"""
        try:
            # Set session.paired temporarily for toggle_pairing to work
            session.paired = is_paired

            # Toggle pairing
            success, error_msg = await asyncio.to_thread(session.toggle_pairing)

            if not success:
                # Show error message
                self.hud.set_session(f"Error: {error_msg}")
                logger.error(f"Failed to toggle pairing: {error_msg}")
                return

            # Update UI state based on new pairing status
            if is_paired:
                # Was paired, now unpaired
                self.paired_session_id = None
                paired_indicator = ""
            else:
                # Was unpaired, now paired
                self.paired_session_id = session.session_id
                paired_indicator = "[P] "

            self.hud.set_session(f"{paired_indicator}{session.session_id}")

            # Refresh the list to show pairing status
            await self.action_refresh()
        finally:
            # Clear status indicator
            self.status_indicator.update("")

    def action_toggle_pairing(self) -> None:
        """Toggle pairing mode for the currently selected session"""
        # Get the currently highlighted session from the list
        index = self.session_list.index
        if index is None or index >= len(self.flat_sessions):
            return

        session = self.flat_sessions[index]

        # Check if this session is currently paired (UI state)
        is_paired = (self.paired_session_id == session.session_id)

        # Show status indicators
        pairing_mode = "paired" if not is_paired else "unpaired"
        self.status_indicator.update(f"⏳ Switching to {pairing_mode}...")
        self.hud.set_session(f"Switching to {pairing_mode} mode...")

        # Run toggle in background without waiting
        asyncio.create_task(self._toggle_pairing_task(session, is_paired))

    def action_open_spec(self) -> None:
        """Open designer.md in vim in a split tmux pane"""
        # Get the highlighted session from the list
        index = self.session_list.index
        if index is None or index >= len(self.flat_sessions):
            logger.warning("No session highlighted to open spec for")
            return

        session = self.flat_sessions[index]
        work_path = Path(session.work_path)
        designer_md = work_path / "designer.md"

        # Create designer.md if it doesn't exist
        if not designer_md.exists():
            designer_md.touch()
            logger.info(f"Created {designer_md}")

        # Register file watcher for designer.md to notify session on changes
        watch_designer_file(self.file_watcher, designer_md, session)

        # Respawn pane 1 (editor pane) with vim, wrapped in bash to keep pane alive after quit
        # When vim exits, show placeholder and keep shell running
        vim_cmd = f"bash -c '$EDITOR {designer_md}; clear; echo \"Press S to open spec editor\"; exec bash'"
        result = subprocess.run(
            ["tmux", "-L", "orchestra", "respawn-pane", "-t", "1", "-k", vim_cmd],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Failed to open spec: {result.stderr}")
        else:
            logger.info(f"Opened spec editor for {designer_md}")

    def action_open_terminal(self) -> None:
        """Open bash terminal in the highlighted session's worktree in pane 1"""
        # Get the highlighted session from the list
        index = self.session_list.index
        if index is None or index >= len(self.flat_sessions):
            logger.warning("No session highlighted to open terminal for")
            return

        session = self.flat_sessions[index]
        work_path = Path(session.work_path)

        # Respawn pane 1 with bash in the session's work directory
        # Keep the shell running and show current directory
        bash_cmd = f"bash -c 'cd {work_path} && exec bash'"
        result = subprocess.run(
            ["tmux", "-L", "orchestra", "respawn-pane", "-t", "1", "-k", bash_cmd],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            logger.error(f"Failed to open terminal: {result.stderr}")
        else:
            logger.info(f"Opened terminal for {work_path}")

    def _attach_to_session(self, session: Session) -> None:
        """Select a session and update monitors to show it"""
        # Mark all sessions as inactive, then mark this one as active
        for s in self.sessions:
            s.active = False
        session.active = True

        # Check session status using the protocol
        status = self.agent.get_status(session.session_id, session.use_docker)

        if not status.get("exists", False):
            # Session doesn't exist, create it
            logger.info(f"Session {session.session_id} doesn't exist, creating it")
            if not session.work_path:
                # Only prepare if work_path not set (i.e., not already prepared)
                session.prepare()

            if not session.start():
                # Failed to create session, show error in pane
                logger.error(f"Failed to start session {session.session_id}")
                error_cmd = f"bash -c 'echo \"Failed to start session {session.session_id}\"; exec bash'"
                subprocess.run(
                    [
                        "tmux",
                        "-L",
                        "orchestra",
                        "respawn-pane",
                        "-t",
                        "2",
                        "-k",
                        error_cmd,
                    ],
                    capture_output=True,
                    text=True,
                )
                return

        # At this point, session exists - attach to it in pane 2
        self.agent.attach(
            session.session_id, target_pane="2", use_docker=session.use_docker
        )

        # Don't auto-focus pane 2 - let user stay in the UI

        # Update HUD with session name
        self.hud.set_session(session.session_id)
        self.current_session = session

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
                        # Reload sessions from disk (only current root session)
                        self.sessions = load_sessions(protocol=self.agent, root=self.root_session_id, project_dir=self.project_dir)
                        await self.action_refresh()
                    self._last_session_mtime = current_mtime
            except Exception as e:
                logger.error(f"Error watching sessions file: {e}")

            # Check every second
            await asyncio.sleep(1)

    def _get_repo_name(self) -> str:
        """Get the current directory name"""
        return Path.cwd().name

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list when clicked"""
        lv: ListView = event.control
        idx = lv.index

        if idx is not None and 0 <= idx < len(self.flat_sessions):
            session = self.flat_sessions[idx]
            self._attach_to_session(session)


class DiffTab(Container):
    """Container for diff display"""

    def compose(self) -> ComposeResult:
        self.diff_log = RichLog(
            highlight=True,
            markup=True,
            auto_scroll=False,
            wrap=True,
            min_width=0,  # Don't enforce minimum width
        )
        yield self.diff_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.set_interval(2.0, self.refresh_diff)
        self.refresh_diff()

    def refresh_diff(self) -> None:
        """Fetch and display the latest diff"""
        app = self.app
        if not hasattr(app, "current_session") or not app.current_session:
            self.diff_log.clear()
            self.diff_log.write("[dim]No session selected[/dim]", expand=True)
            return

        work_path = app.current_session.work_path
        session_id = app.current_session.session_id

        if not work_path:
            self.diff_log.write("[dim]Session has no work path[/dim]", expand=True)
            return

        try:
            # Get git diff
            result = subprocess.run(
                ["git", "diff", "HEAD"], cwd=work_path, capture_output=True, text=True
            )

            if result.returncode == 0:
                # Clear previous content
                self.diff_log.clear()

                if result.stdout:
                    # Write diff line by line for better scrolling
                    for line in result.stdout.split("\n"):
                        escaped_line = escape(line)
                        if line.startswith("+"):
                            self.diff_log.write(
                                f"[green]{escaped_line}[/green]",
                                expand=True,
                            )
                        elif line.startswith("-"):
                            self.diff_log.write(
                                f"[red]{escaped_line}[/red]", expand=True
                            )
                        elif line.startswith("@@"):
                            self.diff_log.write(
                                f"[cyan]{escaped_line}[/cyan]",
                                expand=True,
                            )
                        elif line.startswith("diff --git"):
                            self.diff_log.write(
                                f"[yellow bold]{escaped_line}[/yellow bold]",
                                expand=True,
                            )
                        else:
                            self.diff_log.write(escaped_line, expand=True)
                else:
                    self.diff_log.write(
                        f"[dim]No changes in: {work_path}[/dim]",
                        expand=True,
                    )
                    self.diff_log.write(
                        f"[dim]Session: {session_id}[/dim]", expand=True
                    )
            else:
                self.diff_log.write(
                    f"[red]Git error: {escape(result.stderr)}[/red]", expand=True
                )

        except Exception as e:
            self.diff_log.write(f"[red]Error: {escape(str(e))}[/red]", expand=True)


class ModelMonitorTab(Container):
    """Tab for monitoring session and children monitor.md files"""

    def compose(self) -> ComposeResult:
        self.monitor_log = RichLog(
            highlight=True,
            markup=True,
            auto_scroll=False,
            wrap=True,
            min_width=0,  # Don't enforce minimum width
        )
        yield self.monitor_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.watcher = None
        self.set_interval(2.0, self.refresh_monitor)
        self.refresh_monitor()

    def refresh_monitor(self) -> None:
        """Read and display monitor.md files for current session and children"""
        app = self.app

        # Check if we have a current session
        if not app.current_session:
            self.monitor_log.clear()
            self.monitor_log.write("[dim]No session selected[/dim]", expand=True)
            self.watcher = None
            return

        # Create or update watcher with current session
        if self.watcher is None or self.watcher.session != app.current_session:
            self.watcher = SessionMonitorWatcher(session=app.current_session)

        monitors = self.watcher.get_monitor_files()
        self._update_display(monitors)

    def _update_display(self, monitors: Dict[str, Dict[str, Any]]) -> None:
        """Update the display with new monitor data"""
        self.monitor_log.clear()

        if not monitors:
            self.monitor_log.write(f"[dim]No monitor.md files found[/dim]", expand=True)
            return

        # Sort by last modified time (most recent first)
        sorted_monitors = sorted(
            monitors.items(), key=lambda x: x[1]["mtime"], reverse=True
        )

        for session_id, monitor_data in sorted_monitors:
            # Header for each session
            agent_icon = "👷" if monitor_data.get("agent_type") == "executor" else "🎨"
            self.monitor_log.write("", expand=True)
            self.monitor_log.write(
                f"[bold cyan]══════════════════════════════════════════════════[/bold cyan]",
                expand=True,
            )
            self.monitor_log.write(
                f"[bold yellow]{agent_icon} {session_id}[/bold yellow] [dim]({monitor_data.get('agent_type', 'unknown')})[/dim]",
                expand=True,
            )
            self.monitor_log.write(
                f"[dim]Last updated: {monitor_data['last_updated']}[/dim]",
                expand=True,
            )
            self.monitor_log.write(f"[dim]{monitor_data['path']}[/dim]", expand=True)
            self.monitor_log.write(
                f"[bold cyan]──────────────────────────────────────────────────[/bold cyan]",
                expand=True,
            )

            content = monitor_data["content"]
            if not content or content.strip() == "":
                self.monitor_log.write(
                    "[dim italic]Empty monitor file[/dim italic]",
                    expand=True,
                )
            else:
                # Display content with markdown-like formatting
                for line in content.split("\n"):
                    escaped_line = escape(line)
                    if line.startswith("# "):
                        self.monitor_log.write(
                            f"[bold cyan]{escaped_line}[/bold cyan]",
                            expand=True,
                        )
                    elif line.startswith("## "):
                        self.monitor_log.write(
                            f"[bold green]{escaped_line}[/bold green]",
                            expand=True,
                        )
                    elif line.startswith("### "):
                        self.monitor_log.write(
                            f"[green]{escaped_line}[/green]", expand=True
                        )
                    elif line.startswith("- "):
                        self.monitor_log.write(
                            f"[yellow]{escaped_line}[/yellow]",
                            expand=True,
                        )
                    elif "ERROR" in line or "WARNING" in line:
                        self.monitor_log.write(
                            f"[red]{escaped_line}[/red]", expand=True
                        )
                    elif "SUCCESS" in line or "OK" in line or "✓" in line:
                        self.monitor_log.write(
                            f"[green]{escaped_line}[/green]", expand=True
                        )
                    elif line.startswith("HOOK EVENT:"):
                        self.monitor_log.write(
                            f"[magenta]{escaped_line}[/magenta]",
                            expand=True,
                        )
                    elif (
                        line.startswith("time:")
                        or line.startswith("session_id:")
                        or line.startswith("tool:")
                    ):
                        self.monitor_log.write(
                            f"[blue]{escaped_line}[/blue]", expand=True
                        )
                    else:
                        self.monitor_log.write(escaped_line, expand=True)


START_MONITOR = True


def main():
    """Entry point for the unified UI"""
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance

    # Load config
    config = load_config()
    mcp_port = config.get("mcp_port", 8765)

    # Start the MCP server in the background
    mcp_log = Path.home() / ".kerberos" / "mcp-server.log"
    mcp_log.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting MCP server on port {mcp_port}")
    logger.info(f"MCP server logs: {mcp_log}")

    with open(mcp_log, "w") as log_file:
        mcp_proc = subprocess.Popen(
            ["cerb-mcp", str(mcp_port)],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    logger.info(f"MCP server started with PID {mcp_proc.pid}")

    # Start the monitoring server in the background
    if START_MONITOR:
        monitor_port = 8081
        monitor_log = Path.home() / ".kerberos" / "monitor-server.log"
        monitor_log.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting monitor server on port {monitor_port}")
        logger.info(f"Monitor server logs: {monitor_log}")

        with open(monitor_log, "w") as log_file:
            monitor_proc = subprocess.Popen(
                ["cerb-monitor-server", str(monitor_port)],
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        logger.info(f"Monitor server started with PID {monitor_proc.pid}")

    try:
        UnifiedApp().run()
    finally:
        # Clean up servers on exit
        logger.info("Shutting down MCP server")
        mcp_proc.terminate()
        try:
            mcp_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            mcp_proc.kill()

        if START_MONITOR:
            logger.info("Shutting down monitor server")
            monitor_proc.terminate()
            try:
                monitor_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                monitor_proc.kill()


if __name__ == "__main__":
    main()
