"""Message queue handler for Orchestra system.

Manages JSONL-based message queue for designer sessions.
Messages are stored in ~/.orchestra/messages.jsonl with one JSON object per line.
"""

import json
import fcntl
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any


MESSAGES_FILE = Path.home() / ".orchestra" / "messages.jsonl"


def append_message(
    target_session: str,
    sender: str,
    message: str,
    source_path: str
) -> str:
    """
    Append a new message to the JSONL message queue.

    Args:
        target_session: Name of the session to send the message to
        sender: Name of the sender session
        message: Message content
        source_path: Source path of the project

    Returns:
        The message ID (UUID)
    """
    # Ensure directory exists
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Create message object
    message_obj = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sender": sender,
        "target": target_session,
        "message": message,
        "source_path": source_path
    }

    # Append to file with file locking for concurrent write safety
    with open(MESSAGES_FILE, "a") as f:
        # Acquire exclusive lock
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            # Write message as single JSON line
            f.write(json.dumps(message_obj) + "\n")
            f.flush()
        finally:
            # Release lock
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return message_obj["id"]


def read_pending_messages(session_name: str) -> List[Dict[str, Any]]:
    """
    Read all pending messages for a specific session.

    Args:
        session_name: Name of the session to read messages for

    Returns:
        List of message objects for the specified session
    """
    if not MESSAGES_FILE.exists():
        return []

    messages = []

    with open(MESSAGES_FILE, "r") as f:
        # Acquire shared lock for reading
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    message_obj = json.loads(line)
                    # Filter messages for this session
                    if message_obj.get("target") == session_name:
                        messages.append(message_obj)
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue
        finally:
            # Release lock
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    return messages
