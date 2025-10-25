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
    # Use a unique repo name based on tmp_path to avoid worktree conflicts
    # tmp_path is unique per test function
    import hashlib
    unique_id = hashlib.md5(str(tmp_path).encode()).hexdigest()[:8]
    repo_path = tmp_path / f"test_repo_{unique_id}"
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

    yield repo_path

    # Cleanup: Remove any worktrees associated with this repo before it's deleted
    try:
        # List all worktrees for this repo
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            lines = result.stdout.splitlines()
            worktree_paths = []
            for line in lines:
                if line.startswith("worktree "):
                    wt_path = line.split("worktree ")[1]
                    # Don't remove the main worktree (the repo itself)
                    if wt_path != str(repo_path):
                        worktree_paths.append(wt_path)

            # Remove all non-main worktrees
            for wt_path in worktree_paths:
                subprocess.run(
                    ["git", "worktree", "remove", wt_path, "--force"],
                    cwd=repo_path,
                    capture_output=True,
                )
    except Exception:
        pass  # Best effort cleanup


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
    monkeypatch.setattr("orchestra.lib.helpers.file_ops.SESSIONS_FILE", temp_sessions_file)

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

    # Patch get_tmux_server_name to return test socket name
    def test_get_tmux_server_name():
        return socket_name

    monkeypatch.setattr("orchestra.lib.helpers.tmux.build_tmux_cmd", test_build_tmux_cmd)
    monkeypatch.setattr("orchestra.lib.tmux_protocol.build_tmux_cmd", test_build_tmux_cmd)
    monkeypatch.setattr("orchestra.lib.config.get_tmux_server_name", test_get_tmux_server_name)

    yield socket_name

    # Cleanup: Kill test server after all tests
    subprocess.run(
        ["tmux", "-L", socket_name, "kill-server"],
        capture_output=True,
    )


class OrchestraTestEnv:
    """Complete test environment for Orchestra integration tests"""

    def __init__(self, git_repo: Path, sessions_file: Path, tmux_socket: str, orchestra_dir: Path):
        self.repo = git_repo
        self.sessions_file = sessions_file
        self.tmux = tmux_socket
        self.orchestra_dir = orchestra_dir


@pytest.fixture
def orchestra_test_env(temp_git_repo, isolated_sessions_file, mock_config, tmux, tmp_path, monkeypatch):
    """All-in-one fixture for Orchestra integration tests

    Provides a complete test environment with:
    - Temporary git repository with initial commit
    - Isolated sessions.json file
    - Mocked config (use_docker=False, mcp_port=8765)
    - Isolated tmux server on test socket
    - Temporary .orchestra directory
    - ORCHESTRA_HOME_DIR environment variable set

    Usage:
        def test_something(orchestra_test_env):
            env = orchestra_test_env

            # Access components
            repo_path = env.repo
            sessions_file = env.sessions_file
            tmux_socket = env.tmux
            orchestra_dir = env.orchestra_dir

            # Use tmux socket for subprocess calls
            subprocess.run(["tmux", "-L", env.tmux, "list-sessions"])
    """
    # Create .orchestra directory in the repo (where sessions actually work)
    orchestra_dir = temp_git_repo / ".orchestra"
    orchestra_dir.mkdir(parents=True, exist_ok=True)

    # Set ORCHESTRA_HOME_DIR for all tests using this fixture
    monkeypatch.setenv("ORCHESTRA_HOME_DIR", str(orchestra_dir))

    return OrchestraTestEnv(
        git_repo=temp_git_repo,
        sessions_file=isolated_sessions_file,
        tmux_socket=tmux,
        orchestra_dir=orchestra_dir,
    )


