import json
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple, TYPE_CHECKING

from .agent_protocol import AgentProtocol
from .helpers import (
    get_docker_container_name,
    start_docker_container,
    stop_docker_container,
    docker_exec,
)
from .logger import get_logger
from .tmux import (
    build_new_session_cmd,
    build_respawn_pane_cmd,
    build_tmux_cmd,
    tmux_env,
)

if TYPE_CHECKING:
    from .sessions import Session

logger = get_logger(__name__)


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

    def _exec(self, session: "Session", cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute command (Docker or local mode)"""
        if self.use_docker:
            container_name = get_docker_container_name(session.session_id)
            return docker_exec(container_name, cmd)
        else:
            return subprocess.run(
                cmd,
                env=tmux_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    def start(self, session: "Session", initial_message: str = "") -> bool:
        """
        Start a tmux session for the given Session object.

        Args:
            session: Session object containing session_id and configuration
            initial_message: Optional initial message to pass to claude command

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

        # Build command with optional initial message
        if initial_message:
            # Escape the message for shell execution
            # Use single quotes and escape any single quotes in the message
            escaped_message = initial_message.replace("'", "'\"'\"'")
            command = f"{self.default_command} '{escaped_message}'"
        else:
            command = self.default_command

        # Create tmux session (works same way for both Docker and local)
        result = self._exec(
            session,
            build_new_session_cmd(session.session_id, work_dir, command),
        )

        logger.info(
            f"tmux new-session result: returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}"
        )

        if result.returncode == 0:
            if session.agent_type.value == "executor":
                # For executors in bypass mode, send Down arrow then Enter to accept bypass warning
                logger.info(f"Sending acceptance keys for executor {session.session_id}")

                # Send Down arrow to select "Yes, I accept" option
                self._exec(session, ["tmux", "-L", "orchestra", "send-keys", "-t", f"{session.session_id}:0.0", "Down"])
                time.sleep(0.2)

                # Send Enter to accept
                session.send_message("")
                logger.info(f"Sent acceptance keys to session {session.session_id}")

        return result.returncode == 0

    def get_status(self, session: "Session") -> Dict[str, Any]:
        """
        Get status information for a tmux session.

        Args:
            session: Session object

        Returns:
            dict: Status information including windows count and attached state
        """
        # In Docker mode, first check if container is running
        if self.use_docker:
            container_name = get_docker_container_name(session.session_id)
            container_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
            )
            if not container_check.stdout.strip():
                return {"exists": False}

        # Check if tmux session exists (same for both modes via _exec)
        check_result = self._exec(
            session,
            build_tmux_cmd("has-session", "-t", session.session_id),
        )
        if check_result.returncode != 0:
            return {"exists": False}

        # Get session info (same for both modes via _exec)
        fmt = "#{session_windows}\t#{session_attached}"
        result = self._exec(
            session,
            build_tmux_cmd("display-message", "-t", session.session_id, "-p", fmt),
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

    def _send_with_retry(
        self,
        session: "Session",
        message: str,
        max_retries: int = 5,
        backoff: List[float] = [0.5, 1.0, 2.0, 4.0, 8.0],
    ) -> bool:
        """
        Send a message to tmux session using paste buffer with retry logic and exponential backoff.

        Args:
            session: Session object
            message: Message to send
            max_retries: Maximum number of retries (default: 5)
            backoff: List of backoff delays in seconds (default: [0.5, 1.0, 2.0, 4.0, 8.0])

        Returns:
            bool: True if successful, False otherwise
        """
        target = f"{session.session_id}:0.0"

        for attempt in range(max_retries + 1):
            logger.info(f"Send attempt {attempt + 1}/{max_retries + 1} to {session.session_id}")

            # Use paste buffer method
            r1 = self._exec(
                session,
                build_tmux_cmd("set-buffer", message),
            )
            logger.info(f"set-buffer: returncode={r1.returncode}, stderr={r1.stderr}")

            r2 = self._exec(
                session,
                build_tmux_cmd("paste-buffer", "-t", target),
            )
            logger.info(f"paste-buffer: returncode={r2.returncode}, stderr={r2.stderr}")

            # Check if successful
            if r1.returncode == 0 and r2.returncode == 0:
                logger.info(f"Sent successfully to {session.session_id} on attempt {attempt + 1}")
                return True

            # If this wasn't the last attempt, wait before retrying
            if attempt < max_retries:
                delay = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                logger.warning(
                    f"Send failed (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {delay}s..."
                )
                time.sleep(delay)

        # All retries exhausted
        logger.error(f"Failed to send after {max_retries + 1} attempts.")
        return False

    def _send_enter(self, session: "Session", attempts: int = 3, delay: float = 0.1) -> bool:
        """Send Enter key multiple times to ensure it's received.

        Args:
            session: Session object
            attempts: Number of times to send Enter (default: 3)
            delay: Delay between attempts in seconds (default: 0.1)

        Returns:
            bool: True if at least one attempt succeeded
        """
        target = f"{session.session_id}:0.0"
        success = False

        for i in range(attempts):
            if i > 0:
                time.sleep(delay)
            result = self._exec(session, build_tmux_cmd("send-keys", "-t", target, "C-m"))
            logger.info(f"send-keys C-m attempt {i + 1}/{attempts}: returncode={result.returncode}")
            if result.returncode == 0:
                success = True

        return success

    def send_message(self, session: "Session", message: str) -> bool:
        """Send a message to a tmux session using paste buffer with retry logic (Docker or local mode)"""
        # Send message using buffer with retry logic
        if not self._send_with_retry(session, message + "\n"):
            return False

        # Hammer Enter multiple times to ensure it's received
        return self._send_enter(session)

    def attach(self, session: "Session", target_pane: str = "2") -> bool:
        """Attach to a tmux session in the specified pane"""
        if self.use_docker:
            # Docker mode: spawn docker exec command in the pane
            container_name = get_docker_container_name(session.session_id)
            result = subprocess.run(
                build_respawn_pane_cmd(
                    target_pane,
                    [
                        "docker",
                        "exec",
                        "-it",
                        container_name,
                        "tmux",
                        "-L",
                        "orchestra",
                        *build_tmux_cmd("attach-session", "-t", session.session_id)[3:],
                    ],
                ),
                capture_output=True,
                text=True,
            )
        else:
            # Local mode: attach to tmux on host
            result = subprocess.run(
                build_respawn_pane_cmd(
                    target_pane,
                    [
                        "sh",
                        "-c",
                        f"TMUX= tmux -L orchestra attach-session -t {session.session_id}",
                    ],
                ),
                capture_output=True,
                text=True,
            )

        return result.returncode == 0

    def delete(self, session: "Session") -> bool:
        """Delete a tmux session and cleanup (Docker container or local)"""
        if self.use_docker:
            # Docker mode: stop and remove container (also kills tmux inside)
            container_name = get_docker_container_name(session.session_id)
            stop_docker_container(container_name)
        else:
            # Local mode: kill the tmux session
            subprocess.run(
                build_tmux_cmd("kill-session", "-t", session.session_id),
                capture_output=True,
                text=True,
            )
        return True

    def _configure_mcp_for_local_session(self, session: "Session") -> None:
        """Configure MCP for local (non-Docker) session using .mcp.json and settings.json

        Creates a project-specific .mcp.json and .claude/settings.json with pre-approved MCP permissions.
        """
        logger.info(f"Configuring MCP for local session {session.session_id}")

        if not session.work_path:
            logger.warning("Cannot configure MCP: work_path not set")
            return

        # MCP URL for local sessions (localhost, not host.docker.internal)
        mcp_url = f"http://localhost:{self.mcp_port}/mcp"

        # Create .mcp.json in the session's worktree
        mcp_config = {"mcpServers": {"orchestra-mcp": {"url": mcp_url, "type": "http"}}}

        mcp_config_path = Path(session.work_path) / ".mcp.json"
        try:
            with open(mcp_config_path, "w") as f:
                json.dump(mcp_config, f, indent=2)
            logger.info(f"Created .mcp.json at {mcp_config_path} (URL: {mcp_url})")
        except Exception as e:
            logger.error(f"Failed to create .mcp.json: {e}")

        # Create .claude/settings.json with pre-approved MCP permissions
        claude_dir = Path(session.work_path) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        settings_path = claude_dir / "settings.json"
        settings_config = {
            "permissions": {
                "allow": ["mcp__orchestra-mcp__spawn_subagent", "mcp__orchestra-mcp__send_message_to_session"],
                "allowPathRegex": ["^~/.orchestra/.*"]
            }
        }

        try:
            with open(settings_path, "w") as f:
                json.dump(settings_config, f, indent=2)
            logger.info(f"Created settings.json with MCP permissions at {settings_path}")
        except Exception as e:
            logger.error(f"Failed to create settings.json: {e}")

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
