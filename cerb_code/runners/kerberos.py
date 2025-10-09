#!/usr/bin/env python3
"""Kerberos UI entry point - minimal launcher"""

import os
import signal
import subprocess
from pathlib import Path

from cerb_code.frontend.app import UnifiedApp
from cerb_code.lib.logger import get_logger
from cerb_code.lib.config import load_config

logger = get_logger(__name__)

# UnifiedApp is imported from cerb_code.frontend.app above

START_MONITOR = True


def main():
    """Entry point for the unified UI"""
    # Set terminal environment for better performance
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("TMUX_TMPDIR", "/tmp")  # Use local tmp for better performance

    # Load config
    config = load_config()
    mcp_port = config.get("mcp_port", 8765)

    # Start the MCP server in the background
    mcp_log = Path.home() / ".kerberos" / "mcp-server.log"
    mcp_log.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Starting MCP server on port {mcp_port}")
    logger.info(f"MCP server logs: {mcp_log}")

    with open(mcp_log, "w") as log_file:
        mcp_proc = subprocess.Popen(
            ["cerb-mcp", str(mcp_port)],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    logger.info(f"MCP server started with PID {mcp_proc.pid}")

    # Start the monitoring server in the background
    if START_MONITOR:
        monitor_port = 8081
        monitor_log = Path.home() / ".kerberos" / "monitor-server.log"
        monitor_log.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting monitor server on port {monitor_port}")
        logger.info(f"Monitor server logs: {monitor_log}")

        with open(monitor_log, "w") as log_file:
            monitor_proc = subprocess.Popen(
                ["cerb-monitor-server", str(monitor_port)],
                stdout=log_file,
                stderr=log_file,
                start_new_session=True,
            )
        logger.info(f"Monitor server started with PID {monitor_proc.pid}")

    try:
        UnifiedApp().run()
    finally:
        # Clean up servers on exit
        logger.info("Shutting down MCP server")
        try:
            # Kill the process group since we used start_new_session=True
            os.killpg(os.getpgid(mcp_proc.pid), signal.SIGTERM)
            mcp_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(mcp_proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass  # Process already gone

        if START_MONITOR:
            logger.info("Shutting down monitor server")
            try:
                # Kill the process group since we used start_new_session=True
                os.killpg(os.getpgid(monitor_proc.pid), signal.SIGTERM)
                monitor_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(monitor_proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # Process already gone

        # kill the tmux server
        try:
            subprocess.run(
                ["tmux", "-L", "orchestra", "kill-server"],
                capture_output=True,
                text=True,
            )
        except:
            pass


if __name__ == "__main__":
    main()
