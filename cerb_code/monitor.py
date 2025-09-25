#!/usr/bin/env python3
"""Monitor UI for displaying session diffs and activity"""
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Static, Label, TabbedContent, TabPane, RichLog
from textual.containers import Container
from textual.binding import Binding
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.text import Text

class DiffTab(Container):
    """Container for diff display"""

    def compose(self) -> ComposeResult:
        self.diff_log = RichLog(highlight=True, markup=True, auto_scroll=False)
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

class ModelMonitorTab(Container):
    """Tab for monitoring model activity"""

    def compose(self) -> ComposeResult:
        yield Static("[dim]Model monitoring coming soon...[/dim]", id="model-placeholder")


class MonitorApp(App):
    """Main monitor application"""

    BINDINGS = [
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("page_up", "page_up", "Page Up", show=False),
        Binding("page_down", "page_down", "Page Down", show=False),
        Binding("home", "scroll_home", "Home", show=False),
        Binding("end", "scroll_end", "End", show=False),
    ]

    CSS = """
    Screen {
        background: #0a0a0a;
    }

    #header {
        height: 1;
        padding: 0 1;
        background: #0a0a0a;
        color: #00ff9f;
        text-style: bold;
        border-bottom: solid #333333;
    }

    TabbedContent {
        background: transparent;
        height: 1fr;
    }

    Tab.-active {
        color: #00ff9f;
        background: transparent !important;
    }

    TabPane {
        background: #0a0a0a;
        padding: 1;
        height: 1fr;
    }

    DiffTab {
        height: 100%;
        background: transparent;
    }

    ModelMonitorTab {
        height: 100%;
        background: transparent;
        padding: 1;
    }

    DiffTab RichLog {
        height: 100%;
        scrollbar-size: 1 1;
    }

    RichLog {
        background: #0a0a0a;
        color: #cccccc;
        height: 100%;
    }

    Label {
        color: #00ff9f;
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

    def action_scroll_up(self) -> None:
        """Scroll up in the current tab"""
        self.query_one(RichLog).action_scroll_up()

    def action_scroll_down(self) -> None:
        """Scroll down in the current tab"""
        self.query_one(RichLog).action_scroll_down()

    def action_page_up(self) -> None:
        """Page up in the current tab"""
        self.query_one(RichLog).action_page_up()

    def action_page_down(self) -> None:
        """Page down in the current tab"""
        self.query_one(RichLog).action_page_down()

    def action_scroll_home(self) -> None:
        """Scroll to top in the current tab"""
        self.query_one(RichLog).action_scroll_home()

    def action_scroll_end(self) -> None:
        """Scroll to bottom in the current tab"""
        self.query_one(RichLog).action_scroll_end()


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