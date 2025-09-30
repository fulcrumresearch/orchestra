#!/usr/bin/env python3
"""Unified UI - Session picker and monitor combined"""
from __future__ import annotations
import argparse
import subprocess
import os
import shutil
from pathlib import Path
import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static, Label, TabbedContent, TabPane, RichLog, ListView, ListItem, Input, Tabs
from textual.containers import Container, VerticalScroll, Horizontal, Vertical
from textual.binding import Binding
from textual.reactive import reactive

from cerb_code.lib.sessions import Session, AgentType, load_sessions, save_sessions, SESSIONS_FILE
from cerb_code.lib.tmux_agent import TmuxProtocol
from cerb_code.lib.monitor import SessionMonitorWatcher
from cerb_code.lib.logger import get_logger

logger = get_logger(__name__)

class HUD(Static):
    can_focus = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_text = "⌃N new • ⌃D delete • ⌃R refresh • ⌃S switch • ⌃Q quit"
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
        height: 5;
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

    #session-input {
        margin: 0 1;
        background: #1a1a1a;
        border: solid #333333;
        color: #ffffff;
        height: 3;
    }

    #session-input:focus {
        border: solid #00ff9f;
    }

    #session-input.--placeholder {
        color: #666666;
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
    }

    #sidebar-title {
        color: #00ff9f;
        text-style: bold;
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
    }

    VerticalScroll {
        width: 100%;
    }
