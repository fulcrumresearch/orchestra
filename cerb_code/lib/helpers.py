"""Helper utilities for kerberos"""
import subprocess
import shutil
from pathlib import Path
from .logger import get_logger

logger = get_logger(__name__)


def get_current_branch(cwd: Path = None) -> str:
    """Get the current git branch name"""
    if cwd is None:
        cwd = Path.cwd()

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


def ensure_stable_git_location(project_dir: Path) -> None:
    """
    Move .git to stable location and create symlink if not already done.
    This ensures .git location doesn't change when we swap directories during pairing.

    Should be called once when first setting up sessions for a project.
    """
    source_git = project_dir / ".git"

    # Skip if already a symlink (already relocated)
    if source_git.is_symlink():
        logger.info(f".git already symlinked at {source_git}")
        return

    # Skip if not a git directory
    if not source_git.exists() or not source_git.is_dir():
        logger.warning(f"No .git directory found at {source_git}")
        return

    source_dir_name = project_dir.name
    stable_git_dir = Path.home() / ".kerberos" / "repos" / source_dir_name / ".git" # handle duplicate names later

    # If stable location exists, just create symlink
    if stable_git_dir.exists():
        logger.info(f"Using existing stable .git at {stable_git_dir}")
        # Backup current .git just in case
        if source_git.exists():
            shutil.move(str(source_git), f"{source_git}.backup")
        source_git.symlink_to(stable_git_dir)
        logger.info(f"Created symlink {source_git} → {stable_git_dir}")
        return

    # Move .git to stable location
    stable_git_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_git), str(stable_git_dir))
    logger.info(f"Moved {source_git} → {stable_git_dir}")

    # Create symlink back
    source_git.symlink_to(stable_git_dir)
    logger.info(f"Created symlink {source_git} → {stable_git_dir}")


# Tmux pane constants
PANE_UI = "0"
PANE_EDITOR = "1"
PANE_AGENT = "2"


def respawn_pane(pane: str, command: str) -> bool:
    """Generic helper to respawn a tmux pane with a command.

    Args:
        pane: The pane number to respawn
        command: The command to run in the pane

    Returns:
        True if successful, False otherwise
    """
    result = subprocess.run(
        ["tmux", "-L", "orchestra", "respawn-pane", "-t", pane, "-k", command],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def respawn_pane_with_vim(spec_file: Path) -> bool:
    """Open vim in editor pane.

    Args:
        spec_file: Path to the file to open in vim

    Returns:
        True if successful, False otherwise
    """
    vim_cmd = f"bash -c '$EDITOR {spec_file}; clear; echo \"Press S to open spec editor\"; exec bash'"
    return respawn_pane(PANE_EDITOR, vim_cmd)


def respawn_pane_with_terminal(work_path: Path) -> bool:
    """Open bash in editor pane.

    Args:
        work_path: Path to cd into before starting bash

    Returns:
        True if successful, False otherwise
    """
    bash_cmd = f"bash -c 'cd {work_path} && exec bash'"
    return respawn_pane(PANE_EDITOR, bash_cmd)


def clear_pane(pane: str, message: str = "") -> bool:
    """Clear pane with optional message.

    Args:
        pane: The pane number to clear
        message: Optional message to display

    Returns:
        True if successful, False otherwise
    """
    cmd = f"echo '{message}'" if message else "clear"
    return respawn_pane(pane, cmd)
