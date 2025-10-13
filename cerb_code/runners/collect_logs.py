#!/usr/bin/env python3
"""Collect logs from Orchestra sessions"""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from cerb_code.lib.logger import get_logger
from cerb_code.lib.sessions import load_sessions

logger = get_logger(__name__)


def collect_logs(project_dir: Path, output_dir: Path) -> Dict[str, Any]:
    """
    Collect logs from various Orchestra locations.

    Args:
        project_dir: The project directory to collect logs for
        output_dir: The directory to save collected logs to

    Returns:
        Manifest dictionary with metadata about collected logs
    """
    manifest: Dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "project_dir": str(project_dir),
        "logs": {
            "main_session_logs": [],
            "shared_logs": [],
            "system_logs": [],
            "executor_logs": [],
        }
    }

    # Create output directory structure
    output_dir.mkdir(parents=True, exist_ok=True)
    main_logs_dir = output_dir / "main_session_logs"
    shared_logs_dir = output_dir / "shared_logs"
    system_logs_dir = output_dir / "system_logs"
    executor_logs_dir = output_dir / "executor_logs"

    main_logs_dir.mkdir(exist_ok=True)
    shared_logs_dir.mkdir(exist_ok=True)
    system_logs_dir.mkdir(exist_ok=True)
    executor_logs_dir.mkdir(exist_ok=True)

    # Collect main session logs from ~/.claude/debug/*.txt
    main_claude_debug = Path.home() / ".claude" / "debug"
    if main_claude_debug.exists():
        logger.info(f"Collecting main session logs from {main_claude_debug}")
        for log_file in main_claude_debug.glob("*.txt"):
            try:
                dest = main_logs_dir / log_file.name
                shutil.copy2(log_file, dest)
                manifest["logs"]["main_session_logs"].append({
                    "source": str(log_file),
                    "destination": str(dest.relative_to(output_dir)),
                    "size_bytes": log_file.stat().st_size,
                })
                logger.info(f"  Copied {log_file.name}")
            except Exception as e:
                logger.error(f"  Failed to copy {log_file}: {e}")

    # Collect shared logs from ~/.kerberos/shared-claude/debug/*.txt
    shared_claude_debug = Path.home() / ".kerberos" / "shared-claude" / "debug"
    if shared_claude_debug.exists():
        logger.info(f"Collecting shared logs from {shared_claude_debug}")
        for log_file in shared_claude_debug.glob("*.txt"):
            try:
                dest = shared_logs_dir / log_file.name
                shutil.copy2(log_file, dest)
                manifest["logs"]["shared_logs"].append({
                    "source": str(log_file),
                    "destination": str(dest.relative_to(output_dir)),
                    "size_bytes": log_file.stat().st_size,
                })
                logger.info(f"  Copied {log_file.name}")
            except Exception as e:
                logger.error(f"  Failed to copy {log_file}: {e}")

    # Collect system logs from ~/.kerberos/*.log
    kerberos_dir = Path.home() / ".kerberos"
    if kerberos_dir.exists():
        logger.info(f"Collecting system logs from {kerberos_dir}")
        for log_file in kerberos_dir.glob("*.log"):
            try:
                dest = system_logs_dir / log_file.name
                shutil.copy2(log_file, dest)
                manifest["logs"]["system_logs"].append({
                    "source": str(log_file),
                    "destination": str(dest.relative_to(output_dir)),
                    "size_bytes": log_file.stat().st_size,
                })
                logger.info(f"  Copied {log_file.name}")
            except Exception as e:
                logger.error(f"  Failed to copy {log_file}: {e}")

    # Load sessions and collect executor logs
    sessions = load_sessions(flat=True, project_dir=project_dir)
    logger.info(f"Found {len(sessions)} sessions for project {project_dir}")

    for session in sessions:
        # Skip if not an executor or work_path not set
        if session.agent_type.value != "executor" or not session.work_path:
            continue

        work_path = Path(session.work_path)
        claude_debug_dir = work_path / ".claude" / "debug"

        if not claude_debug_dir.exists():
            logger.info(f"  No debug logs found for executor session '{session.session_name}'")
            continue

        logger.info(f"Collecting executor logs from session '{session.session_name}'")
        session_logs_dir = executor_logs_dir / session.session_id
        session_logs_dir.mkdir(exist_ok=True)

        session_log_entries = []
        for log_file in claude_debug_dir.glob("*.txt"):
            try:
                dest = session_logs_dir / log_file.name
                shutil.copy2(log_file, dest)
                session_log_entries.append({
                    "source": str(log_file),
                    "destination": str(dest.relative_to(output_dir)),
                    "size_bytes": log_file.stat().st_size,
                })
                logger.info(f"  Copied {log_file.name}")
            except Exception as e:
                logger.error(f"  Failed to copy {log_file}: {e}")

        if session_log_entries:
            manifest["logs"]["executor_logs"].append({
                "session_name": session.session_name,
                "session_id": session.session_id,
                "work_path": session.work_path,
                "logs": session_log_entries,
            })

    # Write manifest.json
    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Wrote manifest to {manifest_path}")

    return manifest


def main():
    """Entry point for the collect-logs CLI"""
    parser = argparse.ArgumentParser(
        description="Collect logs from Orchestra sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect logs from current directory project
  cerb-collect-logs

  # Collect logs for a specific project
  cerb-collect-logs --project /path/to/project

  # Specify custom output directory
  cerb-collect-logs --output /tmp/my-logs
        """
    )

    parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project directory to collect logs for (default: current directory)"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory for collected logs (default: .orchestra/logs/{timestamp})"
    )

    args = parser.parse_args()

    # Resolve project directory
    project_dir = args.project.resolve()

    if not project_dir.exists():
        logger.error(f"Project directory does not exist: {project_dir}")
        print(f"Error: Project directory does not exist: {project_dir}")
        return 1

    # Determine output directory
    if args.output:
        output_dir = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = project_dir / ".orchestra" / "logs" / timestamp

    logger.info(f"Collecting logs for project: {project_dir}")
    logger.info(f"Output directory: {output_dir}")

    print(f"Collecting logs for project: {project_dir}")
    print(f"Output directory: {output_dir}")
    print()

    try:
        manifest = collect_logs(project_dir, output_dir)

        # Print summary
        print("Log collection complete!")
        print()
        print("Summary:")
        print(f"  Main session logs: {len(manifest['logs']['main_session_logs'])} files")
        print(f"  Shared logs: {len(manifest['logs']['shared_logs'])} files")
        print(f"  System logs: {len(manifest['logs']['system_logs'])} files")
        print(f"  Executor sessions: {len(manifest['logs']['executor_logs'])} sessions")
        print()
        print(f"Logs saved to: {output_dir}")
        print(f"Manifest: {output_dir / 'manifest.json'}")

        return 0

    except Exception as e:
        logger.error(f"Failed to collect logs: {e}", exc_info=True)
        print(f"Error: Failed to collect logs: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
