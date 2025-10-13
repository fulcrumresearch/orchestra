"""Helper utilities for kerberos"""

import json
import os
import platform
import subprocess
import importlib.resources as resources
import shutil
import shlex

from pathlib import Path
from .logger import get_logger

logger = get_logger(__name__)


def check_dependencies(require_docker: bool = True) -> tuple[bool, list[str]]:
    """Check if required dependencies are available

    Args:
        require_docker: Whether docker is required (default: True)

    Returns:
        (success, missing_dependencies)
    """
    missing = []

    # Check tmux
    if not shutil.which("tmux"):
        missing.append("tmux (install with: apt install tmux / brew install tmux)")

    # Check claude
    if not shutil.which("claude"):
        missing.append("claude (install with: npm install -g @anthropic-ai/claude-code)")

    # Check docker if required
    if require_docker:
        if not shutil.which("docker"):
            missing.append("docker (install from: https://docs.docker.com/get-docker/)")
        else:
            # Check if docker daemon is running
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                missing.append("docker daemon (not running - start docker service)")

    return (len(missing) == 0, missing)


def get_current_branch(cwd: Path | None = None) -> str:
    """Get the current git branch name"""
    cwd = cwd or Path.cwd()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # Fallback to 'main' if not a git repo
        logger.warning("Not in a git repository, using 'main' as branch name")
        return "main"


# Tmux pane constants
PANE_UI = "0"
PANE_EDITOR = "1"
PANE_AGENT = "2"


