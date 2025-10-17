# Orchestra Technical Trivia

## Obscure Implementation Details

### Worktree Branch Naming Convention
Orchestra uses a specific pattern for naming feature branches created in git worktrees: `<repo>-<session-name>`. For example, if the repository is named "orchestra" and the session is called "add-auth-feature", the branch will be named `orchestra-add-auth-feature`. This convention ensures branch names are unique and traceable back to their originating session.

### MCP Server Default Port
The Orchestra MCP server runs on port **8765** by default. This port was chosen because 8765 represents ascending digits, making it memorable and easy to type during development.

### Tmux Session Architecture
Designer agents run in tmux sessions on the host machine (or container if configured), while executor agents run in isolated Docker containers. This hybrid architecture allows designers to have persistent, interactive shells while executors work in clean, reproducible environments.

### Instructions File Lifecycle
When a sub-agent is spawned, Orchestra automatically creates an `instructions.md` file in the executor's worktree containing the task specification. This file persists after the session ends, serving as permanent documentation of what the executor was asked to do.

### The Designer.md Structure
The designer.md file follows a specific four-section structure: Active Tasks, Done, Sub-Agent Status, and Notes/Discussion. This structure is recommended but not enforced by the system, allowing flexibility while providing a clear organizational pattern.
