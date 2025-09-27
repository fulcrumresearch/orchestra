#!/usr/bin/env python3
"""MCP server for spawning sub-agents in Cerb/Kerberos system."""

import sys
from pathlib import Path

from mcp.server import FastMCP

from cerb_code.lib.sessions import load_sessions, save_sessions, find_session
from cerb_code.lib.tmux_agent import TmuxProtocol

# Create FastMCP server instance
mcp = FastMCP("cerb-subagent")

# Create a shared protocol for sessions
protocol = TmuxProtocol(default_command="claude")


@mcp.tool()
def spawn_subagent(
    parent_session_id: str,
    child_session_id: str,
    instructions: str
) -> str:
    """
    Spawn a child Claude session with specific instructions.

    Args:
        parent_session_id: ID of the parent session
        child_session_id: ID for the new child session
        instructions: Instructions to give to the child session

    Returns:
        Success message with child session ID, or error message
    """
    # Load existing sessions with the protocol
    sessions = load_sessions(protocol=protocol)

    # Find parent session
    parent = find_session(sessions, parent_session_id)

    if not parent:
        return f"Error: Parent session '{parent_session_id}' not found"

    # Spawn the executor
    child = parent.spawn_executor(child_session_id, instructions)

    # Save updated sessions (with children)
    save_sessions(sessions)

    return f"Successfully spawned child session '{child_session_id}' under parent '{parent_session_id}'"


def main():
    """Entry point for MCP server."""
    # Run the stdio server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
