"""Monitor tab widget for displaying session monitor files"""

from typing import Dict, Any

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog
from rich.markup import escape

from cerb_code.lib.monitor import SessionMonitorWatcher


class ModelMonitorTab(Container):
    """Tab for monitoring session and children monitor.md files."""

    def compose(self) -> ComposeResult:
        self.monitor_log = RichLog(
            highlight=True,
            markup=True,
            auto_scroll=False,
            wrap=True,
            min_width=0,  # Don't enforce minimum width
        )
        yield self.monitor_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.watcher = None
        self.set_interval(2.0, self.refresh_monitor)
        self.refresh_monitor()

    def refresh_monitor(self) -> None:
        """Read and display monitor.md files for current session and children"""
        app = self.app

        # Check if we have state and a current session
        if not hasattr(app, "state"):
            self.monitor_log.clear()
            self.monitor_log.write("[dim]No state available[/dim]", expand=True)
            self.watcher = None
            return

        current_session = app.state.get_active_session()
        if not current_session:
            self.monitor_log.clear()
            self.monitor_log.write("[dim]No session selected[/dim]", expand=True)
            self.watcher = None
            return

        # Create or update watcher with current session
        if self.watcher is None or self.watcher.session != current_session:
            self.watcher = SessionMonitorWatcher(session=current_session)

        monitors = self.watcher.get_monitor_files()
        self._update_display(monitors)

    def _update_display(self, monitors: Dict[str, Dict[str, Any]]) -> None:
        """Update the display with new monitor data"""
        self.monitor_log.clear()

        if not monitors:
            self.monitor_log.write("[dim]No monitor.md files found[/dim]", expand=True)
            return

        # Sort by last modified time (most recent first)
        sorted_monitors = sorted(monitors.items(), key=lambda x: x[1]["mtime"], reverse=True)

        for session_id, monitor_data in sorted_monitors:
            # Header for each session
            agent_type = monitor_data.get("agent_type", "unknown")
            if agent_type == "executor":
                color = "#00d4ff"
            else:
                color = "#00ff9f"
            self.monitor_log.write("", expand=True)
            self.monitor_log.write(
                f"[bold {color}]══════════════════════════════════════════════════[/bold {color}]",
                expand=True,
            )
            self.monitor_log.write(
                f"[bold yellow]{session_id}[/bold yellow] [dim][{color}]({agent_type})[/{color}][/dim]",
                expand=True,
            )
            self.monitor_log.write(
                f"[dim]Last updated: {monitor_data['last_updated']}[/dim]",
                expand=True,
            )
            self.monitor_log.write(f"[dim]{monitor_data['path']}[/dim]", expand=True)
            self.monitor_log.write(
                "[bold cyan]──────────────────────────────────────────────────[/bold cyan]",
                expand=True,
            )

            content = monitor_data["content"]
            if not content or content.strip() == "":
                self.monitor_log.write(
                    "[dim italic]Empty monitor file[/dim italic]",
                    expand=True,
                )
            else:
                # Display content with markdown-like formatting
                for line in content.split("\n"):
                    escaped_line = escape(line)
                    if line.startswith("# "):
                        self.monitor_log.write(
                            f"[bold cyan]{escaped_line}[/bold cyan]",
                            expand=True,
                        )
                    elif line.startswith("## "):
                        self.monitor_log.write(
                            f"[bold green]{escaped_line}[/bold green]",
                            expand=True,
                        )
                    elif line.startswith("### "):
                        self.monitor_log.write(f"[green]{escaped_line}[/green]", expand=True)
                    elif line.startswith("- "):
                        self.monitor_log.write(
                            f"[yellow]{escaped_line}[/yellow]",
                            expand=True,
                        )
                    elif "ERROR" in line or "WARNING" in line:
                        self.monitor_log.write(f"[red]{escaped_line}[/red]", expand=True)
                    elif "SUCCESS" in line or "OK" in line or "✓" in line:
                        self.monitor_log.write(f"[green]{escaped_line}[/green]", expand=True)
                    elif line.startswith("HOOK EVENT:"):
                        self.monitor_log.write(
                            f"[magenta]{escaped_line}[/magenta]",
                            expand=True,
                        )
                    elif line.startswith("time:") or line.startswith("session_id:") or line.startswith("tool:"):
                        self.monitor_log.write(f"[blue]{escaped_line}[/blue]", expand=True)
                    else:
                        self.monitor_log.write(escaped_line, expand=True)
