"""Global configuration for Orchestra"""

# Test pairing: Added comment to test pairing functionality

import json
from pathlib import Path
from typing import Any, Dict

CONFIG_FILE = Path.home() / ".orchestra" / "config.json"

DEFAULT_CONFIG = {
    "use_docker": True,
    "mcp_port": 8765,
}


def load_config() -> Dict[str, Any]:
    """Load global configuration"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                return {**DEFAULT_CONFIG, **config}
        except (json.JSONDecodeError, IOError):
            pass

    return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]) -> None:
    """Save global configuration"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
