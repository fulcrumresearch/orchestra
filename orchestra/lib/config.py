"""Global configuration for Orchestra"""

# Test pairing: Added comment to test pairing functionality

import json
from pathlib import Path
from typing import Any, Dict

from .logger import get_logger

logger = get_logger(__name__)

CONFIG_FILE = Path.home() / ".orchestra" / "config.json"

DEFAULT_CONFIG = {
    "use_docker": True,
    "mcp_port": 8765,
    "ui_theme": "textual-dark",
}

# Default tmux configuration for all Orchestra sessions
DEFAULT_TMUX_CONF = """# Orchestra tmux configuration

# Disable status bar
set-option -g status off

# Enable scrollback buffer with 10000 lines
set-option -g history-limit 10000

# Enable mouse support for scrolling
set-option -g mouse on

# Ensure proper color support
set-option -g default-terminal "screen-256color"

# Disable all default key bindings to avoid conflicts
unbind-key -a

# Ctrl+S for pane switching
bind-key -n C-s select-pane -t :.+

# Ctrl+\\ for detaching without killing session
bind-key -n C-\\\\ detach-client

# Re-enable mouse wheel scrolling bindings for copy mode
bind-key -n WheelUpPane if-shell -F -t = "#{mouse_any_flag}" "send-keys -M" "if -Ft= '#{pane_in_mode}' 'send-keys -M' 'copy-mode -e; send-keys -M'"
bind-key -n WheelDownPane select-pane -t= \\; send-keys -M

# Copy mode usage:
# Mouse wheel up to scroll
# Press 'q' or Esc to exit copy mode
"""

# Default tmux configuration for main layout (host tmux session)
DEFAULT_TMUX_MAIN_CONF = """# Orchestra main layout tmux configuration
# This config is used for the host tmux session that displays the orchestra layout

# Disable status bar
set-option -g status off

# Enable mouse support
set-option -g mouse on

# Disable all default key bindings
unbind-key -a

# Ctrl+S for pane switching
bind-key -n C-s select-pane -t :.+

# Ctrl+\\ for detaching without killing session
bind-key -n C-\\\\ detach-client

# Re-enable mouse wheel scrolling bindings for copy mode
bind-key -n WheelUpPane if-shell -F -t = "#{mouse_any_flag}" "send-keys -M" "if -Ft= '#{pane_in_mode}' 'send-keys -M' 'copy-mode -e; send-keys -M'"
bind-key -n WheelDownPane select-pane -t= \\; send-keys -M

# Minimal pane border styling
set-option -g pane-border-style fg=colour240
set-option -g pane-active-border-style fg=colour33

# Copy mode usage:
# Mouse wheel up to scroll
# Press 'q' or Esc to exit copy mode
"""

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


def ensure_config_dir() -> Path:
    """Ensure ~/.orchestra/config/ directory exists with default config files.

    Creates the config directory and writes default config files ONLY if they don't exist.
    Never overwrites existing user configs.

    Returns:
        Path to the config directory
    """
    config_dir = Path.home() / ".orchestra" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create tmux.conf if it doesn't exist
    tmux_conf_path = config_dir / "tmux.conf"
    if not tmux_conf_path.exists():
        tmux_conf_path.write_text(DEFAULT_TMUX_CONF)
        logger.info(f"Created default tmux.conf at {tmux_conf_path}")

    return config_dir


def get_tmux_config_path() -> Path:
    """Get path to tmux.conf for all Orchestra sessions.

    Ensures config directory exists before returning path.

    Returns:
        Path to ~/.orchestra/config/tmux.conf
    """
    ensure_config_dir()
    return Path.home() / ".orchestra" / "config" / "tmux.conf"
