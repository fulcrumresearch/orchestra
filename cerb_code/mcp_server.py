#!/usr/bin/env python3
"""MCP server for spawning sub-agents in Cerb/Kerberos system."""

import sys
from pathlib import Path

from mcp.server import FastMCP

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.sessions import load_sessions, save_sessions, find_session
from lib.tmux_agent import TmuxProtocol

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
    try:
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

    except Exception as e:
        return f"Error spawning subagent: {str(e)}"


def main():
    """Entry point for MCP server."""
    # Run the stdio server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()