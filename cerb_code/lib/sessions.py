from enum import Enum
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import subprocess
from .prompts import MERGE_CHILD_COMMAND, PROJECT_CONF, DESIGNER_PROMPT, EXECUTOR_PROMPT

SESSIONS_FILE = Path.home() / ".kerberos" / "sessions.json"


class AgentType(Enum):
    DESIGNER = "designer"
    EXECUTOR = "executor"


class Session:
    def __init__(
        self,
        session_id: str,
        agent_type: AgentType,
        protocol=None,  # AgentProtocol instance
        source_path: str = "",
        work_path: Optional[str] = None,
        active: bool = False,
    ):
        self.session_id = session_id
        self.agent_type = agent_type
        self.protocol = protocol
        self.source_path = source_path
        self.work_path = work_path
        self.active = active
        self.children: List[Session] = []

    def start(self) -> bool:
        """Start the agent using the configured protocol"""
        if not self.protocol:
            return False
        return self.protocol.start(self)

    def add_instructions(self) -> None:
        """Add agent-specific instructions to CLAUDE.md"""
        if not self.work_path:
            return

        claude_dir = Path(self.work_path) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        # Select the appropriate prompt based on agent type
        if self.agent_type == AgentType.DESIGNER:
            prompt_template = DESIGNER_PROMPT
        else:  # AgentType.EXECUTOR
            prompt_template = EXECUTOR_PROMPT

        # Create/update kerberos.md with session-specific information
        kerberos_md_path = claude_dir / "kerberos.md"
        formatted_prompt = prompt_template.format(
            session_id=self.session_id,
            work_path=self.work_path
        )
        kerberos_md_path.write_text(formatted_prompt)

        # Add import to CLAUDE.md if not already present
        claude_md_path = claude_dir / "CLAUDE.md"
        import_line = "@.claude/kerberos.md"

        existing_content = ""
        if claude_md_path.exists():
            existing_content = claude_md_path.read_text()

        # Check if import is already present
        if import_line not in existing_content:
            # Add import line at the beginning with a separator
            if existing_content:
                new_content = f"# Kerberos Session Configuration\n{import_line}\n\n{existing_content}"
            else:
                new_content = f"# Kerberos Session Configuration\n{import_line}\n"

            claude_md_path.write_text(new_content)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dictionary for JSON storage"""
        return {
            "session_id": self.session_id,
            "agent_type": self.agent_type.value,
            "source_path": self.source_path,
            "work_path": self.work_path,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], protocol=None) -> "Session":
        """Deserialize session from dictionary"""
        session = cls(
            session_id=data["session_id"],
            agent_type=AgentType(data["agent_type"]),
            protocol=protocol,
            source_path=data.get("source_path", ""),
            work_path=data.get("work_path"),
            active=data.get("active", False),
        )
        # Recursively load children (they inherit the same protocol)
        session.children = [
            cls.from_dict(child_data, protocol) for child_data in data.get("children", [])
        ]
        return session

    def prepare(self):
        """
        Uses git worktree. If worktree exists, use it. Otherwise create a new one on branch session_id.
        """
        if not self.source_path:
            raise ValueError("Source path is not set")

        # Set work_path in ~/.kerberos/worktrees/source_dir_name/session_id
        source_dir_name = Path(self.source_path).name
        worktree_base = Path.home() / ".kerberos" / "worktrees" / source_dir_name
        self.work_path = str(worktree_base / self.session_id)

        # Check if worktree already exists
        if Path(self.work_path).exists():
            return

        # Ensure worktree base directory exists
        worktree_base.mkdir(parents=True, exist_ok=True)

        # Create new worktree on a new branch
        try:
            # Check if branch exists
            result = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{self.session_id}"],
                cwd=self.source_path,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Branch exists, use it
                subprocess.run(
                    ["git", "worktree", "add", self.work_path, self.session_id],
                    cwd=self.source_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            else:
                # Create new branch
                subprocess.run(
                    ["git", "worktree", "add", "-b", self.session_id, self.work_path],
                    cwd=self.source_path,
                    check=True,
                    capture_output=True,
                    text=True
                )

            # Create .claude/commands directory and add merge-child command
            claude_commands_dir = Path(self.work_path) / ".claude" / "commands"
            claude_commands_dir.mkdir(parents=True, exist_ok=True)

            merge_command_path = claude_commands_dir / "merge-child.md"
            merge_command_path.write_text(MERGE_CHILD_COMMAND)

            # Add agent-specific instructions to CLAUDE.md
            self.add_instructions()

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")

    def spawn_executor(self, session_id: str, instructions: str) -> "Session":
        """Spawn an executor session as a child of this session"""
        if not self.work_path:
            raise ValueError("Work path is not set")

        new_session = Session(
            session_id=session_id,
            agent_type=AgentType.EXECUTOR,
            protocol=self.protocol,  # Inherit parent's protocol
            source_path=self.work_path,  # Child's source is parent's work directory
        )

        # Prepare the child session (creates its own worktree)
        new_session.prepare()

        # Create .claude/settings.json with hook configuration for monitoring
        claude_dir = Path(new_session.work_path) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        settings_path = claude_dir / "settings.json"
        # PROJECT_CONF is already a JSON string, just replace the placeholder
        settings_json = PROJECT_CONF.replace("{session_id}", session_id)
        settings_path.write_text(settings_json)

        instructions_path = Path(new_session.work_path) / "instructions.md"
        instructions_path.write_text(instructions)

        # Add to children
        self.children.append(new_session)

        if not new_session.start():
            raise RuntimeError(f"Failed to start child session {session_id}")

        initial_message = "Please review your task instructions in @instructions.md"
        subprocess.run(["tmux", "send-keys", "-t", session_id, initial_message, "Enter"],
                      capture_output=True, text=True)

        return new_session

    @property
    def display_name(self) -> str:
        """Get display name for UI"""
        status = "●" if self.active else "○"
        return f"{status} {self.session_id}"


def ensure_default_session(sessions: List[Session], protocol=None) -> List[Session]:
    """Ensure main session exists at the beginning of the sessions list"""
    # Look for existing main session
    main_session = None
    other_sessions = []

    for session in sessions:
        if session.session_id == "main":
            main_session = session
        else:
            other_sessions.append(session)

    # If main doesn't exist, create it
    if not main_session:
        main_session = Session(
            session_id="main",
            agent_type=AgentType.DESIGNER,
            protocol=protocol,
            source_path=str(Path.cwd()),
            active=False
        )

        # For the main session, use the source directory directly instead of a worktree
        # This avoids the issue of multiple worktrees for the same branch
        main_session.work_path = main_session.source_path

    # Ensure main session has designer instructions in CLAUDE.md
    main_session.add_instructions()

    # Always put main first
    return [main_session] + other_sessions


def load_sessions(protocol=None, flat=False) -> List[Session]:
    """Load all sessions from JSON file"""
    sessions = []

    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
                sessions = [Session.from_dict(session_data, protocol) for session_data in data]
        except (json.JSONDecodeError, KeyError):
            pass

    sessions = ensure_default_session(sessions, protocol)

    if flat:
        def _flatten_tree(nodes: List[Session]) -> List[Session]:
                flat_list: List[Session] = []
                stack = list(nodes)[::-1]
                while stack:
                    node = stack.pop()
                    flat_list.append(node)
                    children = getattr(node, "children", None) or []
                    # push children in reverse so first child is processed next
                    for child in reversed(children):
                        stack.append(child)
                return flat_list

        return _flatten_tree(sessions)
    else:
        return sessions


def save_sessions(sessions: List[Session]) -> None:
    """Save all sessions to JSON file"""
    # Ensure directory exists
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(SESSIONS_FILE, "w") as f:
        json.dump([session.to_dict() for session in sessions], f, indent=2)


def find_session(sessions: List[Session], session_id: str) -> Optional[Session]:
    """Find a session by ID (searches recursively through children)"""
    for session in sessions:
        if session.session_id == session_id:
            return session
        # Search in children
        child_result = find_session(session.children, session_id)
        if child_result:
            return child_result
    return None
