#!/usr/bin/env python3
"""Orchestra UI entry point - minimal launcher"""

import os
import subprocess
from pathlib import Path

from orchestra.frontend.app import UnifiedApp
from orchestra.lib.logger import get_logger
from orchestra.lib.config import load_config
from orchestra.lib.tmux import build_tmux_cmd, execute_local
from orchestra.lib.helpers import kill_process_gracefully, cleanup_pairing_artifacts
from orchestra.lib.sessions import load_sessions

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

    def cleanup_servers():
        """Clean up background servers and pairing artifacts on exit"""
        # Clean up pairing artifacts for all sessions
        logger.info("Cleaning up pairing artifacts for all sessions")
        sessions = load_sessions(flat=True)
        for session in sessions:
            if not session.source_path:
                continue
            try:
                cleanup_pairing_artifacts(session.source_path, session.session_id)
            except Exception as e:
                logger.error(f"Error cleaning up pairing artifacts for session {session.session_id}: {e}")

        logger.info("Shutting down MCP server")
        kill_process_gracefully(mcp_proc)

        if START_MONITOR:
            logger.info("Shutting down monitor server")
            kill_process_gracefully(monitor_proc)

        # Kill the tmux server
        logger.info("Shutting down tmux server")
        try:
            execute_local(build_tmux_cmd("kill-server"))
        except Exception as e:
            logger.debug(f"Error killing tmux server: {e}")

    try:
        UnifiedApp(shutdown_callback=cleanup_servers).run()
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        cleanup_servers()
        raise


if __name__ == "__main__":
    main()
