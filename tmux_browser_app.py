from __future__ import annotations
import os, shutil, subprocess
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Static, ListView, ListItem, Label
from textual_terminal import Terminal  # pip install textual textual-terminal

from textual.widgets import ListView, ListItem, Label

SIDEBAR_WIDTH = 34  # columns

@dataclass
class PaneRef:
    session: str
    win_idx: str
    pane_idx: str
    title: str
    @property
    def window_target(self) -> str:
        return f"{self.session}:{self.win_idx}"
    @property
    def pane_target(self) -> str:
        return f"{self.session}:{self.win_idx}.{self.pane_idx}"

def tmux_env():
    return dict(os.environ, TERM="xterm-256color")

def tmux(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["tmux", *args],
        env=tmux_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

def list_all_panes() -> list[PaneRef]:
    fmt = "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_title}"
    cp = tmux(["list-panes", "-a", "-F", fmt])
    panes: list[PaneRef] = []
    if cp.returncode == 0:
        for line in cp.stdout.splitlines():
            s, w, p, t = (line.split("\t", 3) + [""])[:4]
            panes.append(PaneRef(s, w, p, t or ""))
    return panes

def attach_command(target_window: str) -> str:
    # Attach the embedded client to a specific window; create session if missing
    return (
        f"/usr/bin/env bash -lc "
        f"\"exec env TERM=xterm-256color tmux attach -t {target_window} "
        f"|| tmux new -s {target_window.split(':',1)[0]}\""
    )

class HUD(Static):
    can_focus = False

class TmuxPanePicker(App):
    CSS = f"""
    Screen {{
        layout: horizontal;
    }}
    #sidebar {{
        width: {SIDEBAR_WIDTH};
        border: tall $panel;
        background: $panel;     /* opaque so nothing shows through */
    }}
    #main {{
        layout: vertical;
    }}
    #hud {{
        height: 3;
        padding: 0 1;
        background: $panel 60%;
    }}
    #term {{
        height: 1fr;            /* fill remaining space */
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+b", "focus_sidebar", "Focus Sidebar", priority=True),
        Binding("ctrl+l", "focus_terminal", "Focus Terminal", priority=True),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
    ]

    def compose(self) -> ComposeResult:
        if not shutil.which("tmux"):
            yield Static("tmux not found. Install tmux first (apt/brew).", id="error")
            return
        self.sidebar = ListView(id="sidebar")
        self.hud  = HUD("HUD: ⌃B focus list • ⌃L focus term • Enter selects pane • r refresh • ⌃Q quit • tip: set -g mouse on", id="hud")
        # Start attached to *something* (your default client state); we’ll retarget on selection
        self.term = Terminal(
            command="/usr/bin/env bash -lc 'exec env TERM=xterm-256color tmux attach || tmux new -s textual'",
            id="term"
        )
        yield self.sidebar
        yield Container(self.hud, self.term, id="main")

    async def on_ready(self) -> None:
        # Start the terminal process after the app is ready
        if hasattr(self, "term"):
            self.term.start()
            self.set_focus(self.term)
            self.capture_mouse(self.term)
        await self.action_refresh()

    # ---- sidebar actions ----
    async def action_refresh(self) -> None:
        self.sidebar.clear()
        panes = list_all_panes()
        if not panes:
            self.sidebar.append(ListItem(Label("No panes found.")))
            return
        for p in panes:
            text = f"{p.session}:{p.win_idx}.{p.pane_idx}  {p.title}"
            item = ListItem(Label(text))
            item.data = p
            self.sidebar.append(item)

    def action_focus_sidebar(self) -> None:
        self.set_focus(self.sidebar)

    def action_focus_terminal(self) -> None:
        self.set_focus(self.term)
        self.capture_mouse(self.term)

    def action_cursor_up(self) -> None:
        if self.focused is self.sidebar:
            self.sidebar.cursor_up()

    def action_cursor_down(self) -> None:
        if self.focused is self.sidebar:
            self.sidebar.cursor_down()

    def action_choose(self) -> None:
        if self.focused is self.sidebar and self.sidebar.index is not None:
            item = self.sidebar.get_child_at_index(self.sidebar.index)
            pane: PaneRef | None = getattr(item, "data", None)
            if pane:
                self._show_one_pane(pane)

    # ---- core: show exactly ONE pane ----
    def _show_one_pane(self, pane: PaneRef) -> None:
        # 1) Reattach the embedded client to the window that contains this pane
        new_cmd = attach_command(pane.window_target)
        try:
            self.term.stop()  # ignore if already stopped
        except Exception:
            pass
        self.term.command = new_cmd
        self.term.start()

        # 2) Inside that window, select the pane and zoom so only it’s visible
        tmux(["select-window", "-t", pane.window_target])
        tmux(["select-pane", "-t", pane.pane_target])
        tmux(["resize-pane", "-Z"])   # ensure zoomed (one pane only)

        # 3) Keep focus/input in the terminal
        self.set_focus(self.term)
        self.capture_mouse(self.term)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item: ListItem = event.item
        pane = getattr(item, "data", None)
        if pane:
            self._show_one_pane(pane)

if __name__ == "__main__":
    os.environ.setdefault("TERM", "xterm-256color")
    TmuxPanePicker().run()

