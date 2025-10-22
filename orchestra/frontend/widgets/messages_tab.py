"""Messages tab widget for displaying filtered session messages."""

from pathlib import Path
from textual.app import ComposeResult
from textual.widgets import RichLog
from textual.containers import Container

from orchestra.lib.message import load_session_messages, Message
from orchestra.lib.sessions import AgentType


class MessagesTab(Container):
    """Container for displaying session-specific messages."""

    def compose(self) -> ComposeResult:
        """Compose the messages tab layout."""
        self.messages_log = RichLog(
            highlight=True,
            markup=True,
            auto_scroll=True,
            wrap=True,
            min_width=0,
        )
        yield self.messages_log

    def on_mount(self) -> None:
        """Start refreshing messages when mounted."""
        self.set_interval(2.0, self.refresh_messages)
        self.refresh_messages()

    def refresh_messages(self) -> None:
        """Refresh messages for the current active session."""
        app = self.app

        # Get current session from app state
        if not hasattr(app, "state"):
            return

        active_session = app.state.get_active_session()
        if not active_session:
            self.messages_log.clear()
            self.messages_log.write("[dim]No session selected[/dim]")
            return

        # Pass None for designer (shows all), or session name for executor (filtered)
        session_name = None if active_session.agent_type == AgentType.DESIGNER else active_session.session_name
        self.load_and_display_messages(Path(app.state.project_dir), session_name)

    def update_messages(self, messages: list[Message]) -> None:
        """Update the display with a list of Message objects.

        Args:
            messages: List of Message objects to display
        """
        self.messages_log.clear()

        if not messages:
            self.messages_log.write("[dim]No messages[/dim]")
            return

        for msg in messages:
            # Color code based on sender type
            if "monitor" in msg.sender.lower():
                sender_color = "yellow"
            elif "designer" in msg.sender.lower():
                sender_color = "cyan"
            else:
                sender_color = "green"

            # Format: [SENDER] message with timestamp
            sender_styled = f"[{sender_color}]{msg.sender}[/{sender_color}]"
            timestamp = f"[dim]{msg.timestamp}[/dim]"

            self.messages_log.write(f"{sender_styled} {msg.message} {timestamp}")

    def load_and_display_messages(self, project_dir: Path, session_name: str | None = None) -> None:
        """Load messages for a specific session and display them.

        If session_name is None, shows all messages (designer mode).

        Args:
            project_dir: Path to the project directory
            session_name: Name of the session to filter messages for (None to show all)
        """
        try:
            messages = load_session_messages(Path(project_dir), session_name)
            self.update_messages(messages)
        except Exception as e:
            self.messages_log.clear()
            self.messages_log.write(f"[red]Error loading messages: {e}[/red]")
