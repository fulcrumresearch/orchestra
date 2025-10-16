# Orchestra Test Suite Design Plan

## Executive Summary

This document outlines the testing strategy for Orchestra, a system that manages multiple Claude Code sessions using tmux, Docker containers, git worktrees, and an MCP server for inter-session communication.

Key structure and central abstractions/fixtures

## Key Architecture Components to Test

### 1. **Session Management** (`orchestra/lib/sessions.py`)
- Session creation (Designer vs Executor types)
- Session preparation (work_path setup, worktrees)
- Session persistence (sessions.json file operations)

### 2. **MCP Server** (`orchestra/backend/mcp_server.py`)
- `spawn_subagent()` - spawns child sessions
- `send_message_to_session()` - inter-session messaging
- Session lookup (by name/ID)

### 3. **Protocol Layer** (`orchestra/lib/tmux_agent.py`)
- Tmux session lifecycle (start, stop, status)
- Docker container management
- Message passing (with retry logic)
- Pairing mode (symlink toggling)
- Local vs Docker execution modes

## Testing Strategy

### Test Pyramid

```
        E2E Tests (5-10 tests)
     ┌─────────────────────┐
     │ Real tmux + Docker  │
     └─────────────────────┘
            ▲
            │
    Integration Tests (15-20 tests)
  ┌─────────────────────────────┐
  │ Mocked subprocess/Docker    │
  │ Real file system operations │
  └─────────────────────────────┘
            ▲
            │
      Unit Tests (30-40 tests)
┌──────────────────────────────────┐
│ Pure functions, data structures  │
│ Minimal external dependencies    │
└──────────────────────────────────┘
```

## Test Structure Proposal

### Directory Structure
```
tests/
├── conftest.py              # Shared fixtures
├── unit/
│   ├── test_sessions.py     # Session data structures
│   ├── test_mcp_server.py   # MCP server functions
│   └── test_helpers.py      # Helper utilities
├── integration/
│   ├── test_session_lifecycle.py  # Session prepare/spawn
│   └── test_docker_container.py   # Container management
└── e2e/
    ├── test_spawn_and_message.py  # Full workflow
    ├── test_pairing.py            # Pairing mode
    └── test_container_lifecycle.py # Real container ops
```

### Fixture Strategy (conftest.py)

#### Essential Fixtures:
1. **`temp_git_repo`** - Creates a real git repo in tmp_path
   - Initializes with .git
   - Has a main branch with initial commit
   - Returns path to repo
   - Cleanup automatic

2. **`mock_config`** - Mocks config loading
   - Returns default config dict
   - Avoids reading real ~/.orchestra/config.json

3. **`mock_docker_subprocess`** - Mocks docker subprocess calls
   - Intercepts docker commands
   - Returns simulated success responses
   - Tracks calls for assertions

4. **`mock_tmux_subprocess`** - Mocks tmux subprocess calls

let's not mock tmux, just have a testing tmux server.

5. **`isolated_sessions_file`** - Uses temporary sessions.json
   - Patches SESSIONS_FILE constant
   - Returns path to temp file
   - Cleanup automatic

6. **`sample_session`** - Factory for creating test sessions
   - Parameterizable (designer/executor, docker/local)
   - Pre-configured with valid paths
   - Can be persisted to isolated_sessions_file

### Mocking Strategy

#### What to Mock:
- ✅ `subprocess.run` for docker/tmux/git commands
- ✅ File system paths (use tmp_path)
- ✅ Config file loading


#### Mocking Levels by Test Type:

**Unit Tests**: Mock all external I/O
```python
@pytest.fixture
def mock_all_subprocess(mocker):
    """Mock all subprocess calls"""
    return mocker.patch('subprocess.run', return_value=CompletedProcess(
        args=[], returncode=0, stdout='', stderr=''
    ))
```

**Integration Tests**: Mock only external services (Docker, tmux), allow real file I/O
```python
@pytest.fixture
def mock_docker_only(mocker):
    """Mock only Docker subprocess calls, allow git/file operations"""
    def side_effect(cmd, **kwargs):
        if cmd[0] == 'docker':
            return CompletedProcess(args=cmd, returncode=0, stdout='', stderr='')
        return subprocess_run_real(cmd, **kwargs)

    return mocker.patch('subprocess.run', side_effect=side_effect)
```

