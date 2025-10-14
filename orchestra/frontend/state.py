"""Application state management for Orchestra UI"""

from pathlib import Path
from typing import Optional, List
from orchestra.lib.sessions import Session, load_sessions
from orchestra.lib.file_watcher import FileWatcher


class AppState:
    """Centralized application state for the Orchestra UI.

    Holds all session data and provides methods to access and manipulate it.
    No UI logic - just data management.
    """

    def __init__(self, project_dir: Path):
        """Initialize app state.

        Args:
            project_dir: The project directory path
        """
        self.root_session: Optional[Session] = None
        self.root_session_name: Optional[str] = None
        self.active_session_name: Optional[str] = None
        self.paired_session_name: Optional[str] = None
        self.project_dir = project_dir
        self.file_watcher = FileWatcher()

    def load(self, root_session_name: str) -> None:
        """Load sessions from disk.

        Args:
            root_session_name: The root session name to load
        """
        sessions = load_sessions(root=root_session_name, project_dir=self.project_dir)
        self.root_session = sessions[0] if sessions else None

    def get_active_session(self) -> Optional[Session]:
        """Get the currently active session.

        Returns:
            The active Session object or None
        """
        if not self.active_session_name or not self.root_session:
            return None

        # Check root
        if self.root_session.session_name == self.active_session_name:
            return self.root_session

        # Check children
        for child in self.root_session.children:
            if child.session_name == self.active_session_name:
                return child

        return None

    def set_active_session(self, session_name: str) -> None:
        """Set the active session by name.

        Args:
            session_name: The session name to set as active
        """
        self.active_session_name = session_name

    def get_session_by_index(self, index: int) -> Optional[Session]:
        """Get session by list index (0 = root, 1+ = children).

        Args:
            index: The list index

        Returns:
            Session at that index, or None if invalid
        """
        if not self.root_session:
            return None

        if index == 0:
            return self.root_session
        else:
            child_index = index - 1
            if 0 <= child_index < len(self.root_session.children):
                return self.root_session.children[child_index]
        return None

    def remove_child(self, session_name: str) -> bool:
        """Remove a child session by name.

        Args:
            session_name: The session name to remove

        Returns:
            True if removed, False if not found
        """
        if not self.root_session:
            return False

        for i, child in enumerate(self.root_session.children):
            if child.session_name == session_name:
                self.root_session.children.pop(i)
                return True
        return False

    def get_index_by_session_name(self, session_name: str) -> Optional[int]:
        """Get list index for a session name (0 = root, 1+ = children).

        Args:
            session_name: The session name to find

        Returns:
            List index, or None if not found
        """
        if not self.root_session:
            return None

        if self.root_session.session_name == session_name:
            return 0

        for i, child in enumerate(self.root_session.children):
            if child.session_name == session_name:
                return i + 1

        return None
