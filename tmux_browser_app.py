from __future__ import annotations
import os, shutil, subprocess, json
from dataclasses import dataclass
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static, ListView, ListItem, Label, Button
from textual_terminal import Terminal  # pip install textual textual-terminal

SIDEBAR_WIDTH = 30  # columns
SESSIONS_FILE = Path.home() / ".kerberos_sessions.json"

@dataclass
class SessionRef:
    name: str
    windows: int
    attached: bool

    @property
    def display_name(self) -> str:
        status = "●" if self.attached else "○"
        return f"{status} {self.name} ({self.windows} win)"

def tmux_env():
    return dict(os.environ, TERM="xterm-256color")

def tmux(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args],
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

def load_managed_sessions() -> set[str]:
    """Load list of sessions managed by Kerberos"""
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_managed_sessions(sessions: set[str]) -> None:
    """Save list of sessions managed by Kerberos"""
    with open(SESSIONS_FILE, 'w') as f:
        json.dump(list(sessions), f)

def list_managed_sessions() -> list[SessionRef]:
    """List only Kerberos-managed tmux sessions"""
    managed = load_managed_sessions()
    fmt = "#{session_name}\t#{session_windows}\t#{session_attached}"
    cp = tmux(["list-sessions", "-F", fmt])
    sessions: list[SessionRef] = []

    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) >= 3:
                name, windows, attached = parts
                # Only include sessions we're managing
                if name in managed:
                    sessions.append(SessionRef(
                        name=name,
                        windows=int(windows) if windows.isdigit() else 0,
                        attached=attached == "1"
                    ))
    return sessions

def create_new_session_with_claude(session_name: str) -> bool:
    """Create a new tmux session and auto-start Claude"""
    # Create session with claude command
    claude_cmd = "claude"  # You can customize this command
    cp = tmux([
        "new-session",
        "-d",  # detached
        "-s", session_name,
        claude_cmd
    ])

    if cp.returncode == 0:
        # Add to managed sessions
        managed = load_managed_sessions()
        managed.add(session_name)
        save_managed_sessions(managed)
        return True
    return False

def attach_to_session(session_name: str) -> str:
    """Generate command to attach to a specific session without overriding"""
    return f"/usr/bin/env bash -lc 'exec env TERM=xterm-256color tmux attach -t {session_name}'"

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
        background: #000000;
    }}

    #container {{
        layout: horizontal;
        height: 100%;
    }}

    #sidebar {{
        width: {SIDEBAR_WIDTH};
        background: #1a1a2e;
        border-right: solid #6C71C4;
        padding: 1 2;
    }}

    #sidebar:focus-within {{
        border-right: thick #C0FFFD;
    }}

    #sidebar-title {{
        color: #C0FFFD;
        text-style: bold;
        margin-bottom: 1;
    }}

    ListView {{
        background: transparent;
        height: auto;
    }}

    ListItem {{
        color: #ffffff;
        background: transparent;
        padding: 0 1;
    }}

    ListItem:hover {{
        background: #6C71C4 30%;
        color: #C0FFFD;
    }}

    ListView > ListItem.--highlight {{
        background: #6C71C4;
        color: #ffffff;
        text-style: bold;
    }}

    #new-session-btn {{
        margin-top: 2;
        background: #6C71C4;
        color: #ffffff;
        text-align: center;
        padding: 1 2;
        border: none;
    }}

    #new-session-btn:hover {{
        background: #8080D4;
        color: #C0FFFD;
    }}

    #new-session-btn:focus {{
        background: #C0FFFD;
        color: #000000;
    }}

    #main {{
        layout: vertical;
        width: 100%;
    }}


    #hud {{
        height: 2;
        padding: 0 1;
        background: #6C71C4;
        color: #ffffff;
        text-align: center;
    }}

    #term {{
        height: 1fr;
    }}

    #term:focus {{
        border: solid #C0FFFD;
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+n", "new_session", "New Session", priority=True, show=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("ctrl+b", "focus_sidebar", "Sessions", priority=True),
        Binding("ctrl+l", "focus_terminal", "Terminal", priority=True),
    ]

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return

        with Container(id="container"):
            with Container(id="sidebar"):
                yield Static("● SESSIONS", id="sidebar-title")
                self.session_list = ListView(id="session-list")
                yield self.session_list
                yield Button("➕ New Session (⌃N)", id="new-session-btn", variant="primary")

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

        await self.action_refresh()

        # If no sessions exist, create the first one automatically
        sessions = list_managed_sessions()
        if not sessions:
            await self.action_new_session()
        else:
            # Focus the session list by default
            self.set_focus(self.session_list)

    async def action_refresh(self) -> None:
        """Refresh the session list"""
        self.session_list.clear()
        sessions = list_managed_sessions()

        if not sessions:
            self.session_list.append(ListItem(Label("No sessions yet")))
            self.session_list.append(ListItem(Label("Press ⌃N to create")))
            return

        for session in sessions:
            item = ListItem(Label(session.display_name))
            item.data = session
            self.session_list.append(item)

    async def action_new_session(self) -> None:
        """Create a new tmux session with Claude"""
        # Generate a unique session name
        managed = load_managed_sessions()
        session_num = 1
        while f"claude-{session_num}" in managed:
            session_num += 1

        new_session_name = f"claude-{session_num}"

        # Create the new session with Claude
        if create_new_session_with_claude(new_session_name):
            # Attach to the new session
            self._attach_to_session(new_session_name)
            # Refresh the session list
            await self.action_refresh()
            # Update HUD with session name
            self.hud.set_session(new_session_name)

    def action_focus_sidebar(self) -> None:
        """Focus the sidebar"""
        self.set_focus(self.session_list)

    def action_focus_terminal(self) -> None:
        """Focus the terminal"""
        self.set_focus(self.term)
        self.capture_mouse(self.term)

    def _attach_to_session(self, session_name: str) -> None:
        """Attach terminal to a specific session"""
        new_cmd = attach_to_session(session_name)
        try:
            self.term.stop()
        except Exception:
            pass
        self.term.command = new_cmd
        self.term.start()

        # Focus back to terminal
        self.set_focus(self.term)
        self.capture_mouse(self.term)

        # Update HUD with session name
        self.hud.set_session(session_name)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle session selection from list"""
        item: ListItem = event.item
        session = getattr(item, "data", None)
        if session:
            self._attach_to_session(session.name)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses"""
        if event.button.id == "new-session-btn":
            await self.action_new_session()

if __name__ == "__main__":
    os.environ.setdefault("TERM", "xterm-256color")
    KerberosApp().run()
