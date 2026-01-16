#!/usr/bin/env python3
"""Configuration panel for TUI Environment."""

import json
import subprocess
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, Header, Footer, ListView, ListItem, Label, TextArea
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


# Default icon mappings for status bar (window index -> icon)
# Window 1 is Term1, Windows 20-27 are apps
DEFAULT_WINDOW_ICONS = {
    "1": "❯",      # Terminal
    "20": "📂",    # Tree (file manager)
    "21": "🦎",    # Lizard
    "22": "📖",    # Glow (markdown)
    "23": "🔖",    # Favorites
    "24": "💬",    # Prompt
    "25": "⚡",    # Git (lazygit)
    "26": "📈",    # Status
    "27": "⚙",     # Config
}


def load_config() -> dict:
    """Load config from file."""
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
            # Ensure window_icons exists with defaults
            if "window_icons" not in config:
                config["window_icons"] = DEFAULT_WINDOW_ICONS.copy()
            return config
        except Exception:
            pass
    return {"theme": "Gruvbox Dark", "status_position": "top", "border_style": "solid", "footer_position": "bottom", "show_header": True, "status_line": "off", "icon_mode": False, "window_icons": DEFAULT_WINDOW_ICONS.copy()}


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


def get_footer_position() -> str:
    """Get current footer position from config (for Textual apps)."""
    config = load_config()
    return config.get("footer_position", "bottom")


def get_show_header() -> bool:
    """Get whether to show header in Textual apps."""
    config = load_config()
    return config.get("show_header", True)


def get_status_line() -> str:
    """Get status line position: 'off', 'before', or 'after'."""
    config = load_config()
    value = config.get("status_line", "off")
    # Handle legacy boolean values
    if value is True:
        return "after"
    if value is False:
        return "off"
    return value


def apply_status_line(position: str, status_content: str = None):
    """Apply status line (horizontal separator) to current tmux session.

    Args:
        position: 'off', 'before', or 'after'
        status_content: The main status bar content (if None, preserves existing)
    """
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    session = result.stdout.strip()
    if not session:
        return

    theme = get_theme_colors()
    line_format = f"#[fg={theme['fg']},dim]#{{=|-:─}}"

    if position == "off":
        subprocess.run(["tmux", "set-option", "-t", session, "status", "on"])
    elif position == "before":
        # Line first, then content
        subprocess.run(["tmux", "set-option", "-t", session, "status", "2"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", line_format])
        if status_content:
            subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", status_content])
    elif position == "after":
        # Content first, then line
        subprocess.run(["tmux", "set-option", "-t", session, "status", "2"])
        if status_content:
            subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", status_content])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", line_format])
    elif position == "both":
        # Line, content, line
        subprocess.run(["tmux", "set-option", "-t", session, "status", "3"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", line_format])
        if status_content:
            subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", status_content])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[2]", line_format])


def get_window_icons() -> dict[int, str]:
    """Get window icons from config file."""
    config = load_config()
    icons_str = config.get("window_icons", DEFAULT_WINDOW_ICONS)
    # Convert string keys to int keys
    return {int(k): v for k, v in icons_str.items()}

# F-key to window index mapping
FKEY_TO_WINDOW = {
    1: 1,    # F1 -> window 1
    2: 20,   # F2 -> window 20
    3: 21,   # F3 -> window 21
    4: 22,   # F4 -> window 22
    5: 23,   # F5 -> window 23
    6: 24,   # F6 -> window 24
    7: 25,   # F7 -> window 25
    8: 26,   # F8 -> window 26
    9: 27,   # F9 -> window 27
}


def get_icon_mode() -> bool:
    """Get icon mode setting from config."""
    config = load_config()
    return config.get("icon_mode", False)


