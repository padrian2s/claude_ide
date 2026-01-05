#!/usr/bin/env python3
"""Configuration panel for TUI Environment."""

import json
import subprocess
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, Header, ListView, ListItem, Label, TextArea
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.binding import Binding
from textual.screen import ModalScreen
from textual import work

from ai_customizer import (
    SCREEN_CONFIGS,
    CodeBackup,
    CodeValidator,
    AICodeModifier,
    ScreenReloader,
    create_diff,
    get_api_key,
    get_screen_path,
    get_window_index_by_name,
)
from upgrader import get_current_version

CONFIG_FILE = Path(__file__).parent / ".tui_config.json"

THEMES = {
    # Dark themes
    "Catppuccin Mocha": {"bg": "#1e1e2e", "fg": "#cdd6f4", "dark": True, "textual": "catppuccin-mocha"},
    "Tokyo Night": {"bg": "#24283b", "fg": "#c0caf5", "dark": True, "textual": "tokyo-night"},
    "Gruvbox Dark": {"bg": "#1d2021", "fg": "#ebdbb2", "dark": True, "textual": "gruvbox"},
    "Dracula": {"bg": "#282a36", "fg": "#f8f8f2", "dark": True, "textual": "dracula"},
    "Nord": {"bg": "#2e3440", "fg": "#eceff4", "dark": True, "textual": "nord"},
    "One Dark": {"bg": "#282c34", "fg": "#abb2bf", "dark": True, "textual": "monokai"},
    "Solarized Dark": {"bg": "#002b36", "fg": "#839496", "dark": True, "textual": "solarized-light"},
    "Monokai": {"bg": "#272822", "fg": "#f8f8f2", "dark": True, "textual": "monokai"},
    # Light themes
    "Solarized Light": {"bg": "#fdf6e3", "fg": "#657b83", "dark": False, "textual": "solarized-light"},
    "Gruvbox Light": {"bg": "#fbf1c7", "fg": "#3c3836", "dark": False, "textual": "gruvbox"},
    "GitHub Light": {"bg": "#ffffff", "fg": "#24292e", "dark": False, "textual": "textual-light"},
    "Catppuccin Latte": {"bg": "#eff1f5", "fg": "#4c4f69", "dark": False, "textual": "catppuccin-latte"},
}

# Available Textual border styles
BORDER_STYLES = [
    "solid", "double", "round", "heavy", "thick", "tall", "wide",
    "dashed", "ascii", "panel", "outer", "inner", "hkey", "vkey",
    "blank", "hidden", "none",
]


def load_config() -> dict:
    """Load config from file."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {"theme": "Gruvbox Dark", "status_position": "top", "border_style": "solid"}


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
        # Apply status bar colors
        subprocess.run([
            "tmux", "set-option", "-t", session,
            "status-style", f"bg={colors['bg']},fg={colors['fg']}"
        ])
        # Update theme variables for new terminals (Ctrl+T)
        subprocess.run([
            "tmux", "set-option", "-t", session,
            "@theme_bg", colors['bg']
        ])
        subprocess.run([
            "tmux", "set-option", "-t", session,
            "@theme_fg", colors['fg']
        ])
        # Apply background and foreground to F1 terminal window (window 1)
        subprocess.run([
            "tmux", "set-option", "-t", f"{session}:1",
            "window-style", f"bg={colors['bg']},fg={colors['fg']}"
        ])
        subprocess.run([
            "tmux", "set-option", "-t", f"{session}:1",
            "window-active-style", f"bg={colors['bg']},fg={colors['fg']}"
        ])
        # Apply to all dynamic terminal windows (2-19)
        for win_idx in range(2, 20):
            subprocess.run([
                "tmux", "set-option", "-t", f"{session}:{win_idx}",
                "window-style", f"bg={colors['bg']},fg={colors['fg']}"
            ], stderr=subprocess.DEVNULL)
            subprocess.run([
                "tmux", "set-option", "-t", f"{session}:{win_idx}",
                "window-active-style", f"bg={colors['bg']},fg={colors['fg']}"
            ], stderr=subprocess.DEVNULL)
        # Apply to F4 (Glow), F6 (Prompt), F7 (Git) windows
        for win_idx in [22, 24, 25]:
            subprocess.run([
                "tmux", "set-option", "-t", f"{session}:{win_idx}",
                "window-style", f"bg={colors['bg']},fg={colors['fg']}"
            ], stderr=subprocess.DEVNULL)
            subprocess.run([
                "tmux", "set-option", "-t", f"{session}:{win_idx}",
                "window-active-style", f"bg={colors['bg']},fg={colors['fg']}"
            ], stderr=subprocess.DEVNULL)


def apply_status_position(position: str):
    """Apply status bar position to current tmux session."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    session = result.stdout.strip()
    if session:
        subprocess.run([
            "tmux", "set-option", "-t", session,
            "status-position", position
        ])


