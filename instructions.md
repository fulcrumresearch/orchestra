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