def get_status_bar_format(icon_mode: bool, path_script: str, status_suffix: str) -> str:
    """Generate the tmux status bar format string.

    Args:
        icon_mode: If True, use icons instead of window names
        path_script: Path to the path_segments.py script
        status_suffix: The suffix containing F10/Help/F12 shortcuts

    Returns:
        The complete status format string for tmux
    """
    # Load icons from config
    icons = get_window_icons()

    # Build the window format based on icon mode
    if icon_mode:
        # In icon mode, show F-key + icon for known windows, name for dynamic terminals
        window_format = (
            "#{W:"
            "#[range=window|#{window_index}]"
            # Window 1 (F1:Term1 or F1:⌨)
            "#{?#{==:#{window_index},1},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F1:{icons.get(1, '❯')} #[default], F1:{icons.get(1, '❯')} }},"
            # Windows 2-19 (dynamic terminals - show name)
            "#{?#{e|<:#{window_index},20},"
            "#{?window_active,#[bg=blue#,fg=black#,bold] #{window_name} #[default], #{window_name} },"
            # Windows 20+ (apps - show F-key + icon)
            "#{?#{==:#{window_index},20},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F2:{icons.get(20, '📂')} #[default], F2:{icons.get(20, '📂')} }},"
            "#{?#{==:#{window_index},21},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F3:{icons.get(21, '🦎')} #[default], F3:{icons.get(21, '🦎')} }},"
            "#{?#{==:#{window_index},22},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F4:{icons.get(22, '📖')} #[default], F4:{icons.get(22, '📖')} }},"
            "#{?#{==:#{window_index},23},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F5:{icons.get(23, '🔖')} #[default], F5:{icons.get(23, '🔖')} }},"
            "#{?#{==:#{window_index},24},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F6:{icons.get(24, '💬')} #[default], F6:{icons.get(24, '💬')} }},"
            "#{?#{==:#{window_index},25},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F7:{icons.get(25, '⚡')} #[default], F7:{icons.get(25, '⚡')} }},"
            "#{?#{==:#{window_index},26},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F8:{icons.get(26, '📈')} #[default], F8:{icons.get(26, '📈')} }},"
            "#{?#{==:#{window_index},27},"
            f"#{{?window_active,#[bg=blue#,fg=black#,bold] F9:{icons.get(27, '⚙')} #[default], F9:{icons.get(27, '⚙')} }},"
            # Unknown high windows - show index:name
            "#{?window_active,#[bg=blue#,fg=black#,bold] #{window_index}:#{window_name} #[default], #{window_index}:#{window_name} }"
            "}}}}}}}}}}"
            "#[norange]"
            "}"
        )
    else:
        # Text mode - original format with window names
        window_format = (
            "#{W:"
            "#[range=window|#{window_index}]"
            "#{?#{==:#{window_index},1},"
            "#{?window_active,#[bg=blue#,fg=black#,bold] F1:#{window_name} #[default], F1:#{window_name} },"
            "#{?#{e|<:#{window_index},20},"
            "#{?window_active,#[bg=blue#,fg=black#,bold] #{window_name} #[default], #{window_name} },"
            "#{?window_active,#[bg=blue#,fg=black#,bold] F#{e|-:#{window_index},18}:#{window_name} #[default], F#{e|-:#{window_index},18}:#{window_name} }"
            "}}"
            "#[norange]"
            "}"
        )

    return (
        f"#(uv run python3 '{path_script}') "
        "#{@focus}#{@passthrough}#[align=centre]"
        f"{window_format} {status_suffix}"
    )