def get_status_position() -> str:
    """Get current status position from config."""
    config = load_config()
    return config.get("status_position", "bottom")


def get_border_style() -> str:
    """Get current border style from config."""
    config = load_config()
    return config.get("border_style", "solid")


def get_textual_theme() -> str:
    """Get Textual theme name based on saved config."""
    config = load_config()
    theme_name = config.get("theme", "Gruvbox Dark")
    theme_config = THEMES.get(theme_name, THEMES["Gruvbox Dark"])
    return theme_config.get("textual", "gruvbox")


import re
from collections import Counter

CLAUDE_HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"
LEARNED_WORDS_FILE = Path(__file__).parent / ".prompt_learned_words.txt"

# Common words to filter out
STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
    'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have', 'has', 'had',
    'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must',
    'shall', 'can', 'need', 'it', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
    'she', 'we', 'they', 'what', 'which', 'who', 'when', 'where', 'why', 'how', 'all',
    'each', 'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
    'not', 'only', 'same', 'so', 'than', 'too', 'very', 'just', 'also', 'now', 'here',
    'there', 'then', 'if', 'else', 'use', 'add', 'get', 'set', 'new', 'file', 'code',
    'make', 'like', 'want', 'see', 'look', 'using', 'used', 'first', 'last', 'next',
    'after', 'before', 'into', 'over', 'under', 'again', 'further', 'once', 'any',
    'me', 'my', 'your', 'its', 'our', 'their', 'up', 'down', 'out', 'off', 'about',
}


