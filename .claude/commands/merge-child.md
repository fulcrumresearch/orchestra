---
description: Merge changes from a child session into the current branch
allowed_tools: ["Bash", "Task"]
---

# Merge Child Session Changes

I'll help you merge changes from child session `$1` into your current branch.


Now let's review what changes the child session has made:

!git diff HEAD...$1

## Step 3: Check child's working directory status

Let's check if the child has uncommitted changes:

```bash
cd $(git worktree list | grep "$1" | awk '{print $1}') && git status
```

## Step 4: Commit changes in child (if needed)

If there are uncommitted changes in the child session, I'll help you commit them. First, let's stage and review:

```bash
cd $(git worktree list | grep "$1" | awk '{print $1}') && git add -A && git diff --staged
```

Now I'll commit the changes with an appropriate message.

And then merge into the parent, current branch.
