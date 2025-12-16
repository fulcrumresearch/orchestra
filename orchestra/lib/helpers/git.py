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


def create_worktree(work_path: str, branch_name: str, source_path: str) -> None:
    """Create a git worktree at the specified path

    Args:
        work_path: Path where worktree should be created
        branch_name: Name of the branch for the worktree
        source_path: Path to the source git repository

    Raises:
        RuntimeError: If worktree creation fails
    """
    work_path_obj = Path(work_path)

    # Check if worktree already exists with files
    if work_path_obj.exists() and list(work_path_obj.iterdir()):
        # Already has files, assume worktree exists
        return

    # Create new worktree on a new branch
    try:
        # Check if branch already exists
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
            cwd=source_path,
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # Branch exists, use it
            subprocess.run(
                ["git", "worktree", "add", work_path, branch_name],
                cwd=source_path,
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            # Branch doesn't exist, create it
            subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, work_path],
                cwd=source_path,
                check=True,
                capture_output=True,
                text=True,
            )

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to create worktree: {e.stderr}")
