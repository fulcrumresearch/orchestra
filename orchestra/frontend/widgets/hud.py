"""HUD widget for displaying session and control information"""

from textual.widgets import Static


class HUD(Static):
    """Heads-up display widget showing current session and keyboard shortcuts."""

    can_focus = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_text = "⌃D delete • ⌃R refresh • p pair • s spec • m docs • t terminal • ⌃\\ detach • ⌃Q quit"
        self.current_session = ""

    def set_session(self, session_name: str):
        """Update the current session display.

        Args:
            session_name: The name of the current session
        """
        self.current_session = session_name
        self.update(f"[{session_name}] • {self.default_text}")
