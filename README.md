# Cerberus

Cerberus is an AI coding that allows you to quickly design good software. It allows you to iterate on specs for what you want to build, and then delegate work in parallel to agents building your software in an overseeable way..

The best coding experiences understand the tango of deference between human and AI thinking.

Humans excel at:
- Articulating vision and requirements
- Making architectural decisions
- Providing context and judgment

AI agents excel at:
- Implementing well-specified tasks
- Exploring codebases
- Handling repetitive transformations

Cerberus is a multi-agent development environment that lets you focus on the creative work of software design while coordinating swarms of AI agents to handle implementation. You provide the vision, Cerberus manages the execution.


## How It Works

### Designer and Executor Sessions

**Main Session (Designer):** Your primary workspace lives in your source code directory. The designer agent discusses with you, understands your requirements, and orchestrates the work.

**Executor Sessions:** When you define a task, the designer spawns executor agents in isolated git worktrees. Each executor works independently on their assigned task, reaching out to you only when clarification is needed.

### The Orchestrator UI

Cerberus provides a unified interface to manage your agent swarm:

- **Session List:** View all active designer and executor sessions
- **Diff View:** See changes in real-time as agents work
- **Monitor Tab:** Watch automated summaries of agent activities
- **Keyboard Controls:**
  - `s` - Open spec editor for the selected session (designer gets notified on save)
  - `t` - Open terminal in the selected session's worktree
  - `N` - Create new session
  - `D` - Delete session
  - Arrow keys - Navigate sessions

### Workflow

1. **Design:** Discuss your ideas with the designer agent. Use the spec editor (`s`) to sketch out plans.

2. **Delegate:** The designer spawns executor agents with clear task specifications.

3. **Monitor:** Watch executors work through the UI. They'll reach out if they need guidance.

4. **Review:** Jump into executor worktrees (`t`) to test changes, or view diffs before merging.

5. **Integrate:** Merge completed work back into your main branch.

## Architecture

Cerberus uses git worktrees to isolate agent work:
- Each executor gets its own branch and working directory
- Changes are tracked independently
- No conflicts between concurrent agent work
- Easy to review, test, and merge completed tasks

Communication between agents uses MCP (Model Context Protocol):
- Designers spawn executors with detailed instructions
- Executors can message back with questions or completion status
- Automated monitoring tracks agent activity

## Getting Started

```bash
# Launch the Cerberus orchestrator
cerb

# The UI will open with a main designer session
# Press 's' to open the spec editor and start planning
# The designer will spawn executors as needed
```
