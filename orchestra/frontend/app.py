#!/usr/bin/env python3
"""Unified UI - Session picker and monitor combined (refactored)"""

from __future__ import annotations

import asyncio
from pathlib import Path

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
from orchestra.frontend.widgets.hud import HUD
from orchestra.frontend.widgets.diff_tab import DiffTab
from orchestra.frontend.widgets.messages_tab import MessagesTab
from orchestra.frontend.state import AppState
from orchestra.lib.message import load_messages

# Import from lib
from orchestra.lib.sessions import (
    Session,
    AgentType,
    save_session,
)
from orchestra.lib.logger import get_logger
from orchestra.lib.config import load_config
from orchestra.lib.helpers.process import check_dependencies
from orchestra.lib.helpers.git import get_current_branch
from orchestra.lib.helpers.tmux import (
    respawn_pane,
    respawn_pane_with_vim,
    respawn_pane_with_terminal,
    PANE_AGENT,
)
from orchestra.lib.helpers.docker import ensure_docker_image
from orchestra.lib.helpers.file_ops import (
    ensure_orchestra_directory,
    is_first_run,
    SESSIONS_FILE,
)

logger = get_logger(__name__)


class UnifiedApp(App):
    """Unified app combining session picker and monitor"""

    CSS = """
    Screen {
        background: $background;
    }

    #header {
        height: 1;
        background: $panel;
        dock: top;
        padding: 0 1;
    }



    #hud {
        height: 1;
        padding: 0;
        color: $primary;
        text-align: center;
        width: 100%;
    }

    #main-content {
        height: 1fr;
    }

    #left-pane {
        width: 30%;
        background: $background;
        padding: 1;
    }

    #right-pane {
        width: 1fr;
        background: $background;
        padding: 1;
    }

    /* Card-like containers, inspired by Posting */
    #session-card {
        border: round $panel;
        background: $background;
        height: 1fr;
        width: 1fr;
        padding: 0;
    }

    #diff-card {
        border: round $panel;
        background: $background;
        height: 1fr;
        width: 1fr;
        padding: 0;
    }

    TabbedContent {
        height: 1fr;
        padding: 0;
    }

    Tabs {
        background: transparent;
        width: 100%;
        padding: 0;
    }

    Tab {
        padding: 0 1;
        margin: 0;
    }

    Tab.-active {
        text-style: bold;
    }

    Tab.-active:focus-within {
        background: $primary 25%;
    }

    TabPane {
        padding: 1;
        background: $background;
        layout: vertical;
    }

    #sidebar-title {
        color: $success;
        text-style: bold;
        margin-bottom: 0;
        height: 1;
        width: 100%;
        padding: 0 1;
    }

    #branch-info {
        color: $foreground;
        text-style: italic;
        margin-bottom: 0;
        height: 1;
        width: 100%;
        padding: 0 1;
    }

    #status-indicator {
        color: $warning;
        text-style: italic;
        margin-bottom: 1;
        height: 1;
        width: 100%;
        padding: 0 1;
    }

    #sessions-header {
        color: $secondary;
        text-style: bold;
        margin-bottom: 1;
        height: 1;
        width: 100%;
        padding: 0 1;
    }

    ListView {
        height: 1fr;
        width: 1fr;
        padding: 0;
        margin: 0;
        border: none;
    }

    ListView > .list-view--container {
        padding: 0;
        margin: 0;
    }

    ListItem {
        color: $foreground;
        background: $background;
        width: 100%;
        padding: 0;
        margin: 0;
        layout: horizontal;
        height: 1;
    }

    ListItem Label {
        width: 1fr;
        padding: 0 1;
        height: 1;              /* one line tall */
        text-wrap: nowrap;      /* no wrapping */
        overflow: hidden;       /* truncate visually */
    }

    /* Left-side rectangular indicator bar for highlighted item */
    ListItem .indicator { width: 1; height: 1; background: transparent; }

    /* Subtle purple background for highlighted item (both focused and unfocused) */
    ListItem.-highlight {
        background: $primary 25%;
    }

    ListItem.-highlight Label {
        color: $text;
        text-style: bold;
    }

    RichLog {
        background: $background;
        color: $foreground;
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
        Binding("m", "open_docs", "Open Docs", priority=True),
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

    def __init__(self, shutdown_callback=None):
        super().__init__()
        project_dir = Path.cwd().resolve()
        self.state = AppState(project_dir)
        self.shutdown_callback = shutdown_callback

        # Load theme from config
        config = load_config()
        self.theme = config.get("ui_theme", "textual-light")

    def compose(self) -> ComposeResult:
        # Check dependencies based on config
        config = load_config()
        require_docker = config.get("use_docker", True)
        success, missing = check_dependencies(require_docker=require_docker)

        if not success:
            print("\n❌ Missing dependencies:")
            for dep in missing:
                print(f"  • {dep}")
            print()

        with Container(id="header"):
            self.hud = HUD(id="hud")
            yield self.hud

        with Horizontal(id="main-content"):
            with Container(id="left-pane"):
                yield Static("Orchestra", id="sidebar-title")
                self.status_indicator = Static("", id="status-indicator")
                yield self.status_indicator
                with Container(id="session-card"):
                    yield Static("Sessions", id="sessions-header")
                    self.session_list = ListView(id="session-list")
                    yield self.session_list

            with Container(id="right-pane"):
                with Container(id="diff-card"):
                    with TabbedContent(initial="diff-tab"):
                        with TabPane("Diff", id="diff-tab"):
                            yield DiffTab()
                        with TabPane("Messages", id="messages-tab"):
                            self.messages_tab = MessagesTab()
                            yield self.messages_tab

    async def on_ready(self) -> None:
        """Load sessions and refresh list"""
        # Build docker image in background if needed
        config = load_config()
        if config.get("use_docker", True):
            asyncio.create_task(asyncio.to_thread(ensure_docker_image))

        # Check if this is the first run BEFORE creating any sessions
        first_run = is_first_run(self.state.project_dir)

        # Detect current git branch and store as fixed root
        branch_name = get_current_branch()
        self.state.root_session_name = branch_name
        self.state.load(root_session_name=self.state.root_session_name)

        if not self.state.root_session:
            try:
                self.status_indicator.update("⏳ Creating session...")

                logger.info(f"Creating designer session for branch: {branch_name}")

                new_session = Session(
                    session_name=branch_name,
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
            # Regenerate instructions to ensure session context is current
            self.state.root_session.add_instructions()
            self._attach_to_session(self.state.root_session)

        self.set_focus(self.session_list)

        async def on_sessions_file_change(path, last_call_time):
            self.state.load(root_session_name=self.state.root_session_name)
            await self.action_refresh()

        self.state.file_watcher.register(SESSIONS_FILE, on_sessions_file_change)

        messages_file = Path.cwd() / ".orchestra" / "messages.jsonl"

        def messages_filter(path: Path) -> bool:
            """Only notify if message is for root session (designer)"""

            all_messages = load_messages(Path.cwd())
            if not all_messages:
                return False
            latest_msg = all_messages[-1]
            return latest_msg.recipient == self.state.root_session.session_name

        self.state.file_watcher.add_session_change_notifier(messages_file, self.state.root_session, messages_filter)

        designer_md, doc_md = ensure_orchestra_directory(self.state.project_dir)

        if self.state.root_session:
            self.state.file_watcher.add_session_change_notifier(designer_md, self.state.root_session)

        await self.state.file_watcher.start()

        # Auto-open doc.md on first run, otherwise open designer.md
        if first_run:
            respawn_pane_with_vim(doc_md)
        else:
            respawn_pane_with_vim(designer_md)

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        index = self.session_list.index if self.session_list.index is not None else 0
        current_session = self.state.get_session_by_index(index)
        selected_name = current_session.session_name if current_session else None

        self.session_list.clear()

        root = self.state.root_session
        if not root:
            return

        paired_marker = "[bold magenta]◆[/bold magenta] " if self.state.paired_session_name == root.session_name else ""
        label_text = f"{paired_marker}{root.session_name} (designer)"
        self.session_list.append(
            ListItem(
                Horizontal(
                    Static("", classes="indicator"),
                    Label(label_text, markup=True),
                )
            )
        )

        for child in root.children:
            paired_marker = "[bold magenta]◆[/bold magenta] " if self.state.paired_session_name == child.session_name else ""
            label_text = f"{paired_marker}  {child.session_name} (executor)"
            self.session_list.append(
                ListItem(
                    Horizontal(
                        Static("", classes="indicator"),
                        Label(label_text, markup=True),
                    )
                )
            )

        if selected_name:
            new_index = self.state.get_index_by_session_name(selected_name)
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
        self.state.remove_child(session_to_delete.session_name)
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

        if self.state.active_session_name == session_to_delete.session_name:
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
            self.state.paired_session_name = None
            paired_indicator = ""
        else:
            self.state.paired_session_name = session.session_name
            paired_indicator = "[P] "

        self.hud.set_session(f"{paired_indicator}{session.session_name}")
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

        is_paired = self.state.paired_session_name == session.session_name
        pairing_mode = "paired" if not is_paired else "unpaired"
        self.status_indicator.update(f"⏳ Switching to {pairing_mode}...")
        self.hud.set_session(f"Switching to {pairing_mode} mode...")

        asyncio.create_task(self._toggle_pairing_task(session, is_paired))

    def action_open_spec(self) -> None:
        """Open designer.md in vim in a split tmux pane"""
        designer_md, _ = ensure_orchestra_directory(self.state.project_dir)

        if not respawn_pane_with_vim(designer_md):
            self.status_indicator.update("❌ No editor found. Install nano, vim, or VS Code")
            logger.error(f"Failed to open spec: {designer_md}")

    def action_open_docs(self) -> None:
        """Open doc.md in vim in a split tmux pane"""
        _, doc_md = ensure_orchestra_directory(self.state.project_dir)

        if not respawn_pane_with_vim(doc_md):
            self.status_indicator.update("❌ No editor found. Install nano, vim, or VS Code")
            logger.error(f"Failed to open docs: {doc_md}")

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
        self.state.set_active_session(session.session_name)
        self.messages_tab.refresh_messages()
        status = session.get_status()

        if not status.get("exists", False):
            if not session.start():
                logger.error(f"Failed to start session: {session.session_id}")
                error_cmd = f"$SHELL -c 'echo \"Failed to start session {session.session_id}\"; exec $SHELL'"
                respawn_pane(PANE_AGENT, error_cmd)
                return

        session.protocol.attach(session, target_pane=PANE_AGENT)
        self.hud.set_session(session.session_name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list when clicked"""
        self.action_select_session()

    def action_quit(self) -> None:
        """Override quit to show shutdown message and run cleanup"""
        self.status_indicator.update("⏳ Quitting...")
        logger.info("Shutting down Orchestra...")

        # Unpair synchronously if needed
        paired_session = self.state.get_paired_session()
        if paired_session:
            logger.info(f"Unpairing {paired_session.session_name} before shutdown...")
            success, error_msg = paired_session.toggle_pairing()
            if not success:
                logger.error(f"Failed to unpair: {error_msg}")
            else:
                self.state.set_paired_session(None)

        asyncio.create_task(self._shutdown_task())

    async def _shutdown_task(self) -> None:
        """Perform shutdown cleanup before exiting"""
        if self.shutdown_callback:
            await asyncio.to_thread(self.shutdown_callback)
        self.exit()
