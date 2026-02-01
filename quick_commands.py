#!/usr/bin/env python3
"""Quick commands popup - predefined commands sent to F1 terminal."""

import json
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, Label, ListView, ListItem
from textual.containers import Vertical
from textual.binding import Binding

from config_panel import get_textual_theme, get_theme_colors

SCRIPT_DIR = Path(__file__).parent
QUICK_COMMANDS_FILE = SCRIPT_DIR / ".tui_quick_commands.json"

DEFAULT_QUICK_COMMANDS = [
    "commit all changes and push",
    "pull and merge from remote",
    "Explain how this feature works in the UI",
    "Reflect on the md files and restructure them clean",
    "Review the last changes and suggest improvements",
    "Summarize what was done in this session",
    "Find bugs and potential issues in the recent code",
    "Write a clear commit message for the current changes",
    "Refactor this for readability and simplicity",
    "Explain this error and how to fix it",
]


def load_quick_commands():
    """Load quick commands from config file, or return defaults."""
    if QUICK_COMMANDS_FILE.exists():
        try:
            with open(QUICK_COMMANDS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_QUICK_COMMANDS


class QuickCommandsApp(App):
    """Full-screen quick commands selector."""

    BINDINGS = [
        Binding("escape", "quit", "Quit", priority=True),
        Binding("q", "quit", "Quit", priority=True),
        Binding("1", "select_1", show=False, priority=True),
        Binding("2", "select_2", show=False, priority=True),
        Binding("3", "select_3", show=False, priority=True),
        Binding("4", "select_4", show=False, priority=True),
        Binding("5", "select_5", show=False, priority=True),
        Binding("6", "select_6", show=False, priority=True),
        Binding("7", "select_7", show=False, priority=True),
        Binding("8", "select_8", show=False, priority=True),
        Binding("9", "select_9", show=False, priority=True),
        Binding("0", "select_10", show=False, priority=True),
        Binding("enter", "select_focused", "Select", priority=True),
    ]

    def __init__(self):
        theme_colors = get_theme_colors()
        bg = theme_colors['bg']
        fg = theme_colors['fg']
        self.CSS = f"""
        Screen {{
            background: {bg};
            color: {fg};
        }}
        #qc-container {{
            width: 100%;
            height: 100%;
            background: {bg};
            color: {fg};
            padding: 0 1;
        }}
        #qc-title {{
            text-align: center;
            text-style: bold;
            padding: 1 0;
            background: {bg};
            color: {fg};
        }}
        #qc-list {{
            height: 1fr;
            background: {bg};
            color: {fg};
        }}
        #qc-list > ListItem {{
            background: {bg};
            color: {fg};
            height: 3;
            padding: 1 2;
        }}
        #qc-list > ListItem:hover {{
            background: {fg} 20%;
        }}
        #qc-list:focus > .list-view--highlight {{
            background: {fg} 30%;
        }}
        #qc-hint {{
            text-align: center;
            text-opacity: 60%;
            padding: 1 0;
            background: {bg};
            color: {fg};
        }}
        Label {{
            background: {bg};
            color: {fg};
        }}
        Static {{
            background: {bg};
            color: {fg};
        }}
        Vertical {{
            background: {bg};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        self.commands = load_quick_commands()

    def compose(self) -> ComposeResult:
        with Vertical(id="qc-container"):
            yield Label("⚡ Quick Commands", id="qc-title")
            items = []
            for i, cmd in enumerate(self.commands):
                num = (i + 1) % 10
                items.append(
                    ListItem(Label(f" {num}   {cmd}"), id=f"qc-{i}")
                )
            yield ListView(*items, id="qc-list")
            yield Static("1-0: Select  |  Enter: Confirm  |  Esc/q: Cancel", id="qc-hint")

    def on_mount(self):
        self.query_one("#qc-list").focus()

    def _send_command(self, idx: int) -> None:
        if 0 <= idx < len(self.commands):
            cmd = self.commands[idx]
            subprocess.run(["tmux", "send-keys", "-t", ":1", "-l", cmd], capture_output=True)
            subprocess.run(["tmux", "send-keys", "-t", ":1", "Enter"], capture_output=True)
            self.exit()

    def action_quit(self):
        self.exit()

    def action_select_focused(self):
        lv = self.query_one("#qc-list", ListView)
        if lv.index is not None:
            self._send_command(lv.index)

    def action_select_1(self):
        self._send_command(0)

    def action_select_2(self):
        self._send_command(1)

    def action_select_3(self):
        self._send_command(2)

    def action_select_4(self):
        self._send_command(3)

    def action_select_5(self):
        self._send_command(4)

    def action_select_6(self):
        self._send_command(5)

    def action_select_7(self):
        self._send_command(6)

    def action_select_8(self):
        self._send_command(7)

    def action_select_9(self):
        self._send_command(8)

    def action_select_10(self):
        self._send_command(9)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        lv = self.query_one("#qc-list", ListView)
        if lv.index is not None:
            self._send_command(lv.index)


def main():
    app = QuickCommandsApp()
    app.run()


if __name__ == "__main__":
    main()
