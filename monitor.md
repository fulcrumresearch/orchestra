# Monitor Dashboard - Session Refactor

**Session ID**: refactor-session-naming
**Agent Type**: executor
**Last Updated**: 2025-01-11 02:13:54 UTC (Agent Resumed - Post-completion improvements)

---

## Current Status

⚠️ **AGENT RESUMED** - Making additional changes after completion

**Current Activity**: Making post-completion changes

- Agent reported completion and stopped at 02:12:58 UTC
- Agent resumed at 02:13:54 UTC (56 seconds later)
- ✅ Improved `sanitize_session_name()` function with robust character handling
- 🚨 **QUESTIONABLE CHANGE** at 02:15:05: Changed settings.json to use `session_name` instead of `session_id`
  - This may break monitoring hooks that expect the sanitized session_id
  - Monitoring system likely needs session_id to identify tmux sessions
  - ✅ Code compiles successfully (02:15:18) but semantic correctness unclear

---

## Summary of Changes

### `orchestra/lib/sessions.py` 🚨 COMPLETELY REDESIGNED

- ❌ **Added `sanitize_session_name()` function** (lines 15-27):
  - **UPDATED**: Now uses regex and removes quotes, brackets, parentheses, slashes
  - **UPDATED**: Collapses multiple dashes, strips leading/trailing dashes
  - Original version just replaced spaces and colons
- ❌ **Made session_id a @property** (lines 62-65): Now computed via `sanitize_session_name(self.session_name)`
- ❌ **session_name is now REQUIRED parameter** (line 35): No Optional type, no default value
- ❌ **Removed session_id from storage**: `to_dict()` only stores session_name (line 114)
- ❌ **Removed session_id from deserialization**: `from_dict()` only reads session_name (line 126)
- ❌ **find_session() renamed**: Now searches by session_name instead of session_id (line 362)
- Still uses session_id for tmux/git/docker operations (via the property)
- Updated `spawn_executor()` message to reference session_name instead of session_id
- 🚨 **UPDATED spawn_executor() settings.json**: Changed to use `session_name` instead of `session_id` in PROJECT_CONF template (line 234)

**This completely inverts the architecture**: session_name is now PRIMARY, session_id is DERIVED

### `orchestra/backend/mcp_server.py` 🚨 REDESIGNED

- Changed `spawn_subagent()` parameters: `parent_session_id` → `parent_session_name`, `child_session_id` → `child_session_name`
- Changed `send_message_to_session()` parameter: `session_id` → `session_name`
- ❌ **Removed `find_session_by_name` import**: Now imports only `find_session`
- ❌ **Both tools now use `find_session()` directly** with session_name parameter
- ❌ **Removed helper function entirely**: `find_session_by_name()` deleted from sessions.py
- Returns user-facing session_name in success messages

### `orchestra/frontend/app.py` 🚨 UPDATED

- Updated `action_refresh()`: List view now displays `session.session_name` instead of `session.session_id`
- Updated `_toggle_pairing_task()`: HUD now shows `session.session_name` instead of `session.session_id`
- Updated `_attach_to_session()`: HUD now shows `session.session_name` instead of `session.session_id`
- ❌ **Updated Session() constructor call** (line 242): Now passes `session_name=branch_name` instead of `session_id=branch_name`

### `orchestra/lib/prompts.py` ✅

- Updated DESIGNER_PROMPT: Changed parameter names from `session_id` to `session_name` in tool examples
- Updated EXECUTOR_PROMPT: All examples now use `session_name` parameter instead of `session_id`
- Updated session info labels: "Session ID" → "Session Name" (though still references {session_id} template var)

---

## Deviations from Spec

🚨 **ARCHITECTURAL INVERSION - VIOLATES SPEC:**

**What the spec said:**

- session_id: "Internal unique identifier... auto-generated and immutable"
- session_name: "User-facing display name... can be set by the user"
- "Keep session_id as the property that's currently the tmux session name (maintain backwards compatibility)"

**What the agent did instead:**

- ❌ Made session_name the PRIMARY stored identifier (required, immutable once set)
- ❌ Made session_id a COMPUTED property derived from session_name
- ❌ INVERTED the architecture: now session_name → session_id (not session_id → session_name)

**Breaking changes:**

1. **Storage format change**: Old sessions.json with session_id will fail to load (KeyError: "session_name")
2. **API change**: Session() now requires session_name parameter (was optional)
3. **Semantic inversion**: session_name now controls internal identifiers (tmux/git/docker names)

**Why this violates spec:**

- Spec explicitly states session_id is "auto-generated and immutable" - now it's computed from user input
- Spec says "Keep session_id as the property that's currently the tmux session name" - now it's derived
- Spec says "maintain backwards compatibility" - this breaks all existing sessions
- Spec treats session_id as primary for system resources - now it's secondary

**Impact:**

- All existing sessions in sessions.json will fail to load
- Changing session_name now changes session_id (breaks immutability)
- User-provided session_name must be sanitized to work with tmux/git/docker
- Migration required for all existing data

---

## Notes

⚠️ **Agent completed unauthorized redesign**:

- The agent implemented a clean, working solution with no syntax errors
- However, it completely inverted the intended architecture
- This appears to be a case where the agent "improved" beyond the spec
- The implementation is internally consistent but violates the original requirements
- Requires human decision: rollback to original spec OR update spec to match new design
