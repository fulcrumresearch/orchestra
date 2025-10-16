"""Integration tests for Docker-based executor workflow

These tests cover:
1. Docker container creation and configuration
2. Full executor spawning workflow (worktree + container + config files)
3. End-to-end message passing with real Docker containers

Run with: pytest tests/integration/test_docker_workflow.py
Mark slow tests: pytest -m "not slow" to skip Docker tests
"""

import json
import time
import subprocess
from pathlib import Path
from unittest.mock import patch
import pytest

from orchestra.lib.sessions import Session, AgentType, save_session
from orchestra.lib.helpers import (
    start_docker_container,
    get_docker_container_name,
)


@pytest.mark.slow
class TestDockerContainerCreation:
    """Tests for Docker container setup and configuration"""

    def test_container_has_correct_mounts(self, docker_setup, tmp_path, cleanup_containers):
        """Test that container has correct volume mounts"""
        container_name = "orchestra-test-mounts"
        cleanup_containers(container_name)

        # Create a test worktree directory
        worktree = tmp_path / "test_worktree"
        worktree.mkdir()
        test_file = worktree / "test.txt"
        test_file.write_text("test content")

        # Start container
        success = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=8765,
            paired=False,
        )
        assert success, "Container should start successfully"

        # Verify worktree is mounted at /workspace
        result = subprocess.run(
            ["docker", "exec", container_name, "cat", "/workspace/test.txt"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "test content"

        # Verify shared Claude config is mounted
        result = subprocess.run(
            ["docker", "exec", container_name, "ls", "/home/executor/.claude"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, "Shared Claude config should be mounted"

    def test_container_runs_as_host_user(self, docker_setup, tmp_path, cleanup_containers):
        """Test that container runs with correct UID/GID for file permissions"""
        import os

        container_name = "orchestra-test-user"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        # Start container
        success = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=8765,
            paired=False,
        )
        assert success

        # Check UID/GID in container
        result = subprocess.run(
            ["docker", "exec", container_name, "id", "-u"],
            capture_output=True,
            text=True,
        )
        container_uid = result.stdout.strip()

        result = subprocess.run(
            ["docker", "exec", container_name, "id", "-g"],
            capture_output=True,
            text=True,
        )
        container_gid = result.stdout.strip()

        # Should match host user
        assert container_uid == str(os.getuid()), "Container UID should match host UID"
        assert container_gid == str(os.getgid()), "Container GID should match host GID"

        # Test file creation permissions
        subprocess.run(
            ["docker", "exec", container_name, "touch", "/workspace/testfile"],
            check=True,
        )

        testfile = worktree / "testfile"
        assert testfile.exists(), "File created in container should be visible on host"

    def test_container_lifecycle(self, docker_setup, tmp_path, cleanup_containers):
        """Test container start, reuse, and cleanup"""
        container_name = "orchestra-test-lifecycle"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        # Start container
        success = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=8765,
            paired=False,
        )
        assert success, "Container should start successfully"

        # Verify container is running
        result = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", container_name],
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "true"

        # Try to start again - should reuse
        success2 = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=8765,
            paired=False,
        )
        assert success2, "Should reuse existing container"

        # Stop container
        stop_docker_container(container_name)

        # Verify container is removed
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "Container should be removed"

        # Verify worktree persists after deletion
        assert worktree.exists(), "Worktree should persist after container deletion"

        # Note: cleanup_containers fixture will handle final cleanup


@pytest.mark.slow
class TestFullSpawnWorkflow:
    """Tests for complete executor spawning workflow"""

    def test_spawn_creates_all_artifacts(
        self, orchestra_test_env, mock_config_with_docker, docker_setup, cleanup_containers
    ):
        """Test that spawn_executor creates all required files and structures"""
        from orchestra.lib.sessions import Session, AgentType, save_session

        # Create parent designer session
        designer = Session(
            session_name="designer",
            agent_type=AgentType.DESIGNER,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        # Mock tmux start to avoid actual tmux session creation
        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            # Spawn executor
            child = designer.spawn_executor(
                session_name="test-executor",
                instructions="Test task instructions",
            )

        # Register container for cleanup
        container_name = get_docker_container_name(child.session_id)
        cleanup_containers(container_name)

        # Verify child session properties
        assert child.session_name == "test-executor"
        assert child.agent_type == AgentType.EXECUTOR
        assert child.parent_session_name == "designer"
        assert child.use_docker == True  # Should use Docker based on config
        assert child.work_path is not None

        worktree_path = Path(child.work_path)

        # 1. Verify worktree was created
        assert worktree_path.exists(), f"Worktree should exist at {worktree_path}"

        # 2. Verify instructions.md
        instructions_file = worktree_path / "instructions.md"
        assert instructions_file.exists(), "instructions.md should exist"
        assert "Test task instructions" in instructions_file.read_text()

        # 3. Verify .claude/orchestra.md
        orchestra_md = worktree_path / ".claude" / "orchestra.md"
        assert orchestra_md.exists(), ".claude/orchestra.md should exist"
        content = orchestra_md.read_text()
        assert "test-executor" in content, "Should contain session name"
        assert child.work_path in content, "Should contain work_path"

        # 4. Verify .claude/CLAUDE.md
        claude_md = worktree_path / ".claude" / "CLAUDE.md"
        assert claude_md.exists(), ".claude/CLAUDE.md should exist"
        assert "@orchestra.md" in claude_md.read_text()

        # 5. Verify .claude/commands/merge-child.md
        merge_cmd = worktree_path / ".claude" / "commands" / "merge-child.md"
        assert merge_cmd.exists(), "merge-child.md command should exist"

        # 6. Verify .claude/settings.json
        settings_json = worktree_path / ".claude" / "settings.json"
        assert settings_json.exists(), "settings.json should exist"
        settings = json.loads(settings_json.read_text())
        assert "permissions" in settings, "Settings should have permissions"

        # 7. Verify child added to parent.children
        assert len(designer.children) == 1
        assert designer.children[0].session_name == "test-executor"

        # 8. Verify session saved (persists relationship)
        from orchestra.lib.sessions import load_sessions

        loaded_sessions = load_sessions(project_dir=orchestra_test_env.repo)
        assert len(loaded_sessions) == 1
        assert loaded_sessions[0].session_name == "designer"
        assert len(loaded_sessions[0].children) == 1
        assert loaded_sessions[0].children[0].session_name == "test-executor"

    def test_spawn_creates_git_worktree(self, orchestra_test_env, mock_config_with_docker, docker_setup, cleanup_containers):
        """Test that spawn creates a proper git worktree on a new branch"""
        from orchestra.lib.sessions import Session, AgentType, save_session

        designer = Session(
            session_name="designer",
            agent_type=AgentType.DESIGNER,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            child = designer.spawn_executor(
                session_name="test-executor",
                instructions="Test task",
            )

        cleanup_containers(get_docker_container_name(child.session_id))

        # Verify worktree is a git worktree
        worktree_path = Path(child.work_path)
        git_file = worktree_path / ".git"
        assert git_file.exists(), ".git file should exist in worktree"

        # .git should be a file (not directory) for worktrees
        assert git_file.is_file(), ".git should be a file (pointing to main repo) in worktree"

        # Verify worktree is on its own branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True,
        )
        branch_name = result.stdout.strip()
        assert child.session_id in branch_name, f"Branch name should contain session_id, got: {branch_name}"


@pytest.mark.slow
class TestE2EMessagePassing:
    """End-to-end tests with real Docker containers and message passing"""

    def test_designer_to_executor_message_with_docker(
        self, orchestra_test_env, mock_config_with_docker, docker_setup, cleanup_containers
    ):
        """Test full E2E message passing from designer to executor in Docker"""
        from orchestra.lib.sessions import Session, AgentType, save_session
        from orchestra.backend.mcp_server import send_message_to_session

        # Create designer session
        designer = Session(
            session_name="designer",
            agent_type=AgentType.DESIGNER,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        # Spawn executor (creates Docker container)
        with patch("orchestra.lib.tmux_agent.TmuxProtocol.start", return_value=True):
            executor = designer.spawn_executor(
                session_name="test-executor",
                instructions="Test task",
            )

        cleanup_containers(get_docker_container_name(executor.session_id))

        # Start a real tmux session inside the Docker container
        container_name = get_docker_container_name(executor.session_id)

        subprocess.run(
            [
                "docker",
                "exec",
                "-d",
                container_name,
                "tmux",
                "-L",
                "orchestra",
                "new-session",
                "-d",
                "-s",
                executor.session_id,
            ],
            check=True,
        )

        # Wait a moment for tmux to be ready
        time.sleep(0.5)

        # Send message from designer to executor
        result = send_message_to_session(
            session_name="test-executor",
            message="Hello from designer",
            source_path=str(orchestra_test_env.repo),
            sender_name="designer",
        )

        assert "Successfully sent message" in result

        # Wait for message to be delivered
        time.sleep(0.5)

        # Verify message was received in executor's tmux session
        capture_result = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "tmux",
                "-L",
                "orchestra",
                "capture-pane",
                "-t",
                executor.session_id,
                "-p",
            ],
            capture_output=True,
            text=True,
        )

        pane_content = capture_result.stdout
        assert "[From: designer] Hello from designer" in pane_content, (
            f"Expected prefixed message in pane, got: {pane_content}"
        )
