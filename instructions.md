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