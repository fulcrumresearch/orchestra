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
<<<<<<< HEAD
from orchestra.lib.sessions import Session, AgentType, save_session
=======
from orchestra.lib.sessions import Session, save_session
from orchestra.lib.agent import DESIGNER_AGENT, EXECUTOR_AGENT
>>>>>>> main
from orchestra.lib.config import get_orchestra_home


class TestSpawnSubagentIntegration:
    """Integration tests for spawn_subagent MCP function"""

    def test_spawn_creates_worktree_and_files(self, designer_session, orchestra_test_env):
        """Test that spawn_subagent creates a real git worktree and instruction files"""
        # Mock only the tmux start operation (we're not testing tmux startup here)
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            result = spawn_subagent(
                parent_session_name="designer",
                child_session_name="test-child",
                instructions="Build the login feature",
                source_path=str(orchestra_test_env.repo),
            )

        # Verify success
        assert "Successfully spawned child session 'test-child'" in result

        # Verify subagent directory was created
        repo_name = orchestra_test_env.repo.name
        session_id = f"{repo_name}-test-child"
<<<<<<< HEAD
        worktree_path = get_orchestra_home() / "worktrees" / repo_name / session_id
        assert worktree_path.exists(), f"Worktree should exist at {worktree_path}"
=======
        subagent_path = get_orchestra_home() / "subagents" / session_id
        assert subagent_path.exists(), f"Subagent directory should exist at {subagent_path}"
>>>>>>> main

        # Verify instructions.md was created
        instructions_file = subagent_path / "instructions.md"
        assert instructions_file.exists()
        assert "Build the login feature" in instructions_file.read_text()

        # Verify .claude/orchestra.md was created
        orchestra_md = subagent_path / ".claude" / "orchestra.md"
        assert orchestra_md.exists()


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
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
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

    def test_send_message_to_executor(self, designer_session, orchestra_test_env):
        """Test that messages to executor sessions are sent via tmux with [From: sender_name] prefix"""
        # Create an executor as a child of designer (real scenario)
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            target = designer_session.spawn_child(
                session_name="target",
                instructions="Test task",
            )
        save_session(designer_session, project_dir=orchestra_test_env.repo)

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

    def test_send_message_to_designer_queues_to_jsonl(self, designer_session, orchestra_test_env):
        """Test that messages to designer sessions are written to messages.jsonl"""
        # Send a message to the designer session
        result = send_message_to_session(
            session_name="designer",
            message="Please review the PR",
            source_path=str(orchestra_test_env.repo),
            sender_name="child-executor",
        )

        # Verify success
        assert "Successfully sent message" in result

        # Verify message was written to messages.jsonl
        messages_file = Path(designer_session.work_path) / ".orchestra" / "messages.jsonl"
        assert messages_file.exists(), "messages.jsonl should exist"

        # Read and verify message format
        with open(messages_file) as f:
            line = f.readline().strip()
            message_obj = json.loads(line)
            assert message_obj["sender"] == "child-executor"
            assert message_obj["message"] == "Please review the PR"
