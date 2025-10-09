<<<<<<< HEAD
# Task: Refactor kerberos.py into Frontend/Backend Structure

## Overview
Split the 1039-line `cerb_code/runners/kerberos.py` into clean, modular components. Full design spec is in @designer.md - please review it first.

## Architecture Summary

```
cerb_code/
├── backend/
│   ├── mcp_server.py    (move from runners/)
│   └── monitor.py       (move from runners/)
├── frontend/
│   ├── state.py         (NEW: app state)
│   ├── app.py           (refactored kerberos.py)
│   └── widgets/
│       ├── hud.py
│       ├── session_list.py
│       ├── diff_tab.py
│       └── monitor_tab.py
├── lib/
│   └── helpers.py       (add tmux pane helpers)
└── runners/
    └── kerberos.py      (minimal entry point)
```

## Key Design Decisions

1. **State separation**: AppState holds data (root_session, active_session_id, paired_session_id), no UI logic
2. **Simple hierarchy**: Just root_session (designer) + root_session.children (executors), no deep nesting
3. **File watching**: App owns the watch loop, calls state.load() when sessions.json changes
4. **Tmux helpers**: Generic respawn_pane() base function + specialized helpers
5. **No protocols in state**: Each Session has its own protocol, no global one

## Implementation Steps

### Step 1: Create Directory Structure

```bash
mkdir -p cerb_code/backend
mkdir -p cerb_code/frontend/widgets
touch cerb_code/backend/__init__.py
touch cerb_code/frontend/__init__.py
touch cerb_code/frontend/widgets/__init__.py
```

### Step 2: Move Backend Servers

Move the already-working servers:
```bash
git mv cerb_code/runners/mcp_server.py cerb_code/backend/
git mv cerb_code/runners/monitor.py cerb_code/backend/
```

Update imports in `cerb_code/runners/kerberos.py` main() function:
```python
# Change from:
# from cerb_code.runners.mcp_server import ...
# To:
from cerb_code.backend.mcp_server import main as mcp_main
from cerb_code.backend.monitor import main as monitor_main
```

Test: Run `cerb` and verify servers still start.

### Step 3: Create AppState

Create `cerb_code/frontend/state.py`:

```python
from pathlib import Path
from typing import Optional, List
from cerb_code.lib.sessions import Session, load_sessions, SESSIONS_FILE
from cerb_code.lib.file_watcher import FileWatcher

class AppState:
    def __init__(self, project_dir: Path):
        self.root_session: Optional[Session] = None
        self.active_session_id: Optional[str] = None
        self.paired_session_id: Optional[str] = None
        self.project_dir = project_dir
        self.file_watcher = FileWatcher()

    def load(self, root_session_id: str) -> None:
        """Load sessions from disk"""
        sessions = load_sessions(root=root_session_id, project_dir=self.project_dir)
        self.root_session = sessions[0] if sessions else None

    def get_flat_sessions(self) -> List[Session]:
        """Get flat list: [root_session] + root_session.children"""
        if not self.root_session:
            return []
        return [self.root_session] + self.root_session.children

    def get_active_session(self) -> Optional[Session]:
        """Get currently active session"""
        if not self.active_session_id:
            return None
        for session in self.get_flat_sessions():
            if session.session_id == self.active_session_id:
                return session
        return None
```

### Step 4: Add Tmux Helpers

Add to `cerb_code/lib/helpers.py`:

```python
import subprocess

# Pane constants
PANE_UI = "0"
PANE_EDITOR = "1"
PANE_AGENT = "2"

def respawn_pane(pane: str, command: str) -> bool:
    """Generic helper to respawn a pane with a command"""
    result = subprocess.run(
        ["tmux", "-L", "orchestra", "respawn-pane", "-t", pane, "-k", command],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0

def respawn_pane_with_vim(spec_file) -> bool:
    """Open vim in editor pane"""
    vim_cmd = f"bash -c '$EDITOR {spec_file}; clear; echo \"Press S to open spec editor\"; exec bash'"
    return respawn_pane(PANE_EDITOR, vim_cmd)

def respawn_pane_with_terminal(work_path) -> bool:
    """Open bash in editor pane"""
    bash_cmd = f"bash -c 'cd {work_path} && exec bash'"
    return respawn_pane(PANE_EDITOR, bash_cmd)

def clear_pane(pane: str, message: str = "") -> bool:
    """Clear pane with optional message"""
    cmd = f"echo '{message}'" if message else "clear"
    return respawn_pane(pane, cmd)
```

### Step 5: Extract Widgets

Move existing widget classes to separate files:

