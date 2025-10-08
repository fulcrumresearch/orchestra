# Test Pairing Logic

Your task is to help test the pairing functionality by making some changes in your worktree.

## What to do:

1. **Modify an existing file**: Edit one of the existing Python files (like `cerb_code/lib/helpers.py`) - add a comment or small change

2. **Create a new file**: Create a new test file that doesn't exist in the source directory, for example:
   - `test_pairing_feature.py` with some simple content
   - Or `test_notes.md` with some notes

3. **Report back**: Once you've made these changes, let me know what you changed so we can test the pairing toggle to see if:
   - Modified tracked files get staged with `git add -u`
   - New untracked files (that don't exist in source) get staged
   - Everything gets auto-committed before merging

Make simple, obvious changes so we can easily verify the pairing logic worked correctly.