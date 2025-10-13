#!/usr/bin/env python3
"""Streamlit web app for viewing collected Orchestra logs"""

import streamlit as st
from pathlib import Path
from datetime import datetime
import json
import argparse
import sys


def get_latest_log_dir(orchestra_dir: Path) -> Path | None:
    """Get the latest log directory from .orchestra/logs/"""
    logs_dir = orchestra_dir / "logs"
    if not logs_dir.exists():
        return None

    # Get all timestamp directories
    log_dirs = [d for d in logs_dir.iterdir() if d.is_dir()]
    if not log_dirs:
        return None

    # Sort by directory name (timestamp format should sort chronologically)
    log_dirs.sort(reverse=True)
    return log_dirs[0]


def load_manifest(log_dir: Path) -> dict | None:
    """Load manifest.json from the log directory"""
    manifest_path = log_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading manifest: {e}")
        return None


def get_transcripts(log_dir: Path) -> list[dict]:
    """Get all JSONL transcript files"""
    log_files = []

    # Get all JSONL files directly in log_dir
    for log_file in log_dir.glob("*.jsonl"):
        stat = log_file.stat()

        # Try to extract summary and branch from first few lines
        display_name = log_file.name
        try:
            with open(log_file, 'r') as f:
                # Check first line for summary
                first_line = f.readline()
                if first_line.strip():
                    first_item = json.loads(first_line)
                    summary = first_item.get("summary")
                    if summary:
                        display_name = summary

                # Check next few lines for git branch
                git_branch = None
                for _ in range(5):
                    line = f.readline()
                    if not line:
                        break
                    if line.strip():
                        item = json.loads(line)
                        branch = item.get("gitBranch")
                        if branch:
                            git_branch = branch
                            break

                if git_branch and summary:
                    display_name = f"{summary} [{git_branch}]"
                elif git_branch:
                    display_name = f"{log_file.stem} [{git_branch}]"
        except:
            pass

        log_files.append({
            "name": log_file.name,
            "display_name": display_name,
            "path": log_file,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime),
        })

    # Sort by modification time, newest first
    log_files.sort(key=lambda x: x["modified"], reverse=True)
    return log_files


def parse_jsonl_transcript(file_path: Path) -> list[dict]:
    """Parse JSONL transcript file and return a list of conversation items"""
    items = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
    except Exception as e:
        st.error(f"Error parsing JSONL file: {e}")
    return items


def display_jsonl_transcript(file_path: Path, search_term: str = "", date_filter: tuple = None):
    """Display JSONL transcript in a readable format"""
    items = parse_jsonl_transcript(file_path)

    if not items:
        st.info("No conversation data found in this transcript")
        return

    # Collect statistics
    user_messages = []
    assistant_messages = []
    tool_calls = []
    total_tokens = 0

    for item in items:
        item_type = item.get("type")
        if item_type == "user":
            user_messages.append(item)
        elif item_type == "assistant":
            assistant_messages.append(item)
            # Track token usage
            usage = item.get("usage", {})
            total_tokens += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        elif item_type == "tool_use" or item_type == "tool_result":
            tool_calls.append(item)

    # Display statistics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("User Messages", len(user_messages))
    with col2:
        st.metric("Assistant Messages", len(assistant_messages))
    with col3:
        st.metric("Tool Calls", len(tool_calls))
    with col4:
        st.metric("Total Tokens", f"{total_tokens:,}")

    st.divider()

    # Display conversation
    message_count = 0
    for idx, item in enumerate(items):
        item_type = item.get("type")
        timestamp = item.get("timestamp", "")

        # Apply search filter
        item_text = json.dumps(item).lower()
        if search_term and search_term.lower() not in item_text:
            continue

        # Display based on type
        if item_type == "user":
            message_count += 1

            # User messages have content in message.content as a string
            message_obj = item.get("message", {})
            content = message_obj.get("content", "")

            # Handle if content is a string (user messages) or array
            if isinstance(content, str):
                user_text = content
            else:
                # Fallback for array format
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        text_parts.append(part)
                user_text = "\n".join(text_parts)

            with st.container():
                st.markdown(f"### 👤 User Message {message_count}")
                if timestamp:
                    st.caption(f"🕐 {timestamp}")
                st.markdown(user_text)
                st.divider()

        elif item_type == "assistant":
            message_count += 1

            # Assistant messages have content in message.content as an array
            message_obj = item.get("message", {})
            content = message_obj.get("content", [])
            usage = message_obj.get("usage", {})
            model = message_obj.get("model", "")

            with st.container():
                st.markdown(f"### 🤖 Assistant Message {message_count}")
                if timestamp:
                    st.caption(f"🕐 {timestamp} | Model: {model}")

                # Display token usage
                if usage:
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    st.caption(f"📊 Tokens: {input_tokens:,} in / {output_tokens:,} out")

                # Process content blocks
                has_text = False
                tool_uses = []

                for block in content:
                    if isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            text = block.get("text", "")
                            if text.strip():
                                has_text = True
                                st.markdown(text)
                        elif block_type == "tool_use":
                            tool_uses.append(block)

                if not has_text and not tool_uses:
                    st.info("_No text content_")

                # Display tool uses
                if tool_uses:
                    with st.expander(f"🔧 Tool Calls ({len(tool_uses)})", expanded=False):
                        for tool in tool_uses:
                            tool_name = tool.get("name", "unknown")
                            tool_input = tool.get("input", {})
                            st.markdown(f"**{tool_name}**")
                            st.json(tool_input, expanded=False)

                st.divider()

        elif item_type == "tool_result":
            # Display tool results in a collapsible section
            tool_use_id = item.get("tool_use_id", "")
            content = item.get("content", [])

            with st.expander(f"🔨 Tool Result", expanded=False):
                if timestamp:
                    st.caption(f"🕐 {timestamp}")
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        result_text = block.get("text", "")
                        # Truncate long results
                        if len(result_text) > 1000:
                            st.text(result_text[:1000] + "\n... (truncated)")
                        else:
                            st.text(result_text)

    if message_count == 0:
        st.info("No messages match your search criteria")


