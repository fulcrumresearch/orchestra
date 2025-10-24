"""Test custom agent that prints hello message"""
from pathlib import Path
from orchestra.lib.agent import Agent


class HelloAgent(Agent):
    """Custom agent that just prints hello"""

    def __init__(self):
        super().__init__(
            name="hello-agent",
            prompt="You are a hello agent. Say hello and complete immediately.",
            use_docker=False,
            mcp_config=None,
            tools=None
        )

    def setup(self, session):
        """Setup workspace - create work directory in subagents"""
        if not session.source_path:
            raise ValueError("Source path is not set")

        # Custom agents use ~/.orchestra/subagents/ directory
        source_dir_name = Path(session.source_path).name
        subagents_base = Path.home() / ".orchestra" / "subagents" / source_dir_name
        session.work_path = str(subagents_base / session.session_id)

        # Create the work directory
        work_path = Path(session.work_path)
        work_path.mkdir(parents=True, exist_ok=True)

        # Create a marker file to prove this agent ran
        marker = work_path / "hello_marker.txt"
        marker.write_text(f"Hello from {session.session_name}!")
