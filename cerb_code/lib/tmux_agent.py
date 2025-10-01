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
                "cerb-subagent": {"command": "cerb-mcp", "args": [], "env": {}}
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
        result = tmux(
            [
                "new-session",
                "-d",  # detached
                "-s",
                session.session_id,
                "-c",
                session.work_path,  # start in work directory
                self.default_command,
            ]
        )

        logger.info(
            f"tmux new-session result: returncode={result.returncode}, stderr={result.stderr}"
        )

        if result.returncode == 0:
            # Send Enter to accept the trust prompt
            logger.info(
                f"Starting 10 second wait before sending Enter to {session.session_id}"
            )
            time.sleep(2)  # Give Claude a moment to start
            logger.info(f"Wait complete, now sending Enter to {session.session_id}")
            session.send_message("")
            logger.info(
                f"Sent Enter to session {session.session_id} to accept trust prompt"
            )

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
        # Target pane 0 specifically (where Claude runs), not the active pane
        target = f"{session_id}:0.0"
        # send the literal bytes of the message
        r1 = tmux(["send-keys", "-t", target, "-l", "--", message])
        # then send a carriage return (equivalent to pressing Enter)
        r2 = tmux(["send-keys", "-t", target, "C-m"])
        return r1.returncode == 0 and r2.returncode == 0
