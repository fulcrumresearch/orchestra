#!/usr/bin/env python3
"""MCP server for spawning sub-agents in Cerb/Kerberos system."""

import sys
from pathlib import Path

from mcp.server import FastMCP

from cerb_code.lib.sessions import load_sessions, save_session, find_session

# Create FastMCP server instance
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
host = "0.0.0.0"
mcp = FastMCP("cerb-subagent", port=port, host=host)


@mcp.tool()
def spawn_subagent(parent_session_id: str, child_session_id: str, instructions: str, source_path: str) -> str:
    """
    Spawn a child Claude session with specific instructions.

    Args:
        parent_session_id: ID of the parent session
        child_session_id: ID for the new child session
        instructions: Instructions to give to the child session
        source_path: Source path of the parent session's project

    Returns:
        Success message with child session ID, or error message
    """
    # Load sessions from source path
    sessions = load_sessions(project_dir=Path(source_path))

    # Find parent session
    parent = find_session(sessions, parent_session_id)

    if not parent:
        return f"Error: Parent session '{parent_session_id}' not found"

    # Spawn the executor (this adds child to parent.children in memory)
    child = parent.spawn_executor(child_session_id, instructions)

    # Save updated parent session
    save_session(parent, project_dir=Path(source_path))

    return f"Successfully spawned child session '{child_session_id}' under parent '{parent_session_id}'"


@mcp.tool()
def send_message_to_session(session_id: str, message: str, source_path: str) -> str:
    """
    Send a message to a specific Claude session.

    Args:
        session_id: ID of the session to send the message to
        message: Message to send to the session
        source_path: Source path of the project

    Returns:
        Success or error message
    """
    # Load sessions from source path
    sessions = load_sessions(project_dir=Path(source_path))

    # Find target session
    target = find_session(sessions, session_id)

    if not target:
        return f"Error: Session '{session_id}' not found"

    target.send_message(message)
    return f"Successfully sent message to session '{session_id}'"


def main():
    """Entry point for MCP server."""
    # Run the SSE server
    print(f"Starting MCP server on port {port}...")
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
