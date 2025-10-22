"""Process management utilities"""

import os
import signal
import subprocess
import shutil

from ..logger import get_logger

logger = get_logger(__name__)


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
