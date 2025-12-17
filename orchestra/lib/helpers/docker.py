"""Docker container management utilities"""

import json
import os
import platform
import subprocess
import shutil
import importlib.resources as resources
from pathlib import Path

from ..logger import get_logger
from ..config import get_orchestra_home, get_tmux_config_path

logger = get_logger(__name__)


def get_docker_container_name(session_id: str) -> str:
    """Get Docker container name for a session"""
    return f"orchestra-{session_id}"


def ensure_docker_image() -> None:
    """Ensure Docker image exists, build if necessary"""
    # Check if image exists
    result = subprocess.run(
        ["docker", "images", "-q", "orchestra-image"],
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        # Image doesn't exist, build it
        # Find Dockerfile in the orchestra package
        try:
            dockerfile_path = resources.files("orchestra") / "Dockerfile"
        except (ImportError, AttributeError):
            # Fallback for older Python or development mode
            dockerfile_path = Path(__file__).parent.parent.parent / "Dockerfile"

        if not Path(dockerfile_path).exists():
            raise RuntimeError(f"Dockerfile not found at {dockerfile_path}")

        # Get host user's UID and GID to create matching user in container
        uid = os.getuid()
        gid = os.getgid()

        logger.info(f"Building Docker image orchestra-image with USER_ID={uid}, GROUP_ID={gid}...")
        build_result = subprocess.run(
            [
                "docker",
                "build",
                "--build-arg",
                f"USER_ID={uid}",
                "--build-arg",
                f"GROUP_ID={gid}",
                "-t",
                "orchestra-image",
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


def start_docker_container(
    container_name: str, work_path: str, mcp_port: int, monitor_port: int, paired: bool = False
) -> bool:
    """Start Docker container with mounted worktree

    Args:
        container_name: Name for the container
        work_path: Path to mount as /workspace
        mcp_port: Port for MCP server on host
        monitor_port: Port for monitor server on host
        paired: Whether this is a paired session

    Returns:
        True on success, False on failure
    """
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
    shared_claude_dir = get_orchestra_home() / "shared-claude"
    shared_claude_json = get_orchestra_home() / "shared-claude.json"
    ensure_shared_claude_config(shared_claude_dir, shared_claude_json, mcp_port)

    # Mount shared .claude directory and .claude.json for all executor agents
    # This is separate from host's ~/.claude to avoid conflicts
    mounts.extend(
        ["-v", f"{shared_claude_dir}:/home/executor/.claude", "-v", f"{shared_claude_json}:/home/executor/.claude.json"]
    )

    # Mount tmux config file for agent sessions to default location
    tmux_config_path = get_tmux_config_path()
    mounts.extend(["-v", f"{tmux_config_path}:/home/executor/.tmux.conf:ro"])

    mode = "PAIRED (source symlinked)" if paired else "UNPAIRED"
    logger.info(
        f"Starting container in {mode} mode: worktree at /workspace, shared Claude config at {shared_claude_dir}"
    )

    # Get API key from environment
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if api_key:
        env_vars.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

    # Pass monitor URL to container for hook forwarding
    monitor_url = f"http://localhost:{monitor_port}"
    env_vars.extend(["-e", f"CLAUDE_MONITOR_BASE={monitor_url}"])

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
        "-p",
        f"127.0.0.1:{mcp_port}:{mcp_port}",
        "-p",
        f"127.0.0.1:{monitor_port}:{monitor_port}",
        *env_vars,
        *mounts,
        "-w",
        "/workspace",
        "orchestra-image",
        "tail",
        "-f",
        "/dev/null",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container: {result.stderr}")

    logger.info(f"Container {container_name} started successfully")

    return True


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

    # MCP URL for Docker containers (uses localhost with port forwarding)
    mcp_url = f"http://localhost:{mcp_port}/mcp"

    # Initialize or update shared .claude.json
    config = {}

    # Load existing config if it exists
    if shared_claude_json.exists():
        with open(shared_claude_json, "r") as f:
            config = json.load(f)
    # On Linux, copy auth settings from host's .claude directory and .claude.json
    elif platform.system() == "Linux":
        host_claude_dir = Path.home() / ".claude"
        host_claude_json = Path.home() / ".claude.json"

        # Copy .claude directory if it exists
        if host_claude_dir.exists():
            shutil.copytree(host_claude_dir, shared_claude_dir, dirs_exist_ok=True)
            logger.info(f"Copied .claude directory to {shared_claude_dir}")

        # Load .claude.json if it exists
        if host_claude_json.exists():
            with open(host_claude_json, "r") as f:
                config = json.load(f)
            logger.info(f"Loaded config from host's .claude.json")

    # Inject MCP server configuration (HTTP transport)
    config.setdefault("mcpServers", {})["orchestra-mcp"] = {
        "url": mcp_url,
        "type": "http",
    }

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
