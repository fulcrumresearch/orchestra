"""Diff tab widget for displaying git diffs"""

import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog
from rich.markup import escape


class DiffTab(Container):
    """Container for displaying git diff output."""

    def compose(self) -> ComposeResult:
        self.diff_log = RichLog(
            highlight=True,
            markup=True,
            auto_scroll=False,
            wrap=True,
            min_width=0,  # Don't enforce minimum width
        )
        yield self.diff_log

    def on_mount(self) -> None:
        """Start refreshing when mounted"""
        self.set_interval(2.0, self.refresh_diff)
        self.refresh_diff()

    def refresh_diff(self) -> None:
        """Fetch and display the latest diff"""
        app = self.app

        # Get current session from app state
        if not hasattr(app, "state"):
            self.diff_log.clear()
            self.diff_log.write("[dim]No state available[/dim]", expand=True)
            return

        current_session = app.state.get_active_session()
        if not current_session:
            self.diff_log.clear()
            self.diff_log.write("[dim]No session selected[/dim]", expand=True)
            return

        work_path = current_session.work_path
        session_id = current_session.session_id

        if not work_path:
            self.diff_log.write("[dim]Session has no work path[/dim]", expand=True)
            return

        try:
            # Get git diff
            result = subprocess.run(["git", "diff", "HEAD"], cwd=work_path, capture_output=True, text=True)

            if result.returncode == 0:
                # Clear previous content
                self.diff_log.clear()

                if result.stdout:
                    # Write diff line by line for better scrolling
                    for line in result.stdout.split("\n"):
                        escaped_line = escape(line)
                        if line.startswith("+"):
                            self.diff_log.write(
                                f"[green]{escaped_line}[/green]",
                                expand=True,
                            )
                        elif line.startswith("-"):
                            self.diff_log.write(f"[red]{escaped_line}[/red]", expand=True)
                        elif line.startswith("@@"):
                            self.diff_log.write(
                                f"[cyan]{escaped_line}[/cyan]",
                                expand=True,
                            )
                        elif line.startswith("diff --git"):
                            self.diff_log.write(
                                f"[yellow bold]{escaped_line}[/yellow bold]",
                                expand=True,
                            )
                        else:
                            self.diff_log.write(escaped_line, expand=True)
                else:
                    self.diff_log.write(
                        f"[dim]No changes in: {work_path}[/dim]",
                        expand=True,
                    )
                    self.diff_log.write(f"[dim]Session: {session_id}[/dim]", expand=True)
            else:
                self.diff_log.write(f"[red]Git error: {escape(result.stderr)}[/red]", expand=True)

        except Exception as e:
            self.diff_log.write(f"[red]Error: {escape(str(e))}[/red]", expand=True)
