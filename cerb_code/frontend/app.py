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
from cerb_code.lib.logger import get_logger
from cerb_code.lib.config import load_config
from cerb_code.lib.helpers import (
    check_dependencies,
    get_current_branch,
    respawn_pane,
    respawn_pane_with_vim,
    respawn_pane_with_terminal,
    ensure_docker_image,
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
        Binding("enter", "select_session", "Select", show=False),
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
        project_dir = Path.cwd().resolve()
        self.state = AppState(project_dir)


    def compose(self) -> ComposeResult:
        # Check dependencies based on config
        config = load_config()
        require_docker = config.get("use_docker", True)
        success, missing = check_dependencies(require_docker=require_docker)

        if not success:
            error_msg = "Missing dependencies:\n" + "\n".join(f"  • {dep}" for dep in missing)
            yield Static(error_msg, id="error")
            return

        with Container(id="header"):
            self.hud = HUD(
                "⌃D delete • ⌃R refresh • P pair • S spec • T terminal • ⌃Q quit",
                id="hud",
            )
            yield self.hud

        with Horizontal(id="main-content"):
            with Container(id="left-pane"):
                yield Static("Orchestra", id="sidebar-title")
                self.status_indicator = Static("", id="status-indicator")
                yield self.status_indicator
                self.session_list = ListView(id="session-list")
                yield self.session_list

            with Container(id="right-pane"):
                with TabbedContent(initial="diff-tab"):
                    with TabPane("Diff", id="diff-tab"):
                        yield DiffTab()
                    with TabPane("Monitor", id="monitor-tab"):
                        yield ModelMonitorTab()

    async def on_ready(self) -> None:
        """Load sessions and refresh list"""
        # Build docker image in background if needed
        config = load_config()
        if config.get("use_docker", True):
            asyncio.create_task(asyncio.to_thread(ensure_docker_image))

        # Detect current git branch and store as fixed root
        branch_name = get_current_branch()
        self.state.root_session_id = branch_name
        self.state.load(root_session_id=self.state.root_session_id)

        if not self.state.root_session:
            try:
                self.status_indicator.update("⏳ Creating session...")

                logger.info(f"Creating designer session for branch: {branch_name}")

                new_session = Session(
                    session_id=branch_name,
                    agent_type=AgentType.DESIGNER,
                    source_path=str(Path.cwd()),
                )
                new_session.prepare()
                if new_session.start():
                    self.state.root_session = new_session
                    save_session(new_session, self.state.project_dir)
                    logger.info(f"Created designer session: {branch_name}")
                else:
                    logger.error(f"Failed to start designer session: {branch_name}")

                self.status_indicator.update("")
            except Exception as e:
                logger.exception(f"Error creating designer session: {e}")
                self.status_indicator.update("")

        await self.action_refresh()

        if self.state.root_session:
            self._attach_to_session(self.state.root_session)

        self.set_focus(self.session_list)

        # Watch sessions.json for changes
        async def on_sessions_file_change(path, change_type):
            self.state.load(root_session_id=self.state.root_session_id)
            await self.action_refresh()

        self.state.file_watcher.register(SESSIONS_FILE, on_sessions_file_change)
        await self.state.file_watcher.start()

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        index = self.session_list.index if self.session_list.index is not None else 0
        current_session = self.state.get_session_by_index(index)
        selected_id = current_session.session_id if current_session else None

        self.session_list.clear()

        root = self.state.root_session
        if not root:
            return

        paired_marker = "[bold magenta]◆[/bold magenta] " if self.state.paired_session_id == root.session_id else ""
        label_text = f"{paired_marker}{root.session_id} [dim][#00ff9f](designer)[/#00ff9f][/dim]"
        self.session_list.append(ListItem(Label(label_text, markup=True)))

        for child in root.children:
            paired_marker = "[bold magenta]◆[/bold magenta] " if self.state.paired_session_id == child.session_id else ""
            label_text = f"{paired_marker}  {child.session_id} [dim][#00d4ff](executor)[/#00d4ff][/dim]"
            self.session_list.append(ListItem(Label(label_text, markup=True)))

        if selected_id:
            new_index = self.state.get_index_by_session_id(selected_id)
            self.session_list.index = new_index if new_index is not None else 0

    def action_cursor_up(self) -> None:
        """Move cursor up in the list"""
        self.session_list.action_cursor_up()

    def action_cursor_down(self) -> None:
        """Move cursor down in the list"""
        self.session_list.action_cursor_down()

    def action_select_session(self) -> None:
        """Select and attach to the currently highlighted session"""
        session = self.state.get_session_by_index(self.session_list.index)
        if session:
            self._attach_to_session(session)

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
        await asyncio.to_thread(session_to_delete.delete)
        self.state.remove_child(session_to_delete.session_id)
        save_session(self.state.root_session, self.state.project_dir)
        await self.action_refresh()
        self.status_indicator.update("")

    def action_delete_session(self) -> None:
        """Delete the currently selected session"""
        index = self.session_list.index
        if index is None:
            return

        session_to_delete = self.state.get_session_by_index(index)
        if not session_to_delete:
            return

        if session_to_delete == self.state.root_session:
            self.status_indicator.update("Cannot delete designer session")
            return

        if self.state.active_session_id == session_to_delete.session_id:
            self._attach_to_session(self.state.root_session)

        self.status_indicator.update("⏳ Deleting session...")
        asyncio.create_task(self._delete_session_task(session_to_delete))

    async def _toggle_pairing_task(self, session: Session, is_paired: bool) -> None:
        """Background task for toggling pairing"""
        session.paired = is_paired
        success, error_msg = await asyncio.to_thread(session.toggle_pairing)

        if not success:
            self.hud.set_session(f"Error: {error_msg}")
            logger.error(f"Failed to toggle pairing: {error_msg}")
            self.status_indicator.update("")
            return

        if is_paired:
            self.state.paired_session_id = None
            paired_indicator = ""
        else:
            self.state.paired_session_id = session.session_id
            paired_indicator = "[P] "

        self.hud.set_session(f"{paired_indicator}{session.session_id}")
        await self.action_refresh()
        self.status_indicator.update("")

    def action_toggle_pairing(self) -> None:
        """Toggle pairing mode for the currently selected session"""
        index = self.session_list.index
        if index is None:
            return

        session = self.state.get_session_by_index(index)
        if not session:
            return

        is_paired = self.state.paired_session_id == session.session_id
        pairing_mode = "paired" if not is_paired else "unpaired"
        self.status_indicator.update(f"⏳ Switching to {pairing_mode}...")
        self.hud.set_session(f"Switching to {pairing_mode} mode...")

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

        if not designer_md.exists():
            designer_md.touch()

        self.state.file_watcher.add_designer_watcher(designer_md, session)

        if not respawn_pane_with_vim(designer_md):
            logger.error(f"Failed to open spec: {designer_md}")

    def action_open_terminal(self) -> None:
        """Open bash terminal in the highlighted session's worktree in pane 1"""
        index = self.session_list.index
        if index is None:
            return

        session = self.state.get_session_by_index(index)
        if not session:
            return
        work_path = Path(session.work_path)

        if not respawn_pane_with_terminal(work_path):
            logger.error(f"Failed to open terminal: {work_path}")

    def _attach_to_session(self, session: Session) -> None:
        """Select a session and update monitors to show it"""
        self.state.set_active_session(session.session_id)
        status = session.get_status()

        if not status.get("exists", False):
            if not session.start():
                logger.error(f"Failed to start session: {session.session_id}")
                error_cmd = (
                    f"bash -c 'echo \"Failed to start session {session.session_id}\"; exec bash'"
                )
                respawn_pane(PANE_AGENT, error_cmd)
                return

        session.protocol.attach(session.session_id, target_pane=PANE_AGENT)
        self.hud.set_session(session.session_id)

        monitor_tab = self.query_one(ModelMonitorTab)
        monitor_tab.refresh_monitor()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list when clicked"""
        self.action_select_session()