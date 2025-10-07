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
        use_docker: bool = True,
        mcp_port: int = 8765,
    ):
        """
        Initialize TmuxAgent.

        Args:
            default_command: Default command to run when starting a session
            use_docker: Whether to use Docker containers (default: True)
            mcp_port: Port where MCP server is running (default: 8765)
        """
        self.default_command = default_command
        self.use_docker = use_docker
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
        mounts = [
            "-v",
            f"{session.work_path}:/workspace",
        ]

        # Add project mount if paired
        if session.paired and session.source_path:
            mounts.extend(["-v", f"{session.source_path}:/project"])
            logger.info(f"Starting container in PAIRED mode: worktree + project")
        else:
            logger.info(f"Starting container in UNPAIRED mode: worktree only")

        # Ensure persistent credentials volume exists and mount it
        cred_volume = self._ensure_credentials_volume()
        mounts.extend(["-v", f"{cred_volume}:/persist/claude"])

        # Get API key from environment
        env_vars = []
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

        # Ensure symlinks inside the container point to the persistent volume
        # so that /root/.claude and /root/.claude.json are backed by the volume.
        setup_cmd = [
            "docker",
            "exec",
            "-i",
            container_name,
            "sh",
            "-lc",
            (
                "set -e; "
                # Create directories in the mounted volume
                "mkdir -p /persist/claude/.claude; "
                # If a real directory exists, migrate its contents then replace with symlink
                "if [ -d /root/.claude ] && [ ! -L /root/.claude ]; then "
                "cp -a /root/.claude/. /persist/claude/.claude/ 2>/dev/null || true; "
                "rm -rf /root/.claude; "
                "fi; "
                # Point $HOME/.claude to the persistent volume
                "ln -sfn /persist/claude/.claude /root/.claude; "
                # Handle .claude.json file similarly
                "touch /persist/claude/.claude.json; "
                "if [ -f /root/.claude.json ] && [ ! -L /root/.claude.json ]; then "
                "cp -a /root/.claude.json /persist/claude/.claude.json 2>/dev/null || true; "
                "rm -f /root/.claude.json; "
                "fi; "
                # Point $HOME/.claude.json to the persistent volume
                "ln -sfn /persist/claude/.claude.json /root/.claude.json"
            ),
        ]
        setup_result = subprocess.run(setup_cmd, capture_output=True, text=True)
        if setup_result.returncode == 0:
            logger.info(
                "Configured persistent Claude credentials volume and symlinks in container"
            )
        else:
            logger.warning(
                f"Failed to configure persistent credentials volume: {setup_result.stderr}"
            )

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

        # Determine MCP URL based on mode
        if self.use_docker:
            mcp_url = f"http://host.docker.internal:{self.mcp_port}/sse"
        else:
            mcp_url = f"http://localhost:{self.mcp_port}/sse"

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
            # Write the config into the persistent path (if present) to survive container lifecycle
            # Prefer writing via docker exec into /persist/claude/.claude.json if it exists
            exec_write = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    container_name,
                    "sh",
                    "-lc",
                    "mkdir -p /persist/claude; touch /persist/claude/.claude.json",
                ],
                capture_output=True,
                text=True,
            )

            target_path = f"{container_name}:/root/.claude.json"
            # If persistent mount exists, prefer that as the target for durability
            if exec_write.returncode == 0:
                target_path = f"{container_name}:/persist/claude/.claude.json"

            copy_result = subprocess.run(
                ["docker", "cp", tmp_path, target_path],
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

    def _exec(self, session_id: str, cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute command (Docker or local mode)"""
        if self.use_docker:
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
        if self.use_docker:
            try:
                self._start_container(session)
            except Exception as e:
                logger.error(f"Failed to start container: {e}")
                return False

        # Determine working directory
        work_dir = "/workspace" if self.use_docker else session.work_path

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
            container_name = self._get_container_name(session_id)
            container_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name=^{container_name}$"],
                capture_output=True,
                text=True,
            )
            if not container_check.stdout.strip():
                return {"exists": False}

        # Check if tmux session exists (same for both modes via _exec)
        check_result = self._exec(session_id, ["tmux", "has-session", "-t", session_id])
        if check_result.returncode != 0:
            return {"exists": False}

        # Get session info (same for both modes via _exec)
        fmt = "#{session_windows}\t#{session_attached}"
        result = self._exec(
            session_id, ["tmux", "display-message", "-t", session_id, "-p", fmt]
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
            session_id, ["tmux", "send-keys", "-t", target, "-l", "--", message]
        )
        # Then send a carriage return (equivalent to pressing Enter)
        r2 = self._exec(session_id, ["tmux", "send-keys", "-t", target, "C-m"])
        return r1.returncode == 0 and r2.returncode == 0

    def attach(self, session_id: str, target_pane: str = "2") -> bool:
        """Attach to a tmux session in the specified pane"""
        if self.use_docker:
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

    def delete(self, session_id: str) -> bool:
        """Delete a tmux session and cleanup (Docker container or local)"""
        if self.use_docker:
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
