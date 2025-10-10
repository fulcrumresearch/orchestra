"""Help modal screen for Orchestra UI"""

from textual.screen import ModalScreen
from textual.widgets import Static
from textual.containers import Container, VerticalScroll
from textual.binding import Binding


class HelpScreen(ModalScreen):
    """Modal help screen displaying keyboard shortcuts and usage information."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("q", "dismiss", "Close", show=False),
        Binding("?", "dismiss", "Close", show=False),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-dialog {
        width: 80;
        height: 30;
        background: #1a1a1a;
        border: thick #00ff9f;
        padding: 0;
    }

    #help-title {
        width: 100%;
        background: #00ff9f;
        color: #000000;
        text-align: center;
        padding: 1;
        text-style: bold;
    }

    #help-content {
        width: 100%;
        height: 1fr;
        padding: 1 2;
        background: #1a1a1a;
    }

    .help-section {
        margin-bottom: 1;
    }

    .help-heading {
        color: #00ff9f;
        text-style: bold;
        margin-bottom: 0;
    }

    .help-item {
        color: #cccccc;
    }

    .help-key {
        color: #00d4ff;
        text-style: bold;
    }

    .help-footer {
        width: 100%;
        background: #111111;
        color: #888888;
        text-align: center;
        padding: 1;
        text-style: italic;
    }
    """

    def compose(self):
        """Create the help dialog layout."""
        with Container(id="help-dialog"):
            yield Static("Orchestra Help", id="help-title")

            with VerticalScroll(id="help-content"):
                yield Static(
                    "[bold #00ff9f]Session Management[/bold #00ff9f]",
                    classes="help-section help-heading",
                )
                yield Static(
                    "[bold #00d4ff]Enter[/bold #00d4ff]      Select and attach to highlighted session\n"
                    "[bold #00d4ff]↑ / ↓[/bold #00d4ff]      Navigate session list\n"
                    "[bold #00d4ff]Ctrl+R[/bold #00d4ff]     Refresh session list\n"
                    "[bold #00d4ff]Ctrl+D[/bold #00d4ff]     Delete selected session (cannot delete designer)",
                    classes="help-section help-item",
                )

                yield Static(
                    "[bold #00ff9f]Session Actions[/bold #00ff9f]",
                    classes="help-section help-heading",
                )
                yield Static(
                    "[bold #00d4ff]P[/bold #00d4ff]          Toggle pairing mode for current session\n"
                    "[bold #00d4ff]S[/bold #00d4ff]          Open designer.md spec file in vim\n"
                    "[bold #00d4ff]T[/bold #00d4ff]          Open terminal in session's worktree",
                    classes="help-section help-item",
                )

                yield Static(
                    "[bold #00ff9f]Tab Navigation[/bold #00ff9f]",
                    classes="help-section help-heading",
                )
                yield Static(
                    "[bold #00d4ff]← / →[/bold #00d4ff]      Switch between Diff and Monitor tabs\n"
                    "[bold #00d4ff]H / L[/bold #00d4ff]      Switch between Diff and Monitor tabs (vim-style)\n"
                    "[bold #00d4ff]J / K[/bold #00d4ff]      Scroll down/up in active tab",
                    classes="help-section help-item",
                )

                yield Static(
                    "[bold #00ff9f]Application[/bold #00ff9f]",
                    classes="help-section help-heading",
                )
                yield Static(
                    "[bold #00d4ff]?[/bold #00d4ff]          Show this help screen\n"
                    "[bold #00d4ff]Ctrl+Q[/bold #00d4ff]     Quit Orchestra",
                    classes="help-section help-item",
                )

                yield Static(
                    "[bold #00ff9f]About[/bold #00ff9f]",
                    classes="help-section help-heading",
                )
                yield Static(
                    "Orchestra is a tmux-based AI agent orchestration system.\n"
                    "Designer sessions manage high-level tasks and spawn executor\n"
                    "sessions for specific work. Use pairing mode to collaborate\n"
                    "with agents in real-time.",
                    classes="help-section help-item",
                )

            yield Static("Press Esc, Q, or ? to close", classes="help-footer")

    def action_dismiss(self):
        """Close the help modal."""
        self.dismiss()
