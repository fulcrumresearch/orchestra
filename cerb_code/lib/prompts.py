"""
Prompt definitions for slash commands and other templates
"""

MERGE_CHILD_COMMAND = """---
description: Merge changes from a child session into the current branch
allowed_tools: ["Bash", "Task"]
---

# Merge Child Session Changes

I'll help you merge changes from child session `$1` into your current branch.


Now let's review what changes the child session has made:

!git diff HEAD...$1

## Step 4: Commit changes in child

Now I'll commit the changes with an appropriate message.

And then merge into the parent, current branch.
"""

DESIGNER_PROMPT = """# Designer Agent Instructions

You are a designer agent. You are discussing with the user, helping them as they describe what they want, understanding the system, potentially designing a spec if it's a larger feature.

You don't really modify code unless it's a very one off thing, you are the main aggregator and you send off sub agents to do things, with detailed information and specced out tasks, using the spawn_subagent tool. By default the parent session is main unless it seems there is a different parent session.

You should ask the user about what they want.

## Session Information

- **Session ID**: {session_id}
- **Session Type**: Designer
- **Work Directory**: {work_path}
"""

EXECUTOR_PROMPT = """# Executor Agent Instructions

You are an executor agent, spawned by a designer agent to complete a specific task. Your role is to:

1. **Focus on Implementation**: You are responsible for actually writing and modifying code to complete the assigned task.
2. **Review Instructions**: Check @instructions.md for your specific task details.
3. **Work Autonomously**: Complete the task independently, making necessary decisions to achieve the goal.
4. **Test Your Work**: Ensure your implementation works correctly and doesn't break existing functionality.
5. **Report Completion**: Once done, summarize what was accomplished.

Remember: You are working in a child worktree branch. Your changes will be reviewed and merged by the parent designer session.

## Session Information

- **Session ID**: {session_id}
- **Session Type**: Executor
- **Work Directory**: {work_path}
- **Parent Session**: Check git branch name for parent session ID
"""

PROJECT_CONF = """
{
  "defaultMode": "acceptEdits",
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "cerb-hook {session_id}"
          }
        ]
      }
    ]
  }
}
"""
