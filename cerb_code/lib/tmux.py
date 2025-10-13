"""Centralized tmux command builders and executor.

This module provides a single source of truth for all tmux command construction.
All tmux commands should be built using these builders to ensure consistency.
"""

import os
import subprocess
from collections.abc import Sequence
from typing import Union


# Constants
TMUX_SOCKET = "orchestra"  # Socket name for all tmux servers


def tmux_env() -> dict:
    """Get environment for tmux commands.

    Returns:
        Environment dictionary with TERM set for proper color support
    """
    return dict(os.environ, TERM="xterm-256color")


def _build_tmux_cmd(*args: str) -> list[str]:
    """Build command with tmux prefix."""
    return ["tmux", "-L", TMUX_SOCKET, *args]


# Command Builders (Pure Functions)
# These return command arrays, don't execute


def build_new_session_cmd(session_id: str, work_dir: str, command: str) -> list[str]:
    """Build command to create new tmux session with status bar disabled.

    Args:
        session_id: Unique identifier for the session
        work_dir: Working directory for the session
        command: Command to run in the session

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd(
        "new-session", "-d", "-s", session_id, "-c", work_dir, command, ";", "set-option", "-t", session_id, "status", "off"
    )


def build_has_session_cmd(session_id: str) -> list[str]:
    """Build command to check if session exists.

    Args:
        session_id: Session identifier to check

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("has-session", "-t", session_id)


def build_display_message_cmd(session_id: str, format_str: str) -> list[str]:
    """Build command to get session info.

    Args:
        session_id: Session identifier
        format_str: tmux format string (e.g., "#{session_windows}")

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("display-message", "-t", session_id, "-p", format_str)


def build_set_buffer_cmd(content: str) -> list[str]:
    """Build command to set paste buffer.

    Args:
        content: Content to store in paste buffer

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("set-buffer", content)


def build_paste_buffer_cmd(target: str) -> list[str]:
    """Build command to paste buffer to target.

    Args:
        target: Target pane (e.g., "session_id:0.0")

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("paste-buffer", "-t", target)


def build_send_keys_cmd(target: str, *keys: str) -> list[str]:
    """Build command to send keys to target.

    Args:
        target: Target pane (e.g., "session_id:0.0")
        *keys: Keys to send (e.g., "C-m" for Enter)

    Returns:
        Command array ready for execution
    """
    if not keys:
        raise ValueError("build_send_keys_cmd requires at least one key")
    return _build_tmux_cmd("send-keys", "-t", target, *keys)


def build_respawn_pane_cmd(pane: str, command: Union[str, Sequence[str]]) -> list[str]:
    """Build command to respawn pane with new command.

    Args:
        pane: Pane identifier
        command: Command (string or argument sequence) to run in the respawned pane

    Returns:
        Command array ready for execution
    """
    args = ["respawn-pane", "-t", pane, "-k"]
    if isinstance(command, str):
        args.append(command)
    else:
        args.extend(command)
    return _build_tmux_cmd(*args)


def build_kill_session_cmd(session_id: str) -> list[str]:
    """Build command to kill session.

    Args:
        session_id: Session identifier to kill

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("kill-session", "-t", session_id)


def build_kill_server_cmd() -> list[str]:
    """Build command to kill tmux server.

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("kill-server")


def build_attach_session_cmd(session_id: str) -> list[str]:
    """Build command to attach to session.

    Args:
        session_id: Session identifier to attach to

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("attach-session", "-t", session_id)


def build_set_option_cmd(option: str, value: str, global_option: bool = False, target: str = None) -> list[str]:
    """Build command to set tmux option.

    Args:
        option: Option name (e.g., "status")
        value: Option value (e.g., "off")
        global_option: If True, sets global option (-g flag)
        target: Target session (ignored if global_option is True)

    Returns:
        Command array ready for execution
    """
    args = ["set-option"]
    if global_option:
        args.append("-g")
    elif target:
        args.extend(["-t", target])
    args.extend([option, value])
    return _build_tmux_cmd(*args)


def build_new_session_with_window_cmd(session_id: str, window_name: str) -> list[str]:
    """Build command to create new tmux session with named window and status off.

    Args:
        session_id: Unique identifier for the session
        window_name: Name for the first window

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd(
        "new-session", "-d", "-s", session_id, "-n", window_name, ";",
        "set-option", "-t", session_id, "status", "off"
    )


def build_bind_key_cmd(key: str, *command_args: str, prefix: bool = True) -> list[str]:
    """Build command to bind a key.

    Args:
        key: Key to bind (e.g., "C-s")
        *command_args: Command arguments to execute when key is pressed
        prefix: If False, use -n flag for no prefix required

    Returns:
        Command array ready for execution
    """
    args = ["bind-key"]
    if not prefix:
        args.append("-n")
    args.append(key)
    args.extend(command_args)
    return _build_tmux_cmd(*args)


def build_split_window_cmd(
    target: str = None,
    horizontal: bool = False,
    before: bool = False,
    size: int = None
) -> list[str]:
    """Build command to split a window.

    Args:
        target: Target pane to split
        horizontal: If True, split horizontally (side by side)
        before: If True, create new pane before target
        size: Size of new pane in lines/columns

    Returns:
        Command array ready for execution
    """
    args = ["split-window"]
    if horizontal:
        args.append("-h")
    else:
        args.append("-v")
    if before:
        args.append("-b")
    if size is not None:
        args.extend(["-l", str(size)])
    if target:
        args.extend(["-t", target])
    return _build_tmux_cmd(*args)


def build_select_pane_cmd(target: str) -> list[str]:
    """Build command to select a pane.

    Args:
        target: Pane target to select

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("select-pane", "-t", target)


def build_new_window_cmd(window_name: str) -> list[str]:
    """Build command to create a new window.

    Args:
        window_name: Name for the new window

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("new-window", "-n", window_name)


# Local Executor


def execute_local(cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute tmux command locally (for UI layer).

    Args:
        cmd: Command array to execute

    Returns:
        CompletedProcess with stdout, stderr, and returncode
    """
    return subprocess.run(
        cmd,
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
