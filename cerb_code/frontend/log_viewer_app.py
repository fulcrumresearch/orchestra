#!/usr/bin/env python3
"""Streamlit web app for viewing Orchestra session logs"""

import streamlit as st
from pathlib import Path
from datetime import datetime
import time

# Import from lib
from cerb_code.lib.sessions import load_sessions


def get_log_files():
    """Get all log files from ~/.claude/debug/"""
    debug_dir = Path.home() / ".claude" / "debug"
    if not debug_dir.exists():
        return []

    log_files = []
    for log_file in debug_dir.glob("*.txt"):
        # Skip the 'latest' symlink
        if log_file.is_symlink():
            continue

        stat = log_file.stat()
        log_files.append({
            "name": log_file.name,
            "path": log_file,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime)
        })

    # Sort by modification time, newest first
    log_files.sort(key=lambda x: x["modified"], reverse=True)
    return log_files


def get_sessions_info():
    """Get session information from sessions.json"""
    try:
        sessions = load_sessions(flat=True)
        return sessions
    except Exception as e:
        st.warning(f"Could not load sessions: {e}")
        return []


def format_log_content(content, max_lines=None):
    """Format log content for display"""
    lines = content.split('\n')
    if max_lines:
        lines = lines[-max_lines:]
    return '\n'.join(lines)


def run_app():
    """Main streamlit app function"""
    st.set_page_config(
        page_title="Orchestra Log Viewer",
        page_icon="📋",
        layout="wide"
    )

    st.title("📋 Orchestra Session Logs")

    # Sidebar configuration
    st.sidebar.header("Settings")

    # Auto-refresh option
    auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
    if auto_refresh:
        refresh_interval = st.sidebar.slider("Refresh interval (seconds)", 1, 30, 5)

    # Display options
    show_debug = st.sidebar.checkbox("Show DEBUG lines", value=True)
    show_error = st.sidebar.checkbox("Show ERROR lines", value=True)
    tail_lines = st.sidebar.number_input("Tail lines (0 = all)", min_value=0, max_value=10000, value=1000)

    # Get log files
    log_files = get_log_files()

    if not log_files:
        st.warning("No log files found in ~/.claude/debug/")
        return

    # Session info
    sessions = get_sessions_info()
    if sessions:
        st.sidebar.header("Active Sessions")
        for session in sessions:
            session_type = session.agent_type.value
            st.sidebar.text(f"• {session.session_name} ({session_type})")

    # Main content area
    st.sidebar.header("Select Log File")

    # Create a dropdown with log file names and timestamps
    log_options = [f"{log['name']} ({log['modified'].strftime('%Y-%m-%d %H:%M:%S')})"
                   for log in log_files]

    selected_index = st.sidebar.selectbox(
        "Log file",
        range(len(log_options)),
        format_func=lambda x: log_options[x]
    )

    selected_log = log_files[selected_index]

    # Display log file info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("File", selected_log["name"])
    with col2:
        st.metric("Size", f"{selected_log['size'] / 1024:.1f} KB")
    with col3:
        st.metric("Modified", selected_log["modified"].strftime("%H:%M:%S"))

    st.divider()

    # Read and display log content
    try:
        with open(selected_log["path"], "r") as f:
            content = f.read()

        # Filter based on options
        lines = content.split('\n')
        if not show_debug:
            lines = [line for line in lines if '[DEBUG]' not in line]
        if not show_error:
            lines = [line for line in lines if '[ERROR]' not in line]

        # Apply tail limit
        if tail_lines > 0:
            lines = lines[-tail_lines:]

        filtered_content = '\n'.join(lines)

        # Display in a code block for better formatting
        st.code(filtered_content, language="log", line_numbers=False)

        # Show stats
        st.caption(f"Showing {len(lines)} lines")

    except Exception as e:
        st.error(f"Error reading log file: {e}")

    # Auto-refresh implementation
    if auto_refresh:
        time.sleep(refresh_interval)
        st.rerun()


def main():
    """CLI entry point that launches streamlit"""
    import sys
    import subprocess

    # Get the path to this file
    app_path = Path(__file__).resolve()

    # Launch streamlit with this file
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.headless", "true"
    ])


if __name__ == "__main__":
    run_app()
