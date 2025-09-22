from __future__ import annotations
import os, shutil
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static, ListView, ListItem, Label, Button, Input
from textual_terminal import Terminal

from lib.sessions import Session, AgentType, load_sessions, save_sessions
from lib.tmux_agent import TmuxAgent
from lib.logger import get_logger

logger = get_logger(__name__)

SIDEBAR_WIDTH = 30  # columns


class HUD(Static):
    can_focus = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_text = "⌃N new session • ⌃B sessions • ⌃L terminal • ⌃Q quit"
        self.current_session = ""

    def set_session(self, session_name: str):
        """Update the current session display"""
        self.current_session = session_name
        self.update(f"[{session_name}] • {self.default_text}")


class KerberosApp(App):
    CSS = f"""
    Screen {{
        background: #0a0a0a;
    }}

    #container {{
        layout: horizontal;
        height: 100%;
    }}

    #sidebar {{
        width: {SIDEBAR_WIDTH};
        background: #111111;
        border-right: solid #333333;
        padding: 1 2;
    }}

    #sidebar:focus-within {{
        border-right: thick #00ff9f;
    }}

    #sidebar-title {{
        color: #00ff9f;
        text-style: bold;
        margin-bottom: 1;
    }}

    ListView {{
        background: transparent;
        height: auto;
    }}

    ListItem {{
        color: #cccccc;
        background: transparent;
        padding: 0 1;
    }}

    ListItem:hover {{
        background: #222222;
        color: #ffffff;
    }}

    ListView > ListItem.--highlight {{
        background: #1a1a1a;
        color: #00ff9f;
        text-style: bold;
        border-left: thick #00ff9f;
    }}

    #session-input {{
        margin-top: 1;
        background: #1a1a1a;
        border: solid #333333;
        color: #ffffff;
    }}

    #session-input:focus {{
        border: solid #00ff9f;
    }}

    #session-input.--placeholder {{
        color: #666666;
    }}

    #main {{
        layout: vertical;
        width: 100%;
    }}

    #hud {{
        height: 2;
        padding: 0 1;
        background: #111111;
        color: #999999;
        text-align: center;
        border-bottom: solid #333333;
    }}

    #term {{
        height: 1fr;
        overflow: auto;
    }}

    #term:focus {{
        border: solid #00ff9f;
    }}

    Terminal {{
        overflow: auto;
        width: 100%;
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New Session", priority=True, show=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+b", "focus_sidebar", "Sessions", priority=True),
        Binding("ctrl+l", "focus_terminal", "Terminal", priority=True),
        Binding("ctrl+shift+c", "copy_to_clipboard", "Copy", priority=False),
        Binding("ctrl+shift+v", "paste_from_clipboard", "Paste", priority=False),
    ]

    def __init__(self):
        super().__init__()
        logger.info("KerberosApp initializing")
        self.sessions: list[Session] = []
        self.current_session: Session | None = None
        # Create a shared TmuxAgent for all sessions
        self.agent = TmuxAgent(default_command="claude")
        logger.info("KerberosApp initialized")

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return

        with Container(id="container"):
            with Container(id="sidebar"):
                yield Static("● SESSIONS", id="sidebar-title")
                self.session_list = ListView(id="session-list")
                yield self.session_list
                self.session_input = Input(
                    placeholder="New session name...",
                    id="session-input"
                )
                yield self.session_input

            with Container(id="main"):
                self.hud = HUD("⌃N new session • ⌃B sessions • ⌃L terminal • ⌃Q quit", id="hud")
                # Start with empty terminal - will create session if needed
                self.term = Terminal(
                    command="/usr/bin/env bash -lc 'echo \"Press Ctrl+N to create a new Claude session\"'",
                    id="term"
                )
                yield self.hud
                yield self.term

    async def on_ready(self) -> None:
        """Start the terminal and refresh session list"""
        if hasattr(self, "term"):
            self.term.start()

        # Load existing sessions with the shared agent protocol
        self.sessions = load_sessions(protocol=self.agent)
        await self.action_refresh()

        # If no sessions exist, create the first one automatically
        if not self.sessions:
            self.action_new_session()  # No await - it's not async anymore
        else:
            # Focus the session list by default
            self.set_focus(self.session_list)

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        self.session_list.clear()

        if not self.sessions:
            self.session_list.append(ListItem(Label("No sessions yet")))
            self.session_list.append(ListItem(Label("Press ⌃N to create")))
            return

        # Update active status based on tmux state
        for session in self.sessions:
            status = self.agent.get_status(session.session_id)
            session.active = status.get("attached", False)

        # Add sessions to list
        for session in self.sessions:
            item = ListItem(Label(session.display_name))
            item.data = session
            self.session_list.append(item)

        # Save updated session states
        save_sessions(self.sessions)

    def action_new_session(self) -> None:
        """Focus the session input for creating a new session"""
        logger.info("action_new_session called - focusing input")
        self.session_input.focus()
        self.session_input.clear()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle when user presses Enter in the input field"""
        if event.input.id == "session-input":
            session_name = event.value.strip()

            if not session_name:
                # Generate default name if empty
                session_num = 1
                existing_ids = {s.session_id for s in self.sessions}
                while f"claude-{session_num}" in existing_ids:
                    session_num += 1
                session_name = f"claude-{session_num}"

            self.create_session(session_name)
            # Clear the input
            self.session_input.clear()

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

                # Attach to the new session
                self._attach_to_session(new_session)

                # Refresh the session list
                self.call_later(self.action_refresh)

                # Update HUD with session name
                self.hud.set_session(session_name)
                self.current_session = new_session
                logger.info(f"Successfully created and attached to {session_name}")
            else:
                logger.error(f"Failed to start session {session_name}")
        except Exception as e:
            logger.exception(f"Error in create_session: {e}")

    def action_focus_sidebar(self) -> None:
        """Focus the sidebar"""
        self.set_focus(self.session_list)

    def action_focus_terminal(self) -> None:
        """Focus the terminal"""
        self.set_focus(self.term)
        self.capture_mouse(self.term)

    def _attach_to_session(self, session: Session) -> None:
        """Attach terminal to a specific session"""
        # Mark all sessions as inactive, then mark this one as active
        for s in self.sessions:
            s.active = False
        session.active = True

        # Get attach command for tmux
        attach_cmd = self._get_tmux_attach_command(session.session_id)

        # Only restart terminal if command actually changes
        if getattr(self.term, 'command', None) != attach_cmd:
            try:
                self.term.stop()
            except Exception:
                pass

            self.term.command = attach_cmd
            self.term.start()

        # Focus back to terminal
        self.set_focus(self.term)
        self.capture_mouse(self.term)

        # Update HUD with session name
        self.hud.set_session(session.session_id)
        self.current_session = session

        # Save updated session states
        save_sessions(self.sessions)

    def _get_tmux_attach_command(self, session_id: str) -> str:
        """Get the tmux attach command for a session"""
        # Direct tmux attach without extra shell wrapping for better performance
        return f"tmux attach -t {session_id}"

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list"""
        item: ListItem = event.item
        session = getattr(item, "data", None)
        if session and isinstance(session, Session):
            self._attach_to_session(session)

    def action_copy_to_clipboard(self) -> None:
        """Copy selected text to clipboard"""
        # This will pass through to the terminal's native copy handling
        if self.focused == self.term:
            # Let the terminal handle the copy operation
            pass

    def action_paste_from_clipboard(self) -> None:
        """Paste from clipboard"""
        # This will pass through to the terminal's native paste handling
        if self.focused == self.term:
            # Let the terminal handle the paste operation
            pass



if __name__ == "__main__":
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance
    KerberosApp().run()