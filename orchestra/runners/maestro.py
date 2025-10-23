#!/usr/bin/env python3
"""Orchestra UI entry point - minimal launcher"""

import os
import subprocess
from pathlib import Path

from orchestra.frontend.app import UnifiedApp
from orchestra.lib.logger import get_logger
from orchestra.lib.config import load_config
from orchestra.lib.helpers.tmux import build_tmux_cmd, execute_local
from orchestra.lib.helpers.process import kill_process_gracefully

logger = get_logger(__name__)

START_MONITOR = True


def main():
    """Entry point for the unified UI"""
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance

    # Check if orchestra-main session already exists

    # If we get here, no session exists or attach failed - proceed with normal startup
    logger.info("Starting new Orchestra session...")

    # Clear the message queue on startup
    messages_file = Path.cwd() / ".orchestra" / "messages.jsonl"
    if messages_file.exists():
        messages_file.unlink()
        logger.debug("Cleared messages queue")

    # Start the MCP server in the background (HTTP transport)
    mcp_log = Path.home() / ".orchestra" / "mcp-server.log"
    mcp_log.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"MCP server logs: {mcp_log}")

    with open(mcp_log, "w") as log_file:
        mcp_proc = subprocess.Popen(
            ["orchestra-mcp"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    logger.info(f"MCP server started with PID {mcp_proc.pid}")

    # Start the monitoring server in the background
    if START_MONITOR:
        monitor_port = 8081
        monitor_log = Path.home() / ".orchestra" / "monitor-server.log"
        monitor_log.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting monitor server on port {monitor_port}")
        logger.info(f"Monitor server logs: {monitor_log}")

        with open(monitor_log, "w") as log_file:
            monitor_proc = subprocess.Popen(
                ["orchestra-monitor-server", str(monitor_port)],
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        logger.info(f"Monitor server started with PID {monitor_proc.pid}")

    def cleanup():
        """Clean up background servers on exit"""
        logger.info("Shutting down MCP server")
        kill_process_gracefully(mcp_proc)

        if START_MONITOR:
            logger.info("Shutting down monitor server")
            kill_process_gracefully(monitor_proc)

        # remove doc injection
        claude_path = Path.cwd() / ".claude" / "CLAUDE.md"
        if claude_path.exists():
            claude_path.write_text(claude_path.read_text().replace("@orchestra.md", ""))

        logger.info("Shutting down tmux server")
        try:
            execute_local(build_tmux_cmd("kill-server"))
        except Exception as e:
            logger.debug(f"Error killing tmux server: {e}")

    try:
        UnifiedApp(shutdown_callback=cleanup).run()
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        cleanup()
        raise


if __name__ == "__main__":
    main()