@pytest.fixture
def orchestra_test_env_with_custom_agents(orchestra_test_env):
    """Orchestra test environment with custom agent fixtures pre-loaded

    This fixture extends orchestra_test_env by copying custom agent files
    into the test .orchestra directory, so tests can use custom agents
    without manual setup.

    Provides everything from orchestra_test_env plus:
    - Custom agent Python modules in .orchestra/custom_agents/
    - Custom agent config in .orchestra/config/agents.yaml

    Usage:
        def test_something(orchestra_test_env_with_custom_agents):
            env = orchestra_test_env_with_custom_agents
            # Custom agents are ready to use
            agent = load_agent("hello-agent")
    """
    import shutil

    fixtures_dir = Path(__file__).parent / "fixtures"

    # Copy custom_agents directory
    custom_agents_src = fixtures_dir / "custom_agents"
    custom_agents_dst = orchestra_test_env.orchestra_dir / "custom_agents"
    shutil.copytree(custom_agents_src, custom_agents_dst)

    # Copy test agents.yaml
    config_dir = orchestra_test_env.orchestra_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    test_config = fixtures_dir / "config" / "agents.yaml"
    shutil.copy(test_config, config_dir / "agents.yaml")

    return orchestra_test_env


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
            assert designer_session.agent.name == "designer"
            assert designer_session.work_path is not None

            # Spawn a child
            designer_session.spawn_child("child", "Task instructions")
    """
    from orchestra.lib.sessions import Session, save_session
    from orchestra.lib.agent import DESIGNER_AGENT

    session = Session(
        session_name="designer",
        agent=DESIGNER_AGENT,
        source_path=str(orchestra_test_env.repo),
    )
    session.prepare()
    save_session(session, project_dir=orchestra_test_env.repo)

    return session


@pytest.fixture
def designer_session_with_custom_agents(orchestra_test_env_with_custom_agents):
    """Create a prepared designer session with custom agents available

    Like designer_session, but with custom agent fixtures pre-loaded,
    so spawned children can use custom agent types.

    Usage:
        def test_something(designer_session_with_custom_agents):
            # Spawn a child with custom agent type
            child = designer_session_with_custom_agents.spawn_child(
                "test-child", "Do something", agent_type="hello-agent"
            )
    """
    from orchestra.lib.sessions import Session, save_session
    from orchestra.lib.agent import DESIGNER_AGENT

    session = Session(
        session_name="designer",
        agent=DESIGNER_AGENT,
        source_path=str(orchestra_test_env_with_custom_agents.repo),
    )
    session.prepare()
    save_session(session, project_dir=orchestra_test_env_with_custom_agents.repo)

    return session


@pytest.fixture(scope="session")
def docker_available():
    """Check if Docker is available, skip tests if not

    Session-scoped so the check only happens once per test session.
    """
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip("Docker is not available")
    except FileNotFoundError:
        pytest.skip("Docker is not installed")
    return True


@pytest.fixture(scope="session")
def docker_setup(docker_available):
    """One-time Docker setup for all tests

    This fixture:
    - Ensures the orchestra-image is built once
    - Returns image info
    - Session-scoped so it only runs once for entire test suite

    Usage:
        def test_something(docker_setup):
            # orchestra-image is guaranteed to exist
            ...
    """
    from orchestra.lib.helpers.docker import ensure_docker_image

    # Build image once for all tests
    ensure_docker_image()

    # Get image ID for verification
    result = subprocess.run(
        ["docker", "images", "-q", "orchestra-image"],
        capture_output=True,
        text=True,
    )
    image_id = result.stdout.strip()

    return {
        "image_id": image_id,
        "image_name": "orchestra-image",
    }


@pytest.fixture
def cleanup_containers(request):
    """Ensure test containers are cleaned up after tests

    Usage in tests:
        def test_something(cleanup_containers):
            cleanup_containers("my-container-name")
            # ... test code that creates container ...
            # Container will be cleaned up automatically after test
    """
    from orchestra.lib.helpers.docker import stop_docker_container

    containers_to_cleanup = []

    def register_container(container_name: str):
        """Register a container for cleanup"""
        containers_to_cleanup.append(container_name)
        return container_name

    yield register_container

    # Cleanup all registered containers
    for container_name in containers_to_cleanup:
        try:
            stop_docker_container(container_name)
        except Exception as e:
            print(f"Warning: Failed to cleanup container {container_name}: {e}")


@pytest.fixture
def mock_config_with_docker(monkeypatch):
    """Mock config loading to return test configuration with use_docker=True"""
    test_config = {
        "mcp_port": 8765,
        "use_docker": True,  # Enable Docker for these tests
    }

    monkeypatch.setattr("orchestra.lib.sessions.load_config", lambda: test_config)
    monkeypatch.setattr("orchestra.lib.config.load_config", lambda: test_config)

    return test_config

@pytest.fixture
def executor_session(orchestra_test_env, monkeypatch):
    """Create a prepared executor session for testing

    Returns a Session object that:
    - Is an EXECUTOR type (works in separate worktree)
    - Has use_docker=False
    - Is prepared (worktree created, work_path set)
    - Is saved to sessions.json
    - Has a separate worktree with its own branch

    Usage:
        def test_something(executor_session):
            # Session is ready to use
            assert executor_session.agent.name == "executor"
            assert executor_session.work_path is not None
            assert executor_session.work_path != executor_session.source_path

            # Test pairing
            executor_session.toggle_pairing()
    """
    from orchestra.lib.sessions import Session, save_session
    from orchestra.lib.agent import EXECUTOR_AGENT
    import os

    # Temporarily unset ORCHESTRA_HOME_DIR so worktrees are created in default location
    # This is needed for pairing tests to work correctly
    if "ORCHESTRA_HOME_DIR" in os.environ:
        monkeypatch.delenv("ORCHESTRA_HOME_DIR")

    session = Session(
        session_name="executor",
        agent=EXECUTOR_AGENT,
        source_path=str(orchestra_test_env.repo),
        parent_session_name="test-parent",  # Make it non-root
    )
    session.prepare()
    save_session(session, project_dir=orchestra_test_env.repo)

    yield session

    # Cleanup: Remove worktree after test
    import subprocess
    import shutil
    from pathlib import Path

    try:
        # Remove the worktree
        if session.work_path and Path(session.work_path).exists():
            subprocess.run(
                ["git", "worktree", "remove", session.work_path, "--force"],
                cwd=session.source_path,
                capture_output=True,
            )

        # Remove the branch
        subprocess.run(
            ["git", "branch", "-D", session.session_id],
            cwd=session.source_path,
            capture_output=True,
        )

        # Clean up backup if it exists (from pairing tests)
        backup = Path(f"{session.source_path}.backup")
        if backup.exists():
            shutil.rmtree(backup)

        # Clean up symlink if it exists
        source = Path(session.source_path)
        if source.is_symlink():
            source.unlink()
            # Restore from backup if available
            if backup.exists():
                backup.rename(source)
    except Exception:
        pass  # Best effort cleanup
