from __future__ import annotations
import os, shutil, subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static, ListView, ListItem, Label, Input

from lib.sessions import Session, AgentType, load_sessions, save_sessions
from lib.tmux_agent import TmuxProtocol
from lib.logger import get_logger

logger = get_logger(__name__)

SIDEBAR_WIDTH = 30  # columns


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


class KerberosApp(App):
    CSS = f"""
    Screen {{
        background: #0a0a0a;
    }}

    #container {{
        layout: vertical;
        height: 100%;
        padding: 1 1;
    }}

    #sidebar-title {{
        color: #00ff9f;
        text-style: bold;
        margin-bottom: 1;
        height: 1;
    }}

    ListView {{
        background: transparent;
        height: 1fr;
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
        height: 3;
    }}

    #session-input:focus {{
        border: solid #00ff9f;
    }}

    #session-input.--placeholder {{
        color: #666666;
    }}

    #hud {{
        height: 2;
        padding: 0 1;
        background: #111111;
        color: #999999;
        text-align: center;
        border-bottom: solid #333333;
        margin-bottom: 1;
    }}
"""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New Session", priority=True, show=True),
        Binding("ctrl+r", "refresh", "Refresh", priority=True),
        Binding("ctrl+d", "delete_session", "Delete", priority=True),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("j", "cursor_down", show=False),
        # Removed global enter binding - let ListView and Input handle their own
    ]

    def __init__(self):
        super().__init__()
        logger.info("KerberosApp initializing")
        self.sessions: list[Session] = []
        self.current_session: Session | None = None
        # Create a shared TmuxProtocol for all sessions
        self.agent = TmuxProtocol(default_command="claude")
        logger.info("KerberosApp initialized")

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return

        with Container(id="container"):
            self.hud = HUD("⌃N new • ⌃D delete • ⌃R refresh • ⌃Q quit", id="hud")
            yield self.hud
            yield Static("● SESSIONS", id="sidebar-title")
            self.session_list = ListView(id="session-list")
            yield self.session_list
            self.session_input = Input(
                placeholder="New session name...",
                id="session-input"
            )
            yield self.session_input

    async def on_ready(self) -> None:
        """Load sessions and refresh list"""
        # Load existing sessions with the shared agent protocol
        self.sessions = load_sessions(protocol=self.agent)
        await self.action_refresh()

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
        # Debug: Show that we received the event
        self.hud.update(f"Creating session...")
        if event.input.id == "session-input":
            session_name = event.value.strip()

            if not session_name:
                # Generate default name if empty
                session_num = 1
                existing_ids = {s.session_id for s in self.sessions}
                while f"claude-{session_num}" in existing_ids:
                    session_num += 1
                session_name = f"claude-{session_num}"

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

    def action_select_session(self) -> None:
        """Select the highlighted session"""
        index = self.session_list.index
        if index is not None and 0 <= index < len(self.sessions):
            session = self.sessions[index]
            self._attach_to_session(session)

    def action_delete_session(self) -> None:
        """Delete the currently selected session"""
        if not self.current_session:
            return

        # Kill the tmux session
        subprocess.run(["tmux", "kill-session", "-t", self.current_session.session_id],
                      capture_output=True, text=True)

        # Remove from sessions list
        self.sessions = [s for s in self.sessions if s.session_id != self.current_session.session_id]
        save_sessions(self.sessions)

        # Clear current session
        self.current_session = None
        self.hud.set_session("")

        # Refresh the list
        self.call_later(self.action_refresh)

    def _attach_to_session(self, session: Session) -> None:
        """Display session in the right pane using tmux commands"""
        # Mark all sessions as inactive, then mark this one as active
        for s in self.sessions:
            s.active = False
        session.active = True

        # Check session status using the protocol
        status = self.agent.get_status(session.session_id)

        if not status.get("exists", False):
            # Session doesn't exist, try to start it
            # Note: For existing sessions being reattached, we need to prepare first
            logger.info(f"Session {session.session_id} doesn't exist, creating it")
            if not session.work_path:
                # Only prepare if work_path not set (i.e., not already prepared)
                session.prepare()
            if not session.start():
                logger.error(f"Failed to start session {session.session_id}")
                return

        # Use tmux's respawn-pane to replace the right pane content with our session
        # This avoids the nested tmux issue
        right_pane = "{right}"

        # Kill whatever's in the right pane and respawn it with a new shell attached to our session
        # We use TMUX= to override the TMUX env var, allowing the attach
        cmd = f"TMUX= tmux attach-session -t {session.session_id}"
        subprocess.run(["tmux", "respawn-pane", "-t", right_pane, "-k", cmd],
                      capture_output=True, text=True)

        # Auto-focus the right pane so user can start typing immediately
        subprocess.run(["tmux", "select-pane", "-t", right_pane],
                      capture_output=True, text=True)

        # Update HUD with session name
        self.hud.set_session(session.session_id)
        self.current_session = session

        # Save updated session states
        save_sessions(self.sessions)



    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list when clicked"""
        if event.index is not None and 0 <= event.index < len(self.sessions):
            session = self.sessions[event.index]
            self._attach_to_session(session)



if __name__ == "__main__":
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance
    KerberosApp().run()
