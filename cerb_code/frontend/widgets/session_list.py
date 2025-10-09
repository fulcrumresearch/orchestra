"""Session list widget for displaying session hierarchy"""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import ListView, Static


class SessionListContainer(Container):
    """Container for session list with title and status.

    This is a simple wrapper that provides structure for the session list
    display. The actual session rendering logic remains in the app for now
    due to tight coupling with state management.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title = Static("Orchestra", id="sidebar-title")
        self.branch_info = Static("", id="branch-info")
        self.status_indicator = Static("", id="status-indicator")
        self.session_list = ListView(id="session-list")

    def compose(self) -> ComposeResult:
        """Compose the session list container"""
        yield self.title
        yield self.branch_info
        yield self.status_indicator
        yield self.session_list