def import_claude_prompts() -> tuple[int, int, list[str]]:
    """Import prompts from Claude Code history and extract NEW learned words.
    
    Only saves words that are not already in the learned words file.
    Words are shuffled randomly to prevent reverse engineering of prompts.
    
    Returns:
        Tuple of (prompts_count, new_words_count, sample_words)
    """
    import random
    
    if not CLAUDE_HISTORY_FILE.exists():
        return 0, 0, []
    
    # Load existing words first
    existing_words = set()
    if LEARNED_WORDS_FILE.exists():
        try:
            with open(LEARNED_WORDS_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word:
                        existing_words.add(word.lower())
        except Exception:
            pass
    
    prompts = []
    try:
        with open(CLAUDE_HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if 'display' in obj:
                        prompts.append(obj['display'])
                except json.JSONDecodeError:
                    continue
    except Exception:
        return 0, 0, []
    
    if not prompts:
        return 0, 0, []
    
    # Extract ALL unique words from all prompts (min 3 chars, not stop words)
    all_words = set()
    for prompt in prompts:
        # Extract words (alphanumeric, underscores, hyphens, Unicode support)
        words = re.findall(r'\b\w{3,}\b', prompt.lower(), re.UNICODE)
        for word in words:
            if word not in STOP_WORDS and not word.isdigit():
                all_words.add(word)
    
    # Filter to only NEW words (not in existing file)
    new_words = all_words - existing_words
    
    if not new_words:
        return len(prompts), 0, []
    
    # Shuffle new words randomly (prevent reverse engineering)
    new_words_list = list(new_words)
    random.shuffle(new_words_list)
    
    # Append new words to existing file
    try:
        with open(LEARNED_WORDS_FILE, 'a', encoding='utf-8') as f:
            for word in new_words_list:
                f.write(f"{word}\n")
    except Exception:
        pass
    
    # Return stats with random sample
    sample = new_words_list[:10]
    return len(prompts), len(new_words_list), sample


class ConfirmDialog(ModalScreen):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmDialog { align: center middle; }
    #confirm-dialog { width: 40; height: 7; border: solid $error; background: $surface; padding: 1; }
    #confirm-title { text-align: center; text-style: bold; }
    #confirm-help { text-align: center; color: $text-muted; }
    """

    BINDINGS = [("escape", "cancel", "No"), ("y", "confirm", "Yes"), ("n", "cancel", "No")]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"{self.title_text}: {self.message}", id="confirm-title")
            yield Label("y:Yes  n:No", id="confirm-help")

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class ScreenItem(ListItem):
    """A screen list item for customization."""

    def __init__(self, name: str, script: str, description: str):
        super().__init__()
        self.screen_name = name
        self.script = script
        self.description = description

    def compose(self) -> ComposeResult:
        yield Label(f"  {self.screen_name}")
        yield Label(f"    [dim]{self.script}[/dim]")


class ScreenSelectorDialog(ModalScreen):
    """Dialog to select which screen to customize."""

    CSS = """
    ScreenSelectorDialog {
        align: center middle;
    }
    #screen-selector-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #screen-selector-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #screen-list {
        height: auto;
        max-height: 60%;
        border: solid $primary-darken-2;
        padding: 0;
    }
    #screen-list > ListItem {
        padding: 0;
    }
    #screen-help {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Select"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="screen-selector-dialog"):
            yield Label("Select Screen to Customize", id="screen-selector-title")
            yield ListView(
                *[
                    ScreenItem(name, cfg["script"], cfg["description"])
                    for name, cfg in SCREEN_CONFIGS.items()
                ],
                id="screen-list",
            )
            yield Label("Enter: Select  |  Esc: Cancel", id="screen-help")

    def on_mount(self):
        self.query_one("#screen-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, ScreenItem):
            self.dismiss(item.screen_name)

    def action_select(self):
        list_view = self.query_one("#screen-list", ListView)
        if list_view.highlighted_child:
            item = list_view.highlighted_child
            if isinstance(item, ScreenItem):
                self.dismiss(item.screen_name)

    def action_cancel(self):
        self.dismiss(None)


class PromptInputDialog(ModalScreen):
    """Dialog to enter customization prompt."""

    CSS = """
    PromptInputDialog {
        align: center middle;
    }
    #prompt-dialog {
        width: 80%;
        height: auto;
        max-height: 80%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #prompt-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #prompt-screen-info {
        color: $text-muted;
        padding-bottom: 1;
    }
    #prompt-input {
        height: 10;
        border: solid $primary-darken-2;
    }
    #prompt-examples {
        color: $text-muted;
        padding-top: 1;
    }
    #prompt-help {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "submit", "Submit"),
    ]

    def __init__(self, screen_name: str):
        super().__init__()
        self.screen_name = screen_name
        self.screen_config = SCREEN_CONFIGS.get(screen_name, {})

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-dialog"):
            yield Label("Describe Your Changes", id="prompt-title")
            yield Label(
                f"Screen: {self.screen_name} ({self.screen_config.get('script', '')})",
                id="prompt-screen-info",
            )
            yield TextArea(id="prompt-input")
            yield Label(
                "[dim]Examples:\n"
                "  - Change the background color to dark purple\n"
                "  - Add vim-style j/k navigation keys\n"
                "  - Make the font larger and use cyan for highlights[/dim]",
                id="prompt-examples",
            )
            yield Label("Ctrl+S: Submit  |  Esc: Cancel", id="prompt-help")

    def on_mount(self):
        self.query_one("#prompt-input", TextArea).focus()

    def action_submit(self):
        text_area = self.query_one("#prompt-input", TextArea)
        prompt = text_area.text.strip()
        if prompt:
            self.dismiss({"screen": self.screen_name, "prompt": prompt})
        else:
            self.notify("Please enter a prompt", severity="warning")

    def action_cancel(self):
        self.dismiss(None)


class PreviewDiffDialog(ModalScreen):
    """Dialog to preview diff and approve/reject changes."""

    CSS = """
    PreviewDiffDialog {
        align: center middle;
    }
    #preview-dialog {
        width: 90%;
        height: 90%;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #preview-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #preview-status {
        padding-bottom: 1;
    }
    #diff-scroll {
        height: 1fr;
        border: solid $primary-darken-2;
    }
    #diff-content {
        padding: 1;
    }
    #preview-warnings {
        color: $warning;
        padding-top: 1;
    }
    #preview-help {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("a", "apply", "Apply"),
        ("e", "edit", "Edit Prompt"),
    ]

    def __init__(
        self,
        screen_name: str,
        original_code: str,
        modified_code: str,
        diff_text: str,
        syntax_ok: bool,
        syntax_msg: str,
        warnings: list[str],
    ):
        super().__init__()
        self.screen_name = screen_name
        self.original_code = original_code
        self.modified_code = modified_code
        self.diff_text = diff_text
        self.syntax_ok = syntax_ok
        self.syntax_msg = syntax_msg
        self.warnings = warnings

    def compose(self) -> ComposeResult:
        status_color = "green" if self.syntax_ok else "red"
        status_text = f"[{status_color}]{self.syntax_msg}[/{status_color}]"

        with Vertical(id="preview-dialog"):
            yield Label(f"Preview Changes: {self.screen_name}", id="preview-title")
            yield Label(f"Status: {status_text}", id="preview-status")
            with VerticalScroll(id="diff-scroll"):
                # Show diff as plain text (no markup to avoid escape issues)
                yield Static(self.diff_text, id="diff-content", markup=False)
            if self.warnings:
                yield Label(
                    "[bold]Warnings:[/bold]\n" + "\n".join(f"  - {w}" for w in self.warnings),
                    id="preview-warnings",
                )
            yield Label(
                "a: Apply Changes  |  e: Edit Prompt  |  Esc: Cancel",
                id="preview-help",
            )

    def _format_diff(self, diff_text: str) -> str:
        """Format diff with colors for display."""
        from rich.markup import escape

        lines = []
        for line in diff_text.split("\n"):
            # Escape the line first to prevent markup interpretation
            escaped_line = escape(line)
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(f"[green]{escaped_line}[/green]")
            elif line.startswith("-") and not line.startswith("---"):
                lines.append(f"[red]{escaped_line}[/red]")
            elif line.startswith("@@"):
                lines.append(f"[cyan]{escaped_line}[/cyan]")
            else:
                lines.append(escaped_line)
        return "\n".join(lines)

    def on_mount(self):
        self.query_one("#diff-scroll").focus()

    def action_apply(self):
        if not self.syntax_ok:
            self.notify("Cannot apply: syntax errors detected", severity="error")
            return
        self.dismiss({"action": "apply", "code": self.modified_code})

    def action_edit(self):
        self.dismiss({"action": "edit"})

    def action_cancel(self):
        self.dismiss(None)


