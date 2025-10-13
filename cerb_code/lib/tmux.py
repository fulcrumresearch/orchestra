"""Tmux command builder and executor for orchestra socket."""

import os
import subprocess
from collections.abc import Sequence
from typing import Union


TMUX_SOCKET = "orchestra"


def tmux_env() -> dict:
    """Get environment for tmux commands with proper color support."""
    return dict(os.environ, TERM="xterm-256color")


def build_tmux_cmd(*args: str) -> list[str]:
    """Build tmux command for orchestra socket."""
    return ["tmux", "-L", TMUX_SOCKET, *args]


def execute_local(cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute tmux command locally."""
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

    Chains session creation with status configuration.
    """
    return build_tmux_cmd(
        "new-session", "-d", "-s", session_id, "-c", work_dir, command, ";", "set-option", "-t", session_id, "status", "off"
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