"""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New Session", priority=True, show=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+d", "delete_session", "Delete", priority=True),
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
        # Create a shared TmuxProtocol for all sessions
        self.agent = TmuxProtocol(default_command="claude")
        self._last_session_mtime = None
        self._watch_task = None
        logger.info("KerberosApp initialized")

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return

        # Global header with HUD and input
        with Container(id="header"):
            self.hud = HUD("⌃N new • ⌃D delete • ⌃R refresh • ⌃Q quit", id="hud")
            yield self.hud
            self.session_input = Input(
                placeholder="New session name...",
                id="session-input"
            )
            yield self.session_input

        # Main content area - split horizontally
        with Horizontal(id="main-content"):
            # Left pane - session list
            with Container(id="left-pane"):
                yield Static("● SESSIONS", id="sidebar-title")
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
        # Load existing sessions with the shared agent protocol
        self.sessions = load_sessions(protocol=self.agent)
        await self.action_refresh()

        # Auto-load 'main' session if it exists
        for session in self.sessions:
            if session.session_id == "main":
                self._attach_to_session(session)
                break

        # Focus the session list by default
        self.set_focus(self.session_list)

        # Start watching sessions file for changes
        self._watch_task = asyncio.create_task(self._watch_sessions_file())

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
            self.session_list.append(ListItem(Label("No sessions yet")))
            self.session_list.append(ListItem(Label("Press ⌃N to create")))
            return

        # Add sessions to list with hierarchy
        def add_session_tree(session, indent=0):
            # Update status for this session
            status = self.agent.get_status(session.session_id)
            session.active = status.get("attached", False)

            # Keep track in flat list for selection
            self.flat_sessions.append(session)

            # Display with indentation
            prefix = "  " * indent
            item = ListItem(Label(f"{prefix}{session.display_name}"))
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

    def action_new_session(self) -> None:
        """Toggle focus on the session input"""
        logger.info("action_new_session called - toggling input focus")
        if self.focused == self.session_input:
            # If already focused, return focus to session list
            self.session_list.focus()
        else:
            # Focus and clear the input
            self.session_input.focus()
            self.session_input.clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle when user presses Enter in the input field"""
        # Debug: Show that we received the event
        self.hud.update(f"Creating session...")
        if event.input.id == "session-input":
            session_name = event.value.strip()

            if not session_name:
                # Generate default name with cerb-reponame format
                repo_name = self._get_repo_name()
                session_num = 1
                existing_ids = {s.session_id for s in self.sessions}
                while f"cerb-{repo_name}-{session_num}" in existing_ids:
                    session_num += 1
                session_name = f"cerb-{repo_name}-{session_num}"

            # Add visual feedback
            self.session_input.placeholder = f"Creating {session_name}..."
            self.session_input.disabled = True

            self.create_session(session_name)

            # Clear the input and unfocus it
            self.session_input.clear()
            self.session_input.placeholder = "New session name..."
            self.session_input.disabled = False
            # Focus back on the session list
            self.set_focus(self.session_list)

    def create_session(self, session_name: str) -> None:
        """Actually create the session with the given name"""
        logger.info(f"Creating new session: {session_name}")

        try:
            # Check if session name already exists
            if any(s.session_id == session_name for s in self.sessions):
                logger.warning(f"Session {session_name} already exists")
                return

            # Create Session object with the protocol
            new_session = Session(
                session_id=session_name,
                agent_type=AgentType.DESIGNER,
                protocol=self.agent,
                source_path=str(Path.cwd()),
                active=False
            )

            # Prepare the worktree for this session
            logger.info(f"Preparing worktree for session {session_name}")
            new_session.prepare()
            logger.info(f"Worktree prepared at: {new_session.work_path}")

            # Start the session (it will use its protocol internally)
            logger.info(f"Starting session {session_name}")
            result = new_session.start()
            logger.info(f"Session start result: {result}")

            if result:
                # Add to sessions list
                self.sessions.append(new_session)
                save_sessions(self.sessions)
                logger.info(f"Session {session_name} saved")

                # Refresh the session list immediately
                self.run_worker(self.action_refresh())

                # Attach to the new session (this also updates HUD and current_session)
                self._attach_to_session(new_session)

                logger.info(f"Successfully created and attached to {session_name}")
            else:
                logger.error(f"Failed to start session {session_name}")
                self.hud.update(f"ERROR: Failed to start {session_name}")
        except Exception as e:
            logger.exception(f"Error in create_session: {e}")
            self.hud.update(f"ERROR: {str(e)[:50]}")

    def action_cursor_up(self) -> None:
        """Move cursor up in the list"""
        self.session_list.action_up()

    def action_cursor_down(self) -> None:
        """Move cursor down in the list"""
        self.session_list.action_down()

    def action_scroll_tab_up(self) -> None:
        """Scroll up in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            # Find and scroll the RichLog widget directly
            for widget in active_pane.query(RichLog):
                widget.scroll_relative(y=-1)

    def action_scroll_tab_down(self) -> None:
        """Scroll down in the active monitor/diff tab"""
        tabs = self.query_one(TabbedContent)
        active_pane = tabs.get_pane(tabs.active)
        if active_pane:
            # Find and scroll the RichLog widget directly
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

    def action_select_session(self) -> None:
        """Select the highlighted session"""
        index = self.session_list.index
        if index is not None and 0 <= index < len(self.flat_sessions):
            session = self.flat_sessions[index]
            self._attach_to_session(session)

    def action_delete_session(self) -> None:
        """Delete the currently selected session"""
        # Get the currently highlighted session from the list instead of current_session
        index = self.session_list.index
        if index is None or index >= len(self.flat_sessions):
            return

        session_to_delete = self.flat_sessions[index]

        # Kill the tmux session
        subprocess.run(["tmux", "kill-session", "-t", session_to_delete.session_id],
                      capture_output=True, text=True)

        # Remove from sessions list
        self.sessions = [s for s in self.sessions if s.session_id != session_to_delete.session_id]
        save_sessions(self.sessions)

        # If we deleted the current session, handle the right pane
        if self.current_session and self.current_session.session_id == session_to_delete.session_id:
            self.current_session = None

            if self.sessions:
                # Try to select the session at the same index, or the previous one if we deleted the last
                new_index = min(index, len(self.sessions) - 1)
                if new_index >= 0:
                    # Move the list highlight to the new index
                    self.session_list.index = new_index
                    # Attach to the new session
                    self._attach_to_session(self.sessions[new_index])
            else:
                # No sessions left, show empty state
                self.hud.set_session("")
                # Clear the right pane with a message
                right_pane = "{right}"
                msg_cmd = "echo 'No active sessions. Press Ctrl+N to create a new session.'"
                subprocess.run(["tmux", "respawn-pane", "-t", right_pane, "-k", msg_cmd],
                              capture_output=True, text=True)
                # Also clear the monitor pane
                subprocess.run(["tmux", "respawn-pane", "-t", "2", "-k", "echo 'No session to monitor'"],
                              capture_output=True, text=True)

        # Keep focus on the session list
        self.set_focus(self.session_list)

        # Refresh the list
        self.call_later(self.action_refresh)

    def _attach_to_session(self, session: Session) -> None:
        """Select a session and update monitors to show it"""
        # Mark all sessions as inactive, then mark this one as active
        for s in self.sessions:
            s.active = False
        session.active = True

        # Check session status using the protocol
        status = self.agent.get_status(session.session_id)

        if not status.get("exists", False):
            # Session doesn't exist, try to start it
            logger.info(f"Session {session.session_id} doesn't exist, creating it")
            if not session.work_path:
                # Only prepare if work_path not set (i.e., not already prepared)
                session.prepare()
            if not session.start():
                logger.error(f"Failed to start session {session.session_id}")
                return

        # Use tmux's respawn-pane to attach to the session in pane 1
        cmd = f"TMUX= tmux attach-session -t {session.session_id}"
        subprocess.run(["tmux", "respawn-pane", "-t", "1", "-k", cmd],
                      capture_output=True, text=True)

        # Don't auto-focus pane 1 - let user stay in the UI

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
                    if self._last_session_mtime is not None and current_mtime != self._last_session_mtime:
                        logger.info("Sessions file changed, refreshing...")
                        # Reload sessions from disk
                        self.sessions = load_sessions(protocol=self.agent)
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
        if event.index is not None and 0 <= event.index < len(self.flat_sessions):
            session = self.flat_sessions[event.index]
            self._attach_to_session(session)

class DiffTab(VerticalScroll):
    """Scrollable container for diff display"""

    def compose(self) -> ComposeResult:
        self.diff_log = RichLog(highlight=True, markup=True, auto_scroll=False, wrap=True)
        yield self.diff_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.set_interval(2.0, self.refresh_diff)
        self.refresh_diff()

    def refresh_diff(self) -> None:
        """Fetch and display the latest diff"""
        app = self.app
        if not hasattr(app, 'current_session') or not app.current_session:
            self.diff_log.clear()
            self.diff_log.write("[dim]No session selected[/dim]")
            return

        work_path = app.current_session.work_path
        session_id = app.current_session.session_id

        if not work_path:
            self.diff_log.write("[dim]Session has no work path[/dim]")
            return

        try:
            # Get git diff
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=work_path,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Clear previous content
                self.diff_log.clear()

                if result.stdout:
                    # Write diff line by line for better scrolling
                    for line in result.stdout.split('\n'):
                        if line.startswith('+'):
                            self.diff_log.write(f"[green]{line}[/green]")
                        elif line.startswith('-'):
                            self.diff_log.write(f"[red]{line}[/red]")
                        elif line.startswith('@@'):
                            self.diff_log.write(f"[cyan]{line}[/cyan]")
                        elif line.startswith('diff --git'):
                            self.diff_log.write(f"[yellow bold]{line}[/yellow bold]")
                        else:
                            self.diff_log.write(line)
                else:
                    self.diff_log.write(f"[dim]No changes in: {work_path}[/dim]")
                    self.diff_log.write(f"[dim]Session: {session_id}[/dim]")
            else:
                self.diff_log.write(f"[red]Git error: {result.stderr}[/red]")

        except Exception as e:
            self.diff_log.write(f"[red]Error: {str(e)}[/red]")

class ModelMonitorTab(VerticalScroll):
    """Tab for monitoring session and children monitor.md files"""

    def compose(self) -> ComposeResult:
        self.monitor_log = RichLog(highlight=True, markup=True, auto_scroll=False, wrap=True)
        yield self.monitor_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.watcher = None
        self._last_monitors = {}
        self.set_interval(2.0, self.refresh_monitor)
        self.refresh_monitor()

    def refresh_monitor(self) -> None:
        """Read and display monitor.md files for current session and children"""
        app = self.app

        # Check if we have a current session
        if not app.current_session:
            self.monitor_log.clear()
            self.monitor_log.write("[dim]No session selected[/dim]")
            self.watcher = None
            self._last_monitors = {}
            return

        # Create or update watcher with current session
        if self.watcher is None or self.watcher.session != app.current_session:
            self.watcher = SessionMonitorWatcher(session=app.current_session)
            self._last_monitors = {}

        monitors = self.watcher.get_monitor_files()

        # Only update display if monitors have changed
        if monitors != self._last_monitors:
            self._update_display(monitors)
            self._last_monitors = monitors

    def _update_display(self, monitors: Dict[str, Dict[str, Any]]) -> None:
        """Update the display with new monitor data"""
        self.monitor_log.clear()

        if not monitors:
            self.monitor_log.write(f"[dim]No monitor.md files found[/dim]")
            return

        # Sort by last modified time (most recent first)
        sorted_monitors = sorted(monitors.items(), key=lambda x: x[1]['mtime'], reverse=True)

        for session_id, monitor_data in sorted_monitors:
            # Header for each session
            agent_icon = "👷" if monitor_data.get('agent_type') == 'executor' else "🎨"
            self.monitor_log.write("")
            self.monitor_log.write(f"[bold cyan]══════════════════════════════════════════════════[/bold cyan]")
            self.monitor_log.write(f"[bold yellow]{agent_icon} {session_id}[/bold yellow] [dim]({monitor_data.get('agent_type', 'unknown')})[/dim]")
            self.monitor_log.write(f"[dim]Last updated: {monitor_data['last_updated']}[/dim]")
            self.monitor_log.write(f"[dim]{monitor_data['path']}[/dim]")
            self.monitor_log.write(f"[bold cyan]──────────────────────────────────────────────────[/bold cyan]")

            content = monitor_data['content']
            if not content or content.strip() == "":
                self.monitor_log.write("[dim italic]Empty monitor file[/dim italic]")
            else:
                # Display content with markdown-like formatting
                for line in content.split('\n'):
                    if line.startswith('# '):
                        self.monitor_log.write(f"[bold cyan]{line}[/bold cyan]")
                    elif line.startswith('## '):
                        self.monitor_log.write(f"[bold green]{line}[/bold green]")
                    elif line.startswith('### '):
                        self.monitor_log.write(f"[green]{line}[/green]")
                    elif line.startswith('- '):
                        self.monitor_log.write(f"[yellow]{line}[/yellow]")
                    elif 'ERROR' in line or 'WARNING' in line:
                        self.monitor_log.write(f"[red]{line}[/red]")
                    elif 'SUCCESS' in line or 'OK' in line or '✓' in line:
                        self.monitor_log.write(f"[green]{line}[/green]")
                    elif line.startswith('HOOK EVENT:'):
                        self.monitor_log.write(f"[magenta]{line}[/magenta]")
                    elif line.startswith('time:') or line.startswith('session_id:') or line.startswith('tool:'):
                        self.monitor_log.write(f"[blue]{line}[/blue]")
                    else:
                        self.monitor_log.write(line)


def main():
    """Entry point for the unified UI"""
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance

    # Start the monitoring server in the background
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
            start_new_session=True
        )
    logger.info(f"Monitor server started with PID {monitor_proc.pid}")

    try:
        UnifiedApp().run()
    finally:
        # Clean up monitor server on exit
        logger.info("Shutting down monitor server")
        monitor_proc.terminate()
        try:
            monitor_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            monitor_proc.kill()


if __name__ == "__main__":
    main()
