#!/usr/bin/env bash
set -euo pipefail

# Simple launcher script for Cerb - just left UI and right terminal
# Uses dedicated tmux server named "cerb"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMUX_SERVER="cerb"

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
        WIN_WIDTH=$(tmux -L "$TMUX_SERVER" display-message -p -t "$target_prefix" '#{window_width}')
    else
        WIN_WIDTH=$(tmux -L "$TMUX_SERVER" display-message -p '#{window_width}')
    fi
    LEFT_SIZE=$(( WIN_WIDTH * 50 / 100 ))

    # Create 3-pane layout: sidebar (top-left), editor (bottom-left), claude (right)

    # First split: left pane and right pane (50/50)
    tmux -L "$TMUX_SERVER" split-window -h -b -l "$LEFT_SIZE" $target_flag
    # Now we have: Pane 0 (left), Pane 1 (right)

    # Split the left pane horizontally: sidebar on top, editor below (8 lines)
    if [[ -n "$target_prefix" ]]; then
        tmux -L "$TMUX_SERVER" split-window -t "${target_prefix}.0" -v -l 8
    else
        tmux -L "$TMUX_SERVER" split-window -t 0 -v -l 8
    fi
    # Now we have: Pane 0 (sidebar top-left), Pane 1 (editor bottom-left), Pane 2 (claude right)

    # Start content in each pane
    for pane in 0 1 2; do
        if [[ -n "$target_prefix" ]]; then
            pane_target="${target_prefix}.${pane}"
        else
            pane_target="$pane"
        fi

        case $pane in
            0) # Sidebar - Unified UI
                tmux -L "$TMUX_SERVER" send-keys -t "$pane_target" "cerb-ui" C-m
                ;;
            1) # Editor placeholder
                tmux -L "$TMUX_SERVER" send-keys -t "$pane_target" "clear; echo 'Press S to open spec editor'; echo ''" C-m
                ;;
            2) # Claude sessions
                tmux -L "$TMUX_SERVER" send-keys -t "$pane_target" "echo 'Claude sessions will appear here'; echo 'Use the left panel to create or select a session'" C-m
                ;;
        esac
    done

    # Focus on the sidebar (pane 0)
    if [[ -n "$target_prefix" ]]; then
        tmux -L "$TMUX_SERVER" select-pane -t "${target_prefix}.0"
    else
        tmux -L "$TMUX_SERVER" select-pane -t 0
    fi
}

# Get directory name for session naming
REPO_NAME=$(basename "$(pwd)")

# Check if we're already in a tmux session (check both default and cerb server)
if [[ -n "${TMUX:-}" ]] || tmux -L "$TMUX_SERVER" list-sessions >/dev/null 2>&1; then
    # Create new window in current session
    tmux -L "$TMUX_SERVER" new-window -n "cerb-${REPO_NAME}"
    create_layout ""  # Empty prefix since we're in the current window
else
    # Not in tmux, create new session
    SESSION_NAME="cerb-${REPO_NAME}"
    WINDOW_NAME="main"

    # Kill existing session if it exists
    tmux -L "$TMUX_SERVER" kill-session -t "$SESSION_NAME" 2>/dev/null || true

    # Create new session with a window
    tmux -L "$TMUX_SERVER" new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME"

    # Enable mouse support for scrolling and pane selection
    tmux -L "$TMUX_SERVER" set -t "$SESSION_NAME" -g mouse on

    # Add custom keybinding: Ctrl+S to switch between panes
    tmux -L "$TMUX_SERVER" bind-key -n C-s select-pane -t :.+

    # Create the two-pane layout
    create_layout "$SESSION_NAME:$WINDOW_NAME"

    # Attach to the session
    exec tmux -L "$TMUX_SERVER" attach-session -t "$SESSION_NAME"
fi