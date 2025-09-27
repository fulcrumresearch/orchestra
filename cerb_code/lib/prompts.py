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
