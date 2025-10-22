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
            auto_scroll=False,  # Manual scroll control to avoid constant scrolling
            wrap=True,
            min_width=0,
        )
        self._message_count = 0
        yield self.messages_log

    def on_mount(self) -> None:
        """Start watching messages file for changes."""
        app = self.app
        if hasattr(app, "state") and hasattr(app.state, "file_watcher"):
            messages_path = Path(app.state.project_dir) / ".orchestra" / "messages.jsonl"

            async def on_messages_changed(path: Path, last_call_time: float) -> None:
                self.refresh_messages()

            app.state.file_watcher.register(messages_path, on_messages_changed)

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
        # Check if we should scroll (only if new messages added)
        should_scroll = len(messages) > self._message_count
        self._message_count = len(messages)

        self.messages_log.clear()

        if not messages:
            self.messages_log.write("[dim]No messages[/dim]")
            return

        for i, msg in enumerate(messages):
            # Color code based on sender type
            if "monitor" in msg.sender.lower():
                sender_color = "bright_yellow"
            elif "designer" in msg.sender.lower():
                sender_color = "bright_magenta"
            else:
                sender_color = "magenta"

            # Sleek minimal format: sender on its own line, message below with padding
            sender_styled = f"[bold {sender_color}]▸ {msg.sender}[/bold {sender_color}]"

            self.messages_log.write(sender_styled)
            self.messages_log.write(f"  {msg.message}")

            # Add subtle spacing between messages (but not after the last one)
            if i < len(messages) - 1:
                self.messages_log.write("")

        # Only scroll to bottom when new messages are added
        if should_scroll:
            self.messages_log.scroll_end()

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
