"""Global configuration for Orchestra"""

# Test pairing: Added comment to test pairing functionality

import json
from pathlib import Path
from typing import Any, Dict

from .logger import get_logger

logger = get_logger(__name__)

CONFIG_FILE = Path.home() / ".orchestra" / "config" / "settings.json"

DEFAULT_CONFIG = {
    "use_docker": True,
    "mcp_port": 8765,
    "ui_theme": "textual-dark",
    "tmux_server_name": "orchestra",
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


def get_tmux_server_name() -> str:
    """Get configured tmux server name.

    Returns:
        Configured tmux server name (defaults to "orchestra")
    """
    config = load_config()
    return config.get("tmux_server_name", "orchestra")


def claude_settings_builder(
    session_id: str,
    source_path: str,
    mcp_config: Dict[str, Any] = None,
    allowed_tools: list[str] = None,
    is_monitored: bool = True
) -> Dict[str, Any]:
    """Build Claude settings.json configuration

    Args:
        session_id: Session ID for hook commands
        source_path: Source path for hook commands
        mcp_config: Extra MCP servers to add (merged with orchestra-mcp)
        allowed_tools: List of allowed tools (None = bypass all permissions)
        is_monitored: Whether to include orchestra-hook monitoring

    Returns:
        Settings dict ready to write as JSON
    """
    config = load_config()
    mcp_port = config.get("mcp_port", 8765)

    settings = {
        "permissions": {
            "defaultMode": "bypassPermissions" if not allowed_tools else "requireApproval",
            "allow": allowed_tools or [
                "Edit", "Glob", "Grep", "LS", "MultiEdit", "Read", "Write",
                "Bash(cat:*)", "Bash(cp:*)", "Bash(grep:*)", "Bash(head:*)",
                "Bash(mkdir:*)", "Bash(pwd:*)", "Bash(rg:*)", "Bash(tail:*)",
                "Bash(tree:*)", "mcp__orchestra-mcp"
            ]
        },
        "mcpServers": {
            "orchestra-mcp": {
                "url": f"http://localhost:{mcp_port}/mcp",
                "type": "http"
            }
        }
    }

    # Ensure mcp__orchestra-mcp is always in allow list
    if allowed_tools and "mcp__orchestra-mcp" not in settings["permissions"]["allow"]:
        settings["permissions"]["allow"].append("mcp__orchestra-mcp")

    # Add extra MCP servers
    if mcp_config:
        settings["mcpServers"].update(mcp_config)

    # Add monitoring hooks if enabled
    if is_monitored:
        hook_command = f"orchestra-hook {session_id} {source_path}"
        settings["hooks"] = {
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": hook_command}]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [{"type": "command", "command": hook_command}]
                }
            ],
            "Stop": [
                {
                    "hooks": [{"type": "command", "command": hook_command}]
                }
            ]
        }

    return settings
