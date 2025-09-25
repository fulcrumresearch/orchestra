#!/usr/bin/env bash
set -euo pipefail

# Launcher script for Kerberos - sets up tmux with sidebar and main pane

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERBEROS_PY="${SCRIPT_DIR}/kerberos.py"

if ! command -v tmux >/dev/null 2>&1; then
    echo "Error: tmux not found. Install tmux first (apt/brew install tmux)." >&2
    exit 1
fi

if [[ ! -f "$KERBEROS_PY" ]]; then
    echo "Error: kerberos.py not found at: $KERBEROS_PY" >&2
    exit 1
fi

# Function to create the L-shaped layout
create_layout() {
    local target_prefix="$1"  # Either empty or "SESSION:WINDOW"

    # Set target flag for tmux commands (empty if no prefix)
    local target_flag=""
    local pane1_target="1"
    if [[ -n "$target_prefix" ]]; then
        target_flag="-t $target_prefix"
        pane1_target="${target_prefix}.1"
    fi

    # Get window width and calculate right pane size (sidebar is 15 cols)
    WIN_WIDTH=$(tmux display-message -p $target_flag '#{window_width}')
    RIGHT_SIZE=$((WIN_WIDTH - 15))

    # Split horizontally: left (sidebar) | right (rest)
    tmux split-window -h $target_flag -l "$RIGHT_SIZE"

    # Now split the right pane (pane 1) vertically
    tmux select-pane -t "$pane1_target"

    # Get height of the selected pane and calculate bottom size (30% for monitor)
    PANE_HEIGHT=$(tmux display-message -p '#{pane_height}')
    BOTTOM_SIZE=$((PANE_HEIGHT * 30 / 100))
    tmux split-window -v -l "$BOTTOM_SIZE"

    # Now we have L-shape:
    # Pane 0: Sidebar (left)
    # Pane 1: Claude session (top-right)
    # Pane 2: Monitor (bottom-right)

    # Start the apps in each pane
    for pane in 0 1 2; do
        if [[ -n "$target_prefix" ]]; then
            pane_target="${target_prefix}.${pane}"
        else
            pane_target="$pane"
        fi

        case $pane in
            0) # Sidebar
                tmux send-keys -t "$pane_target" "cerb-sidebar" C-m
                ;;
            1) # Claude session area
                tmux send-keys -t "$pane_target" "echo 'Use the sidebar to create or select a Claude session'; echo 'Press Ctrl+N in the sidebar to create a new session'" C-m
                ;;
            2) # Monitor area
                tmux send-keys -t "$pane_target" "echo 'Monitor will appear here when you select a session'" C-m
                ;;
        esac
    done

    # Focus on the sidebar
    if [[ -n "$target_prefix" ]]; then
        tmux select-pane -t "${target_prefix}.0"
    else
        tmux select-pane -t 0
    fi
}

# Get directory name for session naming
REPO_NAME=$(basename "$(pwd)")

# Check if we're already in a tmux session
# If we are, we can still run this in a new window
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

    # Add custom keybinding: Ctrl+S to cycle through all 3 panes
    # -n means no prefix needed (direct binding)
    # This will rotate through panes 0 -> 1 -> 2 -> 0
    tmux bind-key -n C-s select-pane -t :.+

    # Create the L-shaped layout
    create_layout "$SESSION_NAME:$WINDOW_NAME"

    # Attach to the session
    exec tmux attach-session -t "$SESSION_NAME"
fi
