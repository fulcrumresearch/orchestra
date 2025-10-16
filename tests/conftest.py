"""Shared pytest fixtures for Orchestra tests"""

import pytest
import subprocess
from pathlib import Path


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository for testing

    Returns:
        Path: Path to the temporary git repository
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, capture_output=True, check=True)

    # Create initial commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Repository")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True, check=True)

    return repo_path


@pytest.fixture
def isolated_sessions_file(tmp_path, monkeypatch):
    """Use a temporary sessions.json file isolated from the real one

    This fixture:
    1. Creates a temporary sessions.json file
    2. Patches SESSIONS_FILE in all relevant modules
    3. Ensures tests don't affect the real sessions file

    Returns:
        Path: Path to the temporary sessions file
    """
    temp_sessions_file = tmp_path / "sessions.json"

    # Patch SESSIONS_FILE in all modules that use it
    monkeypatch.setattr("orchestra.lib.sessions.SESSIONS_FILE", temp_sessions_file)
    monkeypatch.setattr("orchestra.lib.helpers.SESSIONS_FILE", temp_sessions_file)

    # Initialize empty sessions file
    temp_sessions_file.write_text("{}")

    return temp_sessions_file


@pytest.fixture
def mock_config(monkeypatch):
    """Mock config loading to return test configuration with use_docker=False"""
    test_config = {
        "mcp_port": 8765,
        "use_docker": False,  # No Docker for integration tests
    }

    monkeypatch.setattr("orchestra.lib.sessions.load_config", lambda: test_config)

    return test_config


@pytest.fixture
def tmux(monkeypatch):
    """Patch Orchestra's tmux commands to use an isolated test socket

    This fixture:
    1. Creates an isolated tmux server using socket "orchestra-test"
    2. Patches build_tmux_cmd so all Orchestra code uses this test socket
    3. Cleans up sessions before each test
    4. Returns the socket name for direct subprocess calls

    Usage in tests:
        def test_something(tmux):
            # Orchestra's real code will use test socket automatically
            from orchestra.lib.sessions import Session
            session.start()  # Uses test socket

            # Or use socket name directly for subprocess calls
            subprocess.run(["tmux", "-L", tmux, "new-session", "-d", "-s", "test"])
    """
    socket_name = "orchestra-test"

    # Clean up any existing sessions before test
    result = subprocess.run(
        ["tmux", "-L", socket_name, "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        for session in result.stdout.strip().split("\n"):
            subprocess.run(
                ["tmux", "-L", socket_name, "kill-session", "-t", session],
                capture_output=True,
            )

    # Patch build_tmux_cmd to use test socket
    def test_build_tmux_cmd(*args):
        return ["tmux", "-L", socket_name] + list(args)

    monkeypatch.setattr("orchestra.lib.tmux.build_tmux_cmd", test_build_tmux_cmd)
    monkeypatch.setattr("orchestra.lib.tmux_agent.build_tmux_cmd", test_build_tmux_cmd)

    yield socket_name

    # Cleanup: Kill test server after all tests
    subprocess.run(
        ["tmux", "-L", socket_name, "kill-server"],
        capture_output=True,
    )


class OrchestraTestEnv:
    """Complete test environment for Orchestra integration tests"""

    def __init__(self, git_repo: Path, sessions_file: Path, tmux_socket: str):
        self.repo = git_repo
        self.sessions_file = sessions_file
        self.tmux = tmux_socket


@pytest.fixture
def orchestra_test_env(temp_git_repo, isolated_sessions_file, mock_config, tmux):
    """All-in-one fixture for Orchestra integration tests

    Provides a complete test environment with:
    - Temporary git repository with initial commit
    - Isolated sessions.json file
    - Mocked config (use_docker=False, mcp_port=8765)
    - Isolated tmux server on test socket

    Usage:
        def test_something(orchestra_test_env):
            env = orchestra_test_env

            # Access components
            repo_path = env.repo
            sessions_file = env.sessions_file
            tmux_socket = env.tmux

            # Use tmux socket for subprocess calls
            subprocess.run(["tmux", "-L", env.tmux, "list-sessions"])
    """
    return OrchestraTestEnv(
        git_repo=temp_git_repo,
        sessions_file=isolated_sessions_file,
        tmux_socket=tmux,
    )


@pytest.fixture
def designer_session(orchestra_test_env):
    """Create a prepared designer session for testing

    Returns a Session object that:
    - Is a DESIGNER type (works in source directory)
    - Has use_docker=False
    - Is prepared (work_path set)
    - Is saved to sessions.json

    Usage:
        def test_something(designer_session):
            # Session is ready to use
            assert designer_session.agent_type == AgentType.DESIGNER
            assert designer_session.work_path is not None

            # Spawn a child
            designer_session.spawn_executor("child", "Task instructions")
    """
    from orchestra.lib.sessions import Session, AgentType, save_session

    session = Session(
        session_name="designer",
        agent_type=AgentType.DESIGNER,
        source_path=str(orchestra_test_env.repo),
        use_docker=False,
    )
    session.prepare()
    save_session(session, project_dir=orchestra_test_env.repo)

    return session