**E2E Tests**: No mocks (or skip if dependencies unavailable)
```python
@pytest.mark.e2e
@pytest.mark.skipif(not shutil.which('docker'), reason="Docker not available")
def test_real_container_spawn():
    """Use real Docker and tmux"""
    pass
```

## Detailed Test Cases

### Unit Tests (tests/unit/)

#### test_mcp_server.py (6-8 tests)
1. `test_spawn_subagent_success` - Creates child, updates parent
2. `test_spawn_subagent_parent_not_found` - Error message
3. `test_spawn_subagent_saves_session` - Persists to file
4. `test_send_message_success` - Sends with prefix
5. `test_send_message_not_found` - Error message
6. `test_send_message_prefixes_sender` - Adds "[From: X]"
7. `test_spawn_subagent_creates_instructions_file` - instructions.md created
8. `test_spawn_subagent_creates_merge_command` - .claude/commands/merge-child.md

### Integration Tests (tests/integration/)

#### test_session_lifecycle.py (8-10 tests)
2. `test_designer_prepare_adds_instructions` - .claude/orchestra.md created
3. `test_executor_prepare_creates_worktree` - git worktree add
4. `test_executor_prepare_creates_branch` - New branch created
5. `test_executor_prepare_adds_instructions` - .claude files created
6. `test_executor_prepare_creates_merge_command` - merge-child.md
7. `test_spawn_executor_creates_child` - Child added to parent.children
8. `test_spawn_executor_sets_parent_name` - parent_session_name set
9. `test_spawn_executor_creates_instructions_md` - instructions.md with content
10. `test_spawn_executor_creates_settings_json` - .claude/settings.json


### E2E Tests (tests/e2e/)

#### test_spawn_and_message.py (2-3 tests)
1. `test_full_spawn_workflow` - Designer → spawn executor → verify container + tmux
2. `test_message_passing` - Designer → send message → executor receives
3. `test_multiple_children` - Spawn 2 executors, both work independently

#### test_pairing.py (3-4 tests)
1. `test_toggle_pairing_creates_symlink` - source → worktree symlink
2. `test_toggle_pairing_updates_git_file` - .git file points to backup
3. `test_toggle_pairing_back_restores` - Unpair restores original
4. `test_pairing_not_available_for_designer` - Error message

#### test_container_lifecycle.py (2-3 tests)
1. `test_container_has_correct_mounts` - Verify all mounts present
2. `test_container_cleanup_preserves_worktree` - Container deleted, worktree persists
3. `test_container_runs_as_host_user` - UID/GID match

put these together, reuse a single container and check all relevant properties

#### test_docker_container.py (6-8 tests)
1. `test_start_docker_container_mounts_workspace` - -v work_path:/workspace
2. `test_start_docker_container_mounts_claude_config` - Shared config mounted
3. `test_start_docker_container_mounts_tmux_config` - tmux.conf mounted
4. `test_start_docker_container_sets_api_key` - ANTHROPIC_API_KEY env
5. `test_start_docker_container_adds_host_gateway` - host.docker.internal
6. `test_start_docker_container_reuses_running` - Skips if already running
7. `test_ensure_docker_image_builds_with_uid_gid` - Passes USER_ID, GROUP_ID
8. `test_shared_claude_config_mcp_url` - Uses host.docker.internal


### 3. **Temp Path Usage**
- Always use pytest's `tmp_path` fixture
- Never write to real ~/.orchestra in tests
- Patch SESSIONS_FILE constant to point to temp location

### 4. **E2E Test Cleanup**
```python
@pytest.fixture
def cleanup_docker():
    """Ensure Docker containers are cleaned up"""
    yield
    # Cleanup after test
    subprocess.run(['docker', 'ps', '-aq', '-f', 'name=orchestra-test-*'], ...)
    subprocess.run(['docker', 'rm', '-f', ...], ...)
```

### 5. **Assertion Patterns**
```python
# Good: Test behavior, not implementation
assert session.session_id == "myproject-test-session"
assert len(parent.children) == 1
assert Path(work_path / "instructions.md").exists()

# Bad: Test internal state
assert session._internal_cache is not None
```



## Questions/Decisions Needed

1. **Should we test the UI components** (textual app)? → Defer to later
2. **How to handle ANTHROPIC_API_KEY in tests?** → Use fake key, or skip tests requiring API
3. **Should E2E tests cleanup worktrees?** → Yes, but save failure artifacts for debugging
4. **Test on both Linux and macOS?** → Yes, CI should run on both (pairing behavior differs)