def respawn_pane(pane: str, command: str) -> bool:
    """Generic helper to respawn a tmux pane with a command.

    Args:
        pane: The pane number to respawn
        command: The command to run in the pane

    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        ["tmux", "-L", "orchestra", "respawn-pane", "-t", pane, "-k", command],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def respawn_pane_with_vim(spec_file: Path) -> bool:
    """Open vim in editor pane.

    Args:
        spec_file: Path to the file to open in vim

    Returns:
        True if successful, False otherwise
    """
    vim_cmd = f"bash -c '$EDITOR {shlex.quote(str(spec_file))}; clear; echo \"Press S to open spec editor\"; exec bash'"
    return respawn_pane(PANE_EDITOR, vim_cmd)


def respawn_pane_with_terminal(work_path: Path) -> bool:
    """Open bash in editor pane.

    Args:
        work_path: Path to cd into before starting bash

    Returns:
        True if successful, False otherwise
    """
    bash_cmd = f"bash -c 'cd {shlex.quote(str(work_path))} && exec bash'"
    return respawn_pane(PANE_EDITOR, bash_cmd)


# Docker Helper Functions


def get_docker_container_name(session_id: str) -> str:
    """Get Docker container name for a session"""
    return f"cerb-{session_id}"


def ensure_docker_image() -> None:
    """Ensure Docker image exists, build if necessary"""
    # Check if image exists
    result = subprocess.run(
        ["docker", "images", "-q", "cerb-image"],
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        # Image doesn't exist, build it
        # Find Dockerfile in the cerb_code package
        try:
            dockerfile_path = resources.files("cerb_code") / "Dockerfile"
        except (ImportError, AttributeError):
            # Fallback for older Python or development mode
            dockerfile_path = Path(__file__).parent.parent / "Dockerfile"

        if not Path(dockerfile_path).exists():
            raise RuntimeError(f"Dockerfile not found at {dockerfile_path}")

        # Get host user's UID and GID to create matching user in container
        uid = os.getuid()
        gid = os.getgid()

        logger.info(f"Building Docker image cerb-image with USER_ID={uid}, GROUP_ID={gid}...")
        build_result = subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                f"USER_ID={uid}",
                "--build-arg",
                f"GROUP_ID={gid}",
                "-t",
                "cerb-image",
                "-f",
                str(dockerfile_path),
                str(Path(dockerfile_path).parent),
            ],
            capture_output=True,
            text=True,
        )

        if build_result.returncode != 0:
            raise RuntimeError(f"Failed to build Docker image: {build_result.stderr}")
        logger.info("Docker image built successfully")


def start_docker_container(container_name: str, work_path: str, mcp_port: int, paired: bool = False) -> bool:
    """Start Docker container with mounted worktree

    Returns:
        True on success, False on failure
    """
    try:
        # Ensure Docker image exists
        ensure_docker_image()

        # Check if container already exists (exact name match)
        check_result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", container_name],
            capture_output=True,
            text=True,
        )

        if check_result.returncode == 0:
            is_running = check_result.stdout.strip() == "true"
            if is_running:
                logger.info(f"Container {container_name} already running")
                return True
            else:
                subprocess.run(["docker", "rm", container_name], capture_output=True)

        # Prepare volume mounts
        env_vars = []

        # Always mount worktree at /workspace
        mounts = ["-v", f"{work_path}:/workspace"]

        # Ensure shared Claude Code directory and config file exist
        shared_claude_dir = Path.home() / ".kerberos" / "shared-claude"
        shared_claude_json = Path.home() / ".kerberos" / "shared-claude.json"
        ensure_shared_claude_config(shared_claude_dir, shared_claude_json, mcp_port)

        # Mount shared .claude directory and .claude.json for all executor agents
        # This is separate from host's ~/.claude to avoid conflicts
        mounts.extend(
            ["-v", f"{shared_claude_dir}:/home/executor/.claude", "-v", f"{shared_claude_json}:/home/executor/.claude.json"]
        )

        mode = "PAIRED (source symlinked)" if paired else "UNPAIRED"
        logger.info(
            f"Starting container in {mode} mode: worktree at /workspace, shared Claude config at {shared_claude_dir}"
        )

        # Get API key from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if api_key:
            env_vars.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

        # Get host user's UID and GID to run container as matching user
        uid = os.getuid()
        gid = os.getgid()

        # Start container (keep alive with tail -f)
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--user",
            f"{uid}:{gid}",  # Run as host user to match file permissions
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

        return True

    except Exception as e:
        logger.error(f"Failed to start container: {e}")
        return False


def stop_docker_container(container_name: str) -> None:
    """Stop and remove Docker container"""
    logger.info(f"Stopping container {container_name}")
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)


def ensure_shared_claude_config(shared_claude_dir: Path, shared_claude_json: Path, mcp_port: int) -> None:
    """Ensure shared Claude Code directory and config file exist with proper MCP configuration

    This is called once per container start to ensure the shared config is properly initialized.
    All executor containers will mount these same files.

    Args:
        shared_claude_dir: Path to shared .claude directory
        shared_claude_json: Path to shared .claude.json file
        mcp_port: Port for MCP server
    """

    # Ensure shared directory exists
    shared_claude_dir.mkdir(parents=True, exist_ok=True)

    # MCP URL for Docker containers (always uses host.docker.internal)
    mcp_url = f"http://host.docker.internal:{mcp_port}/sse"

    # Initialize or update shared .claude.json
    config = {}

    # Load existing config if it exists
    if shared_claude_json.exists():
        with open(shared_claude_json, "r") as f:
            config = json.load(f)
        return None

    # On Linux, try to copy auth settings from host's .claude.json (if it exists)
    if platform.system() == "Linux":
        host_claude_json = Path.home() / ".claude.json"
        if host_claude_json.exists():
            with open(host_claude_json, "r") as f:
                config = json.load(f)
            logger.info(f"Initialized shared config from host's .claude.json")

    # Inject MCP server configuration
    config.setdefault("mcpServers", {})["cerb-mcp"] = {"url": mcp_url, "type": "sse"}

    # Write config
    with open(shared_claude_json, "w") as f:
        json.dump(config, f, indent=2)

    logger.info(f"Shared Claude config ready at {shared_claude_json} (MCP URL: {mcp_url})")


def docker_exec(container_name: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute command in Docker container"""
    return subprocess.run(
        ["docker", "exec", "-i", "-e", "TERM=xterm-256color", container_name, *cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
