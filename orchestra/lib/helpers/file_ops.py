"""File and directory utilities"""

import json
from pathlib import Path

from ..logger import get_logger
from ..prompts import DESIGNER_MD_TEMPLATE, DOC_MD_TEMPLATE, ARCHITECTURE_MD_TEMPLATE

logger = get_logger(__name__)


# Sessions file path (shared constant)
SESSIONS_FILE = Path.home() / ".orchestra" / "sessions.json"


def ensure_orchestra_directory(project_dir: Path) -> tuple[Path, Path]:
    """Ensure .orchestra/ directory exists with designer.md, doc.md, and docs/architecture.md templates,
    and create a .gitignore file inside .orchestra/ to manage what gets committed.

    Args:
        project_dir: Path to the project directory

    Returns:
        Tuple of (designer_md_path, doc_md_path)
    """
    orchestra_dir = project_dir / ".orchestra"
    orchestra_dir.mkdir(exist_ok=True)

    # Create .gitignore inside .orchestra/ to ignore most content but preserve docs and markdown files
    gitignore_path = orchestra_dir / ".gitignore"
    gitignore_content = "*"
    if not gitignore_path.exists():
        gitignore_path.write_text(gitignore_content)
        logger.info(f"Created .gitignore at {gitignore_path}")

    # Create docs directory
    docs_dir = orchestra_dir / "docs"
    docs_dir.mkdir(exist_ok=True)

    designer_md = orchestra_dir / "designer.md"
    doc_md = orchestra_dir / "doc.md"
    architecture_md = docs_dir / "architecture.md"

    # Create designer.md with template if it doesn't exist
    if not designer_md.exists():
        designer_md.write_text(DESIGNER_MD_TEMPLATE)
        logger.info(f"Created designer.md with template at {designer_md}")

    # Create doc.md with template if it doesn't exist
    if not doc_md.exists():
        doc_md.write_text(DOC_MD_TEMPLATE)
        logger.info(f"Created doc.md with template at {doc_md}")

    # Create architecture.md with template if it doesn't exist
    if not architecture_md.exists():
        architecture_md.write_text(ARCHITECTURE_MD_TEMPLATE)
        logger.info(f"Created architecture.md with template at {architecture_md}")

    return designer_md, doc_md


def is_first_run(project_dir: Path | None = None) -> bool:
    """Check if this is the first run for a project (no sessions in sessions.json)

    Args:
        project_dir: Path to the project directory. Defaults to current directory.

    Returns:
        True if no sessions exist for the project, False otherwise
    """
    if project_dir is None:
        project_dir = Path.cwd()

    project_dir_str = str(project_dir)

    if not SESSIONS_FILE.exists():
        return True

    try:
        with open(SESSIONS_FILE, "r") as f:
            data = json.load(f)
            project_sessions = data.get(project_dir_str, [])
            return len(project_sessions) == 0
    except (json.JSONDecodeError, KeyError):
        return True
