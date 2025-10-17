"""Tmux command builder and executor for orchestra socket."""

import os
import subprocess
from collections.abc import Sequence
from typing import Union

from .config import get_tmux_config_path


TMUX_SOCKET = "orchestra"


def tmux_env() -> dict:
    """Get environment for tmux commands with proper color support."""
    return dict(os.environ, TERM="xterm-256color")


def build_tmux_cmd(*args: str) -> list[str]:
    """Build tmux command for orchestra socket."""
    return ["tmux", "-L", TMUX_SOCKET, *args]


def execute_local(cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute tmux command locally with orchestra config."""
    # Insert -f flag after "tmux -L orchestra" for local execution
    config_path = str(get_tmux_config_path())
    if cmd[0] == "tmux" and len(cmd) > 2 and cmd[1] == "-L":
        # Insert -f config_path after -L SOCKET
        cmd = cmd[:3] + ["-f", config_path] + cmd[3:]

    return subprocess.run(
        cmd,
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def run_local_tmux_command(*args: str) -> subprocess.CompletedProcess:
    """Execute tmux command on the Orchestra socket in the local machine."""
    return execute_local(build_tmux_cmd(*args))


def build_new_session_cmd(session_id: str, work_dir: str, command: str) -> list[str]:
    """Create new tmux session with status bar disabled.

    Config is auto-loaded:
    - Docker: From /home/executor/.tmux.conf (mounted from host)
    - Local: Via execute_local() which adds -f flag automatically
    """
    return build_tmux_cmd(
        "new-session",
        "-d",
        "-s",
        session_id,
        "-c",
        work_dir,
        command,
        ";",
        "set-option",
        "-t",
        session_id,
        "status",
        "off",
    )


def build_respawn_pane_cmd(pane: str, command: Union[str, Sequence[str]]) -> list[str]:
    """Respawn pane with new command.

    Handles both string and sequence command forms.
    """
    args = ["respawn-pane", "-t", pane, "-k"]
    if isinstance(command, str):
        args.append(command)
    else:
        args.extend(command)
    return build_tmux_cmd(*args)


def is_in_permission_prompt(session_id: str) -> bool:
    """Check if a tmux session is stuck in a permission prompt.

    Args:
        session_id: The tmux session ID

    Returns:
        True if session appears to be in a permission prompt, False otherwise
    """
    # Capture the pane content using run_local_tmux_command
    result = run_local_tmux_command(
        "capture-pane", "-p", "-t", f"{session_id}:0.0"
    )

    if result.returncode != 0:
        return False

    pane_content = result.stdout.lower()

    # Common permission prompt patterns
    permission_patterns = [
        "allow this action",
        "do you want to",
        "are you sure",
        "press enter to continue",
        "(y/n)",
        "permission required",
    ]

    # Check if any pattern is present in the last 20 lines
    last_lines = "\n".join(pane_content.split("\n")[-20:])

    for pattern in permission_patterns:
        if pattern in last_lines:
            return True

    return False


def send_escape(session_id: str) -> bool:
    """Send ESC key to a tmux session to clear prompts.

    Args:
        session_id: The tmux session ID

    Returns:
        True if successful, False otherwise
    """
    result = run_local_tmux_command(
        "send-keys", "-t", f"{session_id}:0.0", "Escape"
    )
    return result.returncode == 0