class LoadingDialog(ModalScreen):
    """Dialog showing AI generation progress with animated spinner."""

    CSS = """
    LoadingDialog {
        align: center middle;
    }
    #loading-dialog {
        width: 60;
        height: 12;
        border: solid $primary;
        background: $surface;
        padding: 1 2;
    }
    #loading-title {
        text-align: center;
        text-style: bold;
        padding-bottom: 1;
    }
    #loading-spinner {
        text-align: center;
        color: $primary;
        text-style: bold;
        padding: 1;
    }
    #loading-status {
        text-align: center;
        color: $text-muted;
    }
    #loading-hint {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    SPINNER_FRAMES = [
        "⠋ Analyzing code...",
        "⠙ Analyzing code...",
        "⠹ Understanding structure...",
        "⠸ Understanding structure...",
        "⠼ Generating modifications...",
        "⠴ Generating modifications...",
        "⠦ Applying AI magic...",
        "⠧ Applying AI magic...",
        "⠇ Almost there...",
        "⠏ Almost there...",
    ]

    def __init__(self, screen_name: str):
        super().__init__()
        self.screen_name = screen_name
        self._frame = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-dialog"):
            yield Label("AI Code Generation", id="loading-title")
            yield Label(self.SPINNER_FRAMES[0], id="loading-spinner")
            yield Label(f"Customizing: {self.screen_name}", id="loading-status")
            yield Label("[dim]This may take a few seconds...[/dim]", id="loading-hint")

    def on_mount(self):
        self._timer = self.set_interval(0.15, self._animate)

    def _animate(self):
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        spinner = self.query_one("#loading-spinner", Label)
        spinner.update(self.SPINNER_FRAMES[self._frame])

    def on_unmount(self):
        if self._timer:
            self._timer.stop()


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
    #version-info {
        text-align: center;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("p", "toggle_position", "Toggle Position"),
        Binding("b", "toggle_border", "Toggle Border"),
        Binding("c", "customize", "Customize Screen"),
        Binding("i", "import_prompts", "Import Words"),
        Binding("t", "command_palette", "Theme Palette"),
    ]

    def __init__(self):
        super().__init__()
        self.theme = get_textual_theme()
        self.config = load_config()
        self.selected_theme = self.config.get("theme", "Catppuccin Mocha")
        self.status_position = self.config.get("status_position", "bottom")
        self.border_style = self.config.get("border_style", "solid")
        # Customization state
        self._current_screen: str | None = None
        self._current_prompt: str | None = None
        self._original_code: str | None = None
        self._backup_path: Path | None = None
        self._loading_screen: LoadingDialog | None = None

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
            yield Static("", id="position-info")
            yield Static("", id="border-info")
            version = get_current_version() or "dev"
            yield Static(f"Version: {version}", id="version-info")
            yield Static("Enter: Apply | p: Position | b: Border | t: Palette | c: Customize | i: Import | q: Quit", id="help")

    def on_mount(self):
        self.title = "Config"
        self.sub_title = "Enter:apply  p:position  b:border  t:palette  q:quit"
        # Focus the list and highlight current theme
        list_view = self.query_one("#theme-list", ListView)
        list_view.focus()
        # Find and highlight current theme
        for i, (name, _) in enumerate(THEMES.items()):
            if name == self.selected_theme:
                list_view.index = i
                break
        self.update_position_info()
        self.update_border_info()

        # Cache the tmux session name for later use
        ScreenReloader.get_session_name()

    def update_position_info(self):
        """Update position info display."""
        pos_label = "TOP" if self.status_position == "top" else "BOTTOM"
        self.query_one("#position-info", Static).update(f"Status Bar Position: [{pos_label}]")

    def update_border_info(self):
        """Update border info display."""
        self.query_one("#border-info", Static).update(f"Border Style: [{self.border_style.upper()}]")

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle theme selection on Enter."""
        item = event.item
        if isinstance(item, ThemeItem):
            self.selected_theme = item.theme_name
            self.config["theme"] = self.selected_theme
            save_config(self.config)
            apply_theme_to_tmux(self.selected_theme)
            # Apply Textual theme
            theme_config = THEMES.get(self.selected_theme, {})
            textual_theme = theme_config.get("textual", "gruvbox")
            self.app.theme = textual_theme
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

    def action_toggle_position(self):
        """Toggle status bar position between top and bottom."""
        self.status_position = "top" if self.status_position == "bottom" else "bottom"
        self.config["status_position"] = self.status_position
        save_config(self.config)
        apply_status_position(self.status_position)
        self.update_position_info()
        self.notify(f"Status bar: {self.status_position.upper()}", timeout=1)

    def action_toggle_border(self):
        """Cycle through border styles."""
        current_idx = BORDER_STYLES.index(self.border_style) if self.border_style in BORDER_STYLES else 0
        next_idx = (current_idx + 1) % len(BORDER_STYLES)
        self.border_style = BORDER_STYLES[next_idx]
        self.config["border_style"] = self.border_style
        save_config(self.config)
        self.update_border_info()
        self.notify(f"Border: {self.border_style.upper()} (restart apps to apply)", timeout=2)

    def action_quit(self):
        """Quit with confirmation."""
        def handle_confirm(confirmed: bool):
            if confirmed:
                self.exit()
        self.push_screen(ConfirmDialog("Quit", "Exit application?"), handle_confirm)

    def action_customize(self):
        """Open screen customization dialog."""
        # Check for API key first
        api_key = get_api_key()
        if not api_key:
            self.notify(
                "No API key found. Set ANTHROPIC_API_KEY environment variable.",
                severity="error",
                timeout=5,
            )
            return
        self.push_screen(ScreenSelectorDialog(), self._on_screen_selected)


    def action_import_prompts(self):
        """Import prompts from Claude Code and extract NEW learned words."""
        if not CLAUDE_HISTORY_FILE.exists():
            self.notify(
                f"Claude history not found: {CLAUDE_HISTORY_FILE}",
                severity="error",
                timeout=4,
            )
            return
        
        prompts_count, new_words_count, sample_words = import_claude_prompts()
        
        if prompts_count == 0:
            self.notify("No prompts found in Claude history", severity="warning", timeout=3)
            return
        
        if new_words_count == 0:
            self.notify(f"Scanned {prompts_count} prompts - no new words to add", severity="information", timeout=3)
            return
        
        # Show success with sample of new words
        sample_str = ", ".join(sample_words[:5])
        self.notify(
            f"Added {new_words_count} new words from {prompts_count} prompts\nSample: {sample_str}...",
            severity="information",
            timeout=5,
        )

    def _on_screen_selected(self, screen_name: str | None):
        """Handle screen selection."""
        if screen_name is None:
            return
        self._current_screen = screen_name
        self.push_screen(PromptInputDialog(screen_name), self._on_prompt_entered)

    def _on_prompt_entered(self, result: dict | None):
        """Handle prompt entry."""
        if result is None:
            self._current_screen = None
            return

        self._current_prompt = result["prompt"]
        screen_name = result["screen"]

        # Read current code
        script_path = get_screen_path(screen_name)
        if not script_path or not script_path.exists():
            self.notify(f"Script not found: {script_path}", severity="error")
            return

        self._original_code = script_path.read_text()

        # Show loading dialog and start AI generation
        self._loading_screen = LoadingDialog(screen_name)
        self.push_screen(self._loading_screen)
        self._generate_modification(screen_name, self._current_prompt, self._original_code)

    @work(thread=True)
    def _generate_modification(self, screen_name: str, prompt: str, original_code: str):
        """Generate code modification using AI (runs in background thread)."""
        try:
            api_key = get_api_key()
            modifier = AICodeModifier(api_key)
            screen_config = SCREEN_CONFIGS.get(screen_name, {})
            context = f"{screen_name} - {screen_config.get('description', '')}"

            modified_code, _ = modifier.generate_modification(
                original_code, prompt, context
            )

            # Validate the generated code
            validator = CodeValidator()
            syntax_ok, syntax_msg = validator.validate_syntax(modified_code)
            warnings = validator.check_dangerous_patterns(modified_code)

            # Create diff
            script_name = screen_config.get("script", "code.py")
            diff_text = create_diff(original_code, modified_code, script_name)

            # Show preview dialog on main thread
            self.call_from_thread(
                self._show_preview,
                screen_name,
                original_code,
                modified_code,
                diff_text,
                syntax_ok,
                syntax_msg,
                warnings,
            )

        except Exception as e:
            self.call_from_thread(self._on_generation_error, str(e))

    def _on_generation_error(self, error_msg: str):
        """Handle AI generation error."""
        # Dismiss the loading dialog
        if self._loading_screen:
            self.pop_screen()
            self._loading_screen = None
        self.notify(f"AI generation failed: {error_msg}", severity="error", timeout=5)

    def _show_preview(
        self,
        screen_name: str,
        original_code: str,
        modified_code: str,
        diff_text: str,
        syntax_ok: bool,
        syntax_msg: str,
        warnings: list[str],
    ):
        """Show the preview dialog."""
        # Dismiss the loading dialog
        if self._loading_screen:
            self.pop_screen()
            self._loading_screen = None

        if not diff_text.strip():
            self.notify("No changes generated", severity="warning")
            return

        self.push_screen(
            PreviewDiffDialog(
                screen_name,
                original_code,
                modified_code,
                diff_text,
                syntax_ok,
                syntax_msg,
                warnings,
            ),
            self._on_preview_result,
        )

    def _on_preview_result(self, result: dict | None):
        """Handle preview dialog result."""
        if result is None:
            # Cancelled
            self._reset_customization_state()
            return

        action = result.get("action")

        if action == "edit":
            # Go back to prompt input
            if self._current_screen:
                self.push_screen(
                    PromptInputDialog(self._current_screen), self._on_prompt_entered
                )
            return

        if action == "apply":
            modified_code = result.get("code")
            if modified_code and self._current_screen:
                self._apply_changes(self._current_screen, modified_code)

    def _apply_changes(self, screen_name: str, modified_code: str):
        """Apply the changes to the script and reload."""
        script_path = get_screen_path(screen_name)
        if not script_path:
            self.notify("Script path not found", severity="error")
            return

        screen_config = SCREEN_CONFIGS.get(screen_name, {})
        window_name = screen_config.get("window_name")
        window_index = get_window_index_by_name(window_name) if window_name else None

        # Show loading dialog for apply process
        self._loading_screen = LoadingDialog(screen_name)
        self._loading_screen.SPINNER_FRAMES = [
            "⠋ Creating backup...",
            "⠙ Creating backup...",
            "⠹ Writing code...",
            "⠸ Writing code...",
            "⠼ Reloading screen...",
            "⠴ Reloading screen...",
            "⠦ Restarting app...",
            "⠧ Restarting app...",
            "⠇ Almost done...",
            "⠏ Almost done...",
        ]
        self.push_screen(self._loading_screen)

        # Run apply in background thread
        self._run_apply(screen_name, modified_code, script_path, window_index)

    @work(thread=True)
    def _run_apply(self, screen_name: str, modified_code: str, script_path: Path, window_index: int | None):
        """Run the apply process in background thread."""
        try:
            # Create backup
            backup = CodeBackup()
            self._backup_path = backup.create_backup(script_path)

            # Write new code
            script_path.write_text(modified_code)

            # Reload the screen if it's not the config panel itself
            if screen_name != "Config Panel" and window_index:
                reloader = ScreenReloader()
                success, msg = reloader.reload_screen(window_index, script_path)
                if success:
                    self.call_from_thread(
                        self._on_apply_complete,
                        screen_name,
                        True,
                        f"Applied and reloaded {screen_name}!",
                    )
                else:
                    self.call_from_thread(
                        self._on_apply_complete,
                        screen_name,
                        False,
                        f"Code applied but reload failed: {msg}",
                    )
            else:
                self.call_from_thread(
                    self._on_apply_complete,
                    screen_name,
                    True,
                    f"Applied changes to {screen_name}. Restart to see changes.",
                )

            # Cleanup old backups
            backup.cleanup_old_backups(script_path.stem, keep=5)

        except Exception as e:
            # Restore from backup if we made one
            if self._backup_path and self._backup_path.exists():
                try:
                    backup = CodeBackup()
                    backup.restore_backup(self._backup_path, script_path)
                except Exception:
                    pass
            self.call_from_thread(
                self._on_apply_complete,
                screen_name,
                False,
                f"Failed to apply changes: {e}",
            )

    def _on_apply_complete(self, screen_name: str, success: bool, message: str):
        """Handle apply completion."""
        # Dismiss loading dialog
        if self._loading_screen:
            self.pop_screen()
            self._loading_screen = None

        # Show result notification
        severity = "information" if success else "error"
        self.notify(message, severity=severity, timeout=4)

        self._reset_customization_state()

    def _reset_customization_state(self):
        """Reset customization state."""
        self._current_screen = None
        self._current_prompt = None
        self._original_code = None
        self._backup_path = None
        self._loading_screen = None


def main():
    ConfigPanel().run()


if __name__ == "__main__":
    main()
