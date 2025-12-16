from abc import ABC
from typing import TYPE_CHECKING, Optional, Dict, List, Any
from pathlib import Path
import yaml
import importlib.util

from orchestra.lib.config import get_orchestra_home

if TYPE_CHECKING:
    from .sessions import Session


class Agent(ABC):
    """Base class for agent types in Orchestra

    This allows customization of agent behavior, setup, and configuration.
    Subclass this to create custom agent types for different workflows.

    Example:
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
    ):
        """Initialize an agent

        Args:
            name: Unique identifier for this agent type
            prompt: System prompt template for this agent
            use_docker: Whether this agent runs in Docker by default
            mcp_config: MCP server configuration (optional)
            tools: List of allowed tool names (optional, None = no restrictions)
        """
        self.name = name
        self.prompt = prompt
        self.use_docker = use_docker
        self.mcp_config = mcp_config
        self.tools = tools

    def setup(self, session: "Session") -> None:
        """Setup work environment for this agent type

        Called during Session.prepare(). Subclasses must override this method.

        Args:
            session: Session object being prepared
        """
        raise NotImplementedError(f"Agent '{self.name}' must implement setup()")


class StaleAgent(Agent):
    """Placeholder agent for sessions that can't be restored

    Used when a session's agent type is no longer available (e.g., dynamic agents
    created via create_from_agent that weren't persisted properly).
    """

    def __init__(self, original_name: str = "unknown"):
        super().__init__(
            name=f"stale-{original_name}",
            prompt="# Stale Agent\n\nThis session could not be restored.",
            use_docker=False,
        )
        self.original_name = original_name

    def setup(self, session: "Session") -> None:
        """Raise an error if someone tries to use a stale agent"""
        raise RuntimeError(
            f"Cannot setup stale agent. Original agent '{self.original_name}' "
            f"is no longer available. This session cannot be restarted."
        )


class DesignerAgent(Agent):
    """Designer agent - orchestrator that works in source directory"""

    def __init__(self, prompt: Optional[str] = None):
        from .prompts import DESIGNER_PROMPT

        super().__init__(
            name="designer",
            prompt=prompt or DESIGNER_PROMPT,
            use_docker=False,
        )

    def setup(self, session: "Session") -> None:
        """Setup designer workspace"""
        # work_path already set to source_path by prepare()
        # Create .claude/commands directory and add merge-child command
        from .prompts import MERGE_CHILD_COMMAND
        from .config import get_orchestra_home

        claude_commands_dir = Path(session.work_path) / ".claude" / "commands"
        claude_commands_dir.mkdir(parents=True, exist_ok=True)

        # Format the merge command with dynamic orchestra subagents directory
        orchestra_subagents_dir = str(get_orchestra_home() / "subagents")
        formatted_merge_command = MERGE_CHILD_COMMAND.format(orchestra_subagents_dir=orchestra_subagents_dir)

        merge_command_path = claude_commands_dir / "merge-child.md"
        merge_command_path.write_text(formatted_merge_command)


class ExecutorAgent(Agent):
    """Executor agent - worker that runs in isolated git worktree"""

    def __init__(
        self,
        prompt: Optional[str] = None,
        name: str = "executor",
        use_docker: bool = True,
        mcp_config: Optional[Dict[str, Any]] = None,
        tools: Optional[List[str]] = None,
    ):
        from .prompts import EXECUTOR_PROMPT

        super().__init__(
            name=name,
            prompt=prompt or EXECUTOR_PROMPT,
            use_docker=use_docker,
            mcp_config=mcp_config,
            tools=tools,
        )

    def setup(self, session: "Session") -> None:
        """Setup executor workspace"""
        # work_path already set and worktree already created by prepare()
        # Nothing extra needed for executor setup
        pass


# Default instances for Orchestra's built-in agent types
DESIGNER_AGENT = DesignerAgent()
EXECUTOR_AGENT = ExecutorAgent()


def load_agent(name: str) -> Agent:
    """Load agent by name from agents.yaml

    Args:
        name: Agent name to load
        config_dir: Path to .orchestra/config/ (defaults to ORCHESTRA_CONFIG_DIR env var or cwd/.orchestra/config)

    Returns:
        Agent instance

    Raises:
        ValueError: If agent not found or config invalid
    """

    # Check for agents.yaml
    config_dir = get_orchestra_home() / "config"
    agents_file = config_dir / "agents.yaml"
    if not agents_file.exists():
        return _get_builtin_agent(name)

    # Load config
    try:
        with open(agents_file) as f:
            config = yaml.safe_load(f)
            if config is None:
                config = {}
    except Exception as e:
        raise ValueError(f"Failed to load agents.yaml: {e}")

    agents_config = config.get("agents", {})
    if agents_config is None:
        agents_config = {}

    if name not in agents_config:
        # Fall back to built-in
        return _get_builtin_agent(name)

    agent_config = agents_config[name]

    # Delegate to helper functions
    if "module" in agent_config:
        return _load_module_agent(name, agent_config["module"], config_dir)
    elif name in ("designer", "executor"):
        return _override_builtin_agent(name, agent_config, config_dir)
    else:
        return _create_simple_agent(name, agent_config, config_dir)


def _get_builtin_agent(name: str) -> Agent:
    """Get built-in agent by name"""
    if name == "designer":
        return DESIGNER_AGENT
    elif name == "executor":
        return EXECUTOR_AGENT
    else:
        raise ValueError(f"Unknown agent: {name}")


def _load_module_agent(name: str, module_spec: str, config_dir: Path) -> Agent:
    """Load agent from Python module

    Args:
        module_spec: "path/to/file.py:ClassName"
        config_dir: Base directory for relative paths
    """
    try:
        if ":" not in module_spec:
            raise ValueError(f"Invalid module spec '{module_spec}'. Expected format: 'path/to/file.py:ClassName'")
        parts = module_spec.rsplit(":", 1)
        module_path, class_name = Path(parts[0]), parts[1]

        # Module paths relative to config_dir
        if not module_path.is_absolute():
            module_path = config_dir / module_path

        if not module_path.exists():
            raise ValueError(f"Module file not found: {module_path}")

        # Load module dynamically
        spec = importlib.util.spec_from_file_location(f"agent_{name}", module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Failed to load module from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Get class and instantiate
        if not hasattr(module, class_name):
            raise ValueError(f"Class '{class_name}' not found in module {module_path}")
        agent_class = getattr(module, class_name)
        return agent_class()

    except Exception as e:
        raise ValueError(f"Failed to load module agent {name}: {e}")


def _override_builtin_agent(name: str, config: dict, config_dir: Path) -> Agent:
    """Override built-in agent prompt

    Args:
        name: "designer" or "executor"
        config: Agent configuration with prompt override
        config_dir: Base directory for relative paths
    """
    # Load prompt
    prompt = _load_prompt(config, config_dir)
    if not prompt:
        # Keep original if prompt loading fails
        return _get_builtin_agent(name)

    # Create new agent instance with overridden prompt
    if name == "designer":
        return DesignerAgent(prompt=prompt)
    else:  # executor
        return ExecutorAgent(prompt=prompt)


def _create_simple_agent(name: str, config: dict, config_dir: Path) -> Agent:
    """Create simple config-based agent (always executor-like)

    Args:
        name: Agent name
        config: Agent configuration
        config_dir: Base directory for relative paths
    """
    # Load prompt
    prompt = _load_prompt(config, config_dir)
    if not prompt:
        raise ValueError(f"Agent {name} missing prompt or prompt_file")

    # Create an ExecutorAgent with custom configuration
    return ExecutorAgent(
        prompt=prompt,
        name=name,
        use_docker=config.get("use_docker", False),
        mcp_config=config.get("mcp_config"),
        tools=config.get("tools"),
    )


def _load_prompt(config: dict, config_dir: Path) -> Optional[str]:
    """Load prompt from config (inline or file)

    Args:
        config: Agent configuration
        config_dir: Base directory for relative paths
    """
    # Inline prompt
    if "prompt" in config:
        return config["prompt"]

    # Prompt file
    if "prompt_file" in config:
        prompt_path = Path(config["prompt_file"])

        # Paths relative to config_dir
        if not prompt_path.is_absolute():
            prompt_path = config_dir / prompt_path

        if not prompt_path.exists():
            raise ValueError(f"Prompt file not found: {prompt_path}")

        return prompt_path.read_text()

    return None
