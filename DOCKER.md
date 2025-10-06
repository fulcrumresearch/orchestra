# Docker Containerization

Cerberus uses Docker to provide isolated execution environments for agent sessions while keeping worktrees visible on your filesystem.

## Architecture

### Per-Session Containers

Each Cerberus session runs in its own Docker container:
- **Container naming**: `cerb-{session-id}`
- **Isolation**: Each session has independent filesystem access
- **Persistence**: Containers are long-running and survive between attachments

### Two Modes

**Unpaired Mode (Default)**
- Container mounts only the session's worktree at `/workspace`
- Agent commands execute in isolation
- Cannot access user's project files
- ✅ Maximum security and isolation

**Paired Mode (Optional)**
- NOT CURRENTLY IMPLEMENTED
- Container mounts both worktree (`/workspace`) and user project (`/project`)
- Agent can access and modify both locations
- Only ONE session can be paired at a time
- ⚠️ Use when agent needs direct access to source project

## How It Works

### Workflow

1. **Worktree Creation (Host)**
   - Git worktree created at `~/.kerberos/worktrees/{repo}/{session-id}/`
   - Visible and editable on user's filesystem

2. **Container Start**
   - Docker container created with appropriate volume mounts
   - Tmux session starts inside container
   - Claude agent runs in containerized tmux

3. **UI Attachment**
   - Host UI uses `docker exec` to attach to container's tmux
   - User interacts with agent through this connection
   - Changes written to mounted worktree are immediately visible on host

4. **Session Deletion**
   - Container stopped and removed
   - Worktree remains on filesystem for review

### Command Isolation

**How isolation works:**
- Agent bash commands execute inside Docker container
- Container only sees mounted volumes (worktree, and optionally project)
- Cannot access rest of user's filesystem
- Git operations work on mounted worktree, visible on host

**What's isolated:**
- File system access (limited to mounted volumes)
- Process execution (containerized)
- Network access (container's network namespace)

**What's NOT isolated:**
- File content (agent can read/modify mounted files)
- Git history (worktree is live mount from host repo)

## Requirements

- Docker installed and running
- User in `docker` group (or sudo access)
- `ANTHROPIC_API_KEY` environment variable set

## Local Mode

For development or troubleshooting, Cerberus can run without Docker:

```python
# In kerberos.py
agent = TmuxProtocol(default_command="claude", use_docker=False)
```

Local mode runs tmux sessions directly on the host without containerization.

## Technical Details

### Image

**Base**: `python:3.12-slim`

**Installed**:
- tmux (session management)
- git (version control)
- Node.js + npm (for Claude Code)
- @anthropic-ai/claude-code

**Build**: Automatic on first session creation

### Volume Mounts

Unpaired:
```bash
docker run -d --name cerb-{session-id} \
  -v ~/.kerberos/worktrees/{repo}/{session}:/workspace \
  -e ANTHROPIC_API_KEY \
  cerb-image
```

Paired:
```bash
docker run -d --name cerb-{session-id} \
  -v ~/.kerberos/worktrees/{repo}/{session}:/workspace \
  -v {source_path}:/project \
  -e ANTHROPIC_API_KEY \
  cerb-image
```

### Container Lifecycle

1. **Creation**: During `session.prepare()` via `TmuxProtocol._start_container()`
2. **Execution**: Tmux + Claude run inside via `docker exec`
3. **Attachment**: UI connects via `docker exec -it cerb-{id} tmux attach`
4. **Cleanup**: Container removed on `session.delete()`

## Security Considerations

### Isolation Guarantees

✅ **File system isolation**: Agent cannot access files outside mounted volumes

✅ **Process isolation**: Agent commands run in container namespace

✅ **Network isolation**: Container has separate network stack

### Accepted Risks

⚠️ **File content**: Agent can read/modify all files in mounted volumes

⚠️ **Git operations**: Agent can commit, push, modify git history

⚠️ **Malicious code**: User should review agent changes before running/deploying

### Best Practices

1. **Review changes**: Always inspect diffs before merging agent work
2. **Use unpaired mode**: Default to maximum isolation
3. **Pair selectively**: Only enable pairing when necessary
4. **Test in worktree**: Run/test agent code in isolated worktree first

## Troubleshooting

### Container won't start
```bash
# Check Docker is running
docker ps

# Check image exists
docker images | grep cerb-image

# Rebuild image
docker rmi cerb-image
# Restart cerb (will rebuild)
```

### Can't attach to session
```bash
# Check container is running
docker ps | grep cerb-

# Check logs
docker logs cerb-{session-id}

# Restart container
docker restart cerb-{session-id}
```

### Permission errors in container
```bash
# Check volume mounts
docker inspect cerb-{session-id} | grep Mounts -A 10

# Verify worktree exists on host
ls ~/.kerberos/worktrees/
```

## Implementation Files

- `Dockerfile`: Container image definition
- `cerb_code/lib/tmux_agent.py`: Docker integration in TmuxProtocol
- `cerb_code/lib/sessions.py`: Session management
- `cerb_code/runners/kerberos.py`: UI and orchestration