**`cerb_code/frontend/widgets/hud.py`**:
```python
from textual.widgets import Static

class HUD(Static):
    can_focus = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.default_text = "⌃D delete • ⌃R refresh • P pair • S spec • T terminal • ⌃Q quit"
        self.current_session = ""

    def set_session(self, session_name: str):
        """Update the current session display"""
        self.current_session = session_name
        self.update(f"[{session_name}] • {self.default_text}")
```

**`cerb_code/frontend/widgets/diff_tab.py`**:
- Move the `DiffTab` class as-is (~85 lines)
- Update to get current session from `self.app.state.get_active_session()`

**`cerb_code/frontend/widgets/monitor_tab.py`**:
- Move the `ModelMonitorTab` class as-is (~129 lines)
- Update to get current session from `self.app.state.get_active_session()`

**`cerb_code/frontend/widgets/session_list.py`**:
- Extract session list rendering logic from UnifiedApp
- Create a Container with ListView that shows the session tree
- Handle selection and emit events

### Step 6: Refactor UnifiedApp

Create `cerb_code/frontend/app.py` with simplified UnifiedApp:

Key changes:
1. Move all state fields to `self.state = AppState(...)`
2. Replace `self.sessions` with `self.state.root_session`
3. Replace `self.current_session` with `self.state.get_active_session()`
4. Replace `self.paired_session_id` with `self.state.paired_session_id`
5. Use tmux helpers instead of inline subprocess calls
6. Keep all the action handlers but simplify them
7. Move file watching to `_watch_sessions_file()` method

Example action handler:
```python
def action_open_spec(self) -> None:
    """Open designer.md in vim"""
    session = self.state.get_active_session()
    if not session:
        return

    spec_file = Path(session.work_path) / "designer.md"
    if not spec_file.exists():
        spec_file.touch()

    # Use helper instead of inline subprocess
    respawn_pane_with_vim(spec_file)

    # Register file watcher
    watch_designer_file(self.state.file_watcher, spec_file, session)
```

### Step 7: Update Imports in kerberos.py

In `cerb_code/runners/kerberos.py`, update to import from new locations:
```python
from cerb_code.frontend.app import UnifiedApp
from cerb_code.backend.mcp_server import main as mcp_main
from cerb_code.backend.monitor import main as monitor_main
```

Keep the `main()` function that starts the servers and runs the app.

## Testing at Each Step

After each step:
1. Run `cerb` and verify UI starts
2. Check that sessions load and display
3. Test keyboard shortcuts work
4. Test session operations (delete, pair, open spec/terminal)
5. Verify no regressions

## Success Criteria

- [ ] `cerb_code/backend/` contains mcp_server.py and monitor.py
- [ ] `cerb_code/frontend/state.py` holds all app state
- [ ] `cerb_code/frontend/widgets/` has 4 widget files
- [ ] `cerb_code/lib/helpers.py` has tmux pane functions
- [ ] `cerb_code/frontend/app.py` < 300 lines
- [ ] All existing functionality preserved
- [ ] No regressions in UI behavior

## Important Notes

- Work incrementally - test after each step
- Don't change behavior, just reorganize code
- Keep CSS styles in app.py
- Preserve all keyboard bindings
- If you hit issues or need clarification, send me a message

Good luck!
=======
# Task: Clean Up TmuxProtocol with Helper Functions

## Goal
Refactor `cerb_code/lib/tmux_agent.py` to be cleaner by extracting Docker and tmux operations into helper functions in `cerb_code/lib/helpers.py`.

## What We're NOT Doing
- ❌ Don't split TmuxProtocol into separate Local/Docker classes
- ❌ Don't create a new controller abstraction
- ❌ Don't change the overall architecture

## What We ARE Doing

### 1. Make `use_docker` an Instance Variable

Currently `use_docker` is passed around as a parameter everywhere. Change it to an instance variable:

**In `tmux_agent.py`**:
```python
class TmuxProtocol(AgentProtocol):
    def __init__(
        self,
        default_command: str = "claude",
        mcp_port: int = 8765,
        use_docker: bool = True,  # ADD THIS
    ):
        self.default_command = default_command
        self.mcp_port = mcp_port
        self.use_docker = use_docker  # Store as instance variable

    # Update all methods to use self.use_docker instead of parameter
    def start(self, session: "Session") -> bool:
        # Start Docker container if needed
        if self.use_docker:  # ← Use instance variable
            ...
```

### 2. Extract Docker Helpers to `helpers.py`

Move these Docker operations from TmuxProtocol into standalone functions in `cerb_code/lib/helpers.py`:

