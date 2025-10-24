from abc import ABC
from typing import TYPE_CHECKING, Optional, Dict, List, Any, Callable
from pathlib import Path
import subprocess

if TYPE_CHECKING:
    from .sessions import Session


class Agent(ABC):
    """Base class for agent types in Orchestra

    This allows customization of agent behavior, setup, and configuration.
    Subclass this to create custom agent types for different workflows.

    For simple customization (e.g., custom prompt), you can pass a setup_fn:
        my_agent = Agent(name="custom", prompt="...", setup_fn=some_setup_function)

    For complex customization, subclass and implement setup():
        class MyAgent(Agent):
            def __init__(self):
                super().__init__(name="my-agent", prompt="...")

            def setup(self, session):
                # custom logic
    """

    def __init__(
        self,
        name: str,
        prompt: str,
        use_docker: bool = False,
        mcp_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[str]] = None,
        setup_fn: Optional[Callable[["Session"], None]] = None,
    ):
        """Initialize an agent

        Args:
            name: Unique identifier for this agent type
            prompt: System prompt template for this agent
            use_docker: Whether this agent runs in Docker by default
            mcp_config: MCP server configuration (optional)
            tools: List of allowed tool names (optional, None = no restrictions)
            setup_fn: Setup function to call instead of overriding setup() (optional)
        """
        self.name = name
        self.prompt = prompt
        self.use_docker = use_docker
        self.mcp_config = mcp_config
        self.tools = tools
        self._setup_fn = setup_fn

    def setup(self, session: "Session") -> None:
        """Setup work environment for this agent type

        Called during Session.prepare(). Either:
        - Override this method in a subclass for complex setup logic, OR
        - Pass setup_fn to __init__ for simple cases

        Args:
            session: Session object being prepared
        """
        if self._setup_fn:
            self._setup_fn(session)
        else:
            raise NotImplementedError(
                f"Agent '{self.name}' must implement setup() or provide setup_fn"
            )


class DesignerAgent(Agent):
    """Designer agent - orchestrator that works in source directory"""

    def __init__(self):
        from .prompts import DESIGNER_PROMPT

        super().__init__(
            name="designer",
            prompt=DESIGNER_PROMPT,
            use_docker=False,
        )

    def setup(self, session: "Session") -> None:
        """Setup designer workspace in source directory"""
        if not session.source_path:
            raise ValueError("Source path is not set")

        # Designer works directly in source directory
        session.work_path = session.source_path

        # Create .claude/commands directory and add merge-child command
        from .prompts import MERGE_CHILD_COMMAND

        claude_commands_dir = Path(session.work_path) / ".claude" / "commands"
        claude_commands_dir.mkdir(parents=True, exist_ok=True)

        merge_command_path = claude_commands_dir / "merge-child.md"
        merge_command_path.write_text(MERGE_CHILD_COMMAND)


class ExecutorAgent(Agent):
    """Executor agent - worker that runs in isolated git worktree"""

    def __init__(self):
        from .prompts import EXECUTOR_PROMPT

        super().__init__(
            name="executor",
            prompt=EXECUTOR_PROMPT,
            use_docker=True,
        )

    def setup(self, session: "Session") -> None:
        """Setup executor workspace in git worktree"""
        if not session.source_path:
            raise ValueError("Source path is not set")

        # Executor uses worktree
        source_dir_name = Path(session.source_path).name
        worktree_base = Path.home() / ".orchestra" / "worktrees" / source_dir_name
        session.work_path = str(worktree_base / session.session_id)

        if Path(session.work_path).exists():
            # Worktree already exists, no need to create it
            return

        worktree_base.mkdir(parents=True, exist_ok=True)

        # Create new worktree on a new branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", f"refs/heads/{session.session_id}"],
                cwd=session.source_path,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                subprocess.run(
                    ["git", "worktree", "add", session.work_path, session.session_id],
                    cwd=session.source_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            else:
                subprocess.run(
                    ["git", "worktree", "add", "-b", session.session_id, session.work_path],
                    cwd=session.source_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")


# Default instances for Orchestra's built-in agent types
DESIGNER_AGENT = DesignerAgent()
EXECUTOR_AGENT = ExecutorAgent()
