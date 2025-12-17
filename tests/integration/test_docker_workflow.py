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

from orchestra.lib.sessions import Session, save_session, load_sessions
from orchestra.lib.agent import DESIGNER_AGENT, EXECUTOR_AGENT
from orchestra.lib.helpers.docker import (
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
            monitor_port=8081,
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
            monitor_port=8081,
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


@pytest.mark.slow
class TestFullSpawnWorkflow:
    """Tests for complete executor spawning workflow"""

    def test_spawn_creates_all_artifacts(
        self, orchestra_test_env, mock_config_with_docker, docker_setup, cleanup_containers
    ):
        """Test that spawn_executor creates all required files and structures"""
        # Create parent designer session
        designer = Session(
            session_name="designer",
            agent=DESIGNER_AGENT,
            source_path=str(orchestra_test_env.repo),
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        # Mock tmux start to avoid actual tmux session creation
        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            # Spawn executor
            child = designer.spawn_child(
                session_name="test-executor",
                instructions="Test task instructions",
            )

        # Save the designer session to persist the child relationship
        save_session(designer, project_dir=orchestra_test_env.repo)

        # Register container for cleanup
        container_name = get_docker_container_name(child.session_id)
        cleanup_containers(container_name)

        # Verify child session properties
        assert child.session_name == "test-executor"
        assert child.agent.name == "executor"
        assert child.parent_session_name == "designer"
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

        # 5. Verify .claude/settings.json
        settings_json = worktree_path / ".claude" / "settings.json"
        assert settings_json.exists(), "settings.json should exist"
        settings = json.loads(settings_json.read_text())
        assert "permissions" in settings, "Settings should have permissions"

        # 6. Verify child added to parent.children
        assert len(designer.children) == 1
        assert designer.children[0].session_name == "test-executor"

        # 7. Verify session saved (persists relationship)
        loaded_sessions = load_sessions(project_dir=orchestra_test_env.repo)
        assert len(loaded_sessions) == 1
        assert loaded_sessions[0].session_name == "designer"
        assert len(loaded_sessions[0].children) == 1
        assert loaded_sessions[0].children[0].session_name == "test-executor"

    def test_spawn_creates_git_worktree(self, orchestra_test_env, mock_config_with_docker, docker_setup, cleanup_containers):
        """Test that spawn creates a proper git worktree on a new branch"""
        designer = Session(
            session_name="designer",
            agent=DESIGNER_AGENT,
            source_path=str(orchestra_test_env.repo),
            use_docker=False,
        )
        designer.prepare()
        save_session(designer, project_dir=orchestra_test_env.repo)

        with patch("orchestra.lib.tmux_protocol.TmuxProtocol.start", return_value=True):
            child = designer.spawn_child(
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
class TestDockerNetworkConnectivity:
    """Tests for Docker container connectivity to MCP and Monitor servers"""

    def test_container_can_reach_mcp_server(self, docker_setup, tmp_path, cleanup_containers):
        """Test that container can connect to MCP server via localhost with custom port"""
        import subprocess
        import os
        from unittest.mock import patch

        # Use custom ports to test config is respected
        custom_mcp_port = 9876
        custom_monitor_port = 9877

        container_name = "orchestra-test-mcp-connectivity"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        # Start MCP server on custom port
        mcp_log = tmp_path / "mcp-server.log"
        with open(mcp_log, "w") as log_file:
            # Override the port by patching config
            with patch("orchestra.backend.mcp_server.default_port", custom_mcp_port):
                mcp_proc = subprocess.Popen(
                    ["python3", "-m", "orchestra.backend.mcp_server"],
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True,
                )

        try:
            # Give server time to start
            time.sleep(2)

            # Start container with custom ports
            success = start_docker_container(
                container_name=container_name,
                work_path=str(worktree),
                mcp_port=custom_mcp_port,
                monitor_port=custom_monitor_port,
                paired=False,
            )
            assert success, "Container should start successfully"

            # Test connectivity from inside container to MCP server
            result = subprocess.run(
                [
                    "docker", "exec", container_name,
                    "python3", "-c",
                    f"import urllib.request; "
                    f"response = urllib.request.urlopen('http://localhost:{custom_mcp_port}/mcp', timeout=5); "
                    f"print('SUCCESS' if response.getcode() == 200 else 'FAILED')"
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            assert result.returncode == 0, f"MCP connectivity check failed: {result.stderr}"
            assert "SUCCESS" in result.stdout, "Container should be able to reach MCP server via localhost"

            # Verify port forwarding is configured correctly
            inspect_result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
            )
            assert inspect_result.returncode == 0

            inspect_data = json.loads(inspect_result.stdout)
            port_bindings = inspect_data[0]["HostConfig"]["PortBindings"]

            # Verify MCP port is bound to 127.0.0.1
            mcp_binding_key = f"{custom_mcp_port}/tcp"
            assert mcp_binding_key in port_bindings, f"MCP port {custom_mcp_port} should be in port bindings"
            assert port_bindings[mcp_binding_key][0]["HostIp"] == "127.0.0.1", "MCP port should be bound to 127.0.0.1"
            assert port_bindings[mcp_binding_key][0]["HostPort"] == str(custom_mcp_port), "MCP port should match config"

        finally:
            # Cleanup MCP server
            os.killpg(os.getpgid(mcp_proc.pid), 15)
            mcp_proc.wait(timeout=5)

    def test_container_receives_monitor_env_var(self, docker_setup, tmp_path, cleanup_containers):
        """Test that container receives CLAUDE_MONITOR_BASE environment variable"""
        import subprocess

        custom_monitor_port = 9988
        container_name = "orchestra-test-monitor-env"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        # Start container with custom monitor port
        success = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=8765,
            monitor_port=custom_monitor_port,
            paired=False,
        )
        assert success, "Container should start successfully"

        # Check that CLAUDE_MONITOR_BASE env var is set correctly
        result = subprocess.run(
            ["docker", "exec", container_name, "printenv", "CLAUDE_MONITOR_BASE"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, "CLAUDE_MONITOR_BASE should be set in container"
        expected_url = f"http://localhost:{custom_monitor_port}"
        assert result.stdout.strip() == expected_url, f"CLAUDE_MONITOR_BASE should be {expected_url}"

    def test_container_port_forwarding_localhost_only(self, docker_setup, tmp_path, cleanup_containers):
        """Test that port forwarding is bound to 127.0.0.1 only (not 0.0.0.0)"""
        import subprocess

        container_name = "orchestra-test-port-binding"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        mcp_port = 8765
        monitor_port = 8081

        # Start container
        success = start_docker_container(
            container_name=container_name,
            work_path=str(worktree),
            mcp_port=mcp_port,
            monitor_port=monitor_port,
            paired=False,
        )
        assert success, "Container should start successfully"

        # Inspect container port bindings
        result = subprocess.run(
            ["docker", "inspect", container_name],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        inspect_data = json.loads(result.stdout)
        port_bindings = inspect_data[0]["HostConfig"]["PortBindings"]

        # Verify both MCP and Monitor ports are bound to 127.0.0.1
        mcp_key = f"{mcp_port}/tcp"
        monitor_key = f"{monitor_port}/tcp"

        assert mcp_key in port_bindings, "MCP port should be in bindings"
        assert monitor_key in port_bindings, "Monitor port should be in bindings"

        # Check MCP port binding
        assert port_bindings[mcp_key][0]["HostIp"] == "127.0.0.1", "MCP port should be bound to localhost only"
        assert port_bindings[mcp_key][0]["HostPort"] == str(mcp_port), "MCP host port should match container port"

        # Check Monitor port binding
        assert port_bindings[monitor_key][0]["HostIp"] == "127.0.0.1", "Monitor port should be bound to localhost only"
        assert port_bindings[monitor_key][0]["HostPort"] == str(monitor_port), "Monitor host port should match container port"

    def test_config_ports_are_respected(self, docker_setup, tmp_path, cleanup_containers):
        """Test that custom ports from config are properly used throughout the system"""
        from unittest.mock import patch
        from orchestra.lib.config import load_config

        # Mock config with custom ports
        custom_config = {
            "use_docker": True,
            "mcp_port": 7777,
            "monitor_port": 7778,
            "ui_theme": "textual-dark",
        }

        container_name = "orchestra-test-config-ports"
        cleanup_containers(container_name)

        worktree = tmp_path / "test_worktree"
        worktree.mkdir()

        with patch("orchestra.lib.config.load_config", return_value=custom_config):
            # Manually call with config values (simulating what Session would do)
            success = start_docker_container(
                container_name=container_name,
                work_path=str(worktree),
                mcp_port=custom_config["mcp_port"],
                monitor_port=custom_config["monitor_port"],
                paired=False,
            )
            assert success, "Container should start with custom ports"

            # Verify ports in container inspection
            result = subprocess.run(
                ["docker", "inspect", container_name],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0

            inspect_data = json.loads(result.stdout)
            port_bindings = inspect_data[0]["HostConfig"]["PortBindings"]

            # Verify custom ports are used
            assert f"{custom_config['mcp_port']}/tcp" in port_bindings, "Custom MCP port should be bound"
            assert f"{custom_config['monitor_port']}/tcp" in port_bindings, "Custom monitor port should be bound"

            # Verify CLAUDE_MONITOR_BASE uses custom port
            result = subprocess.run(
                ["docker", "exec", container_name, "printenv", "CLAUDE_MONITOR_BASE"],
                capture_output=True,
                text=True,
            )
            expected_monitor_url = f"http://localhost:{custom_config['monitor_port']}"
            assert result.stdout.strip() == expected_monitor_url, "CLAUDE_MONITOR_BASE should use custom port"

