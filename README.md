# Orchestra

Orchestra is an experimental multi agent coding system.

Coding agents can be massively parallelized, run quickly, and are good at implementing well scoped tasks, but left unchecked they drift from the human designer's intent. Active human oversight prevents this drift both in the quality of the code and its alignment with what the user wants.

Orchestra is designed to optimize this asymmetry in capabilities, by making it easy for humans to oversee and design systems as they work with many parallel coding agents.

When you start Orchestra, it opens a designer agent, that discusses, and co-writes feature specs with you. When the spec is complete, the designer spawns a sub agent, that runs in a separate git worktree and a local docker container, where it autonomously completes the task.

Orchestra agents run in parallel, and are given tools so they can communicate *with each other*, despite their filesystem isolation.

communicate with the main designer thread that relays information to you. It is easy to jump into a sub agent's execution, see its work, and even stage its changes in your source directory to pair with it.

## Prerequisites

Before installing Orchestra, ensure you have:

- **git** Orchestra uses git worktrees for parallel development
- **claude-code**
- **tmux**
- **docker:** Orchestra runs agents in isolated containers

## Installation

```bash
# Install Orchestra
pip install orchestra-dev

# Verify installation
orchestra --version
```

## Core Concepts

For each project, you communicate with a designer agent, that drafts and creates specs for various tasks with you.

Orchestra uses two types of AI sessions:

**Designer Session (You work here):**

- Lives in your main source code directory
- Discusses requirements with you
- Plans architecture and breaks down work
- Spawns and coordinates executor agents
- Reviews completed work

**Executor Sessions (Agents work here):**

- Created by the designer for specific tasks
- Work in isolated git worktrees (separate branches)
- Implement features independently
- Ask questions when blocked
- Report back when complete

### The Orchestra UI

Orchestra provides a unified terminal interface to manage all sessions:

**Main Views:**

- **Session List:** See all active designer and executor sessions
- **Diff View:** Watch real-time changes as agents work
- **Monitor Tab:** Track automated summaries of agent activity

**Keyboard Controls:**

- `s` - Open spec editor (define tasks, provide context)
- `t` - Open terminal in selected session's worktree
- `Ctrl+N` - Create new session manually
- `Ctrl+D` - Delete session
- `Arrow keys` - Navigate between sessions

## Getting Started

### 1. Launch Orchestra

```bash
# Start Orchestra in your project directory
cd /path/to/your/project
orchestra
```

The UI opens with a designer session connected to your codebase.

### 2. Define What You Want

Talk to the designer agent about your goals:

```
You: I want to add user authentication with JWT tokens
```

For complex features, press `s` to open the spec editor. Write down requirements, constraints, and success criteria. The designer reads this and uses it to plan work.

### 3. Let the Designer Plan

The designer will discuss the approach with you:

- Ask clarifying questions
- Break down the work into tasks
- Identify dependencies
- Propose an implementation strategy

### 4. Spawn Executors

Once you approve the plan, the designer spawns executor agents:

```
Designer: I'll create three executors:
- auth-endpoints: Build login/logout API endpoints
- jwt-middleware: Implement JWT validation middleware
- auth-tests: Write comprehensive test coverage

Each will work in parallel on their isolated branch.
```

You'll see new sessions appear in the UI's session list.

### 5. Monitor Progress

Watch agents work through the UI:

- **Diff View:** See code changes in real-time
- **Monitor Tab:** Track high-level progress updates
- Press `t` on any executor to open a terminal in their worktree

Agents work autonomously but will message you if they need help.

### 6. Respond to Questions

Executors reach out when they hit blockers. You'll see messages like:

```
[From: auth-endpoints]
QUESTION: Should login sessions expire after 24 hours or 7 days?
```

You can respond directly to the executor, and they'll continue with your guidance.

### 7. Review and Merge

When an executor completes their task:

```
[From: auth-endpoints]
COMPLETE: Implemented login/logout endpoints with JWT generation.
All tests passing. Ready for review.
```

The designer will:

- Show you the changes
- Run tests if needed
- Ask for approval
- Merge the branch into your main codebase

## Workflow Example

Here's a complete workflow from start to finish:

**Initial Request:**

```
You: Add rate limiting to all API endpoints
```

**Designer Response:**

```
Designer: I'll handle this. Let me check the current API structure...

[Analyzes codebase]

I'll create one executor to:
1. Add Redis-based rate limiting middleware
2. Apply to all endpoints
3. Add configuration for limits
4. Write tests

Does 100 requests/minute per IP sound reasonable?
```

**You Approve:**

```
You: Yes, that works.
```

**Executor Spawned:**

```
Designer: Created executor 'rate-limiting' working on branch 'rate-limiting'
You can monitor progress in the UI.
```

**Executor Works:**

- You see commits appearing in the diff view
- Monitor tab shows: "Installing redis dependency"
- Monitor tab shows: "Implementing rate limit middleware"

**Executor Asks Question:**

```
[From: rate-limiting]
QUESTION: Should rate limits apply to authenticated API calls, or only public endpoints?
```

**You Respond:**

