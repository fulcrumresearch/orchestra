import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, TYPE_CHECKING

from .agent_protocol import AgentProtocol
from .helpers import (
    get_docker_container_name,
    start_docker_container,
    stop_docker_container,
    docker_exec,
)
from .logger import get_logger

if TYPE_CHECKING:
    from .sessions import Session

logger = get_logger(__name__)


def tmux_env() -> dict:
    """Get environment for tmux commands"""
    import os

    return dict(os.environ, TERM="xterm-256color")


def tmux(args: list[str]) -> subprocess.CompletedProcess:
    """Execute tmux command against the dedicated 'orchestra' server"""
    return subprocess.run(
        ["tmux", "-L", "orchestra", *args],
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class TmuxProtocol(AgentProtocol):
    """TMux implementation of the AgentProtocol with Docker containerization"""

    def __init__(
        self,
        default_command: str = "claude",
        mcp_port: int = 8765,
        use_docker: bool = True,
    ):
        """
        Initialize TmuxAgent.

        Args:
            default_command: Default command to run when starting a session
            mcp_port: Port where MCP server is running (default: 8765)
            use_docker: Whether to use Docker for sessions (default: True)
        """
        self.default_command = default_command
        self.mcp_port = mcp_port
        self.use_docker = use_docker

    def _exec(self, session_id: str, cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute command (Docker or local mode)"""
        if self.use_docker:
            container_name = get_docker_container_name(session_id)
            return docker_exec(container_name, cmd)
        else:
            return subprocess.run(
                cmd,
                env=tmux_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

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

        # Start Docker container if needed
        if self.use_docker:
            container_name = get_docker_container_name(session.session_id)
            if not start_docker_container(
                container_name=container_name,
                work_path=session.work_path,
                mcp_port=self.mcp_port,
                paired=session.paired,
            ):
                return False
        else:
            # Configure MCP for local (non-Docker) session
            self._configure_mcp_for_local_session(session)

        # Determine working directory
        work_dir = "/workspace" if self.use_docker else session.work_path

        # Create tmux session (works same way for both Docker and local)
        result = self._exec(
            session.session_id,
            [
                "tmux",
                "-L",
                "orchestra",
                "new-session",
                "-d",  # detached
                "-s",
                session.session_id,
                "-c",
                work_dir,
                self.default_command,
            ],
        )

        logger.info(
            f"tmux new-session result: returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}"
        )

        if result.returncode == 0:
            # Send Enter to accept the trust prompt
            time.sleep(2)  # Give Claude a moment to start
            logger.info(f"Wait complete, now sending Enter to {session.session_id}")
            session.send_message("")
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
        # In Docker mode, first check if container is running
        if self.use_docker:
            container_name = get_docker_container_name(session_id)
            container_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
            )
            if not container_check.stdout.strip():
                return {"exists": False}

        # Check if tmux session exists (same for both modes via _exec)
        check_result = self._exec(
            session_id,
            ["tmux", "-L", "orchestra", "has-session", "-t", session_id],
        )
        if check_result.returncode != 0:
            return {"exists": False}

        # Get session info (same for both modes via _exec)
        fmt = "#{session_windows}\t#{session_attached}"
        result = self._exec(
            session_id,
            ["tmux", "-L", "orchestra", "display-message", "-t", session_id, "-p", fmt],
        )

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
        """Send a message to a tmux session (Docker or local mode)"""
        # Target pane 0 specifically (where Claude runs), not the active pane
        target = f"{session_id}:0.0"
        # Send the literal bytes of the message (same for both modes via _exec)
        r1 = self._exec(
            session_id,
            ["tmux", "-L", "orchestra", "send-keys", "-t", target, "-l", "--", message],
        )
        # Then send a carriage return (equivalent to pressing Enter)
        r2 = self._exec(
            session_id,
            ["tmux", "-L", "orchestra", "send-keys", "-t", target, "C-m"],
        )
        return r1.returncode == 0 and r2.returncode == 0

    def attach(self, session_id: str, target_pane: str = "2") -> bool:
        """Attach to a tmux session in the specified pane"""
        if self.use_docker:
            # Docker mode: spawn docker exec command in the pane
            container_name = get_docker_container_name(session_id)
            result = subprocess.run(
                [
                    "tmux",
                    "-L",
                    "orchestra",
                    "respawn-pane",
                    "-t",
                    target_pane,
                    "-k",
                    "docker",
                    "exec",
                    "-it",
                    container_name,
                    "tmux",
                    "-L",
                    "orchestra",
                    "attach-session",
                    "-t",
                    session_id,
                ],
                capture_output=True,
                text=True,
            )
        else:
            # Local mode: attach to tmux on host
            result = subprocess.run(
                [
                    "tmux",
                    "-L",
                    "orchestra",
                    "respawn-pane",
                    "-t",
                    target_pane,
                    "-k",
                    "sh",
                    "-c",
                    f"TMUX= tmux -L orchestra attach-session -t {session_id}",
                ],
                capture_output=True,
                text=True,
            )

        return result.returncode == 0

    def delete(self, session_id: str) -> bool:
        """Delete a tmux session and cleanup (Docker container or local)"""
        if self.use_docker:
            # Docker mode: stop and remove container (also kills tmux inside)
            container_name = get_docker_container_name(session_id)
            stop_docker_container(container_name)
        else:
            # Local mode: kill the tmux session
            subprocess.run(
                ["tmux", "-L", "orchestra", "kill-session", "-t", session_id],
                capture_output=True,
                text=True,
            )
        return True

    def _configure_mcp_for_local_session(self, session: "Session") -> None:
        """Configure MCP for local (non-Docker) session using .mcp.json

        Creates a project-specific .mcp.json file in the session's worktree.
        Claude Code will prompt the user to approve this MCP server on first use.
        """
        logger.info(f"Configuring MCP for local session {session.session_id}")

        if not session.work_path:
            logger.warning("Cannot configure MCP: work_path not set")
            return

        # MCP URL for local sessions (localhost, not host.docker.internal)
        mcp_url = f"http://localhost:{self.mcp_port}/sse"

        # Create .mcp.json in the session's worktree
        mcp_config = {"mcpServers": {"orchestra-mcp": {"url": mcp_url, "type": "sse"}}}

        mcp_config_path = Path(session.work_path) / ".mcp.json"
        try:
            with open(mcp_config_path, "w") as f:
                json.dump(mcp_config, f, indent=2)
            logger.info(f"Created .mcp.json at {mcp_config_path} (URL: {mcp_url})")
            logger.info("Claude Code will prompt user to approve this MCP server on first use")
        except Exception as e:
            logger.error(f"Failed to create .mcp.json: {e}")

    def toggle_pairing(self, session: "Session") -> tuple[bool, str]:
        """
        Toggle pairing mode using symlinks.

        Paired: Move user's dir aside, symlink source → worktree, update worktree's .git file
        Unpaired: Remove symlink, restore user's dir, update worktree's .git file

        Returns: (success, error_message)
        """
        if not session.work_path or not session.source_path:
            return False, "Session not properly initialized"

        source = Path(session.source_path)
        worktree = Path(session.work_path)

        # Pairing only works for sessions with separate worktrees (executors)
        # Designer sessions work directly in source, so pairing doesn't apply
        if source == worktree:
            return False, "Pairing not available for designer sessions (no separate worktree)"

        backup = Path(f"{session.source_path}.backup")
        worktree_git_file = worktree / ".git"

        # Switching to paired mode
        if not session.paired:
            # Check if backup already exists
            if backup.exists():
                return False, f"Backup directory already exists: {backup}"

            # Move user's dir to backup
            try:
                source.rename(backup)
                logger.info(f"Moved {source} → {backup}")
            except Exception as e:
                return False, f"Failed to backup source directory: {e}"

            # Update worktree's .git file to point to new location
            # Resolve any symlinks in the .git path
            try:
                backup_git = backup / ".git"
                # Resolve symlink if .git is a symlink
                resolved_git = backup_git.resolve() if backup_git.is_symlink() else backup_git
                worktree_git_file.write_text(f"gitdir: {resolved_git}/worktrees/{session.session_id}\n")
                logger.info(f"Updated {worktree_git_file} to point to {resolved_git}/worktrees/{session.session_id}")
            except Exception as e:
                # Rollback: restore the directory
                backup.rename(source)
                return False, f"Failed to update worktree .git file: {e}"

            source.symlink_to(worktree)
            logger.info(f"Created symlink {source} → {worktree}")

            session.paired = True

        else:
            # Switching to unpaired mode
            # Check if backup exists
            if not backup.exists():
                return False, f"Backup directory not found: {backup}"

            if source.is_symlink():
                source.unlink()
                logger.info(f"Removed symlink {source}")
            else:
                return False, f"Expected symlink at {source}, found regular directory"

            backup.rename(source)
            logger.info(f"Restored {backup} → {source}")

            # Update worktree's .git file to point back to original location
            # Resolve any symlinks in the .git path
            try:
                source_git = source / ".git"
                # Resolve symlink if .git is a symlink
                resolved_git = source_git.resolve() if source_git.is_symlink() else source_git
                worktree_git_file.write_text(f"gitdir: {resolved_git}/worktrees/{session.session_id}\n")
                logger.info(f"Updated {worktree_git_file} to point to {source}/.git/worktrees/{session.session_id}")
            except Exception as e:
                return False, f"Failed to update worktree .git file: {e}"

            session.paired = False

        return True, ""
