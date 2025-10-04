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


def get_source_path() -> Path:
    """Get the source path for this session by reading .claude/source_path file"""
    source_path_file = Path.cwd() / ".claude" / "source_path"

    if source_path_file.exists():
        return Path(source_path_file.read_text().strip())

    # Fallback to cwd if file doesn't exist (for backward compatibility)
    return Path.cwd()


@mcp.tool()
def spawn_subagent(
    parent_session_id: str, child_session_id: str, instructions: str
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
    # Get source path for session lookups (handles worktrees correctly)
    source_path = get_source_path()

    # Load sessions from source path
    sessions = load_sessions(protocol=protocol, project_dir=source_path)

    # Find parent session
    parent = find_session(sessions, parent_session_id)

    if not parent:
        return f"Error: Parent session '{parent_session_id}' not found"

    # Spawn the executor (this adds child to parent.children in memory)
    child = parent.spawn_executor(child_session_id, instructions)

    # Save updated sessions
    save_sessions(sessions, project_dir=source_path)

    return f"Successfully spawned child session '{child_session_id}' under parent '{parent_session_id}'"


@mcp.tool()
def send_message_to_session(session_id: str, message: str) -> str:
    """
    Send a message to a specific Claude session.

    Args:
        session_id: ID of the session to send the message to
        message: Message to send to the session

    Returns:
        Success or error message
    """
    # Get source path for session lookups (handles worktrees correctly)
    source_path = get_source_path()

    # Load sessions from source path
    sessions = load_sessions(protocol=protocol, project_dir=source_path)

    # Find target session
    target = find_session(sessions, session_id)

    if not target:
        return f"Error: Session '{session_id}' not found"

    target.send_message(message)
    return f"Successfully sent message to session '{session_id}'"


def main():
    """Entry point for MCP server."""
    import sys

    # Get port from command line args or use default
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

    # Run the HTTP/SSE server
    print(f"Starting MCP server on port {port}...")
    mcp.run(transport="sse", port=port, host="0.0.0.0")


if __name__ == "__main__":
    main()