def run_app(log_dir: Path):
    """Main streamlit app function"""
    st.set_page_config(
        page_title="Collected Logs Viewer",
        page_icon="📦",
        layout="wide"
    )

    st.title("📦 Orchestra Collected Logs Viewer")

    # Load manifest
    manifest = load_manifest(log_dir)

    # Display manifest info at the top
    if manifest:
        st.subheader("Collection Info")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Timestamp", manifest.get("timestamp", "Unknown"))
        with col2:
            st.metric("Project", manifest.get("project_name", "Unknown"))
        with col3:
            transcripts = manifest.get("transcripts", [])
            st.metric("Transcripts", len(transcripts))

        st.divider()
    else:
        st.warning("No manifest.json found in log directory")

    # Get all transcripts
    transcripts = get_transcripts(log_dir)

    if not transcripts:
        st.info("No transcripts found in this log directory")
        return

    # Sidebar for transcript selection
    st.sidebar.header("Select Transcript")

    # Build transcript options for the dropdown
    transcript_options = []
    for t in transcripts:
        display = t.get('display_name', t['name'])
        size_kb = t['size'] / 1024
        transcript_options.append(f"{display} ({size_kb:.1f} KB)")

    selected_index = st.sidebar.selectbox(
        "Transcript",
        range(len(transcript_options)),
        format_func=lambda x: transcript_options[x]
    )

    selected_transcript = transcripts[selected_index]

    # Display transcript info
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("File", selected_transcript["name"])
    with col2:
        st.metric("Size", f"{selected_transcript['size'] / 1024:.1f} KB")
    with col3:
        st.metric("Modified", selected_transcript["modified"].strftime("%Y-%m-%d %H:%M:%S"))

    # Search filter
    st.sidebar.header("Filter Options")
    search_term = st.sidebar.text_input("Search text", "")

    st.divider()

    # Display the transcript
    try:
        display_jsonl_transcript(selected_transcript["path"], search_term)
    except Exception as e:
        st.error(f"Error reading transcript: {e}")


def main():
    """CLI entry point that launches streamlit"""
    import subprocess

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="View collected Orchestra logs")
    parser.add_argument(
        "--log-dir",
        type=str,
        help="Path to collected logs directory (default: latest in .orchestra/logs/)"
    )

    args = parser.parse_args()

    # Determine log directory
    if args.log_dir:
        log_dir = Path(args.log_dir)
        if not log_dir.exists():
            print(f"Error: Log directory does not exist: {log_dir}")
            sys.exit(1)
    else:
        # Find latest log directory
        orchestra_dir = Path.cwd() / ".orchestra"
        log_dir = get_latest_log_dir(orchestra_dir)

        if not log_dir:
            print("Error: No collected logs found in .orchestra/logs/")
            print("Run 'cerb-collect-logs' first to collect logs")
            sys.exit(1)

    print(f"Viewing logs from: {log_dir}")

    # Store log_dir in session state by setting environment variable
    import os
    os.environ["COLLECTED_LOG_DIR"] = str(log_dir)

    # Get the path to this file
    app_path = Path(__file__).resolve()

    # Launch streamlit with this file
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.headless", "true"
    ])


if __name__ == "__main__":
    # When running under streamlit, get log_dir from environment
    import os
    log_dir_str = os.environ.get("COLLECTED_LOG_DIR")
    if log_dir_str:
        run_app(Path(log_dir_str))
    else:
        # This shouldn't happen, but provide a fallback
        st.error("Log directory not set. Please run via 'cerb-view-collected-logs' command")
