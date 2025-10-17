"""Integration tests for message queue functionality

Tests that:
1. Messages to designer sessions are queued in JSONL file
2. Messages to executor sessions still work via direct tmux
3. JSONL file format is correct
4. Concurrent writes are handled safely
"""

import json
import time
import subprocess
from pathlib import Path
from unittest.mock import patch

from orchestra.backend.mcp_server import send_message_to_session
from orchestra.lib.sessions import Session, AgentType, save_session
from orchestra.lib.message_queue import append_message, read_pending_messages, MESSAGES_FILE


class TestMessageQueueBasics:
    """Basic tests for message queue functions"""

    def test_append_message_creates_file(self, orchestra_test_env, monkeypatch):
        """Test that append_message creates the messages file"""
        # Use a temporary messages file for testing
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Append a message
        message_id = append_message(
            target_session="designer",
            sender="executor1",
            message="Test message",
            source_path=str(orchestra_test_env.repo)
        )

        # Verify file was created
        assert temp_messages_file.exists()

        # Verify message ID was returned
        assert message_id is not None
        assert len(message_id) > 0

    def test_append_message_jsonl_format(self, orchestra_test_env, monkeypatch):
        """Test that messages are written in correct JSONL format"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Append multiple messages
        append_message("designer1", "executor1", "First message", str(orchestra_test_env.repo))
        append_message("designer2", "executor2", "Second message", str(orchestra_test_env.repo))

        # Read and verify format
        with open(temp_messages_file, "r") as f:
            lines = f.readlines()

        assert len(lines) == 2

        # Verify each line is valid JSON
        for line in lines:
            message = json.loads(line)
            assert "id" in message
            assert "timestamp" in message
            assert "sender" in message
            assert "target" in message
            assert "message" in message
            assert "source_path" in message

    def test_read_pending_messages(self, orchestra_test_env, monkeypatch):
        """Test reading messages for a specific session"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Append messages for different targets
        append_message("designer1", "executor1", "Message for designer1", str(orchestra_test_env.repo))
        append_message("designer2", "executor2", "Message for designer2", str(orchestra_test_env.repo))
        append_message("designer1", "executor3", "Another for designer1", str(orchestra_test_env.repo))

        # Read messages for designer1
        messages = read_pending_messages("designer1")

        assert len(messages) == 2
        assert all(msg["target"] == "designer1" for msg in messages)
        assert messages[0]["message"] == "Message for designer1"
        assert messages[1]["message"] == "Another for designer1"

    def test_read_pending_messages_empty_file(self, orchestra_test_env, monkeypatch):
        """Test reading from non-existent file returns empty list"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "nonexistent_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        messages = read_pending_messages("any-session")

        assert messages == []

    def test_concurrent_writes(self, orchestra_test_env, monkeypatch):
        """Test that concurrent writes don't corrupt the file"""
        import threading

        temp_messages_file = orchestra_test_env.orchestra_dir / "test_concurrent.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Write messages from multiple threads
        def write_messages(sender_id):
            for i in range(5):
                append_message(
                    f"designer-{sender_id}",
                    f"executor-{sender_id}",
                    f"Message {i} from {sender_id}",
                    str(orchestra_test_env.repo)
                )

        threads = [threading.Thread(target=write_messages, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify all messages were written correctly
        with open(temp_messages_file, "r") as f:
            lines = f.readlines()

        assert len(lines) == 15  # 3 threads * 5 messages each

        # Verify each line is valid JSON
        for line in lines:
            message = json.loads(line)
            assert "id" in message
            assert "message" in message


class TestSendMessageQueueIntegration:
    """Integration tests for send_message_to_session with queue support"""

    def test_send_message_to_designer_queues(self, orchestra_test_env, monkeypatch):
        """Test that messages to designer sessions are queued"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Create a designer session
        designer = Session(
            session_name="designer",
            agent_type=AgentType.DESIGNER,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        # Send message to designer
        result = send_message_to_session(
            session_name="designer",
            message="Task complete",
            source_path=str(orchestra_test_env.repo),
            sender_name="executor1",
        )

        # Verify it was queued
        assert "Message queued for designer session 'designer'" in result
        assert "ID:" in result

        # Verify message is in queue file
        messages = read_pending_messages("designer")
        assert len(messages) == 1
        assert messages[0]["message"] == "Task complete"
        assert messages[0]["sender"] == "executor1"

    def test_send_message_to_executor_uses_tmux(self, orchestra_test_env, monkeypatch):
        """Test that messages to executor sessions still use tmux"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Create an executor session
        executor = Session(
            session_name="executor",
            agent_type=AgentType.EXECUTOR,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        executor.prepare()
        save_session(executor, project_dir=orchestra_test_env.repo)

        # Start a real tmux session for the executor
        subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "new-session", "-d", "-s", executor.session_id],
            check=True,
        )

        # Send message to executor
        result = send_message_to_session(
            session_name="executor",
            message="Test message",
            source_path=str(orchestra_test_env.repo),
            sender_name="designer",
        )

        # Verify it was sent via tmux (not queued)
        assert "Successfully sent message to session 'executor'" in result
        assert "queued" not in result.lower()

        # Wait for tmux to process
        time.sleep(0.2)

        # Verify message was sent to tmux pane
        capture_result = subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "capture-pane", "-t", executor.session_id, "-p"],
            capture_output=True,
            text=True,
        )
        pane_content = capture_result.stdout

        assert "[From: designer] Test message" in pane_content

        # Verify message is NOT in queue file
        messages = read_pending_messages("executor")
        assert len(messages) == 0

    def test_message_queue_doesnt_affect_executor_sessions(self, orchestra_test_env, monkeypatch):
        """Test that executor sessions continue to work as before (regression test)"""
        temp_messages_file = orchestra_test_env.orchestra_dir / "test_messages.jsonl"
        monkeypatch.setattr("orchestra.lib.message_queue.MESSAGES_FILE", temp_messages_file)

        # Create two executor sessions
        executor1 = Session(
            session_name="executor1",
            agent_type=AgentType.EXECUTOR,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        executor1.prepare()
        save_session(executor1, project_dir=orchestra_test_env.repo)

        executor2 = Session(
            session_name="executor2",
            agent_type=AgentType.EXECUTOR,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        executor2.prepare()
        save_session(executor2, project_dir=orchestra_test_env.repo)

        # Start tmux sessions
        subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "new-session", "-d", "-s", executor1.session_id],
            check=True,
        )
        subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "new-session", "-d", "-s", executor2.session_id],
            check=True,
        )

        # Send messages between executors
        send_message_to_session("executor2", "Hello from executor1", str(orchestra_test_env.repo), "executor1")

        time.sleep(0.2)

        # Verify messages still work via tmux
        capture_result = subprocess.run(
            ["tmux", "-L", orchestra_test_env.tmux, "capture-pane", "-t", executor2.session_id, "-p"],
            capture_output=True,
            text=True,
        )
        pane_content = capture_result.stdout

        assert "[From: executor1] Hello from executor1" in pane_content

        # Verify no messages in queue
        assert len(read_pending_messages("executor1")) == 0
        assert len(read_pending_messages("executor2")) == 0
