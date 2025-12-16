"""Integration tests for custom agent system

These tests verify:
1. Loading custom agents from Python modules
2. Spawning child sessions with custom agent types
3. Custom agent setup methods are called correctly
4. Settings.json generation for custom agents
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch
from orchestra.lib.agent import load_agent


class TestCustomAgentModule:
    """Test custom agents defined via Python modules"""

    def test_load_custom_agent_from_module(self, orchestra_test_env_with_custom_agents):
        """Test loading a custom agent from Python module"""
        # Load the custom agent
        agent = load_agent("hello-agent")

        assert agent.name == "hello-agent"
        assert "hello" in agent.prompt.lower()
        assert agent.use_docker == False

    def test_spawn_custom_agent_child(self, designer_session_with_custom_agents):
        """Test spawning a child session with custom agent type"""

        # Mock tmux start
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer_session_with_custom_agents.spawn_child(
                session_name="hello-child", instructions="Say hello", agent_type="hello-agent"
            )

        # Verify child was created with custom agent
        assert child.agent.name == "hello-agent"
        assert child.work_path is not None

        # Verify setup ran (marker file should exist)
        work_path = Path(child.work_path)
        marker = work_path / "hello_marker.txt"
        assert marker.exists()
        content = marker.read_text()
        assert "Hello from hello-child" in content

    def test_custom_agent_settings_json(self, designer_session_with_custom_agents):
        """Test that custom agent gets proper settings.json"""
        # Mock tmux start
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer_session_with_custom_agents.spawn_child(
                session_name="hello-child", instructions="Say hello", agent_type="hello-agent"
            )

        # Verify settings.json exists with proper hook configuration
        settings_path = Path(child.work_path) / ".claude" / "settings.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text())

        # Should have monitoring hooks (non-root agent)
        assert "hooks" in settings
        assert "PostToolUse" in settings["hooks"]
        assert "UserPromptSubmit" in settings["hooks"]
        assert "Stop" in settings["hooks"]

        # Should have permissions configured
        assert "permissions" in settings

    def test_custom_agent_work_path_in_subagents(self, designer_session_with_custom_agents):
        """Test that custom agents use ~/.orchestra/subagents/ directory"""
        # Mock tmux start
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer_session_with_custom_agents.spawn_child(
                session_name="hello-child", instructions="Say hello", agent_type="hello-agent"
            )

        # Verify work_path is set and directory exists
        assert child.work_path is not None
        work_path = Path(child.work_path)
        assert work_path.exists()

        # Custom agents should use subagents directory
        assert ".orchestra/subagents" in str(work_path)

    def test_custom_agent_instructions_file(self, designer_session_with_custom_agents):
        """Test that custom agent gets instructions.md file"""
        # Mock tmux start
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer_session_with_custom_agents.spawn_child(
                session_name="hello-child", instructions="Say hello to the world", agent_type="hello-agent"
            )

        # Verify instructions.md exists with correct content
        instructions_file = Path(child.work_path) / "instructions.md"
        assert instructions_file.exists()
        content = instructions_file.read_text()
        assert "Say hello to the world" in content

    def test_custom_agent_orchestra_md(self, designer_session_with_custom_agents):
        """Test that custom agent gets proper orchestra.md with custom prompt"""
        # Mock tmux start
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer_session_with_custom_agents.spawn_child(
                session_name="hello-child", instructions="Say hello", agent_type="hello-agent"
            )

        # Verify orchestra.md exists with custom agent prompt
        orchestra_md = Path(child.work_path) / ".claude" / "orchestra.md"
        assert orchestra_md.exists()
        content = orchestra_md.read_text()
        # Should contain the custom agent's prompt
        assert "hello agent" in content.lower()
