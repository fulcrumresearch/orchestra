#!/usr/bin/env python3
"""
Display hook for independent monitor feedback.

This script:
1. Checks if .orchestra-monitor.txt exists in the current working directory
2. If exists: reads contents, prints to stderr, deletes file
3. If not exists: exits silently

This is designed to be called as a hook to display monitor feedback to the agent.
Output to stderr ensures the feedback is visible in the agent's context.
"""

import sys
from pathlib import Path


def main() -> int:
    """Main entry point for monitor display hook"""
    # Look for monitor feedback file in current working directory
    monitor_file = Path.cwd() / ".orchestra-monitor.txt"

    if not monitor_file.exists():
        # No feedback to display - exit silently
        return 0

    # Read the monitor feedback
    feedback = monitor_file.read_text()

    # Print to stderr so it's fed back to the agent
    print("=" * 80, file=sys.stderr)
    print("MONITOR FEEDBACK", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(feedback, file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    # Delete the file after displaying
    monitor_file.unlink()

    # Return exit code 2 to trigger blocking error (feeds stderr back to Claude)
    return 2

if __name__ == "__main__":
    sys.exit(main())
