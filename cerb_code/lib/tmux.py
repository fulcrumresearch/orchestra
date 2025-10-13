"""Centralized tmux command builders and executor.

This module provides a single source of truth for all tmux command construction.
All tmux commands should be built using these builders to ensure consistency.
"""

import os
import subprocess


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
    """Build command to create new tmux session.

    Args:
        session_id: Unique identifier for the session
        work_dir: Working directory for the session
        command: Command to run in the session

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("new-session", "-d", "-s", session_id, "-c", work_dir, command)


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


def build_send_keys_cmd(target: str, keys: str) -> list[str]:
    """Build command to send keys to target.

    Args:
        target: Target pane (e.g., "session_id:0.0")
        keys: Keys to send (e.g., "C-m" for Enter)

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("send-keys", "-t", target, keys)


def build_respawn_pane_cmd(pane: str, command: str) -> list[str]:
    """Build command to respawn pane with new command.

    Args:
        pane: Pane identifier
        command: Command to run in the respawned pane

    Returns:
        Command array ready for execution
    """
    return _build_tmux_cmd("respawn-pane", "-t", pane, "-k", command)


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
