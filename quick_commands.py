#!/usr/bin/env python3
"""Quick commands popup - select and edit with prompt_toolkit."""

import json
import subprocess
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout, Window, HSplit, VSplit
from prompt_toolkit.layout.containers import FormattedTextControl
from prompt_toolkit.widgets import Frame, TextArea
from prompt_toolkit.key_binding import KeyBindings

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


def main():
    commands = load_quick_commands()
    text_areas = []

    for cmd in commands:
        ta = TextArea(text=cmd, multiline=False, scrollbar=False, focus_on_click=True)
        text_areas.append(ta)

    # Build layout
    rows = []
    for i, ta in enumerate(text_areas):
        num = (i + 1) % 10
        row = VSplit([
            Window(FormattedTextControl(lambda n=num: f" {n} "), width=3),
            ta,
        ])
        rows.append(row)

    root_container = Frame(
        body=HSplit(rows + [
            Window(height=1),
            Window(FormattedTextControl(lambda: "Tab: Next  |  Ctrl+J: Send  |  Esc: Cancel")),
        ]),
        title="⚡ Quick Commands",
    )

    app = Application(layout=Layout(root_container), enable_page_navigation_bindings=True)
    kb = KeyBindings()

    @kb.add('c-j')
    def _(event):
        if app.current_buffer:
            cmd = app.current_buffer.text
            subprocess.run(["tmux", "send-keys", "-t", ":1", "-l", cmd], capture_output=True)
            subprocess.run(["tmux", "send-keys", "-t", ":1", "Enter"], capture_output=True)
        event.app.exit()

    @kb.add('tab')
    def _(event):
        event.app.layout.focus_next()

    @kb.add('s-tab')
    def _(event):
        event.app.layout.focus_previous()

    @kb.add('escape')
    @kb.add('c-c')
    def _(event):
        event.app.exit()

    app.key_bindings = kb
    if text_areas:
        app.layout.focus(text_areas[0])

    app.run()


if __name__ == "__main__":
    main()
