#!/usr/bin/env python3
"""Launcher for Orchestra's tmux workspace."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from orchestra.lib.tmux import TMUX_SOCKET, build_tmux_cmd, run_local_tmux_command


TMUX_BIN = shutil.which("tmux") or "tmux"


def main() -> int:
    """Launch Orchestra tmux workspace."""
    try:
        # Setup session names
        repo = Path.cwd().name.replace(" ", "-").replace(":", "-") or "workspace"
        session = f"orchestra-{repo}"
        target = f"{session}:main"

        # Kill old session
        run_local_tmux_command("kill-session", "-t", session)

        # Create new session with config
        run_local_tmux_command(
            "new-session",
            "-d",
            "-s",
            session,
            "-n",
            "main",
            ";",
            "set",
            "-t",
            session,
            "status",
            "off",
            ";",
            "set",
            "-t",
            session,
            "-g",
            "mouse",
            "on",
            ";",
            "bind-key",
            "-n",
            "C-s",
            "select-pane",
            "-t",
            ":.+",
        )

        # Get window width and calculate split
        result = run_local_tmux_command("display-message", "-t", target, "-p", "#{window_width}")
        width = 200  # Default width
        if result.returncode == 0 and result.stdout.strip():
            try:
                width = int(result.stdout.strip())
            except ValueError:
                pass  # Use default width if conversion fails
        left_size = max(width * 50 // 100, 1)

        # Create 3-pane layout
        run_local_tmux_command("split-window", "-t", target, "-h", "-b", "-l", str(left_size))
        run_local_tmux_command("split-window", "-t", f"{target}.0", "-v", "-l", "8")

        # Initialize panes
        run_local_tmux_command("send-keys", "-t", f"{target}.0", "orchestra-ui", "C-m")
        run_local_tmux_command("send-keys", "-t", f"{target}.1", "clear; echo 'Press s to open spec editor'; echo ''", "C-m")
        run_local_tmux_command(
            "send-keys",
            "-t",
            f"{target}.2",
            "echo 'Claude sessions will appear here'; echo 'Use the left panel to create or select a session'",
            "C-m",
        )
        run_local_tmux_command("select-pane", "-t", f"{target}.0")

        # Attach (nested if inside tmux already)
        if os.environ.get("TMUX"):
            subprocess.run([TMUX_BIN, "new-window", "-n", f"orchestra-{repo}"], check=True)
            subprocess.run(
                [
                    TMUX_BIN,
                    "send-keys",
                    "-t",
                    f"orchestra-{repo}",
                    f"TMUX= tmux -L {TMUX_SOCKET} attach-session -t {session}",
                    "C-m",
                ],
                check=True,
            )
            return 0

        return subprocess.run(build_tmux_cmd("attach-session", "-t", session)).returncode

    except subprocess.CalledProcessError as e:
        print(f"tmux error: {e.stderr or e}", file=sys.stderr)
        return e.returncode or 1


if __name__ == "__main__":
    sys.exit(main())
