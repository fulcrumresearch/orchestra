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

# Check if we're already in a tmux session
# If we are, we can still run this in a new window
if [[ -n "${TMUX:-}" ]]; then
    # Create new window in current session
    tmux new-window -n "kerberos"

    # Split window horizontally (left: sidebar 30 cols, right: main takes the rest)
    # The split creates a new pane to the right, we want it to take remaining space
    # So we calculate: total width - 30 for the right pane
    WIN_WIDTH=$(tmux display-message -p '#{window_width}')
    RIGHT_SIZE=$((WIN_WIDTH - 30))
    tmux split-window -h -l $RIGHT_SIZE

    # Run kerberos.py in left pane (pane 0)
    tmux select-pane -t 0
    tmux send-keys "cd '$SCRIPT_DIR' && uv run python3 '$KERBEROS_PY'" C-m

    # Right pane (pane 1) starts with a message
    tmux select-pane -t 1
    tmux send-keys "echo 'Use the sidebar to create or select a Claude session'; echo 'Press Ctrl+N in the sidebar to create a new session'" C-m

    # Focus on the left pane (sidebar)
    tmux select-pane -t 0
else
    # Not in tmux, create new session
    SESSION_NAME="kerberos"
    WINDOW_NAME="main"

    # Kill existing session if it exists
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

    # Create new session with a window
    tmux new-session -d -s "$SESSION_NAME" -n "$WINDOW_NAME"

    # Add custom keybinding: Ctrl+S to switch/toggle between panes
    # -n means no prefix needed (direct binding)
    tmux bind-key -n C-s last-pane

    # Split window horizontally (left: sidebar 30 cols, right: main takes the rest)
    # Get window width and calculate right pane size
    WIN_WIDTH=$(tmux display-message -p -t "$SESSION_NAME:$WINDOW_NAME" '#{window_width}')
    RIGHT_SIZE=$((WIN_WIDTH - 30))
    tmux split-window -h -l $RIGHT_SIZE -t "$SESSION_NAME:$WINDOW_NAME"

    # Select left pane (pane 0) and run kerberos.py
    tmux select-pane -t "$SESSION_NAME:$WINDOW_NAME.0"
    tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME.0" "cd '$SCRIPT_DIR' && uv run python3 '$KERBEROS_PY'" C-m

    # Right pane (pane 1) starts with a message
    tmux select-pane -t "$SESSION_NAME:$WINDOW_NAME.1"
    tmux send-keys -t "$SESSION_NAME:$WINDOW_NAME.1" "echo 'Use the sidebar to create or select a Claude session'; echo 'Press Ctrl+N in the sidebar to create a new session'" C-m

    # Focus on the left pane (sidebar)
    tmux select-pane -t "$SESSION_NAME:$WINDOW_NAME.0"

    # Attach to the session
    exec tmux attach-session -t "$SESSION_NAME"
fi
