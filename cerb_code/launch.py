#!/usr/bin/env python3
"""Launcher for Cerb's tmux workspace.

This script mirrors the behaviour of the previous ``launch.sh``
implementation while using the shared tmux helpers from ``cerb_code``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from cerb_code.lib.tmux import TMUX_SOCKET, tmux_env


TMUX_BIN = shutil.which("tmux")


class LaunchError(RuntimeError):
    """Custom error for launch failures."""


def ensure_tmux_available() -> None:
    """Ensure tmux binary is available on PATH."""

    if TMUX_BIN is None:
        print(
            "Error: tmux not found. Install tmux first (apt/brew install tmux).",
            file=sys.stderr,
        )
        raise LaunchError("tmux command not found")


def run_orchestra_tmux(
    args: Sequence[str],
    *,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a tmux command against the shared orchestra socket."""

    if TMUX_BIN is None:
        raise LaunchError("tmux command not available")

    cmd = [TMUX_BIN, "-L", TMUX_SOCKET, *args]
    return subprocess.run(
        cmd,
        env=tmux_env(),
        text=True,
        capture_output=capture_output,
        check=check,
    )


def run_current_tmux(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a tmux command in the current tmux session (no alternate socket)."""

    if TMUX_BIN is None:
        raise LaunchError("tmux command not available")

    cmd = [TMUX_BIN, *args]
    return subprocess.run(cmd, check=check)


def kill_session(session_name: str) -> None:
    """Kill an existing tmux session, ignoring failures."""

    run_orchestra_tmux(
        ["kill-session", "-t", session_name],
        check=False,
        capture_output=True,
    )


def get_window_width(target_prefix: str | None) -> int:
    """Return the tmux window width for the provided target."""

    args = ["display-message", "-p"]
    if target_prefix:
        args.extend(["-t", target_prefix])
    args.append("#{window_width}")

    result = run_orchestra_tmux(args, capture_output=True, check=False)
    if result.returncode != 0:
        return 0

    try:
        return int(result.stdout.strip())
    except (TypeError, ValueError):
        return 0


def split_left_and_right(target_prefix: str | None, left_size: int) -> None:
    """Create a left/right split with the requested size."""

    args: list[str] = ["split-window", "-h", "-b", "-l", str(left_size)]
    if target_prefix:
        args.extend(["-t", target_prefix])
    run_orchestra_tmux(args)


def split_sidebar(target_prefix: str | None) -> None:
    """Split the left pane into sidebar/editor layout."""

    left_pane = f"{target_prefix}.0" if target_prefix else "0"
    run_orchestra_tmux(["split-window", "-t", left_pane, "-v", "-l", "8"])


def send_keys(pane_target: str, *keys: str) -> None:
    """Send keys to the specified pane."""

    if not keys:
        return

    run_orchestra_tmux(["send-keys", "-t", pane_target, *keys])


def initialize_panes(target_prefix: str | None) -> None:
    """Seed panes with their startup commands."""

    pane_targets = ["0", "1", "2"]
    if target_prefix:
        pane_targets = [f"{target_prefix}.{pane}" for pane in pane_targets]

    sidebar_cmd = "cerb-ui"
    editor_cmd = "clear; echo 'Press s to open spec editor'; echo ''"
    claude_cmd = "echo 'Claude sessions will appear here'; echo 'Use the left panel to create or select a session'"

    send_keys(pane_targets[0], sidebar_cmd, "C-m")
    send_keys(pane_targets[1], editor_cmd, "C-m")
    send_keys(pane_targets[2], claude_cmd, "C-m")


def focus_sidebar(target_prefix: str | None) -> None:
    """Set focus to the sidebar pane."""

    pane = f"{target_prefix}.0" if target_prefix else "0"
    run_orchestra_tmux(["select-pane", "-t", pane])


def create_layout(target_prefix: str | None) -> None:
    """Create the full three-pane layout."""

    width = get_window_width(target_prefix) or 200
    left_size = max(width * 50 // 100, 1)

    split_left_and_right(target_prefix, left_size)
    split_sidebar(target_prefix)
    initialize_panes(target_prefix)
    focus_sidebar(target_prefix)


def configure_orchestra_session(session_name: str, window_name: str) -> None:
    """Prepare tmux session defaults before creating layout."""

    run_orchestra_tmux(["new-session", "-d", "-s", session_name, "-n", window_name])
    run_orchestra_tmux(["set", "-t", session_name, "-g", "mouse", "on"])
    run_orchestra_tmux(["bind-key", "-n", "C-s", "select-pane", "-t", ":.+"])


def open_nested_window(window_name: str, attach_command: str) -> None:
    """Open a window in the current (outer) tmux session and run command."""

    run_current_tmux(["new-window", "-n", window_name])
    run_current_tmux(["send-keys", "-t", window_name, attach_command, "C-m"])


def sanitize_repo_name(name: str) -> str:
    """Replace characters incompatible with tmux session naming."""

    sanitized = name.replace(" ", "-").replace(":", "-")
    return sanitized or "workspace"


def main() -> int:
    """Entry point for launching the Cerb tmux workspace."""

    try:
        ensure_tmux_available()

        repo_name = sanitize_repo_name(Path.cwd().name)
        session_name = f"cerb-{repo_name}"
        window_name = "main"
        target_prefix = f"{session_name}:{window_name}"

        inside_tmux = bool(os.environ.get("TMUX"))

        kill_session(session_name)
        configure_orchestra_session(session_name, window_name)
        create_layout(target_prefix)

        if inside_tmux:
            nested_window = f"cerb-{repo_name}"
            attach_cmd = f"TMUX= tmux -L {TMUX_SOCKET} attach-session -t {session_name}"
            open_nested_window(nested_window, attach_cmd)
            return 0

        result = run_orchestra_tmux(["attach-session", "-t", session_name], check=False)
        return result.returncode or 0

    except LaunchError:
        return 1
    except subprocess.CalledProcessError as exc:
        stderr = getattr(exc, "stderr", None)
        details = stderr.strip() if isinstance(stderr, str) and stderr.strip() else str(exc)
        print(f"Error running tmux command: {details}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
