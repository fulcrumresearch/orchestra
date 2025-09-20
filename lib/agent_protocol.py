from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sessions import Session


class AgentProtocol(ABC):
    """Abstract protocol for agent backends (TMux, SSH, Docker, etc.)"""

    @abstractmethod
    def start(self, session: "Session") -> bool:
        """
        Start an agent for the given session.

        Args:
            session: Session object containing session_id and configuration

        Returns:
            bool: True if agent started successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_status(self, session_id: str) -> dict:
        """
        Get status information for a session.

        Args:
            session_id: ID of the session

        Returns:
            dict: Status information (backend-specific)
        """
        pass