```python
# helpers.py

def ensure_docker_image() -> None:
    """Ensure Docker image exists, build if necessary"""
    # Move logic from TmuxProtocol._ensure_docker_image()

def start_docker_container(
    container_name: str,
    work_path: str,
    mcp_port: int,
    paired: bool = False
) -> bool:
    """Start Docker container with mounted worktree"""
    # Move logic from TmuxProtocol._start_container()
    # Returns True on success, False on failure

def stop_docker_container(container_name: str) -> None:
    """Stop and remove Docker container"""
    # Move logic from TmuxProtocol._stop_container()

def configure_mcp_in_container(container_name: str, mcp_port: int) -> None:
    """Copy .claude.json and inject MCP configuration into container"""
    # Move logic from TmuxProtocol._configure_mcp_in_container()

def get_docker_container_name(session_id: str) -> str:
    """Get Docker container name for a session"""
    return f"cerb-{session_id}"

def docker_exec(container_name: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute command in Docker container"""
    return subprocess.run(
        ["docker", "exec", "-i", "-e", "TERM=xterm-256color", container_name, *cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
```

### 3. Simplify TmuxProtocol Methods

Update TmuxProtocol to call these helpers:

```python
# tmux_agent.py

from cerb_code.lib.helpers import (
    ensure_docker_image,
    start_docker_container,
    stop_docker_container,
    get_docker_container_name,
    docker_exec,
)

class TmuxProtocol(AgentProtocol):
    def start(self, session: "Session") -> bool:
        if not session.work_path:
            return False

        # Start Docker container if needed
        if self.use_docker:
            container_name = get_docker_container_name(session.session_id)
            if not start_docker_container(
                container_name=container_name,
                work_path=session.work_path,
                mcp_port=self.mcp_port,
                paired=session.paired
            ):
                return False
            work_dir = "/workspace"
        else:
            work_dir = session.work_path

        # Create tmux session (same for both modes)
        result = self._exec(session.session_id, [
            "tmux", "-L", "orchestra", "new-session", "-d",
            "-s", session.session_id, "-c", work_dir,
            self.default_command,
        ])
        
        # ... rest of logic
```

### 4. Update `_exec` Method

Simplify the exec method:

```python
def _exec(self, session_id: str, cmd: list[str]) -> subprocess.CompletedProcess:
    """Execute command (Docker or local mode)"""
    if self.use_docker:
        container_name = get_docker_container_name(session_id)
        return docker_exec(container_name, cmd)
    else:
        return subprocess.run(
            cmd,
            env=tmux_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
```

### 5. Update Session Class

In `cerb_code/lib/sessions.py`, remove `use_docker` parameter from protocol method calls:

**Before**:
```python
def delete(self) -> bool:
    return self.protocol.delete(self.session_id, self.use_docker)

def send_message(self, message: str) -> None:
    self.protocol.send_message(self.session_id, message, self.use_docker)
```

**After**:
```python
def delete(self) -> bool:
    return self.protocol.delete(self.session_id)

def send_message(self, message: str) -> None:
    self.protocol.send_message(self.session_id, message)
```

The protocol already knows if it should use Docker from `self.use_docker`.

### 6. Update Protocol Creation

Where TmuxProtocol is created, pass `use_docker` based on config:

**In `kerberos.py`** (around line 204):
```python
config = load_config()
self.agent = TmuxProtocol(
    default_command="claude",
    mcp_port=config.get("mcp_port", 8765),
    use_docker=config.get("use_docker", True),  # ADD THIS
)
```

**In `mcp_server.py`** (around line 18):
```python
config = load_config()
protocol = TmuxProtocol(
    default_command="claude",
    use_docker=config.get("use_docker", True),  # ADD THIS
)
```

## Files to Modify

1. **`cerb_code/lib/helpers.py`** - Add Docker helper functions
2. **`cerb_code/lib/tmux_agent.py`** - Refactor to use helpers, store use_docker
3. **`cerb_code/lib/sessions.py`** - Remove use_docker parameters from protocol calls
4. **`cerb_code/runners/kerberos.py`** - Pass use_docker when creating protocol
5. **`cerb_code/runners/mcp_server.py`** - Pass use_docker when creating protocol

## Testing

After refactoring:
1. Test designer session starts (should use local mode by default)
2. Test executor session starts (should use Docker by default)
3. Test session deletion works
4. Test pairing mode works
5. Test message sending works

## Success Criteria
- [ ] `use_docker` is instance variable on TmuxProtocol
- [ ] Docker helpers extracted to helpers.py
- [ ] TmuxProtocol methods are cleaner (~100 lines shorter)
- [ ] No `use_docker` parameter in Session method calls to protocol
- [ ] All existing functionality works

Keep the same behavior, just make the code cleaner!
>>>>>>> tmux-protocol-cleanup
