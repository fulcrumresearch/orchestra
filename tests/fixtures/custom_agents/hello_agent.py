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
        """Setup workspace - just verify directory exists and create marker"""
        # work_path is already set by prepare()
        work_path = Path(session.work_path)

        # Verify work directory exists (should already be created by prepare)
        assert work_path.exists(), f"Work path should exist: {work_path}"

        # Create a marker file to prove this agent ran
        marker = work_path / "hello_marker.txt"
        marker.write_text(f"Hello from {session.session_name}!")