```
You: Apply to all endpoints, but authenticated users can have higher limits.
```

**Executor Completes:**

```
[From: rate-limiting]
COMPLETE: Rate limiting implemented. Public: 100 req/min, Authenticated: 1000 req/min.
All 34 tests passing, added 12 new rate limit tests. Ready for review.
```

**Designer Reviews:**

```
Designer: The executor finished. Here's the diff...
[Shows changes]

Tests are passing. Should I merge this to main?
```

**You Merge:**

```
You: Looks good, merge it.

Designer: Merged 'rate-limiting' branch to main. Rate limiting is now active.
```

## What to Expect: Executor Communication

Executors work autonomously but will reach out when they need guidance. Here's what you'll experience:

### When Things Go Wrong

**Missing Dependencies**
If an executor can't find a required tool, you'll receive a message:

```
[From: test-automation]
ERROR: Cannot run tests - 'pytest' is not installed.
Should I install it with pip, or would you prefer a different testing approach?
```

You can respond directly to the executor, and they'll continue with your guidance.

**Build Issues**
When executors encounter existing problems in the codebase:

```
[From: api-feature]
ERROR: Build failed with TypeScript errors in 3 files (user.ts, auth.ts, api.ts).
These errors existed before my changes. Should I fix them first or implement my task differently?
```

**Unclear Requirements**
If instructions are ambiguous, executors will ask rather than guess:

```
[From: auth-refactor]
QUESTION: Instructions say to extend 'UserService' but I cannot find this class.
Did you mean 'AuthService' or should I create a new UserService?
```

### When Things Go Right

**Task Completion**
You'll receive a summary when work is ready for review:

```
[From: rate-limiting]
COMPLETE: Added rate limiting to all API endpoints. Implemented using Redis with
100 requests/minute limit. All 23 existing tests pass, added 8 new tests for
rate limiting behavior. Ready for review.
```

At this point, you can review their work in the diff view or jump into their worktree to test the changes before merging.

## How Orchestra Keeps Work Organized

### Isolated Workspaces

Each executor works in its own isolated environment:

- **Separate branches:** No merge conflicts while agents work in parallel
- **Independent directories:** Changes are isolated at `~/.orchestra/worktrees/`
- **Full visibility:** You can view, edit, or test executor changes anytime
- **Safe experimentation:** Executors can't break your main codebase

### Your Files Stay Accessible

While executors work in isolation, all their files are visible on your machine. You can:

- Open executor worktrees in your editor
- Run tests manually in their directories
- Review changes before merging
- Make edits if needed

### Under the Hood

Orchestra combines several technologies to provide safe, parallel development:

**Git Worktrees:**

- Each executor gets its own branch and working directory
- Changes are tracked independently
- Merging is straightforward when work completes
- Located at `~/.orchestra/worktrees/<project>/<session-name>/`

**Docker Containers:**

- Each session runs in an isolated container
- Agents can't accidentally modify your system
- Two modes available:
  - **Unpaired** (default): Agent only accesses their worktree
  - **Paired** (opt-in): Agent can also access your source project for context

**Model Context Protocol (MCP):**

- Enables communication between designer and executors
- Handles message passing, task delegation, and status updates
- Ensures reliable coordination across parallel agents

You don't need to manage any of this manually—Orchestra handles it automatically.

## Tips for Success

### Write Clear Specifications

The better you articulate requirements, the more effectively agents can work:

- Define success criteria explicitly
- Mention edge cases and constraints
- Provide context about existing patterns
- Link to relevant documentation

### Start Small

For your first project with Orchestra:

- Begin with a small, well-defined feature
- Get comfortable with the workflow
- Gradually increase task complexity

### Review Everything

Always review executor work before merging:

- Check the diff carefully
- Run tests in the executor's worktree
- Verify the implementation matches your intent

### Use the Spec Editor

Press `s` to open the spec editor for complex tasks:

- Write design documents
- List requirements and constraints
- Break down work into phases
- The designer will reference this when planning

### Stay Available

Executors may ask questions:

- Respond promptly to keep work moving
- Clarify ambiguities early
- Provide guidance when they're blocked

## Troubleshooting

**Executor won't start:**

- Check that Docker is running
- Verify git is installed and working
- Ensure you have an API key configured

**Can't see executor changes:**

- Navigate to `~/.orchestra/worktrees/` to see all worktrees
- Check the session list in the UI to find the branch name
- Use `t` to open a terminal in the executor's directory

**Merge conflicts:**

- Executors work on isolated branches, so conflicts are rare
- If they occur, resolve them in the executor's worktree before merging
- The designer can help coordinate resolution

**Agent is stuck:**

- Check the monitor tab for status updates
- Press `t` to inspect the executor's worktree
- The designer can send clarifying messages to unblock them

## Next Steps

Now that you understand Orchestra:

1. Install Orchestra and launch it in a project
2. Start with a simple feature request
3. Watch how the designer breaks down and delegates work
4. Review executor output and provide feedback
5. Gradually tackle more complex tasks

---

**Need help?** Open an issue at [github.com/fulcrumresearch/orchestra](https://github.com/fulcrumresearch/orchestra)
