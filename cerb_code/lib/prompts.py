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

PROJECT_CONF = """
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh SessionStart"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh UserPromptSubmit"
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
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh PreToolUse"
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
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh PostToolUse"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh Stop"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/forward.sh SessionEnd"
          }
        ]
      }
    ]
  }
}
"""
