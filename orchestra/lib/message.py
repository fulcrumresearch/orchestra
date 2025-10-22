"""Message object for Orchestra inter-session communication."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json


@dataclass
class Message:
    """Represents a message sent between sessions."""

    recipient: str  # target/recipient session name
    sender: str  # sender session name
    message: str  # message content
    timestamp: str  # ISO format timestamp


def load_messages(project_dir: Path) -> list[Message]:
    """Load all messages from the project's messages.jsonl file.

    Args:
        project_dir: Path to the project directory

    Returns:
        List of Message objects
    """
    messages_path = project_dir / ".orchestra" / "messages.jsonl"

    if not messages_path.exists():
        return []

    messages = []
    with open(messages_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                msg = Message(
                    recipient=data.get("recipient", ""),
                    sender=data.get("sender", ""),
                    message=data.get("message", ""),
                    timestamp=data.get("timestamp", datetime.now().isoformat()),
                )
                messages.append(msg)
            except (json.JSONDecodeError, KeyError):
                continue

    return messages


def load_session_messages(project_dir: Path, session_name: str | None = None, is_designer: bool = False) -> list[Message]:
    """Load messages for a specific session.

    For designers (session_name=None): Returns all messages (no filter).
    For executors (session_name provided): Returns messages where the session is either the sender or the target (source).

    Args:
        project_dir: Path to the project directory
        session_name: Name of the session to filter by (None for designer mode)
        is_designer: If True, return all messages (no filtering)

    Returns:
        List of Message objects
    """
    all_messages = load_messages(project_dir)

    if is_designer or session_name is None:
        return all_messages

    return [msg for msg in all_messages if msg.recipient == session_name or msg.sender == session_name]
