"""Tmux command builders and pane management utilities"""

import os
import subprocess
import shutil
import shlex
from pathlib import Path
from collections.abc import Sequence
from typing import Union

from ..logger import get_logger
from ..config import get_tmux_config_path, get_tmux_server_name
from .process import find_available_editor

logger = get_logger(__name__)


# Tmux pane constants
PANE_UI = "0"
PANE_EDITOR = "1"
PANE_AGENT = "2"


# Low-level command builders


def tmux_env() -> dict:
    """Get environment for tmux commands with proper color support."""
    return dict(os.environ, TERM="xterm-256color")


def build_tmux_cmd(*args: str) -> list[str]:
    """Build tmux command for orchestra socket."""
    return ["tmux", "-L", get_tmux_server_name(), *args]


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


# High-level pane management


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
        f'$SHELL -c "{editor} {shlex.quote(str(spec_file))}; clear; echo \\"Press s to open spec editor\\"; exec $SHELL"'
    )
    return respawn_pane(PANE_EDITOR, editor_cmd)


def respawn_pane_with_terminal(work_path: Path) -> bool:
    """Open shell in editor pane.

    Args:
        work_path: Path to cd into before starting shell

    Returns:
        True if successful, False otherwise
    """
    bash_cmd = f'$SHELL -c "cd {shlex.quote(str(work_path))} && exec $SHELL"'
    return respawn_pane(PANE_EDITOR, bash_cmd)
