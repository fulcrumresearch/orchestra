#!/usr/bin/env python3
"""Entry point for orchestra command"""

import os
import sys
import subprocess
from pathlib import Path


def main():
    """Run the launch.sh script"""
    # launch.sh is in the package root, one level above this runners/ dir
    script_dir = Path(__file__).parent.parent
    launch_script = script_dir / "launch.sh"

    if not launch_script.exists():
        print("Error: launch.sh not found")
        print("Package installation appears incomplete")
        sys.exit(1)

    subprocess.run(["/bin/bash", str(launch_script)], check=True)


if __name__ == "__main__":
    main()
