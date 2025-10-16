"""Integration tests for orchestra.backend.mcp_server module

These tests use real Session objects, real git worktrees, and a real tmux test server
to verify the full MCP workflow end-to-end.
"""

import json
import time
import subprocess
from pathlib import Path
from unittest.mock import patch

from orchestra.backend.mcp_server import spawn_subagent, send_message_to_session
from orchestra.lib.sessions import Session, AgentType, save_session


class TestSpawnSubagentIntegration:
    """Integration tests for spawn_subagent MCP function"""

    def test_spawn_creates_worktree_and_files(self, designer_session, orchestra_test_env):
        """Test that spawn_subagent creates a real git worktree and instruction files"""
        # Mock only the tmux start operation (we're not testing tmux startup here)
        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            result = spawn_subagent(
                parent_session_name="designer",
                child_session_name="test-child",
                instructions="Build the login feature",
                source_path=str(orchestra_test_env.repo),
            )

        # Verify success
        assert "Successfully spawned child session 'test-child'" in result

        # Verify worktree was created (use actual repo name, not hardcoded)
        repo_name = orchestra_test_env.repo.name
        session_id = f"{repo_name}-test-child"
        worktree_path = Path.home() / ".orchestra" / "worktrees" / repo_name / session_id
        assert worktree_path.exists(), f"Worktree should exist at {worktree_path}"

        # Verify instructions.md was created
        instructions_file = worktree_path / "instructions.md"
        assert instructions_file.exists()
        assert "Build the login feature" in instructions_file.read_text()

        # Verify .claude/orchestra.md was created
        orchestra_md = worktree_path / ".claude" / "orchestra.md"
        assert orchestra_md.exists()

        # Verify merge command was created
        merge_cmd = worktree_path / ".claude" / "commands" / "merge-child.md"
        assert merge_cmd.exists()

    def test_spawn_parent_not_found(self, orchestra_test_env):
        """Test error handling when parent session doesn't exist"""
        result = spawn_subagent(
            parent_session_name="nonexistent",
            child_session_name="child",
            instructions="Do something",
            source_path=str(orchestra_test_env.repo),
        )

        assert "Error: Parent session 'nonexistent' not found" in result

    def test_spawn_persists_to_sessions_file(self, designer_session, orchestra_test_env):
        """Test that spawned child is persisted in sessions.json"""
        # Spawn child
        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            spawn_subagent(
                parent_session_name="designer",
                child_session_name="child",
                instructions="Task description",
                source_path=str(orchestra_test_env.repo),
            )

        # Verify sessions file structure
        with open(orchestra_test_env.sessions_file) as f:
            data = json.load(f)

        project_sessions = data[str(orchestra_test_env.repo)]
        assert len(project_sessions) == 1

        parent_data = project_sessions[0]
        assert parent_data["session_name"] == "designer"
        assert len(parent_data["children"]) == 1
        assert parent_data["children"][0]["session_name"] == "child"
        assert parent_data["children"][0]["agent_type"] == "executor"
        assert parent_data["children"][0]["parent_session_name"] == "designer"


class TestSendMessageIntegration:
    """Integration tests for send_message_to_session MCP function"""

    def test_send_message_target_not_found(self, orchestra_test_env):
        """Test error handling when target session doesn't exist"""
        result = send_message_to_session(
            session_name="nonexistent",
            message="Hello",
            source_path=str(orchestra_test_env.repo),
            sender_name="sender",
        )

        assert "Error: Session 'nonexistent' not found" in result

    def test_send_message(self, orchestra_test_env):
        """Test that messages are prefixed with [From: sender_name]"""
        # Create and start a real tmux session
        target = Session(
            session_name="target",
            agent_type=AgentType.DESIGNER,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        target.prepare()
        save_session(target, project_dir=orchestra_test_env.repo)

        # Start a real tmux session for the target
        subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "new-session", "-d", "-s", target.session_id],
            check=True,
        )

        # Send message
        result = send_message_to_session(
            session_name="target",
            message="Test message",
            source_path=str(orchestra_test_env.repo),
            sender_name="my-sender",
        )

        assert "Successfully sent message to session 'target'" in result

        # Wait a moment for tmux to process the paste
        time.sleep(0.2)

        # Capture the pane content to verify the message was sent
        capture_result = subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "capture-pane", "-t", target.session_id, "-p"],
            capture_output=True,
            text=True,
        )
        pane_content = capture_result.stdout

        # Verify the prefixed message is in the pane
        assert "[From: my-sender] Test message" in pane_content, (
            f"Expected message not found in pane content: {pane_content}"
        )