def apply_icon_mode(icon_mode: bool):
    """Apply icon mode to current tmux session status bar.

    Args:
        icon_mode: If True, use icons; if False, use text labels
    """
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    session = result.stdout.strip()
    if not session:
        return

    # Get the path script location (same directory as this file)
    script_dir = Path(__file__).parent
    path_script = script_dir / "path_segments.py"

    # Build status suffix (simplified - actual suffix is set in tui_env.py)
    status_suffix = (
        "#[range=user|f10]F10:Exit#[norange] "
        "#[range=user|help]^H:Help#[norange] "
        "#[range=user|f12]F12:Keys#[norange]"
    )

    # Generate the format string
    status_content = get_status_bar_format(icon_mode, str(path_script), status_suffix)

    # Get current status line setting to preserve it
    status_line = get_status_line()
    theme = get_theme_colors()
    line_format = f"#[fg={theme['fg']},dim]#{{=|-:─}}"

    if status_line == "off":
        subprocess.run(["tmux", "set-option", "-t", session, "status", "on"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", status_content])
    elif status_line == "before":
        subprocess.run(["tmux", "set-option", "-t", session, "status", "2"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", line_format])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", status_content])
    elif status_line == "after":
        subprocess.run(["tmux", "set-option", "-t", session, "status", "2"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", status_content])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", line_format])
    elif status_line == "both":
        subprocess.run(["tmux", "set-option", "-t", session, "status", "3"])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[0]", line_format])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[1]", status_content])
        subprocess.run(["tmux", "set-option", "-t", session, "status-format[2]", line_format])


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
    """Simple confirmation dialog - sqlit style."""

    CSS = """
    ConfirmDialog {
        align: center middle;
        background: transparent;
    }
    #confirm-dialog {
        width: 50;
        height: auto;
        border: round $error;
        background: $background;
        padding: 1 2;

        border-title-align: left;
        border-title-color: $error;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #confirm-message {
        text-align: center;
        margin: 1 0;
    }
    """

    BINDINGS = [("escape", "cancel", "No"), ("y", "confirm", "Yes"), ("n", "cancel", "No")]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="confirm-dialog")
        dialog.border_title = self.title_text
        dialog.border_subtitle = "y:Yes · n:No · Esc:Cancel"
        with dialog:
            yield Label(self.message, id="confirm-message")

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
    """Dialog to select which screen to customize - sqlit style."""

    CSS = """
    ScreenSelectorDialog {
        align: center middle;
        background: transparent;
    }
    #screen-selector-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: $background;
        padding: 1 2;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #screen-list {
        height: auto;
        max-height: 60%;
        border: round $border;
        background: $background;
        padding: 0;
    }
    #screen-list:focus {
        border: round $primary;
    }
    #screen-list > ListItem {
        padding: 0;
    }
    ListItem.-highlight {
        background: $primary 30%;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select", "Select"),
    ]

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="screen-selector-dialog")
        dialog.border_title = "Select Screen to Customize"
        dialog.border_subtitle = "Enter:Select · Esc:Cancel"
        with dialog:
            yield ListView(
                *[
                    ScreenItem(name, cfg["script"], cfg["description"])
                    for name, cfg in SCREEN_CONFIGS.items()
                ],
                id="screen-list",
            )

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
    """Dialog to enter customization prompt - sqlit style."""

    CSS = """
    PromptInputDialog {
        align: center middle;
        background: transparent;
    }
    #prompt-dialog {
        width: 80%;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: $background;
        padding: 1 2;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #prompt-screen-info {
        color: $text-muted;
        padding-bottom: 1;
    }
    #prompt-input {
        height: 10;
        border: round $border;
        background: $background;
    }
    #prompt-input:focus {
        border: round $primary;
    }
    #prompt-examples {
        color: $text-muted;
        padding-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        Binding("ctrl+j", "submit", "Submit", priority=True),
    ]

    def __init__(self, screen_name: str):
        super().__init__()
        self.screen_name = screen_name
        self.screen_config = SCREEN_CONFIGS.get(screen_name, {})

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="prompt-dialog")
        dialog.border_title = "Describe Your Changes"
        dialog.border_subtitle = "Ctrl+J:Submit · Esc:Cancel"
        with dialog:
            yield Label(
                f"Screen: {self.screen_name} ({self.screen_config.get('script', '')})",
                id="prompt-screen-info",
            )
            yield TextArea(id="prompt-input")
            yield Label(
                "[dim]Examples:\n"
                "  - Change the background color to dark purple\n"
                "  - Add vim-style j/k navigation keys\n"
                "  - Make the font larger and use blue for highlights[/dim]",
                id="prompt-examples",
            )

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
    """Dialog to preview diff and approve/reject changes - sqlit style."""

    CSS = """
    PreviewDiffDialog {
        align: center middle;
        background: transparent;
    }
    #preview-dialog {
        width: 90%;
        height: 90%;
        border: round $primary;
        background: $background;
        padding: 1 2;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #preview-status {
        padding-bottom: 1;
    }
    #diff-scroll {
        height: 1fr;
        border: round $border;
        background: $background;
    }
    #diff-scroll:focus {
        border: round $primary;
    }
    #diff-content {
        padding: 1;
    }
    #preview-warnings {
        color: $warning;
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

        dialog = Vertical(id="preview-dialog")
        dialog.border_title = f"Preview: {self.screen_name}"
        dialog.border_subtitle = "a:Apply · e:Edit · Esc:Cancel"
        with dialog:
            yield Label(f"Status: {status_text}", id="preview-status")
            with VerticalScroll(id="diff-scroll"):
                # Show diff as plain text (no markup to avoid escape issues)
                yield Static(self.diff_text, id="diff-content", markup=False)
            if self.warnings:
                yield Label(
                    "[bold]Warnings:[/bold]\n" + "\n".join(f"  - {w}" for w in self.warnings),
                    id="preview-warnings",
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
                lines.append(f"[blue]{escaped_line}[/blue]")
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
    """Dialog showing AI generation progress with animated spinner - sqlit style."""

    CSS = """
    LoadingDialog {
        align: center middle;
        background: transparent;
    }
    #loading-dialog {
        width: 60;
        height: auto;
        border: round $primary;
        background: $background;
        padding: 1 2;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;
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
        dialog = Vertical(id="loading-dialog")
        dialog.border_title = "AI Code Generation"
        with dialog:
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


