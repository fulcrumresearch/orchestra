#!/usr/bin/env python3
"""Monitor UI for displaying session diffs and activity"""
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Static, Label, TabbedContent, TabPane, RichLog
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.text import Text

class DiffTab(VerticalScroll):
    """Scrollable container for diff display"""

    def compose(self) -> ComposeResult:
        self.diff_log = RichLog(highlight=True, markup=True)
        yield self.diff_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        app = self.app
        if hasattr(app, 'work_path'):
            self.set_interval(2.0, self.refresh_diff)
            self.refresh_diff()

    def refresh_diff(self) -> None:
        """Fetch and display the latest diff"""
        app = self.app
        work_path = getattr(app, 'work_path', None)
        session_id = getattr(app, 'session_id', None)

        if not work_path:
            self.diff_log.write("ERROR: No work_path set")
            return

        try:
            # Get git diff
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=work_path,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                # Clear previous content
                self.diff_log.clear()

                if result.stdout:
                    # Write diff line by line for better scrolling
                    for line in result.stdout.split('\n'):
                        if line.startswith('+'):
                            self.diff_log.write(f"[green]{line}[/green]")
                        elif line.startswith('-'):
                            self.diff_log.write(f"[red]{line}[/red]")
                        elif line.startswith('@@'):
                            self.diff_log.write(f"[cyan]{line}[/cyan]")
                        elif line.startswith('diff --git'):
                            self.diff_log.write(f"[yellow bold]{line}[/yellow bold]")
                        else:
                            self.diff_log.write(line)
                else:
                    self.diff_log.write(f"[dim]No changes in: {work_path}[/dim]")
                    self.diff_log.write(f"[dim]Session: {session_id}[/dim]")
            else:
                self.diff_log.write(f"[red]Git error: {result.stderr}[/red]")

        except Exception as e:
            self.diff_log.write(f"[red]Error: {str(e)}[/red]")

class ModelMonitorTab(VerticalScroll):
    """Tab for monitoring model activity"""

    def compose(self) -> ComposeResult:
        self.monitor_log = RichLog(highlight=True, markup=True)
        yield self.monitor_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        app = self.app
        if hasattr(app, 'work_path'):
            self.set_interval(2.0, self.refresh_monitor)
            self.refresh_monitor()

    def refresh_monitor(self) -> None:
        """Read and display monitor.md file"""
        app = self.app
        work_path = getattr(app, 'work_path', None)

        if not work_path:
            self.monitor_log.write("[red]ERROR: No work_path set[/red]")
            return

        monitor_file = Path(work_path) / "monitor.md"

        try:
            if monitor_file.exists():
                # Clear and display the monitor file content
                self.monitor_log.clear()
                content = monitor_file.read_text()

                # Display with markdown-like formatting
                for line in content.split('\n'):
                    if line.startswith('# '):
                        self.monitor_log.write(f"[bold cyan]{line}[/bold cyan]")
                    elif line.startswith('## '):
                        self.monitor_log.write(f"[bold green]{line}[/bold green]")
                    elif line.startswith('- '):
                        self.monitor_log.write(f"[yellow]{line}[/yellow]")
                    elif 'ERROR' in line or 'WARNING' in line:
                        self.monitor_log.write(f"[red]{line}[/red]")
                    elif 'SUCCESS' in line or 'OK' in line:
                        self.monitor_log.write(f"[green]{line}[/green]")
                    else:
                        self.monitor_log.write(line)
            else:
                self.monitor_log.clear()
                self.monitor_log.write("[dim]No monitor.md file found in worktree[/dim]")
                self.monitor_log.write(f"[dim]Looking in: {monitor_file}[/dim]")
        except Exception as e:
            self.monitor_log.write(f"[red]Error reading monitor file: {str(e)}[/red]")


class MonitorApp(App):
    """Main monitor application"""

    CSS = """
    Screen {
        background: #000000;
    }

    #header {
        height: 1;
        padding: 0 1;
        background: #000000;
        color: #C0FFFD;  /* Teal accent - Fulcrum */
        border-bottom: solid #6C71C4;  /* Purple accent - Fulcrum */
    }

    TabbedContent {
        background: #000000;
        height: 1fr;
    }

    Tabs {
        background: #000000;
        color: #C0FFFD;
        height: 3;
        padding: 0;
    }

    Tab {
        padding: 1 2;
        color: #666666;
        background: #000000;
    }

    Tab.-active {
        color: #C0FFFD;
        text-style: bold;
        background: #000000;
        border-bottom: tall #6C71C4;
    }

    Tab:hover {
        color: #C0FFFD;
        background: #111111;
    }

    TabPane {
        background: #000000;
        padding: 1;
        height: 1fr;
    }

    DiffTab {
        height: 100%;
        background: #000000;
    }

    ModelMonitorTab {
        height: 100%;
        background: #000000;
        padding: 1;
    }

    TextLog {
        background: #000000;
        color: #ffffff;
        height: 100%;
        scrollbar-background: #111111;
        scrollbar-color: #6C71C4;
    }

    Label {
        color: #C0FFFD;
    }
    """

    def __init__(self, session_id: str, work_path: str):
        super().__init__()
        self.session_id = session_id
        self.work_path = work_path

    def compose(self) -> ComposeResult:
        # Minimal header - just session name
        yield Container(
            Label(f"{self.session_id}"),
            id="header"
        )

        # Tabbed content with Diff and Model Monitor
        with TabbedContent(initial="diff-tab"):
            with TabPane("Diff", id="diff-tab"):
                yield DiffTab()
            with TabPane("Model Monitor", id="model-tab"):
                yield ModelMonitorTab()

    def on_mount(self) -> None:
        """Set up refresh timer"""
        # No need for constant header updates - keep it minimal
        pass


def main():
    """Entry point for cerb-monitor command"""
    parser = argparse.ArgumentParser(description="Monitor for Cerb sessions")
    parser.add_argument("--session", required=True, help="Session ID to monitor")
    parser.add_argument("--path", required=True, help="Path to session worktree")

    args = parser.parse_args()

    # Verify the path exists
    if not Path(args.path).exists():
        print(f"Error: Path does not exist: {args.path}")
        return

    app = MonitorApp(session_id=args.session, work_path=args.path)
    app.run()


if __name__ == "__main__":
    main()
