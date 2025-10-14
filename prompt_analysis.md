# Agent Prompt Analysis and Improvement Plan

## Executive Summary

Analyzed all agent prompt files in the Cerberus codebase. Current prompts provide solid foundation for agent communication but are missing critical technical details about the environment, tooling, and infrastructure that agents operate within.

## Prompt File Locations

### 1. Primary Prompt Definitions
**File**: `/workspace/cerb_code/lib/prompts.py`
- `DESIGNER_PROMPT`: Template for designer agent instructions
- `EXECUTOR_PROMPT`: Template for executor agent instructions
- `DESIGNER_MD_TEMPLATE`: Structure for designer.md collaboration file
- `MERGE_CHILD_COMMAND`: Slash command for merging child sessions
- `PROJECT_CONF`: Project settings template with hooks and permissions

### 2. Runtime Prompt Files
**Location**: `.claude/kerberos.md` (dynamically created in worktrees)
- Designer version: Created in source directory
- Executor version: Created in worktree directories
- Generated from templates in prompts.py with session-specific variables

### 3. Project Configuration
**Files**:
- `.claude/CLAUDE.md`: Imports kerberos.md via @kerberos.md
- `.claude/settings.json`: Runtime hook and permission configuration

---

## Gap Analysis

### Critical Missing Information

#### 1. Technical Environment Details

**Current State**: Prompts mention "work directory" and "source path" but don't explain the underlying infrastructure.

**Missing**:
- **Tmux architecture**: Sessions run inside tmux for persistence and management # not key
- **Docker containerization**:
  - Executors run in isolated Docker containers by default
  - Containers mount worktrees at `/workspace`
  - Host filesystem access is limited to mounted volumes
  - MCP server connection details (port 8765, http://host.docker.internal)
- **File system layout**:
  - Designer: Works directly in source directory
  - Executor: Works in worktree at `~/.kerberos/worktrees/{repo}/{session-id}/`
        - note docker agents can't use git, orchestrator has to manage, see if it's committed, etc...
  - Instructions file location: `instructions.md` in work_path root
- **Environment variables**: `ANTHROPIC_API_KEY` required

U: clarify this is optional. improve the executor prompt so that it has its instructions and parent session name loaded by default.

#### 2. Git Worktree System

**Current State**: Brief mention that executors work in "child worktree branch"

**Missing**:
- Detailed explanation of git worktree architecture
- Branch naming convention: `{dirname}-{session_name}` (sanitized)
- Worktree creation process and lifecycle
- Designer works on main branch, executors on feature branches
- How to interact with git (all git commands work normally)
- Worktrees persist after session deletion for review

Tell the agents to check and use their cerb-mcp tool, and fix the prompts if something is wrong there, they are often confused about the MCP

