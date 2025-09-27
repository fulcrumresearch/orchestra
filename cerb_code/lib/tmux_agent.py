import os
import subprocess
import time
from typing import Dict, Any, TYPE_CHECKING

from .agent_protocol import AgentProtocol
from .logger import get_logger

if TYPE_CHECKING:
    from .sessions import Session

logger = get_logger(__name__)


def tmux_env() -> dict:
    """Get environment for tmux commands"""
    return dict(os.environ, TERM="xterm-256color")


def tmux(args: list[str]) -> subprocess.CompletedProcess:
    """Execute tmux command"""
    return subprocess.run(
        ["tmux", *args],
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class TmuxProtocol(AgentProtocol):
    """TMux implementation of the AgentProtocol"""

    def __init__(self, default_command: str = "claude"):
        """
        Initialize TmuxAgent.

        Args:
            default_command: Default command to run when starting a session
        """
        # Add MCP config for cerb-subagent
        mcp_config = {
            "mcpServers": {
                "cerb-subagent": {
                    "command": "cerb-mcp",
                    "args": [],
                    "env": {}
                }
            }
        }

        import json
        mcp_config_str = json.dumps(mcp_config)
        self.default_command = f"{default_command} --mcp-config '{mcp_config_str}'"

    def start(self, session: "Session") -> bool:
        """
        Start a tmux session for the given Session object.

        Args:
            session: Session object containing session_id and configuration

        Returns:
            bool: True if session started successfully, False otherwise
        """
        logger.info(f"TmuxProtocol.start called for session {session.session_id}")

        # Ensure work_path is set
        if not session.work_path:
            logger.error(f"Session {session.session_id} has no work_path set")
            return False

        # Create tmux session with the session_id in the work directory
        result = tmux([
            "new-session",
            "-d",  # detached
            "-s", session.session_id,
            "-c", session.work_path,  # start in work directory
            self.default_command
        ])

        logger.info(f"tmux new-session result: returncode={result.returncode}, stderr={result.stderr}")

        if result.returncode == 0:
            # Send Enter to accept the trust prompt
            time.sleep(0.5)  # Give Claude a moment to start
            tmux(["send-keys", "-t", session.session_id, "Enter"])
            logger.info(f"Sent Enter to session {session.session_id} to accept trust prompt")

        return result.returncode == 0


    def get_status(self, session_id: str) -> Dict[str, Any]:
        """
        Get status information for a tmux session.

        Args:
            session_id: ID of the session

        Returns:
            dict: Status information including windows count and attached state
        """
        # Check if session exists
        check_result = tmux(["has-session", "-t", session_id])
        if check_result.returncode != 0:
            return {"exists": False}

        # Get session info
        fmt = "#{session_windows}\t#{session_attached}"
        result = tmux(["display-message", "-t", session_id, "-p", fmt])

        if result.returncode != 0:
            return {"exists": True, "error": result.stderr}

        try:
            windows, attached = result.stdout.strip().split("\t")
            return {
                "exists": True,
                "windows": int(windows) if windows.isdigit() else 0,
                "attached": attached == "1",
            }
        except (ValueError, IndexError):
            return {"exists": True, "error": "Failed to parse tmux output"}

    def send_message(self, session_id: str, message: str) -> bool:
        """
        Send a message to a tmux session.

        Args:
            session_id: ID of the session
            message: Text to send to the session

        Returns:
            bool: True if successful, False otherwise
        """
        result = tmux(["send-keys", "-t", session_id, message, "Enter"])
        return result.returncode == 0
