import logging
import os
from pathlib import Path
from datetime import datetime

# Create $ORCHESTRA_HOME directory if it doesn't exist
# Note: We inline get_orchestra_home() here to avoid circular imports
def _get_log_dir() -> Path:
    """Get Orchestra home directory for logging (inline to avoid circular import)"""
    orchestra_home = os.environ.get("ORCHESTRA_HOME")
    if orchestra_home:
        return Path(orchestra_home)
    return Path.home() / ".orchestra"

LOG_DIR = _get_log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging
LOG_FILE = LOG_DIR / "orchestra.log"


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with proper configuration"""
    logger = logging.getLogger(name)

    if not logger.handlers:  # Avoid adding duplicate handlers
        logger.setLevel(logging.DEBUG)

        # File handler
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.DEBUG)

        # Format
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)

    return logger


# Log startup
logger = get_logger(__name__)
logger.info(f"Logging initialized at {datetime.now()}")
