import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
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
    """TMux implementation of the AgentProtocol with Docker containerization"""

    def __init__(
        self,
        default_command: str = "claude",
        mcp_port: int = 8765,
    ):
        """
        Initialize TmuxAgent.

        Args:
            default_command: Default command to run when starting a session
            mcp_port: Port where MCP server is running (default: 8765)
        """
        self.default_command = default_command
        self.mcp_port = mcp_port

    def _get_container_name(self, session_id: str) -> str:
        """Get Docker container name for a session"""
        return f"cerb-{session_id}"

    def _ensure_docker_image(self) -> None:
        """Ensure Docker image exists, build if necessary"""
        # Check if image exists
        result = subprocess.run(
            ["docker", "images", "-q", "cerb-image"],
            capture_output=True,
            text=True,
        )

        if not result.stdout.strip():
            # Image doesn't exist, build it
            dockerfile_path = Path(__file__).parent.parent.parent / "Dockerfile"
            if not dockerfile_path.exists():
                raise RuntimeError(f"Dockerfile not found at {dockerfile_path}")

            logger.info(f"Building Docker image cerb-image...")
            build_result = subprocess.run(
                [
                    "docker",
                    "build",
                    "-t",
                    "cerb-image",
                    "-f",
                    str(dockerfile_path),
                    str(dockerfile_path.parent),
                ],
                capture_output=True,
                text=True,
            )

            if build_result.returncode != 0:
                raise RuntimeError(
                    f"Failed to build Docker image: {build_result.stderr}"
                )
            logger.info("Docker image built successfully")

    def _ensure_credentials_volume(
        self, volume_name: str = "cerb-claude-credentials"
    ) -> str:
        """Ensure a persistent Docker volume exists for Claude credentials.

        Returns the volume name. This volume will be mounted and used to persist
        login artifacts across containers so the user authenticates only once.
        """
        # Check if volume exists
        check = subprocess.run(
            ["docker", "volume", "ls", "-q", "--filter", f"name=^{volume_name}$"],
            capture_output=True,
            text=True,
        )
        if not check.stdout.strip():
            create = subprocess.run(
                ["docker", "volume", "create", volume_name],
                capture_output=True,
                text=True,
            )
            if create.returncode != 0:
                raise RuntimeError(
                    f"Failed to create credentials volume {volume_name}: {create.stderr}"
                )
            logger.info(f"Created credentials volume {volume_name}")
        else:
            logger.info(f"Using existing credentials volume {volume_name}")
        return volume_name

    def _start_container(self, session: "Session") -> None:
        """Start Docker container for a session"""
        if not session.work_path:
            raise ValueError("Work path not set")

        # Ensure Docker image exists
        self._ensure_docker_image()

        container_name = self._get_container_name(session.session_id)

        # Check if container already exists
        check_result = subprocess.run(
            ["docker", "ps", "-a", "-q", "-f", f"name=^{container_name}$"],
            capture_output=True,
            text=True,
        )

        if check_result.stdout.strip():
            # Container exists, check if it's running
            running_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
            )
            if running_check.stdout.strip():
                # Already running, just return
                logger.info(f"Container {container_name} already running")
                return
            else:
                # Stopped container, remove it
                subprocess.run(["docker", "rm", container_name], capture_output=True)

        # Prepare volume mounts
        env_vars = []

        # Always mount worktree at /workspace
        # In paired mode, source_path is a symlink to work_path, so user sees changes there
        mounts = ["-v", f"{session.work_path}:/workspace"]

        # Don't set CLAUDE_CONFIG_DIR - let Claude use default $HOME/.claude in container

        mode = "PAIRED (source symlinked)" if session.paired else "UNPAIRED"
        logger.info(f"Starting container in {mode} mode: worktree at /workspace")

        # Get API key from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            env_vars.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

        # Start container (keep alive with tail -f)
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--add-host",
            "host.docker.internal:host-gateway",  # Allow access to host
            *env_vars,
            *mounts,
            "-w",
            "/workspace",
            "cerb-image",
            "tail",
            "-f",
            "/dev/null",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")

        logger.info(f"Container {container_name} started successfully")

        # Copy user's .claude directory into container (if it exists)
        claude_dir = Path.home() / ".claude"
        if claude_dir.exists():
            copy_result = subprocess.run(
                ["docker", "cp", f"{claude_dir}/.", f"{container_name}:/root/.claude/"],
                capture_output=True,
                text=True,
            )
            if copy_result.returncode == 0:
                logger.info(f"Copied .claude directory into container")
            else:
                logger.warning(
                    f"Failed to copy .claude directory: {copy_result.stderr}"
                )

        # Copy user's .claude.json config file into container and inject MCP config
        self._configure_mcp_in_container(container_name)

    def _configure_mcp_in_container(self, container_name: str) -> None:
        """Copy .claude.json and inject MCP configuration into container"""

        # MCP URL for Docker container (always uses host.docker.internal since this method only runs for Docker)
        mcp_url = f"http://host.docker.internal:{self.mcp_port}/sse"

        # Load user's .claude.json if it exists
        claude_json_path = Path.home() / ".claude.json"
        config = {}
        if claude_json_path.exists():
            try:
                with open(claude_json_path, "r") as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                logger.warning("Failed to parse .claude.json, using empty config")

        # Inject MCP server configuration
        if "mcpServers" not in config:
            config["mcpServers"] = {}

        config["mcpServers"]["cerb-mcp"] = {"url": mcp_url, "type": "sse"}

        # Write modified config to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(config, tmp, indent=2)
            tmp_path = tmp.name

        try:
            # Copy MCP config directly to container
            copy_result = subprocess.run(
                ["docker", "cp", tmp_path, f"{container_name}:/root/.claude.json"],
                capture_output=True,
                text=True,
            )
            if copy_result.returncode == 0:
                logger.info(
                    f"Configured MCP in container .claude.json (URL: {mcp_url})"
                )
            else:
                logger.warning(
                    f"Failed to copy .claude.json to container: {copy_result.stderr}"
                )
        finally:
            # Clean up temp file
            Path(tmp_path).unlink(missing_ok=True)

    def _stop_container(self, session_id: str) -> None:
        """Stop and remove Docker container for a session"""
        container_name = self._get_container_name(session_id)
        logger.info(f"Stopping container {container_name}")
        subprocess.run(["docker", "stop", container_name], capture_output=True)
        subprocess.run(["docker", "rm", container_name], capture_output=True)

    def _exec(
        self, session_id: str, cmd: list[str], use_docker: bool
    ) -> subprocess.CompletedProcess:
        """Execute command (Docker or local mode)"""
        if use_docker:
            container_name = self._get_container_name(session_id)
            # Pass TERM environment variable to Docker container
            return subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "-e",
                    "TERM=xterm-256color",
                    container_name,
                    *cmd,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
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
        if session.use_docker:
            try:
                self._start_container(session)
            except Exception as e:
                logger.error(f"Failed to start container: {e}")
                return False

        # Determine working directory
        work_dir = "/workspace" if session.use_docker else session.work_path

        # Create tmux session (works same way for both Docker and local)
        result = self._exec(
            session.session_id,
            [
                "tmux",
                "new-session",
                "-d",  # detached
                "-s",
                session.session_id,
                "-c",
                work_dir,
                self.default_command,
            ],
            session.use_docker,
        )

        logger.info(
            f"tmux new-session result: returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}"
        )

        if result.returncode == 0:
            # Send Enter to accept the trust prompt
            logger.info(
                f"Starting 2 second wait before sending Enter to {session.session_id}"
            )
            time.sleep(2)  # Give Claude a moment to start
            logger.info(f"Wait complete, now sending Enter to {session.session_id}")
            session.send_message("")
            logger.info(
                f"Sent Enter to session {session.session_id} to accept trust prompt"
            )

        return result.returncode == 0

    def get_status(self, session_id: str, use_docker: bool) -> Dict[str, Any]:
        """
        Get status information for a tmux session.

        Args:
            session_id: ID of the session
            use_docker: Whether this session uses Docker

        Returns:
            dict: Status information including windows count and attached state
        """
        # In Docker mode, first check if container is running
        if use_docker:
            container_name = self._get_container_name(session_id)
            container_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
            )
            if not container_check.stdout.strip():
                return {"exists": False}

        # Check if tmux session exists (same for both modes via _exec)
        check_result = self._exec(
            session_id, ["tmux", "has-session", "-t", session_id], use_docker
        )
        if check_result.returncode != 0:
            return {"exists": False}

        # Get session info (same for both modes via _exec)
        fmt = "#{session_windows}\t#{session_attached}"
        result = self._exec(
            session_id,
            ["tmux", "display-message", "-t", session_id, "-p", fmt],
            use_docker,
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

    def send_message(self, session_id: str, message: str, use_docker: bool) -> bool:
        """Send a message to a tmux session (Docker or local mode)"""
        # Target pane 0 specifically (where Claude runs), not the active pane
        target = f"{session_id}:0.0"
        # Send the literal bytes of the message (same for both modes via _exec)
        r1 = self._exec(
            session_id,
            ["tmux", "send-keys", "-t", target, "-l", "--", message],
            use_docker,
        )
        # Then send a carriage return (equivalent to pressing Enter)
        r2 = self._exec(
            session_id, ["tmux", "send-keys", "-t", target, "C-m"], use_docker
        )
        return r1.returncode == 0 and r2.returncode == 0

    def attach(
        self, session_id: str, target_pane: str = "2", use_docker: bool = False
    ) -> bool:
        """Attach to a tmux session in the specified pane"""
        if use_docker:
            # Docker mode: spawn docker exec command in the pane
            container_name = self._get_container_name(session_id)
            result = subprocess.run(
                [
                    "tmux",
                    "respawn-pane",
                    "-t",
                    target_pane,
                    "-k",
                    "docker",
                    "exec",
                    "-it",
                    container_name,
                    "tmux",
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
                    "respawn-pane",
                    "-t",
                    target_pane,
                    "-k",
                    "sh",
                    "-c",
                    f"TMUX= tmux attach-session -t {session_id}",
                ],
                capture_output=True,
                text=True,
            )

        return result.returncode == 0

    def delete(self, session_id: str, use_docker: bool) -> bool:
        """Delete a tmux session and cleanup (Docker container or local)"""
        if use_docker:
            # Docker mode: stop and remove container (also kills tmux inside)
            self._stop_container(session_id)
        else:
            # Local mode: kill the tmux session
            subprocess.run(
                ["tmux", "kill-session", "-t", session_id],
                capture_output=True,
                text=True,
            )
        return True

    def toggle_pairing(self, session: "Session") -> tuple[bool, str]:
        """
        Toggle pairing mode using symlinks.

        Paired: Move user's dir aside, symlink source → worktree
        Unpaired: Remove symlink, restore user's dir

        Returns: (success, error_message)
        """
        if not session.work_path or not session.source_path:
            return False, "Session not properly initialized"

        source = Path(session.source_path)
        worktree = Path(session.work_path)
        backup = Path(f"{session.source_path}.backup")

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

            session.paired = False

        return True, ""
