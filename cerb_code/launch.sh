#!/usr/bin/env bash
set -euo pipefail

# Simple launcher script for Cerb - just left UI and right terminal

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux not found. Install tmux first (apt/brew install tmux)." >&2
    exit 1
fi

# Function to create simple two-pane layout
create_layout() {
    local target_prefix="$1"  # Either empty or "SESSION:WINDOW"

    # Set target flag for tmux commands (empty if no prefix)
    local target_flag=""
    if [[ -n "$target_prefix" ]]; then
        target_flag="-t $target_prefix"
    fi

    # Get window width and set left pane to 50% of it
    if [[ -n "$target_prefix" ]]; then
        WIN_WIDTH=$(tmux display-message -p -t "$target_prefix" '#{window_width}')
    else
        WIN_WIDTH=$(tmux display-message -p '#{window_width}')
    fi
    LEFT_SIZE=$(( WIN_WIDTH * 50 / 100 ))

    # Split vertically - left pane for UI, right for terminal (50/50)
    tmux split-window -h -b -l "$LEFT_SIZE" $target_flag

    # Now we have:
    # Pane 0: Unified UI (left)
    # Pane 1: Terminal for Claude sessions (right)

    # Start the unified UI in the left pane
    for pane in 0 1; do
        if [[ -n "$target_prefix" ]]; then
            pane_target="${target_prefix}.${pane}"
        else
            pane_target="$pane"
        fi

        case $pane in
            0) # Unified UI
                tmux send-keys -t "$pane_target" "cerb-ui" C-m
                ;;
            1) # Terminal area
                tmux send-keys -t "$pane_target" "echo 'Claude sessions will appear here'; echo 'Use the left panel to create or select a session'" C-m
                ;;
        esac
    done

    # Focus on the UI (left pane)
    if [[ -n "$target_prefix" ]]; then
        tmux select-pane -t "${target_prefix}.0"
    else
        tmux select-pane -t 0
    fi
}

# Get directory name for session naming
REPO_NAME=$(basename "$(pwd)")

# Check if we're already in a tmux session
if [[ -n "${TMUX:-}" ]]; then
    # Create new window in current session
    tmux new-window -n "cerb-${REPO_NAME}"
    create_layout ""  # Empty prefix since we're in the current window
else
    # Not in tmux, create new session
    SESSION_NAME="cerb-${REPO_NAME}"
    WINDOW_NAME="main"

    # Kill existing session if it exists
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

    # Create new session with a window
    tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME"

    # Enable mouse support for scrolling and pane selection
    tmux set -t "$SESSION_NAME" -g mouse on

    # Add custom keybinding: Ctrl+S to switch between panes
    tmux bind-key -n C-s select-pane -t :.+

    # Create the two-pane layout
    create_layout "$SESSION_NAME:$WINDOW_NAME"

    # Attach to the session
    exec tmux attach-session -t "$SESSION_NAME"
fi