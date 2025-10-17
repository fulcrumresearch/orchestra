"""Helper utilities for Orchestra"""

import json
import os
import platform
import signal
import subprocess
import importlib.resources as resources
import shutil
import shlex
from pathlib import Path

from .logger import get_logger
from .tmux import build_respawn_pane_cmd
from .prompts import DESIGNER_MD_TEMPLATE, DOC_MD_TEMPLATE, ARCHITECTURE_MD_TEMPLATE


logger = get_logger(__name__)


# Sessions file path (shared constant)
SESSIONS_FILE = Path.home() / ".orchestra" / "sessions.json"


def kill_process_gracefully(proc: subprocess.Popen, timeout: int = 5) -> None:
    """Kill a server process gracefully with SIGTERM, fallback to SIGKILL if needed.

    Args:
        proc: The subprocess.Popen process to kill
        timeout: Seconds to wait for graceful shutdown (default: 5)

    The function will:
    1. Send SIGTERM to the process group
    2. Wait up to timeout seconds for graceful shutdown
    3. If timeout, send SIGKILL and wait indefinitely
    4. Silently handle ProcessLookupError if process already gone
    """
    try:
        pgid = os.getpgid(proc.pid)

        # Try graceful shutdown with SIGTERM
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=timeout)
        logger.info(f"Process {proc.pid} terminated gracefully")

    except subprocess.TimeoutExpired:
        # Force kill if graceful shutdown times out
        logger.warning(f"Process {proc.pid} did not terminate after {timeout}s, sending SIGKILL")
        os.killpg(pgid, signal.SIGKILL)
        proc.wait()  # Wait indefinitely for SIGKILL to complete
        logger.info(f"Process {proc.pid} killed")

    except ProcessLookupError:
        logger.debug(f"Process {proc.pid} already gone")


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
        build_respawn_pane_cmd(pane, command),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def find_available_editor() -> str | None:
    """Find the first available editor from the fallback chain.

    Tries editors in this order:
    1. $EDITOR environment variable (if set)
    2. code (VS Code)
    3. nano
    4. vim

    Returns:
        The command for the first available editor, or None if none found
    """
    # Check $EDITOR environment variable first
    editor_env = os.environ.get("EDITOR")
    if editor_env:
        # Check if the editor command exists
        editor_cmd = editor_env.split()[0]  # Get just the command, not args
        if shutil.which(editor_cmd):
            return editor_env

    # Try fallback editors in order
    fallback_editors = ["code", "nano", "vim"]
    for editor in fallback_editors:
        if shutil.which(editor):
            return editor

    return None


def respawn_pane_with_vim(spec_file: Path) -> bool:
    """Open an editor in the editor pane.

    Args:
        spec_file: Path to the file to open

    Returns:
        True if successful, False otherwise
    """
    editor = find_available_editor()

    if not editor:
        logger.error("No editor found. Please install nano, vim, or VS Code, or set the $EDITOR environment variable.")
        return False

    editor_cmd = (
        f'bash -c "{editor} {shlex.quote(str(spec_file))}; clear; echo \\"Press s to open spec editor\\"; exec bash"'
    )
    return respawn_pane(PANE_EDITOR, editor_cmd)


def respawn_pane_with_terminal(work_path: Path) -> bool:
    """Open bash in editor pane.

    Args:
        work_path: Path to cd into before starting bash

    Returns:
        True if successful, False otherwise
    """
    bash_cmd = f'bash -c "cd {shlex.quote(str(work_path))} && exec bash"'
    return respawn_pane(PANE_EDITOR, bash_cmd)


# Docker Helper Functions


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
            dockerfile_path = Path(__file__).parent.parent / "Dockerfile"

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
        shared_claude_dir = Path.home() / ".orchestra" / "shared-claude"
        shared_claude_json = Path.home() / ".orchestra" / "shared-claude.json"
        ensure_shared_claude_config(shared_claude_dir, shared_claude_json, mcp_port)

        # Mount shared .claude directory and .claude.json for all executor agents
        # This is separate from host's ~/.claude to avoid conflicts
        mounts.extend(
            ["-v", f"{shared_claude_dir}:/home/executor/.claude", "-v", f"{shared_claude_json}:/home/executor/.claude.json"]
        )

        # Mount tmux config file for agent sessions to default location
        from .config import get_tmux_config_path

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
    mcp_url = f"http://host.docker.internal:{mcp_port}/mcp"

    # Initialize or update shared .claude.json
    config = {}

    # Load existing config if it exists
    if shared_claude_json.exists():
        with open(shared_claude_json, "r") as f:
            config = json.load(f)
        return None

    # On Linux, copy auth settings from host's .claude directory and .claude.json
    if platform.system() == "Linux":
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


def ensure_orchestra_directory(project_dir: Path) -> tuple[Path, Path]:
    """Ensure .orchestra/ directory exists with designer.md, doc.md, and docs/architecture.md templates,
    and create a .gitignore file inside .orchestra/ to manage what gets committed.

    Args:
        project_dir: Path to the project directory

    Returns:
        Tuple of (designer_md_path, doc_md_path)
    """
    orchestra_dir = project_dir / ".orchestra"
    orchestra_dir.mkdir(exist_ok=True)

    # Create .gitignore inside .orchestra/ to ignore most content but preserve docs and markdown files
    gitignore_path = orchestra_dir / ".gitignore"
    gitignore_content = "*"
    if not gitignore_path.exists():
        gitignore_path.write_text(gitignore_content)
        logger.info(f"Created .gitignore at {gitignore_path}")

    # Create docs directory
    docs_dir = orchestra_dir / "docs"
    docs_dir.mkdir(exist_ok=True)

    designer_md = orchestra_dir / "designer.md"
    doc_md = orchestra_dir / "doc.md"
    architecture_md = docs_dir / "architecture.md"

    # Create designer.md with template if it doesn't exist
    if not designer_md.exists():
        designer_md.write_text(DESIGNER_MD_TEMPLATE)
        logger.info(f"Created designer.md with template at {designer_md}")

    # Create doc.md with template if it doesn't exist
    if not doc_md.exists():
        doc_md.write_text(DOC_MD_TEMPLATE)
        logger.info(f"Created doc.md with template at {doc_md}")

    # Create architecture.md with template if it doesn't exist
    if not architecture_md.exists():
        architecture_md.write_text(ARCHITECTURE_MD_TEMPLATE)
        logger.info(f"Created architecture.md with template at {architecture_md}")

    return designer_md, doc_md


def is_first_run(project_dir: Path | None = None) -> bool:
    """Check if this is the first run for a project (no sessions in sessions.json)

    Args:
        project_dir: Path to the project directory. Defaults to current directory.

    Returns:
        True if no sessions exist for the project, False otherwise
    """
    if project_dir is None:
        project_dir = Path.cwd()

    project_dir_str = str(project_dir)

    if not SESSIONS_FILE.exists():
        return True

    try:
        with open(SESSIONS_FILE, "r") as f:
            data = json.load(f)
            project_sessions = data.get(project_dir_str, [])
            return len(project_sessions) == 0
    except (json.JSONDecodeError, KeyError):
        return True