class ToggleOption(Static):
    """A clickable toggle option that shows label, value, and shortcut key."""

    def __init__(self, label: str, value: str, shortcut: str, action: str, id: str | None = None):
        super().__init__(id=id)
        self.label = label
        self.value = value
        self.shortcut = shortcut
        self.action = action
        self.can_focus = True
        self._update_display()

    def _update_display(self):
        # Escape brackets to prevent Rich markup interpretation
        self.update(f"\\[{self.shortcut}] {self.label}: \\[{self.value}]")

    def set_value(self, value: str):
        self.value = value
        self._update_display()

    def on_click(self):
        self.app.run_action(self.action)

    def key_enter(self):
        self.app.run_action(self.action)


class ConfigPanel(App):
    """Configuration panel app."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("p", "toggle_position", "Position"),
        Binding("b", "toggle_border", "Border"),
        Binding("f", "toggle_footer", "Footer"),
        Binding("h", "toggle_header", "Header"),
        Binding("l", "toggle_status_line", "Line"),
        Binding("o", "toggle_icon_mode", "Icons"),
        Binding("c", "customize", "Customize"),
        Binding("i", "import_prompts", "Import"),
        Binding("t", "command_palette", "Palette"),
    ]

    def __init__(self):
        # Load config BEFORE super().__init__() since compose() is called during init
        self.config = load_config()
        self.selected_theme = self.config.get("theme", "Catppuccin Mocha")
        self.status_position = self.config.get("status_position", "bottom")
        self.border_style = self.config.get("border_style", "solid")
        self.footer_position = self.config.get("footer_position", "bottom")
        self.show_header = self.config.get("show_header", True)
        self.status_line = self.config.get("status_line", "off")
        # Handle legacy boolean values
        if self.status_line is True:
            self.status_line = "after"
        elif self.status_line is False:
            self.status_line = "off"
        self.icon_mode = self.config.get("icon_mode", False)

        # Build CSS with footer position before super().__init__()
        footer_pos = self.footer_position
        self.CSS = f"""
        Screen {{
            background: $background;
        }}
        * {{
            scrollbar-size: 1 1;
        }}
        #main {{
            width: 100%;
            height: 100%;
            padding: 1 2;
        }}
        #theme-list-panel {{
            border: round $border;
            background: $background;
            margin-bottom: 1;
            height: 1fr;

            border-title-align: left;
            border-title-color: $text-muted;
            border-title-background: $background;
        }}
        #theme-list-panel:focus-within {{
            border: round $primary;
            border-title-color: $primary;
        }}
        ListView {{
            width: 100%;
            height: 100%;
            background: $background;
            padding: 1;
        }}
        ListItem {{
            width: 100%;
            padding: 0 1;
            background: $background;
        }}
        ListItem Label {{
            width: 100%;
        }}
        ListItem.-highlight {{
            background: $primary 30%;
        }}
        #version-info {{
            text-align: center;
            color: $text-muted;
            padding: 1;
        }}
        ToggleOption {{
            height: 1;
            padding: 0 1;
            margin-top: 1;
        }}
        ToggleOption:hover {{
            background: $primary 20%;
        }}
        Footer {{
            dock: {footer_pos};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        # Customization state
        self._current_screen: str | None = None
        self._current_prompt: str | None = None
        self._original_code: str | None = None
        self._backup_path: Path | None = None
        self._loading_screen: LoadingDialog | None = None

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=False)
        with Vertical(id="main"):
            theme_panel = Vertical(id="theme-list-panel")
            theme_panel.border_title = "Status Bar Theme"
            with theme_panel:
                yield ListView(
                    *[
                        ThemeItem(name, theme_colors, name == self.selected_theme)
                        for name, theme_colors in THEMES.items()
                    ],
                    id="theme-list"
                )
            # Toggle options with shortcut keys
            pos_label = "TOP" if self.status_position == "top" else "BOTTOM"
            yield ToggleOption("Status Bar Position", pos_label, "p", "toggle_position", id="position-info")
            yield ToggleOption("Border Style", self.border_style.upper(), "b", "toggle_border", id="border-info")
            footer_label = "TOP" if self.footer_position == "top" else "BOTTOM"
            yield ToggleOption("App Footer Position", footer_label, "f", "toggle_footer", id="footer-info")
            header_state = "ON" if self.show_header else "OFF"
            yield ToggleOption("App Header", header_state, "h", "toggle_header", id="header-info")
            yield ToggleOption("Status Bar Line", self.status_line.upper(), "l", "toggle_status_line", id="status-line-info")
            icon_label = "ICONS" if self.icon_mode else "TEXT"
            yield ToggleOption("Status Bar Labels", icon_label, "o", "toggle_icon_mode", id="icon-mode-info")
            version = get_current_version() or "dev"
            yield Static(f"Version: {version}", id="version-info")
        yield Footer()

    def on_mount(self):
        self.title = "Config"
        self.sub_title = ""
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
        self.update_footer_info()
        self.update_header_info()

        # Cache the tmux session name for later use
        ScreenReloader.get_session_name()

    def update_position_info(self):
        """Update position info display."""
        pos_label = "TOP" if self.status_position == "top" else "BOTTOM"
        self.query_one("#position-info", ToggleOption).set_value(pos_label)

    def update_border_info(self):
        """Update border info display."""
        self.query_one("#border-info", ToggleOption).set_value(self.border_style.upper())

    def update_footer_info(self):
        """Update footer info display."""
        pos_label = "TOP" if self.footer_position == "top" else "BOTTOM"
        self.query_one("#footer-info", ToggleOption).set_value(pos_label)

    def update_header_info(self):
        """Update header info display."""
        state = "ON" if self.show_header else "OFF"
        self.query_one("#header-info", ToggleOption).set_value(state)

    def update_status_line_info(self):
        """Update status line info display."""
        self.query_one("#status-line-info", ToggleOption).set_value(self.status_line.upper())

    def update_icon_mode_info(self):
        """Update icon mode info display."""
        label = "ICONS" if self.icon_mode else "TEXT"
        self.query_one("#icon-mode-info", ToggleOption).set_value(label)

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
            # Reload tree_view (F2) to apply new Textual theme
            self._reload_textual_apps()

    def refresh_list(self):
        """Refresh the theme list."""
        list_view = self.query_one("#theme-list", ListView)
        current_index = list_view.index
        list_view.clear()
        for name, theme_colors in THEMES.items():
            list_view.append(ThemeItem(name, theme_colors, name == self.selected_theme))
        list_view.index = current_index

    def _reload_textual_apps(self):
        """Reload Textual apps to apply new theme."""
        import time
        reloader = ScreenReloader()
        script_dir = Path(__file__).parent
        # Reload lstime (F2 = window 20)
        lstime_script = script_dir / "lstime.py"
        if lstime_script.exists():
            # Small delay to ensure config file is fully written
            time.sleep(0.1)
            reloader.reload_screen(20, lstime_script)

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

    def action_toggle_footer(self):
        """Toggle footer position between top and bottom."""
        self.footer_position = "top" if self.footer_position == "bottom" else "bottom"
        self.config["footer_position"] = self.footer_position
        save_config(self.config)
        self.update_footer_info()
        self.notify(f"App Footer: {self.footer_position.upper()} (restart apps to apply)", timeout=2)

    def action_toggle_header(self):
        """Toggle header visibility on/off."""
        self.show_header = not self.show_header
        self.config["show_header"] = self.show_header
        save_config(self.config)
        self.update_header_info()
        state = "ON" if self.show_header else "OFF"
        self.notify(f"App Header: {state} (restart apps to apply)", timeout=2)

    def action_toggle_status_line(self):
        """Cycle status bar line position: off -> before -> after -> both -> off."""
        cycle = ["off", "before", "after", "both"]
        current_idx = cycle.index(self.status_line) if self.status_line in cycle else 0
        self.status_line = cycle[(current_idx + 1) % len(cycle)]
        self.config["status_line"] = self.status_line
        save_config(self.config)
        apply_status_line(self.status_line)
        self.update_status_line_info()
        self.notify(f"Status Bar Line: {self.status_line.upper()}", timeout=1)

    def action_toggle_icon_mode(self):
        """Toggle between icon and text labels in status bar."""
        self.icon_mode = not self.icon_mode
        self.config["icon_mode"] = self.icon_mode
        save_config(self.config)
        apply_icon_mode(self.icon_mode)
        self.update_icon_mode_info()
        label = "ICONS" if self.icon_mode else "TEXT"
        self.notify(f"Status Bar Labels: {label}", timeout=1)

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
