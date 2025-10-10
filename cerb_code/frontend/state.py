"""Application state management for Kerberos UI"""

from pathlib import Path
from typing import Optional, List
from cerb_code.lib.sessions import Session, load_sessions
from cerb_code.lib.file_watcher import FileWatcher


class AppState:
    """Centralized application state for the Kerberos UI.

    Holds all session data and provides methods to access and manipulate it.
    No UI logic - just data management.
    """

    def __init__(self, project_dir: Path):
        """Initialize app state.

        Args:
            project_dir: The project directory path
        """
        self.root_session: Optional[Session] = None
        self.root_session_id: Optional[str] = None
        self.active_session_id: Optional[str] = None
        self.paired_session_id: Optional[str] = None
        self.project_dir = project_dir
        self.file_watcher = FileWatcher()

    def load(self, root_session_id: str) -> None:
        """Load sessions from disk.

        Args:
            root_session_id: The root session ID to load
        """
        sessions = load_sessions(root=root_session_id, project_dir=self.project_dir)
        self.root_session = sessions[0] if sessions else None

    def get_active_session(self) -> Optional[Session]:
        """Get the currently active session.

        Returns:
            The active Session object or None
        """
        if not self.active_session_id or not self.root_session:
            return None

        # Check root
        if self.root_session.session_id == self.active_session_id:
            return self.root_session

        # Check children
        for child in self.root_session.children:
            if child.session_id == self.active_session_id:
                return child

        return None

    def set_active_session(self, session_id: str) -> None:
        """Set the active session ID.

        Args:
            session_id: The session ID to set as active
        """
        self.active_session_id = session_id

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

    def remove_child(self, session_id: str) -> bool:
        """Remove a child session by ID.

        Args:
            session_id: The session ID to remove

        Returns:
            True if removed, False if not found
        """
        if not self.root_session:
            return False

        for i, child in enumerate(self.root_session.children):
            if child.session_id == session_id:
                self.root_session.children.pop(i)
                return True
        return False

    def get_index_by_session_id(self, session_id: str) -> Optional[int]:
        """Get list index for a session ID (0 = root, 1+ = children).

        Args:
            session_id: The session ID to find

        Returns:
            List index, or None if not found
        """
        if not self.root_session:
            return None

        if self.root_session.session_id == session_id:
            return 0

        for i, child in enumerate(self.root_session.children):
            if child.session_id == session_id:
                return i + 1

        return None
