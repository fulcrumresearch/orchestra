from enum import Enum
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import subprocess
import time

from cerb_code.lib.tmux_agent import TmuxProtocol
from .prompts import MERGE_CHILD_COMMAND, PROJECT_CONF, DESIGNER_PROMPT, EXECUTOR_PROMPT
from .config import load_config

SESSIONS_FILE = Path.home() / ".kerberos" / "sessions.json"


class AgentType(Enum):
    DESIGNER = "designer"
    EXECUTOR = "executor"


AGENT_TEMPLATES = {
    AgentType.DESIGNER: DESIGNER_PROMPT,
    AgentType.EXECUTOR: EXECUTOR_PROMPT,
}


class Session:
    def __init__(
        self,
        session_id: str,
        agent_type: AgentType,
        source_path: str = "",
        work_path: Optional[str] = None,
        active: bool = False,
        use_docker: Optional[bool] = None,
    ):
        self.session_id = session_id
        self.agent_type = agent_type
        self.source_path = source_path
        self.work_path = work_path
        self.active = active
        self.paired = False  # Runtime only, not persisted
        self.children: List[Session] = []
        # Default use_docker based on agent type: DESIGNER=False, EXECUTOR=True
        if use_docker is None:
            self.use_docker = agent_type == AgentType.EXECUTOR
        else:
            self.use_docker = use_docker

        config = load_config()
        self.protocol = TmuxProtocol(
            default_command="claude",
            mcp_port=config.get("mcp_port", 8765),
            use_docker=self.use_docker,
        )

    def start(self) -> bool:
        """Start the agent using the configured protocol"""
        return self.protocol.start(self)

    def delete(self) -> bool:
        """Delete the session using the configured protocol"""
        # Delete all children first
        for child in self.children:
            child.delete()
        return self.protocol.delete(self.session_id)

    def add_instructions(self) -> None:
        """Add agent-specific instructions to CLAUDE.md"""
        if not self.work_path:
            return

        claude_dir = Path(self.work_path) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        prompt_template = AGENT_TEMPLATES[self.agent_type]

        kerberos_md_path = claude_dir / "kerberos.md"
        formatted_prompt = prompt_template.format(
            session_id=self.session_id,
            work_path=self.work_path,
            source_path=self.source_path,
        )
        kerberos_md_path.write_text(formatted_prompt)

        claude_md_path = claude_dir / "CLAUDE.md"
        import_line = "@kerberos.md"

        existing_content = ""
        if claude_md_path.exists():
            existing_content = claude_md_path.read_text()

        if import_line not in existing_content:
            if existing_content:
                new_content = f"{existing_content}\n# Kerberos Session Configuration\n{import_line}\n"
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
            "use_docker": self.use_docker,
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Deserialize session from dictionary"""
        session = cls(
            session_id=data["session_id"],
            agent_type=AgentType(data["agent_type"]),
            source_path=data.get("source_path", ""),
            work_path=data.get("work_path"),
            active=data.get("active", False),
            use_docker=data.get("use_docker"),
        )
        # Recursively load children (each creates its own protocol)
        session.children = [cls.from_dict(child_data) for child_data in data.get("children", [])]
        return session

    def prepare(self):
        """
        Prepare the session work directory.
        - Designer: works directly in source_path (no worktree)
        - Executor: creates a git worktree
        """
        if not self.source_path:
            raise ValueError("Source path is not set")

        # Designer works directly in source directory
        if self.agent_type == AgentType.DESIGNER:
            self.work_path = self.source_path
            self.add_instructions()
            return

        # Executor uses worktree
        source_dir_name = Path(self.source_path).name
        worktree_base = Path.home() / ".kerberos" / "worktrees" / source_dir_name
        self.work_path = str(worktree_base / self.session_id)

        if Path(self.work_path).exists():
            return

        worktree_base.mkdir(parents=True, exist_ok=True)

        # Create new worktree on a new branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{self.session_id}"],
                cwd=self.source_path,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                subprocess.run(
                    ["git", "worktree", "add", self.work_path, self.session_id],
                    cwd=self.source_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["git", "worktree", "add", "-b", self.session_id, self.work_path],
                    cwd=self.source_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )

            claude_commands_dir = Path(self.work_path) / ".claude" / "commands"
            claude_commands_dir.mkdir(parents=True, exist_ok=True)

            merge_command_path = claude_commands_dir / "merge-child.md"
            merge_command_path.write_text(MERGE_CHILD_COMMAND)

            self.add_instructions()

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")

    def spawn_executor(self, session_id: str, instructions: str) -> "Session":
        """Spawn an executor session as a child of this session"""
        if not self.work_path:
            raise ValueError("Work path is not set")

        # Load config to get use_docker setting for executors
        config = load_config()
        executor_use_docker = config.get("use_docker", True)

        new_session = Session(
            session_id=session_id,
            agent_type=AgentType.EXECUTOR,
            source_path=self.work_path,  # Child's source is parent's work directory
            use_docker=executor_use_docker,  # Use config value
        )

        # Prepare the child session (creates its own worktree)
        new_session.prepare()

        # Create .claude/settings.json with hook configuration for monitoring
        claude_dir = Path(new_session.work_path) / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)

        settings_path = claude_dir / "settings.json"
        # PROJECT_CONF is already a JSON string, just replace the placeholders
        settings_json = PROJECT_CONF.replace("{session_id}", session_id).replace("{source_path}", self.source_path)
        settings_path.write_text(settings_json)

        instructions_path = Path(new_session.work_path) / "instructions.md"
        instructions_path.write_text(instructions)

        # Add to children
        self.children.append(new_session)

        if not new_session.start():
            raise RuntimeError(f"Failed to start child session {session_id}")

        # Wait for Claude to be ready before sending instructions
        time.sleep(1)

        new_session.send_message(
            f"Please review your task instructions in @instructions.md, and then start implementing the task. "
            f"Your parent session ID is: {self.session_id}. "
            f"Your source path is: {self.source_path}. "
            f'When you\'re done or need help, use: send_message_to_session(session_id="{self.session_id}", message="your summary/question here", source_path="{self.source_path}")'
        )

        return new_session

    def get_status(self) -> Dict[str, Any]:
        """Get status information for this session"""
        return self.protocol.get_status(self.session_id)

    def send_message(self, message: str) -> None:
        """Send a message to the session"""
        self.protocol.send_message(self.session_id, message)

    def toggle_pairing(self) -> tuple[bool, str]:
        """
        Toggle pairing mode for this session.
        Returns: (success, error_message)
        """
        return self.protocol.toggle_pairing(self)


def load_sessions(
    flat=False,
    project_dir: Optional[Path] = None,
    root: Optional[str] = None,
) -> List[Session]:
    """Load sessions from JSON file for a specific project directory

    Args:
        flat: If True, return flattened list of sessions (including children)
        project_dir: Specific project directory to load sessions for. If None, uses cwd.
        root: If specified, only return the session with this ID (+ children). Otherwise return all.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Don't resolve - if project_dir is a symlink (from pairing), we want to keep the original path
    project_dir_str = str(project_dir)
    sessions = []

    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
                project_sessions = data.get(project_dir_str, [])
                sessions = [Session.from_dict(session_data) for session_data in project_sessions]
        except (json.JSONDecodeError, KeyError):
            pass

    # Filter by root if specified
    if root:
        sessions = [s for s in sessions if s.session_id == root]

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


def save_session(session: Session, project_dir: Optional[Path] = None) -> None:
    """
    Save a single session (and its children) to JSON file.
    Updates the session in-place if it exists, or adds it if new.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Don't resolve - if project_dir is a symlink (from pairing), we want to keep the original path
    project_dir_str = str(project_dir)

    # Load existing sessions
    existing_sessions = load_sessions(project_dir=project_dir)

    # Find and update the session, or append if not found
    found = False
    for i, existing in enumerate(existing_sessions):
        if existing.session_id == session.session_id:
            existing_sessions[i] = session
            found = True
            break

    if not found:
        existing_sessions.append(session)

    # Ensure directory exists
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Load full sessions dict (may have other projects)
    sessions_dict = {}
    if SESSIONS_FILE.exists():
        try:
            with open(SESSIONS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    sessions_dict = data
        except (json.JSONDecodeError, KeyError):
            pass

    # Update this project's sessions
    sessions_dict[project_dir_str] = [s.to_dict() for s in existing_sessions]

    # Write back
    with open(SESSIONS_FILE, "w") as f:
        json.dump(sessions_dict, f, indent=2)


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
