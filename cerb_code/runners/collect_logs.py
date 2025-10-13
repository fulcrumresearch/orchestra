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
        "transcripts": []
    }

    # Create output directory structure - only transcripts now
    output_dir.mkdir(parents=True, exist_ok=True)

    # Collect JSONL transcript files from ~/.claude/projects/
    # The project directory path gets encoded in the folder name
    # For example: /home/ec2-user/orchestra becomes -home-ec2-user-orchestra
    project_name_encoded = str(project_dir).replace("/", "-")
    main_transcripts_dir = Path.home() / ".claude" / "projects" / project_name_encoded

    if main_transcripts_dir.exists():
        logger.info(f"Collecting transcripts from {main_transcripts_dir}")
        for jsonl_file in main_transcripts_dir.glob("*.jsonl"):
            try:
                dest = output_dir / jsonl_file.name
                shutil.copy2(jsonl_file, dest)
                manifest["transcripts"].append({
                    "source": str(jsonl_file),
                    "filename": jsonl_file.name,
                    "size_bytes": jsonl_file.stat().st_size,
                    "session_type": "main",
                })
                logger.info(f"  Copied {jsonl_file.name}")
            except Exception as e:
                logger.error(f"  Failed to copy {jsonl_file}: {e}")
    else:
        logger.info(f"No transcripts found at {main_transcripts_dir}")

    # Load sessions and collect executor transcripts
    sessions = load_sessions(flat=True, project_dir=project_dir)
    logger.info(f"Found {len(sessions)} sessions for project {project_dir}")

    for session in sessions:
        # Skip if not an executor or work_path not set
        if session.agent_type.value != "executor" or not session.work_path:
            continue

        work_path = Path(session.work_path)

        # Collect JSONL transcripts for this executor session
        executor_projects_dir = work_path / ".claude" / "projects"
        if executor_projects_dir.exists():
            logger.info(f"Collecting transcripts from executor '{session.session_name}'")
            for jsonl_file in executor_projects_dir.glob("**/*.jsonl"):
                try:
                    # Create a unique filename for executor transcripts
                    dest_name = f"{session.session_id}_{jsonl_file.name}"
                    dest = output_dir / dest_name
                    shutil.copy2(jsonl_file, dest)
                    manifest["transcripts"].append({
                        "source": str(jsonl_file),
                        "filename": dest_name,
                        "size_bytes": jsonl_file.stat().st_size,
                        "session_type": "executor",
                        "session_name": session.session_name,
                        "session_id": session.session_id,
                    })
                    logger.info(f"  Copied {jsonl_file.name}")
                except Exception as e:
                    logger.error(f"  Failed to copy transcript {jsonl_file}: {e}")

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
        print("Transcript collection complete!")
        print()
        print(f"Collected {len(manifest['transcripts'])} conversation transcripts")
        print()
        print(f"Transcripts saved to: {output_dir}")
        print(f"Manifest: {output_dir / 'manifest.json'}")

        return 0

    except Exception as e:
        logger.error(f"Failed to collect logs: {e}", exc_info=True)
        print(f"Error: Failed to collect logs: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
