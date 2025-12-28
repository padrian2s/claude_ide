#!/usr/bin/env python3
"""Configuration panel for TUI Environment."""

import json
import subprocess
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, Header, ListView, ListItem, Label
from textual.containers import Vertical, Horizontal
from textual.binding import Binding

CONFIG_FILE = Path(__file__).parent / ".tui_config.json"

THEMES = {
    "Catppuccin Mocha": {"bg": "#1e1e2e", "fg": "#cdd6f4"},
    "Tokyo Night": {"bg": "#24283b", "fg": "#c0caf5"},
    "Gruvbox Dark": {"bg": "#1d2021", "fg": "#ebdbb2"},
    "Dracula": {"bg": "#282a36", "fg": "#f8f8f2"},
    "Nord": {"bg": "#2e3440", "fg": "#eceff4"},
    "One Dark": {"bg": "#282c34", "fg": "#abb2bf"},
    "Solarized Dark": {"bg": "#002b36", "fg": "#839496"},
    "Monokai": {"bg": "#272822", "fg": "#f8f8f2"},
}


def load_config() -> dict:
    """Load config from file."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"theme": "Gruvbox Dark"}


def save_config(config: dict):
    """Save config to file."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_theme_colors() -> dict:
    """Get current theme colors."""
    config = load_config()
    theme_name = config.get("theme", "Gruvbox Dark")
    return THEMES.get(theme_name, THEMES["Gruvbox Dark"])


def apply_theme_to_tmux(theme_name: str):
    """Apply theme to current tmux session."""
    colors = THEMES.get(theme_name, THEMES["Catppuccin Mocha"])
    # Find current session
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    session = result.stdout.strip()
    if session:
        subprocess.run([
            "tmux", "set-option", "-t", session,
            "status-style", f"bg={colors['bg']},fg={colors['fg']}"
        ])


class ThemeItem(ListItem):
    """A theme list item."""

    def __init__(self, name: str, theme_colors: dict, is_active: bool = False):
        super().__init__()
        self.theme_name = name
        self.theme_colors = theme_colors
        self.is_active = is_active

    def compose(self) -> ComposeResult:
        marker = ">" if self.is_active else " "
        preview = f"[on {self.theme_colors['bg']}][{self.theme_colors['fg']}]  Sample  [/][/]"
        yield Label(f"{marker} {self.theme_name:20} {preview}")


class ConfigPanel(App):
    """Configuration panel app."""

    CSS = """
    #main {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #title {
        text-align: center;
        text-style: bold;
        padding: 1;
    }
    #help {
        text-align: center;
        color: $text-muted;
        padding: 1;
    }
    ListView {
        height: auto;
        max-height: 80%;
        border: solid $primary;
        padding: 1;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:hover {
        background: $surface-lighten-1;
    }
    ListView:focus > ListItem.--highlight {
        background: $primary;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.selected_theme = self.config.get("theme", "Catppuccin Mocha")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="main"):
            yield Static("Status Bar Theme", id="title")
            yield ListView(
                *[
                    ThemeItem(name, theme_colors, name == self.selected_theme)
                    for name, theme_colors in THEMES.items()
                ],
                id="theme-list"
            )
            yield Static("Enter: Apply  |  q: Quit", id="help")

    def on_mount(self):
        self.title = "Config"
        self.sub_title = "Select theme and press Enter"
        # Focus the list and highlight current theme
        list_view = self.query_one("#theme-list", ListView)
        list_view.focus()
        # Find and highlight current theme
        for i, (name, _) in enumerate(THEMES.items()):
            if name == self.selected_theme:
                list_view.index = i
                break

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle theme selection on Enter."""
        item = event.item
        if isinstance(item, ThemeItem):
            self.selected_theme = item.theme_name
            self.config["theme"] = self.selected_theme
            save_config(self.config)
            apply_theme_to_tmux(self.selected_theme)
            self.notify(f"Applied: {self.selected_theme}", timeout=2)
            # Refresh list to update selection marker
            self.refresh_list()

    def refresh_list(self):
        """Refresh the theme list."""
        list_view = self.query_one("#theme-list", ListView)
        current_index = list_view.index
        list_view.clear()
        for name, theme_colors in THEMES.items():
            list_view.append(ThemeItem(name, theme_colors, name == self.selected_theme))
        list_view.index = current_index


if __name__ == "__main__":
    ConfigPanel().run()
