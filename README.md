# Orchestra

Orchestra is an AI coding that allows you to quickly design good software. It allows you to iterate on specs for what you want to build, and then delegate work in parallel to agents building your software in an overseeable way..

The best coding experiences understand the tango of deference between human and AI thinking.

Humans excel at:

- Articulating vision and requirements
- Making architectural decisions
- Providing context and judgment

AI agents excel at:

- Implementing well-specified tasks
- Exploring codebases
- Handling repetitive transformations

Orchestra is a multi-agent development environment that lets you focus on the creative work of software design while coordinating swarms of AI agents to handle implementation. You provide the vision, Orchestra manages the execution.

## How It Works

### Designer and Executor Sessions

**Main Session (Designer):** Your primary workspace lives in your source code directory. The designer agent discusses with you, understands your requirements, and orchestrates the work.

**Executor Sessions:** When you define a task, the designer spawns executor agents in isolated git worktrees. Each executor works independently on their assigned task, reaching out to you only when clarification is needed.

### The Orchestrator UI

Orchestra provides a unified interface to manage your agent swarm:

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

## Executor Communication Examples

Executors are trained to proactively report issues back to the designer. Here are real-world scenarios showing when and how executors should communicate:

### Example 1: Missing Dependencies

**Scenario:** Executor tries to run tests but pytest is not installed.

```
Executor thinks: "I need to run tests but pytest isn't available. I should report this immediately."

Executor sends: send_message_to_session(
  session_id="main",
  message="ERROR: Cannot run tests - 'pytest' is not installed. Should I install it with pip, or would you prefer a different testing approach?"
)

Designer responds: "Yes, go ahead and install pytest. We use it for all Python tests."
```

### Example 2: Build Failures

**Scenario:** Executor makes changes but the build fails with existing TypeScript errors.

```
Executor thinks: "The build is failing, but it's due to pre-existing errors, not my changes. I need guidance."

Executor sends: send_message_to_session(
  session_id="main",
  message="ERROR: Build failed with TypeScript errors in 3 files (user.ts, auth.ts, api.ts). These errors existed before my changes. Should I fix them first or implement my task differently?"
)

Designer responds: "Those are known issues. Focus on your task and we'll fix those separately."
```

### Example 3: Ambiguous Requirements

**Scenario:** Instructions mention a component that doesn't exist in the codebase.

```
Executor thinks: "The instructions reference 'UserService' but I can't find it. Better ask than guess."

Executor sends: send_message_to_session(
  session_id="main",
  message="QUESTION: Instructions say to extend 'UserService' but I cannot find this class in the codebase. Did you mean 'AuthService' or should I create a new UserService?"
)

Designer responds: "Sorry, my mistake - I meant AuthService. Please extend that."
```

### Example 4: Successful Completion

**Scenario:** Executor completes the task successfully.

```
Executor sends: send_message_to_session(
  session_id="main",
  message="COMPLETE: Added rate limiting to all API endpoints. Implemented using Redis with 100 requests/minute limit. All 23 existing tests pass, added 8 new tests for rate limiting behavior. Ready for review."
)
```

**Key Takeaway:** Executors should err on the side of over-communication. It's better to ask a question that seems obvious than to waste time or implement incorrectly.

## Architecture

### Git Worktrees + Docker Isolation

Orchestra combines git worktrees with Docker containerization:

**Worktrees (Visible on Host)**:

- Each executor gets its own branch and working directory at `~/.orchestra/worktrees/`
- Changes are tracked independently
- No conflicts between concurrent agent work
- Easy to review, test, and merge completed tasks
- Worktrees are visible and editable in your editor

**Docker Containers (Isolated Execution)**:

- Each session runs in its own Docker container
- Agent commands execute in isolation with mounted worktree
- Two modes:
  - **Unpaired** (default): Agent only accesses worktree
  - **Paired** (opt-in): Agent also accesses source project
- Provides command isolation while keeping files accessible

See [DOCKER.md](DOCKER.md) for detailed Docker architecture.

**Communication (MCP)**:

- Designers spawn executors with detailed instructions
- Executors can message back with questions or completion status
- Automated monitoring tracks agent activity

## Getting Started

```bash
# Launch the Orchestra orchestrator
orchestra

# The UI will open with a main designer session
# Press 's' to open the spec editor and start planning
# The designer will spawn executors as needed
```
