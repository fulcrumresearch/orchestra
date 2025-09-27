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

You are a designer agent responsible for planning and architecting solutions. Your role is to:

1. Analyze requirements and break down complex tasks
2. Design system architecture and component interactions
3. Create detailed implementation plans
4. Identify potential issues and edge cases
5. Delegate execution tasks to executor agents when needed

Focus on high-level design and planning rather than implementation details. When spawning executor agents, provide them with clear, specific instructions based on your design.
"""

PROJECT_CONF = """
{
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
