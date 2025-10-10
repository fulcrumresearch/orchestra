"""Helper utilities for kerberos"""

import json
import os
import subprocess
import tempfile
import importlib.resources as resources
import shutil

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
    vim_cmd = f"bash -c '$EDITOR {spec_file}; clear; echo \"Press S to open spec editor\"; exec bash'"
    return respawn_pane(PANE_EDITOR, vim_cmd)


def respawn_pane_with_terminal(work_path: Path) -> bool:
    """Open bash in editor pane.

    Args:
        work_path: Path to cd into before starting bash

    Returns:
        True if successful, False otherwise
    """
    bash_cmd = f"bash -c 'cd {work_path} && exec bash'"
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
            dockerfile_path = resources.files('cerb_code') / 'Dockerfile'
        except (ImportError, AttributeError):
            # Fallback for older Python or development mode
            dockerfile_path = Path(__file__).parent.parent / "Dockerfile"

        if not Path(dockerfile_path).exists():
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

        mode = "PAIRED (source symlinked)" if paired else "UNPAIRED"
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
                logger.warning(f"Failed to copy .claude directory: {copy_result.stderr}")

        # Copy user's .claude.json config file into container and inject MCP config
        configure_mcp_in_container(container_name, mcp_port)

        return True

    except Exception as e:
        logger.error(f"Failed to start container: {e}")
        return False


def stop_docker_container(container_name: str) -> None:
    """Stop and remove Docker container"""
    logger.info(f"Stopping container {container_name}")
    subprocess.run(["docker", "stop", container_name], capture_output=True)
    subprocess.run(["docker", "rm", container_name], capture_output=True)


def configure_mcp_in_container(container_name: str, mcp_port: int) -> None:
    """Copy .claude.json and inject MCP configuration into container"""

    # MCP URL for Docker container (always uses host.docker.internal)
    mcp_url = f"http://host.docker.internal:{mcp_port}/sse"

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

    copy_result = subprocess.run(
        ["docker", "cp", tmp_path, f"{container_name}:/root/.claude.json"],
        capture_output=True,
        text=True,
    )
    if copy_result.returncode == 0:
        logger.info(f"Configured MCP in container .claude.json (URL: {mcp_url})")
    else:
        logger.warning(f"Failed to copy .claude.json to container: {copy_result.stderr}")
    Path(tmp_path).unlink(missing_ok=True)


def docker_exec(container_name: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute command in Docker container"""
    return subprocess.run(
        ["docker", "exec", "-i", "-e", "TERM=xterm-256color", container_name, *cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
