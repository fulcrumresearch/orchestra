"""Git operations utilities"""

import subprocess
from pathlib import Path

from ..logger import get_logger

logger = get_logger(__name__)


def get_current_branch(cwd: Path | None = None) -> str:
    """Get the current git branch name"""
    cwd = cwd or Path.cwd()

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # Fallback to 'main' if not a git repo
        logger.warning("Not in a git repository, using 'main' as branch name")
        return "main"
