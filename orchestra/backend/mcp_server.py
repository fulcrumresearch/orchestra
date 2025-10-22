#!/usr/bin/env python3
"""MCP server for spawning sub-agents in Orchestra system."""

import json
from datetime import datetime
from pathlib import Path

from mcp.server import FastMCP

from orchestra.lib.sessions import load_sessions, save_session, find_session, AgentType
from orchestra.lib.config import load_config

# Create FastMCP server instance with default port
# (port can be overridden when running as script)
config = load_config()
default_port = config.get("mcp_port", 8765)
host = "0.0.0.0"
mcp = FastMCP("orchestra-subagent", port=default_port, host=host)


@mcp.tool()
def spawn_subagent(parent_session_name: str, child_session_name: str, instructions: str, source_path: str) -> str:
    """
    Spawn a child Claude session with specific instructions.

    Args:
        parent_session_name: Name of the parent session (user-facing identifier)
        child_session_name: Name for the new child session (user-facing identifier)
        instructions: Instructions to give to the child session
        source_path: Source path of the parent session's project

    Returns:
        Success message with child session name, or error message
    """
    # Load sessions from source path
    sessions = load_sessions(project_dir=Path(source_path))

    # Find parent session by name
    parent = find_session(sessions, parent_session_name)

    if not parent:
        return f"Error: Parent session '{parent_session_name}' not found"

    # Spawn the executor (this adds child to parent.children in memory)
    child = parent.spawn_executor(child_session_name, instructions)

    # Save updated parent session
    save_session(parent, project_dir=Path(source_path))

    return f"Successfully spawned child session '{child_session_name}' under parent '{parent_session_name}'"


@mcp.tool()
def send_message_to_session(session_name: str, message: str, source_path: str, sender_name: str) -> str:
    """
    Send a message to a specific Claude session.

    Args:
        session_name: Name of the session to send the message to (user-facing identifier)
        message: Message to send to the session
        source_path: Source path of the project
        sender_name: Name of the sender session (for prefixing)

    Returns:
        Success or error message
    """
    # Load sessions from source path
    sessions = load_sessions(project_dir=Path(source_path))

    # Find target session by name
    target = find_session(sessions, session_name)

    if not target:
        return f"Error: Session '{session_name}' not found"

    # add message to message queue with target, sender, and timestamp

    messages_path = Path(source_path) / ".orchestra" / "messages.jsonl"
    messages_path.parent.mkdir(parents=True, exist_ok=True)
    message_obj = {
        "recipient": session_name,  # target/recipient
        "sender": sender_name,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }

    with open(messages_path, "a") as f:
        f.write(json.dumps(message_obj) + "\n")

    # Send via protocol ONLY if target is an executor (not designer)
    if target.agent_type == AgentType.EXECUTOR:
        target.send_message(message, sender_name=sender_name)

    return f"Successfully sent message to session '{session_name}'"


def main():
    """Entry point for MCP server."""
    # Override port if provided via command line
    print("Starting MCP server")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
