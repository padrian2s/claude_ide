#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "textual>=0.40.0",
#     "rich>=13.0.0",
# ]
# ///
"""
lstime - Directory Time Listing TUI

A text user interface for viewing directories sorted by creation or access time.
Features a split-pane view with file list on the left and details preview on the right.
Includes dual-panel file manager, fuzzy search, and file operations.

Keyboard shortcuts:
  t - Toggle between creation time and access time
  c - Sort by creation time
  a - Sort by access time
  r - Reverse sort order
  h - Toggle hidden files
  y - Copy path to clipboard
  e - Show recursive tree in preview
  [ - Shrink preview panel
  ] - Grow preview panel
  f - Toggle fullscreen (hide list panel)
  g - Toggle first/last position
  m - Open dual-panel file manager
  v - View file in modal viewer
  Ctrl+F - Fuzzy file search (fzf)
  / - Grep search (rg + fzf)
  Tab - Switch focus between panels
  Enter - Navigate into directory
  Backspace - Go to parent directory
  d - Delete selected file/directory
  R - Rename file/directory
  q - Quit
  Q - Quit and sync shell to current directory
"""

import json
import os
import shutil
import subprocess
import sys
import stat
import threading
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

# Config file for persisting settings
CONFIG_PATH = Path.home() / ".config" / "lstime" / "config.json"
SESSION_PATHS_FILE = Path.home() / ".config" / "lstime" / "session_paths.json"
LASTDIR_FILE = Path(f"/tmp/lstime_lastdir_{os.getenv('USER', 'user')}")


def load_config() -> dict:
    """Load configuration from file."""
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_config(config: dict) -> None:
    """Save configuration to file."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
    except OSError:
        pass


def load_session_paths(home_key: str) -> dict:
    """Load saved session paths for a specific home directory."""
    if SESSION_PATHS_FILE.exists():
        try:
            data = json.loads(SESSION_PATHS_FILE.read_text())
            return data.get(home_key, {})
        except Exception:
            pass
    return {}


def save_session_paths(home_key: str, left_path: Path, right_path: Path):
    """Save session paths keyed by home directory."""
    data = {}
    if SESSION_PATHS_FILE.exists():
        try:
            data = json.loads(SESSION_PATHS_FILE.read_text())
        except Exception:
            pass

    data[home_key] = {
        "left": str(left_path),
        "right": str(right_path)
    }
    SESSION_PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATHS_FILE.write_text(json.dumps(data, indent=2))


try:
    from textual.app import App, ComposeResult
    from textual.widgets import Static, DataTable, ListView, ListItem, Label, ProgressBar, Input, Markdown, Button
    from textual.containers import Horizontal, Vertical, VerticalScroll, ScrollableContainer
    from textual.binding import Binding
    from textual.reactive import reactive
    from textual.screen import ModalScreen, Screen
    from textual.message import Message
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.console import Group
    HAS_TEXTUAL = True
except ImportError:
    HAS_TEXTUAL = False

# Import theme function from config_panel (for IDE theme sync)
try:
    from config_panel import get_textual_theme
    HAS_THEME_SYNC = True
except ImportError:
    HAS_THEME_SYNC = False
    def get_textual_theme():
        return "gruvbox"

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.style import Style
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class DirEntry(NamedTuple):
    """Directory entry with time metadata."""
    name: str
    path: Path
    created: datetime
    accessed: datetime
    modified: datetime
    size: int
    is_dir: bool


def get_dir_entries(path: Path = None) -> list[DirEntry]:
    """Get all directory entries with their time metadata."""
    if path is None:
        path = Path.cwd()

    entries = []
    try:
        for item in path.iterdir():
            try:
                stat_info = item.stat()
                # On macOS, st_birthtime is creation time
                # On Linux, fall back to st_ctime (metadata change time)
                created = datetime.fromtimestamp(
                    getattr(stat_info, 'st_birthtime', stat_info.st_ctime)
                )
                accessed = datetime.fromtimestamp(stat_info.st_atime)
                modified = datetime.fromtimestamp(stat_info.st_mtime)

                entries.append(DirEntry(
                    name=item.name,
                    path=item,
                    created=created,
                    accessed=accessed,
                    modified=modified,
                    size=stat_info.st_size,
                    is_dir=item.is_dir()
                ))
            except (PermissionError, OSError):
                continue
    except PermissionError:
        pass

    return entries


def format_time(dt: datetime) -> str:
    """Format datetime as relative time (x days ago)."""
    now = datetime.now()
    diff = now - dt

    if diff.total_seconds() < 60:
        return "just now"
    elif diff.total_seconds() < 3600:
        mins = int(diff.total_seconds() / 60)
        return f"{mins}m ago"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours}h ago"
    elif diff.days == 1:
        return "1 day ago"
    elif diff.days < 30:
        return f"{diff.days} days ago"
    elif diff.days < 365:
        months = diff.days // 30
        return f"{months}mo ago" if months > 1 else "1 month ago"
    else:
        years = diff.days // 365
        return f"{years}y ago" if years > 1 else "1 year ago"


def format_size(size: int) -> str:
    """Format file size for display."""
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if size < 1024:
            if unit == 'B':
                return f"{size:>4}{unit}"
            return f"{size:>4.0f}{unit}"
        size /= 1024
    return f"{size:.0f}P"


# ═══════════════════════════════════════════════════════════════════════════════
# UI Components
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_TEXTUAL:


    class HomeIcon(Static):
        """A clickable home icon that navigates to initial path."""
        
        DEFAULT_CSS = """
        HomeIcon {
            width: auto;
            height: 1;
            padding: 0 1 0 0;
            color: $text-muted;
        }
        HomeIcon:hover {
            color: $primary;
        }
        """
        
        def __init__(self, panel: str = ""):
            super().__init__("🏠", markup=False)
            self.panel = panel
        
        def on_click(self, event) -> None:
            """Handle click to navigate to home path."""
            event.stop()
            self.post_message(HomeIcon.Clicked(self.panel))
        
        class Clicked(Message):
            """Message sent when home icon is clicked."""
            def __init__(self, panel: str):
                super().__init__()
                self.panel = panel

    class HelpBar(Static):
        """Help bar that highlights pressed shortcuts temporarily."""

        DEFAULT_CSS = """
        HelpBar {
            height: 1;
            background: $surface;
            color: $text-muted;
            text-align: center;
            padding: 0 1;
        }
        """

        def __init__(self, shortcuts: list[tuple[str, str]], **kwargs):
            """
            shortcuts: list of (key, description) tuples, e.g. [("h", "home"), ("q", "quit")]
            """
            super().__init__(**kwargs)
            self.shortcuts = shortcuts
            self._highlighted_key: str | None = None
            self._clear_timer = None

        def render(self) -> str:
            """Render the help bar with optional highlight."""
            parts = []
            for key, desc in self.shortcuts:
                label = f"{key}:{desc}"
                if key == self._highlighted_key:
                    parts.append(f"[bold reverse]{label}[/]")
                else:
                    parts.append(label)
            return "  ".join(parts)

        def highlight(self, key: str, duration: float = 0.5):
            """Highlight a key temporarily."""
            self._highlighted_key = key
            self.refresh()
            if self._clear_timer:
                self._clear_timer.stop()
            self._clear_timer = self.set_timer(duration, self._clear_highlight)

        def _clear_highlight(self):
            """Clear the highlight."""
            self._highlighted_key = None
            self.refresh()

    class PathSegment(Static):
        """A clickable path segment."""

        def __init__(self, text: str, path: Path, panel: str):
            super().__init__(text, markup=False)
            self.path = path
            self.panel = panel

        def on_click(self, event) -> None:
            """Handle click to navigate to this path."""
            event.stop()
            self.post_message(PathSegment.Clicked(self.path, self.panel))

        class Clicked(Message):
            """Message sent when path segment is clicked."""
            def __init__(self, path: Path, panel: str):
                super().__init__()
                self.path = path
                self.panel = panel


    class PathBar(Horizontal):
        """A clickable path bar showing path segments."""

        DEFAULT_CSS = """
        PathBar {
            height: 1;
            width: 100%;
            background: $surface;
            padding: 0 1;
        }
        PathBar > PathSegment {
            width: auto;
            padding: 0 0;
            color: $text-muted;
        }
        PathBar > PathSegment:hover {
            color: $primary;
            text-style: underline;
        }
        PathBar > Static.separator {
            width: auto;
            padding: 0;
            color: $text-muted;
        }
        PathBar > Static.sort-icon {
            width: auto;
            padding: 0 1 0 0;
            color: $text-muted;
        }
        """

        def __init__(self, path: Path, panel: str, sort_icon: str = ""):
            super().__init__()
            self.path = path
            self.panel = panel
            self.sort_icon = sort_icon

        def compose(self) -> ComposeResult:
            yield HomeIcon(self.panel)
            if self.sort_icon:
                yield Static(self.sort_icon, classes="sort-icon")

            # Build path segments
            parts = self.path.parts
            for i, part in enumerate(parts):
                # Build path up to this segment
                segment_path = Path(*parts[:i+1])
                yield PathSegment(part, segment_path, self.panel)
                # Add separator after each part except last and root "/"
                if i < len(parts) - 1 and part != "/":
                    yield Static("/", classes="separator")

        def update_path(self, path: Path, sort_icon: str = None):
            """Update the path bar with a new path."""
            self.path = path
            if sort_icon is not None:
                self.sort_icon = sort_icon
            self.remove_children()
            self.mount(HomeIcon(self.panel))
            if self.sort_icon:
                self.mount(Static(self.sort_icon, classes="sort-icon"))
            parts = path.parts
            for i, part in enumerate(parts):
                segment_path = Path(*parts[:i+1])
                self.mount(PathSegment(part, segment_path, self.panel))
                if i < len(parts) - 1 and part != "/":
                    self.mount(Static("/", classes="separator"))


    class FileItem(ListItem):
        """A file/directory item for the dual panel."""

        def __init__(self, path: Path, is_selected: bool = False, is_parent: bool = False):
            super().__init__()
            self.path = path
            self.is_selected = is_selected
            self.is_parent = is_parent

        def compose(self) -> ComposeResult:
            yield Static(self._render_content(), id="item-content")

        def _render_content(self) -> str:
            if self.is_parent:
                return "[bold #0087AF]  /..[/]"

            is_dir = self.path.is_dir()
            mark = "[bold yellow]*[/]" if self.is_selected else " "
            name = self.path.name or str(self.path)

            try:
                size = "" if is_dir else format_size(self.path.stat().st_size)
            except:
                size = ""

            if is_dir:
                # Color directories with readable teal (works on dark backgrounds)
                return f"{mark} [bold #0087AF]/{name:<34}[/]"
            else:
                return f"{mark} {name:<35} {size}"

        def update_selection(self, is_selected: bool):
            """Update selection state without full refresh."""
            self.is_selected = is_selected
            self.query_one("#item-content", Static).update(self._render_content())


    class SearchItem(ListItem):
        """An item in the search results."""

        def __init__(self, path: Path):
            super().__init__()
            self.path = path

        def compose(self) -> ComposeResult:
            is_dir = self.path.is_dir()
            try:
                size = "" if is_dir else format_size(self.path.stat().st_size)
            except:
                size = ""
            if is_dir:
                yield Static(f" [bold #0087AF]/{self.path.name:<34}[/]")
            else:
                yield Static(f"   {self.path.name:<35} {size}")


    # ═══════════════════════════════════════════════════════════════════════════════
    # Modal Dialogs
    # ═══════════════════════════════════════════════════════════════════════════════

    class SearchDialog(ModalScreen):
        """Popup search dialog."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
            ("tab", "select_first", "Select First"),
            Binding("enter", "submit", "Submit", priority=True),
        ]

        CSS = """
        * {
            scrollbar-size: 1 1;
        }
        SearchDialog {
            align: center middle;
            background: transparent;
        }
        #search-dialog {
            width: 65;
            height: 22;
            border: round $primary;
            background: $surface;
            padding: 1;
            border-title-align: left;
            border-title-color: $primary;
            border-title-background: $surface;
            border-title-style: bold;
        }
        #search-input {
            margin-bottom: 1;
            border: round $border;
            background: $surface;
        }
        #search-input:focus {
            border: round $primary;
        }
        #search-results {
            height: 1fr;
            border: round $border;
            background: $surface;
        }
        #search-results:focus {
            border: round $primary;
        }
        ListView {
            background: $surface;
        }
        ListItem {
            background: $surface;
        }
        ListItem.-highlight {
            background: $primary 30%;
        }
        ListItem.-highlight > Static {
            background: transparent;
        }
        """

        def __init__(self, items: list[Path]):
            super().__init__()
            self.all_items = items
            self.filter_text = ""

        def compose(self) -> ComposeResult:
            dialog = Vertical(id="search-dialog")
            dialog.border_title = "Search"
            with dialog:
                yield Input(placeholder="Type to filter...", id="search-input")
                yield ListView(id="search-results")

        def on_mount(self):
            self._refresh_results()
            self.query_one("#search-input", Input).focus()

        def _refresh_results(self):
            results = self.query_one("#search-results", ListView)
            results.clear()
            for path in self.all_items:
                if not self.filter_text or self.filter_text.lower() in path.name.lower():
                    results.append(SearchItem(path))

        def on_input_changed(self, event: Input.Changed):
            self.filter_text = event.value
            self._refresh_results()

        def action_submit(self):
            """Submit - select first result or highlighted item."""
            results = self.query_one("#search-results", ListView)
            # If list has focus and item is highlighted, use that
            if results.has_focus and results.highlighted_child:
                if isinstance(results.highlighted_child, SearchItem):
                    self.dismiss(results.highlighted_child.path)
                    return
            # Otherwise, select first result
            if results.children:
                results.index = 0
                item = results.children[0]
                if isinstance(item, SearchItem):
                    self.dismiss(item.path)

        def on_input_submitted(self, event: Input.Submitted):
            self.action_submit()

        def on_list_view_selected(self, event: ListView.Selected):
            if isinstance(event.item, SearchItem):
                self.dismiss(event.item.path)

        def action_cancel(self):
            self.dismiss(None)

        def action_select_first(self):
            results = self.query_one("#search-results", ListView)
            if not results.children:
                return
            if len(results.children) == 1:
                item = results.children[0]
                if isinstance(item, SearchItem):
                    self.dismiss(item.path)
            else:
                results.index = 0
                results.focus()


    class ConfirmDialog(ModalScreen):
        """Confirmation dialog."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
            ("y", "confirm", "Yes"),
            ("n", "cancel", "No"),
        ]

        CSS = """
        ConfirmDialog {
            align: center middle;
            background: transparent;
        }
        #confirm-dialog {
            width: 50;
            height: auto;
            border: round $error;
            background: $surface;
            padding: 1 2;
            border-title-align: left;
            border-title-color: $error;
            border-title-background: $surface;
            border-title-style: bold;
            border-subtitle-align: right;
            border-subtitle-color: $text-muted;
            border-subtitle-background: $surface;
        }
        #confirm-message {
            text-align: center;
            margin: 1 0;
        }
        """

        def __init__(self, title: str, message: str):
            super().__init__()
            self.dialog_title = title
            self.message = message

        def compose(self) -> ComposeResult:
            dialog = Vertical(id="confirm-dialog")
            dialog.border_title = self.dialog_title
            dialog.border_subtitle = "y:Yes  n:No  Esc:Cancel"
            with dialog:
                yield Label(self.message, id="confirm-message")

        def action_confirm(self):
            self.dismiss(True)

        def action_cancel(self):
            self.dismiss(False)


    class RenameDialog(ModalScreen):
        """Rename dialog."""

        BINDINGS = [
            ("escape", "cancel", "Cancel"),
            Binding("enter", "submit", "Submit", priority=True),
        ]

        CSS = """
        RenameDialog {
            align: center middle;
            background: transparent;
        }
        #rename-dialog {
            width: 80%;
            max-width: 100;
            height: auto;
            border: round $primary;
            background: $surface;
            padding: 1 2;
            border-title-align: left;
            border-title-color: $primary;
            border-title-background: $surface;
            border-title-style: bold;
            border-subtitle-align: right;
            border-subtitle-color: $text-muted;
            border-subtitle-background: $surface;
        }
        #rename-input {
            margin: 1 0;
            border: round $border;
            background: $surface;
        }
        #rename-input:focus {
            border: round $primary;
        }
        """

        def __init__(self, current_name: str):
            super().__init__()
            self.current_name = current_name

        def compose(self) -> ComposeResult:
            dialog = Vertical(id="rename-dialog")
            dialog.border_title = "Rename"
            dialog.border_subtitle = "Enter:Confirm  Esc:Cancel"
            with dialog:
                yield Input(value=self.current_name, id="rename-input")

        def on_mount(self):
            input_widget = self.query_one("#rename-input", Input)
            input_widget.focus()
            name = self.current_name
            if "." in name and not name.startswith("."):
                dot_pos = name.rfind(".")
                input_widget.selection = (0, dot_pos)
            else:
                input_widget.selection = (0, len(name))

        def action_submit(self):
            input_widget = self.query_one("#rename-input", Input)
            new_name = input_widget.value.strip()
            if new_name and new_name != self.current_name:
                self.dismiss(new_name)
            else:
                self.dismiss(None)

        def on_input_submitted(self, event: Input.Submitted):
            self.action_submit()

        def action_cancel(self):
            self.dismiss(None)


    # ═══════════════════════════════════════════════════════════════════════════════
    # File Viewer
    # ═══════════════════════════════════════════════════════════════════════════════

    class FileViewer(VerticalScroll):
        """Scrollable file content viewer with syntax highlighting."""

        file_path = reactive(None)
        MARKDOWN_EXTENSIONS = {'.md', '.markdown', '.mdown', '.mkd'}

        LEXER_MAP = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.tsx': 'tsx', '.jsx': 'jsx', '.json': 'json',
            '.yaml': 'yaml', '.yml': 'yaml', '.html': 'html',
            '.css': 'css', '.scss': 'scss', '.md': 'markdown',
            '.sh': 'bash', '.bash': 'bash', '.zsh': 'zsh',
            '.sql': 'sql', '.rs': 'rust', '.go': 'go',
            '.rb': 'ruby', '.java': 'java', '.c': 'c',
            '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
            '.toml': 'toml', '.xml': 'xml', '.vue': 'vue',
            '.php': 'php', '.swift': 'swift', '.kt': 'kotlin',
            '.lua': 'lua', '.r': 'r', '.dockerfile': 'dockerfile',
            '.hs': 'haskell', '.scala': 'scala', '.ex': 'elixir',
            '.exs': 'elixir', '.nim': 'nim', '.clj': 'clojure',
            '.erl': 'erlang', '.ml': 'ocaml', '.fs': 'fsharp',
            '.zig': 'zig', '.dart': 'dart', '.groovy': 'groovy',
            '.gradle': 'groovy', '.pl': 'perl', '.jl': 'julia',
        }

        def compose(self) -> ComposeResult:
            yield Static("", id="file-content")
            yield Markdown("", id="md-content")

        def on_mount(self):
            self.query_one("#md-content").display = False

        def load_file(self, path: Path):
            self.file_path = path
            is_markdown = path.suffix.lower() in self.MARKDOWN_EXTENSIONS

            static_widget = self.query_one("#file-content", Static)
            md_widget = self.query_one("#md-content", Markdown)

            image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.tiff', '.tif'}
            binary_extensions = {'.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
                               '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
                               '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.wav', '.flac',
                               '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}

            suffix = path.suffix.lower()

            if suffix in image_extensions:
                static_widget.display = True
                md_widget.display = False
                static_widget.update(f"[bold magenta]{path.name}[/bold magenta]\n\n[dim]Image file - press 'o' to open[/dim]")
                self.scroll_home()
                return

            if suffix in binary_extensions:
                static_widget.display = True
                md_widget.display = False
                static_widget.update(f"[yellow]Binary file: {path.name}[/yellow]\n\n[dim]Cannot display {suffix} files[/dim]")
                self.scroll_home()
                return

            try:
                with open(path, 'r', errors='replace') as f:
                    code = f.read()

                if is_markdown:
                    static_widget.display = False
                    md_widget.display = True
                    md_widget.update(code)
                else:
                    static_widget.display = True
                    md_widget.display = False

                    line_count = len(code.splitlines())
                    lexer = self.LEXER_MAP.get(suffix)
                    if lexer is None and path.name.lower() == 'dockerfile':
                        lexer = 'dockerfile'

                    header = Text()
                    header.append(f"{path.name}", style="bold magenta")
                    header.append(f" ({line_count} lines)", style="dim")
                    header.append("\n" + "-" * 50 + "\n", style="dim")

                    if lexer:
                        syntax = Syntax(code, lexer, theme="monokai", line_numbers=True, word_wrap=False)
                        static_widget.update(Group(header, syntax))
                    else:
                        lines = code.splitlines()
                        plain_content = Text()
                        for i, line in enumerate(lines, 1):
                            plain_content.append(f"{i:4} ", style="dim")
                            plain_content.append(f"{line}\n")
                        static_widget.update(Group(header, plain_content))

            except Exception as e:
                static_widget.display = True
                md_widget.display = False
                static_widget.update(f"[red]Error: {e}[/red]")

            self.scroll_home()

        def clear(self):
            self.file_path = None
            self.query_one("#file-content", Static).display = True
            self.query_one("#md-content", Markdown).display = False
            self.query_one("#file-content", Static).update("[dim]Select a file to view[/dim]")


    class FileViewerScreen(ModalScreen):
        """Modal screen for viewing a file."""

        BINDINGS = [
            ("escape", "close", "Close"),
            ("q", "close", "Close"),
            ("v", "close", "Close"),
        ]

        CSS = """
        * {
            scrollbar-size: 1 1;
        }
        FileViewerScreen {
            align: center middle;
            background: transparent;
        }
        #viewer-container {
            width: 95%;
            height: 95%;
            background: $surface;
            border: round $primary;
            padding: 0;
            border-title-align: left;
            border-title-color: $primary;
            border-title-background: $surface;
            border-title-style: bold;
            border-subtitle-align: right;
            border-subtitle-color: $text-muted;
            border-subtitle-background: $surface;
        }
        #viewer-content {
            height: 1fr;
            background: $surface;
            padding: 0 1;
        }
        FileViewer {
            background: $surface;
        }
        """

        def __init__(self, file_path: Path):
            super().__init__()
            self.file_path = file_path

        def compose(self) -> ComposeResult:
            container = Vertical(id="viewer-container")
            container.border_title = f"{self.file_path.name}"
            container.border_subtitle = "v/q/Esc:Close"
            with container:
                yield FileViewer(id="viewer-content")

        def on_mount(self):
            viewer = self.query_one("#viewer-content", FileViewer)
            viewer.load_file(self.file_path)

        def action_close(self):
            self.dismiss()


    class MaskedInput(Input):
        """Input that shows masked value when not focused."""

        class ValueChanged(Message):
            """Emitted when value changes on blur."""
            def __init__(self, key: str, value: str) -> None:
                self.key = key
                self.value = value
                super().__init__()

        def __init__(self, env_key: str, real_value: str, **kwargs) -> None:
            self.env_key = env_key
            self.real_value = real_value
            self.is_masked = True
            masked = "*" * min(len(real_value), 20) if real_value else ""
            super().__init__(value=masked, **kwargs)

        def on_focus(self) -> None:
            """Show real value when focused."""
            if self.is_masked:
                self.is_masked = False
                self.value = self.real_value
                self.cursor_position = len(self.value)

        def on_blur(self) -> None:
            """Mask value when unfocused."""
            self.real_value = self.value
            self.is_masked = True
            self.value = "*" * min(len(self.real_value), 20) if self.real_value else ""
            self.post_message(self.ValueChanged(self.env_key, self.real_value))

        def get_real_value(self) -> str:
            """Get the actual unmasked value."""
            return self.real_value if self.is_masked else self.value


    class EnvEditorScreen(ModalScreen):
        """Modal screen for editing .env files with masked values."""

        BINDINGS = [
            ("escape", "close", "Close"),
            ("ctrl+s", "save", "Save"),
            ("ctrl+n", "new_var", "New Variable"),
        ]

        CSS = """
        * {
            scrollbar-size: 1 1;
        }
        EnvEditorScreen {
            align: center middle;
            background: transparent;
        }
        #env-container {
            width: 95%;
            height: 95%;
            background: $surface;
            border: round $primary;
            padding: 1;
            border-title-align: left;
            border-title-color: $primary;
            border-title-background: $surface;
            border-title-style: bold;
            border-subtitle-align: right;
            border-subtitle-color: $text-muted;
            border-subtitle-background: $surface;
        }
        #env-list {
            height: 1fr;
            background: $surface;
        }
        .env-row {
            height: 3;
            margin-bottom: 1;
        }
        .env-row .key-label {
            width: 30;
            padding: 1;
            background: $panel;
            color: $text;
        }
        .env-row .value-input {
            width: 1fr;
        }
        .env-row .delete-btn {
            width: 3;
            min-width: 3;
            padding: 0 1;
        }
        #env-status {
            height: 1;
            background: $panel;
            padding: 0 1;
        }
        #add-dialog {
            width: 60;
            height: auto;
            padding: 1 2;
            background: $surface;
            border: solid $primary;
        }
        #add-dialog Input {
            margin-bottom: 1;
        }
        #add-dialog .buttons {
            height: 3;
            align: center middle;
        }
        #add-dialog .buttons Button {
            margin: 0 1;
        }
        #dialog-layer {
            align: center middle;
            display: none;
        }
        #dialog-layer.visible {
            display: block;
            layer: dialog;
        }
        """

        def __init__(self, file_path: Path):
            super().__init__()
            self.file_path = file_path
            self.env_vars: dict[str, str] = {}
            self.modified = False

        def compose(self) -> ComposeResult:
            container = Vertical(id="env-container")
            container.border_title = f"{self.file_path.name}"
            container.border_subtitle = "^S:Save ^N:New Esc:Close"
            with container:
                yield ScrollableContainer(id="env-list")
                yield Static("", id="env-status")
            yield Vertical(id="dialog-layer")

        def on_mount(self):
            self._load_env_file()

        def _load_env_file(self):
            """Load and parse the .env file."""
            self.env_vars.clear()
            container = self.query_one("#env-list", ScrollableContainer)
            container.remove_children()

            if self.file_path.exists():
                content = self.file_path.read_text()
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip()
                        if (value.startswith('"') and value.endswith('"')) or \
                           (value.startswith("'") and value.endswith("'")):
                            value = value[1:-1]
                        self.env_vars[key] = value

                for key, value in self.env_vars.items():
                    container.mount(self._create_env_row(key, value))

                self._update_status(f"Loaded {len(self.env_vars)} variables")
            else:
                self._update_status(f"File not found (will be created on save)")

            self.modified = False
            self._update_title()

        def _create_env_row(self, key: str, value: str) -> Horizontal:
            """Create a row for an env variable."""
            row = Horizontal(classes="env-row")
            row.env_key = key

            key_label = Static(key, classes="key-label")
            value_input = MaskedInput(key, value, classes="value-input")
            delete_btn = Button("x", classes="delete-btn", variant="error")

            row.compose_add_child(key_label)
            row.compose_add_child(value_input)
            row.compose_add_child(delete_btn)
            return row

        def on_masked_input_value_changed(self, event: MaskedInput.ValueChanged) -> None:
            """Track when values change."""
            if event.key in self.env_vars:
                if self.env_vars[event.key] != event.value:
                    self.env_vars[event.key] = event.value
                    self.modified = True
                    self._update_title()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            """Handle delete button or dialog buttons."""
            btn = event.button
            if "delete-btn" in btn.classes:
                row = btn.parent
                if hasattr(row, 'env_key'):
                    del self.env_vars[row.env_key]
                    row.remove()
                    self.modified = True
                    self._update_title()
                    self._update_status(f"Deleted: {row.env_key}")
            elif btn.id == "add-btn":
                self._submit_new_var()
            elif btn.id == "cancel-btn":
                self._close_dialog()

        def _update_status(self, message: str) -> None:
            self.query_one("#env-status", Static).update(message)

        def _update_title(self) -> None:
            marker = " *" if self.modified else ""
            container = self.query_one("#env-container")
            container.border_title = f"{self.file_path.name}{marker}"

        def action_save(self) -> None:
            """Save the .env file."""
            lines = []
            for row in self.query(".env-row"):
                if hasattr(row, 'env_key'):
                    key = row.env_key
                    inp = row.query_one(Input)
                    value = inp.real_value if hasattr(inp, 'real_value') else inp.value
                    if " " in value or '"' in value:
                        value = f'"{value}"'
                    lines.append(f"{key}={value}")

            self.file_path.write_text("\n".join(lines) + "\n")
            self.modified = False
            self._update_title()
            self._update_status(f"Saved {len(lines)} variables")

        def action_new_var(self) -> None:
            """Show dialog to add new variable."""
            dialog_layer = self.query_one("#dialog-layer")
            dialog_layer.remove_children()

            dialog = Vertical(id="add-dialog")
            dialog.compose_add_child(Label("Add New Variable"))
            key_input = Input(placeholder="KEY_NAME", id="new-key")
            value_input = Input(placeholder="value", id="new-value")
            buttons = Horizontal(classes="buttons")
            buttons.compose_add_child(Button("Add", variant="primary", id="add-btn"))
            buttons.compose_add_child(Button("Cancel", id="cancel-btn"))
            dialog.compose_add_child(key_input)
            dialog.compose_add_child(value_input)
            dialog.compose_add_child(buttons)

            dialog_layer.mount(dialog)
            dialog_layer.add_class("visible")
            self.set_timer(0.1, lambda: self.query_one("#new-key", Input).focus())

        def on_input_submitted(self, event: Input.Submitted) -> None:
            """Handle Enter in dialog inputs."""
            if event.input.id == "new-key":
                self.query_one("#new-value", Input).focus()
            elif event.input.id == "new-value":
                self._submit_new_var()

        def _submit_new_var(self) -> None:
            """Submit the new variable from dialog."""
            try:
                key = self.query_one("#new-key", Input).value.strip()
                value = self.query_one("#new-value", Input).value
                if key and key not in self.env_vars:
                    self.env_vars[key] = value
                    container = self.query_one("#env-list", ScrollableContainer)
                    container.mount(self._create_env_row(key, value))
                    self.modified = True
                    self._update_title()
                    self._update_status(f"Added: {key}")
                elif key in self.env_vars:
                    self._update_status(f"Key already exists: {key}")
            except Exception:
                pass
            self._close_dialog()

        def _close_dialog(self) -> None:
            """Close the add dialog."""
            dialog_layer = self.query_one("#dialog-layer")
            dialog_layer.remove_children()
            dialog_layer.remove_class("visible")

        def action_close(self) -> None:
            if self.modified:
                self._update_status("Unsaved changes! ^S to save, Esc again to discard")
                self.modified = False
            else:
                self.dismiss()


    # ═══════════════════════════════════════════════════════════════════════════════
    # Dual Panel File Manager
    # ═══════════════════════════════════════════════════════════════════════════════

    class DualPanelScreen(Screen):
        """Dual panel file manager for copying files."""

        _session_left_path: Path = None
        _session_right_path: Path = None
        _session_sort_left: bool = False
        _session_sort_right: bool = False
        _session_left_index: int = 1
        _session_right_index: int = 1
        _initial_start_path: Path = None
        _session_show_hidden: bool = True

        BINDINGS = [
            ("escape", "cancel_or_close", "Close"),
            ("q", "close", "Close"),
            ("tab", "switch_panel", "Switch"),
            ("space", "toggle_select", "Select"),
            ("backspace", "go_up", "Up"),
            ("c", "copy_selected", "Copy"),
            ("a", "select_all", "All"),
            ("s", "toggle_sort", "Sort"),
            ("r", "rename", "Rename"),
            ("d", "delete", "Delete"),
            Binding("g", "toggle_position", "g=jump"),
            Binding("home", "go_first", "First", priority=True),
            Binding("end", "go_last", "Last", priority=True),
            ("pageup", "page_up", "PgUp"),
            ("pagedown", "page_down", "PgDn"),
            ("h", "go_home", "Home"),
            ("i", "sync_panels", "Sync"),
            ("v", "view_file", "View"),
            ("/", "start_search", "Search"),
            ("e", "edit_nano", "Edit"),
            Binding("ctrl+f", "fzf_files", "^F=find", priority=True),
        ]

        CSS = """
        * {
            scrollbar-size: 1 1;
        }
        DualPanelScreen {
            align: center middle;
            background: transparent;
        }
        #dual-container {
            width: 100%;
            height: 100%;
            background: $background;
            border: none;
            padding: 0;
        }
        #panels {
            height: 1fr;
            background: $background;
        }
        .panel {
            width: 50%;
            height: 100%;
            border: round $border;
            background: $background;
            margin: 0 1;
            border-title-align: left;
            border-title-color: $text-muted;
            border-title-background: $background;
        }
        .panel:focus-within {
            border: round $primary;
            border-title-color: $primary;
        }
        .panel-list {
            height: 1fr;
            background: $background;
        }
        #progress-container {
            height: 3;
            padding: 0 1;
            display: none;
            background: $background;
        }
        #progress-container.visible {
            display: block;
        }
        #help-bar {
            height: 1;
            background: $surface;
            color: $text-muted;
            text-align: center;
            padding: 0 1;
        }
        ListItem {
            padding: 0;
            background: $background;
        }
        ListItem.-highlight {
            background: $panel;
        }
        ListItem.-highlight > Static {
            background: transparent;
        }
        ListView:focus ListItem.-highlight {
            background: $primary 30%;
        }
        ListView:focus ListItem.-highlight > Static {
            background: transparent;
        }
        ListView {
            background: $background;
        }
        ProgressBar {
            background: $background;
        }
        ProgressBar > .bar--bar {
            color: $success;
        }
        """

        def __init__(self, start_path: Path = None):
            super().__init__()
            if DualPanelScreen._initial_start_path is None:
                DualPanelScreen._initial_start_path = start_path or Path.cwd()

            home_key = str(DualPanelScreen._initial_start_path)

            if DualPanelScreen._session_left_path is None:
                saved = load_session_paths(home_key)
                if saved.get("left"):
                    saved_left = Path(saved["left"])
                    if saved_left.exists():
                        DualPanelScreen._session_left_path = saved_left
                if saved.get("right"):
                    saved_right = Path(saved["right"])
                    if saved_right.exists():
                        DualPanelScreen._session_right_path = saved_right

            self.left_path = DualPanelScreen._session_left_path or start_path or Path.cwd()
            self.right_path = DualPanelScreen._session_right_path or Path.home()
            self.sort_left = DualPanelScreen._session_sort_left
            self.sort_right = DualPanelScreen._session_sort_right
            self.show_hidden = DualPanelScreen._session_show_hidden
            self.selected_left: set[Path] = set()
            self.selected_right: set[Path] = set()
            self.active_panel = "left"
            self.copying = False

        def compose(self) -> ComposeResult:
            container = Vertical(id="dual-container")
            with container:
                with Horizontal(id="panels"):
                    left_panel = Vertical(id="left-panel", classes="panel")
                    with left_panel:
                        yield PathBar(self.left_path, "left", "")
                        yield ListView(id="left-list", classes="panel-list")
                    right_panel = Vertical(id="right-panel", classes="panel")
                    with right_panel:
                        yield PathBar(self.right_path, "right", "")
                        yield ListView(id="right-list", classes="panel-list")
                with Vertical(id="progress-container"):
                    yield Static("", id="progress-text")
                    yield ProgressBar(id="progress-bar", total=100)
                yield HelpBar([
                    ("/", "search"), ("^F", "find"), ("Space", "sel"), ("v", "view"), ("e", "edit"),
                    ("c", "copy"), ("r", "ren"), ("d", "del"), ("a", "all"),
                    ("s", "sort"), ("h", "home"), ("i", "sync"), ("g", "jump")
                ], id="help-bar")

        def on_mount(self):
            self.refresh_panels()
            left_list = self.query_one("#left-list", ListView)
            right_list = self.query_one("#right-list", ListView)
            if left_list.children:
                max_left = len(left_list.children) - 1
                left_list.index = min(DualPanelScreen._session_left_index, max_left)
            if right_list.children:
                max_right = len(right_list.children) - 1
                right_list.index = min(DualPanelScreen._session_right_index, max_right)
            left_list.focus()

        def _highlight_key(self, key: str):
            """Highlight a key in the help bar."""
            try:
                self.query_one("#help-bar", HelpBar).highlight(key)
            except:
                pass

        def on_path_segment_clicked(self, message: PathSegment.Clicked) -> None:
            if message.panel == "left":
                self.left_path = message.path
                self.selected_left.clear()
                DualPanelScreen._session_left_path = message.path
                self._refresh_single_panel("left")
            else:
                self.right_path = message.path
                self.selected_right.clear()
                DualPanelScreen._session_right_path = message.path
                self._refresh_single_panel("right")
            self._save_paths_to_config()

        def on_home_icon_clicked(self, message: HomeIcon.Clicked) -> None:
            """Handle click on home icon to navigate to initial path."""
            home_path = DualPanelScreen._initial_start_path or Path.cwd()
            if message.panel == "left":
                self.left_path = home_path
                self.selected_left.clear()
                DualPanelScreen._session_left_path = home_path
                self._refresh_single_panel("left")
            else:
                self.right_path = home_path
                self.selected_right.clear()
                DualPanelScreen._session_right_path = home_path
                self._refresh_single_panel("right")
            self._save_paths_to_config()
            self.notify(f"Home: {home_path}", timeout=1)

        def refresh_panels(self):
            self._refresh_panel("left", self.left_path, self.selected_left)
            self._refresh_panel("right", self.right_path, self.selected_right)

        def _refresh_panel(self, side: str, path: Path, selected: set):
            list_view = self.query_one(f"#{side}-list", ListView)
            panel = self.query_one(f"#{side}-panel", Vertical)

            sort_by_date = self.sort_left if side == "left" else self.sort_right
            sort_icon = "t" if sort_by_date else "n"

            try:
                path_bar = panel.query_one(PathBar)
                path_bar.update_path(path, sort_icon)
            except:
                pass

            list_view.clear()

            try:
                if path.parent != path:
                    list_view.append(FileItem(path.parent, is_selected=False, is_parent=True))

                if self.show_hidden:
                    all_items = list(path.iterdir())
                else:
                    all_items = [p for p in path.iterdir() if not p.name.startswith(".")]

                # Sort: dot directories first, then regular directories, then files
                if sort_by_date:
                    def sort_key(p):
                        try:
                            atime = p.stat().st_atime
                        except:
                            atime = 0
                        is_dir = p.is_dir()
                        return (not is_dir, not p.name.startswith('.') if is_dir else True, -atime)
                else:
                    def sort_key(p):
                        is_dir = p.is_dir()
                        return (not is_dir, not p.name.startswith('.') if is_dir else True, p.name.lower())

                items = sorted(all_items, key=sort_key)
                for item in items:
                    list_view.append(FileItem(item, item in selected))
            except PermissionError:
                pass

        def _refresh_single_panel(self, side: str):
            if side == "left":
                self._refresh_panel("left", self.left_path, self.selected_left)
            else:
                self._refresh_panel("right", self.right_path, self.selected_right)
            list_view = self.query_one(f"#{side}-list", ListView)
            self.set_timer(0.01, lambda: self._set_cursor(list_view))

        def _save_paths_to_config(self):
            home_key = str(DualPanelScreen._initial_start_path or Path.cwd())
            save_session_paths(home_key, self.left_path, self.right_path)

        def _set_cursor(self, list_view: ListView):
            if len(list_view.children) > 1:
                list_view.index = 1
            elif list_view.children:
                list_view.index = 0
            list_view.focus()

        def action_close(self):
            if not self.copying:
                DualPanelScreen._session_left_path = self.left_path
                DualPanelScreen._session_right_path = self.right_path
                DualPanelScreen._session_sort_left = self.sort_left
                DualPanelScreen._session_sort_right = self.sort_right
                left_list = self.query_one("#left-list", ListView)
                right_list = self.query_one("#right-list", ListView)
                DualPanelScreen._session_left_index = left_list.index if left_list.index is not None else 1
                DualPanelScreen._session_right_index = right_list.index if right_list.index is not None else 1
                home_key = str(DualPanelScreen._initial_start_path or Path.cwd())
                save_session_paths(home_key, self.left_path, self.right_path)
                self.dismiss()

        def action_cancel_or_close(self):
            if not self.copying:
                self.action_close()

        def action_start_search(self):
            self._highlight_key("/")
            path = self.left_path if self.active_panel == "left" else self.right_path
            with self.app.suspend():
                if self.show_hidden:
                    cmd = f"ls -1a '{path}' | grep -v '^\\.$' | grep -v '^\\.\\.$' | fzf --prompt='Select: '"
                else:
                    cmd = f"ls -1 '{path}' | fzf --prompt='Select: '"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(path))
                selected = result.stdout.strip()

            if selected:
                selected_path = path / selected
                if selected_path.is_dir():
                    if self.active_panel == "left":
                        self.left_path = selected_path
                        self.selected_left.clear()
                        DualPanelScreen._session_left_path = selected_path
                    else:
                        self.right_path = selected_path
                        self.selected_right.clear()
                        DualPanelScreen._session_right_path = selected_path
                    self._refresh_single_panel(self.active_panel)
                    self._save_paths_to_config()
                else:
                    list_view = self.query_one(f"#{self.active_panel}-list", ListView)
                    target_path = selected_path.resolve()
                    for i, child in enumerate(list_view.children):
                        if isinstance(child, FileItem) and not child.is_parent:
                            if child.path.resolve() == target_path:
                                list_view.index = i
                                child.scroll_visible()
                                break

            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            list_view.focus()

        def action_toggle_sort(self):
            self._highlight_key("s")
            if self.active_panel == "left":
                self.sort_left = not self.sort_left
                DualPanelScreen._session_sort_left = self.sort_left
            else:
                self.sort_right = not self.sort_right
                DualPanelScreen._session_sort_right = self.sort_right
            self._refresh_single_panel(self.active_panel)

        def action_switch_panel(self):
            if self.active_panel == "left":
                self.active_panel = "right"
                self.query_one("#right-list", ListView).focus()
            else:
                self.active_panel = "left"
                self.query_one("#left-list", ListView).focus()

        def action_toggle_select(self):
            self._highlight_key("Space")
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            selected = self.selected_left if self.active_panel == "left" else self.selected_right

            if list_view.highlighted_child and isinstance(list_view.highlighted_child, FileItem):
                item = list_view.highlighted_child
                if item.path.name:
                    if item.path in selected:
                        selected.discard(item.path)
                        item.update_selection(False)
                    else:
                        selected.add(item.path)
                        item.update_selection(True)
                    if list_view.index < len(list_view.children) - 1:
                        list_view.index += 1

        def on_list_view_selected(self, event: ListView.Selected):
            if isinstance(event.item, FileItem):
                item = event.item
                if item.path.is_dir():
                    list_id = event.list_view.id
                    if list_id == "left-list":
                        self.left_path = item.path
                        self.selected_left.clear()
                        self.active_panel = "left"
                        DualPanelScreen._session_left_path = item.path
                    else:
                        self.right_path = item.path
                        self.selected_right.clear()
                        self.active_panel = "right"
                        DualPanelScreen._session_right_path = item.path
                    self._refresh_single_panel(self.active_panel)
                    self._save_paths_to_config()

        def action_go_up(self):
            if self.active_panel == "left":
                if self.left_path.parent != self.left_path:
                    self.left_path = self.left_path.parent
                    self.selected_left.clear()
                    DualPanelScreen._session_left_path = self.left_path
            else:
                if self.right_path.parent != self.right_path:
                    self.right_path = self.right_path.parent
                    self.selected_right.clear()
                    DualPanelScreen._session_right_path = self.right_path
            self._refresh_single_panel(self.active_panel)
            self._save_paths_to_config()

        def action_go_home(self):
            self._highlight_key("h")
            home_path = DualPanelScreen._initial_start_path or Path.cwd()
            if self.active_panel == "left":
                self.left_path = home_path
                self.selected_left.clear()
                DualPanelScreen._session_left_path = home_path
            else:
                self.right_path = home_path
                self.selected_right.clear()
                DualPanelScreen._session_right_path = home_path
            self._refresh_single_panel(self.active_panel)
            self._save_paths_to_config()
            self.notify(f"Home: {home_path}", timeout=1)

        def action_sync_panels(self):
            self._highlight_key("i")
            if self.active_panel == "left":
                self.right_path = self.left_path
                self.selected_right.clear()
                DualPanelScreen._session_right_path = self.left_path
                self._refresh_single_panel("right")
            else:
                self.left_path = self.right_path
                self.selected_left.clear()
                DualPanelScreen._session_left_path = self.right_path
                self._refresh_single_panel("left")
            self._save_paths_to_config()
            self.notify("Synced panels", timeout=1)

        def action_select_all(self):
            self._highlight_key("a")
            path = self.left_path if self.active_panel == "left" else self.right_path
            selected = self.selected_left if self.active_panel == "left" else self.selected_right
            try:
                all_items = {item for item in path.iterdir() if not item.name.startswith(".")}
                if all_items and all_items <= selected:
                    selected.clear()
                else:
                    selected.update(all_items)
            except:
                pass
            self._refresh_single_panel(self.active_panel)

        def action_toggle_position(self):
            self._highlight_key("g")
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if list_view.children:
                current = list_view.index if list_view.index is not None else 0
                if current == 0:
                    list_view.index = len(list_view.children) - 1
                    list_view.scroll_end(animate=False)
                else:
                    list_view.index = 0
                    list_view.scroll_home(animate=False)
                list_view.focus()

        def action_go_first(self):
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if list_view.children:
                list_view.index = 0
                list_view.scroll_home(animate=False)
                list_view.focus()

        def action_go_last(self):
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if list_view.children:
                list_view.index = len(list_view.children) - 1
                list_view.scroll_end(animate=False)
                list_view.focus()


        def action_page_up(self):
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if list_view.children:
                current = list_view.index if list_view.index is not None else 0
                page_size = max(1, list_view.size.height - 2)
                list_view.index = max(0, current - page_size)
                list_view.focus()

        def action_page_down(self):
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if list_view.children:
                current = list_view.index if list_view.index is not None else 0
                page_size = max(1, list_view.size.height - 2)
                list_view.index = min(len(list_view.children) - 1, current + page_size)
                list_view.focus()

        def action_copy_selected(self):
            self._highlight_key("c")
            if self.copying:
                return

            if self.active_panel == "left":
                selected = self.selected_left.copy()
                dest_path = self.right_path
            else:
                selected = self.selected_right.copy()
                dest_path = self.left_path

            used_explicit_selection = bool(selected)

            if not selected:
                list_view = self.query_one(f"#{self.active_panel}-list", ListView)
                if list_view.highlighted_child and isinstance(list_view.highlighted_child, FileItem):
                    item = list_view.highlighted_child
                    if not item.is_parent:
                        selected = {item.path}

            if not selected:
                self.notify("No files to copy", timeout=2)
                return

            self.copying = True
            self._copy_used_explicit_selection = used_explicit_selection
            items = list(selected)
            total = len(items)

            progress_container = self.query_one("#progress-container")
            progress_container.add_class("visible")
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_text = self.query_one("#progress-text", Static)
            progress_text.update(f"Copying {total} item(s)...")
            progress_bar.update(progress=0)

            def do_copy():
                for i, src in enumerate(items):
                    try:
                        dest = dest_path / src.name
                        self.app.call_from_thread(progress_text.update, f"Copying: {src.name} ({i+1}/{total})")
                        self.app.call_from_thread(progress_bar.update, progress=int(((i + 0.5) / total) * 100))
                        if src.is_dir():
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, dest)
                        self.app.call_from_thread(progress_bar.update, progress=int(((i + 1) / total) * 100))
                    except Exception as e:
                        self.app.call_from_thread(self.notify, f"Error copying {src.name}: {e}", timeout=5)
                self.app.call_from_thread(self._copy_complete)

            thread = threading.Thread(target=do_copy, daemon=True)
            thread.start()

        def _copy_complete(self):
            self.copying = False
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_text = self.query_one("#progress-text", Static)
            progress_container = self.query_one("#progress-container")

            progress_bar.update(progress=100)
            progress_text.update("Done!")
            self.notify("Copy complete!", timeout=2)

            if getattr(self, '_copy_used_explicit_selection', False):
                self.selected_left.clear()
                self.selected_right.clear()

            self.refresh_panels()
            self.set_timer(2, lambda: progress_container.remove_class("visible"))

        def action_rename(self):
            self._highlight_key("r")
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if not list_view.highlighted_child:
                self.notify("No item to rename", timeout=2)
                return

            item = list_view.highlighted_child
            if not isinstance(item, FileItem) or item.is_parent:
                self.notify("Cannot rename this item", timeout=2)
                return

            path = item.path

            def handle_rename(new_name: str | None):
                if new_name:
                    try:
                        new_path = path.parent / new_name
                        path.rename(new_path)
                        self.notify(f"Renamed to: {new_name}", timeout=2)
                        self._refresh_single_panel(self.active_panel)
                    except Exception as e:
                        self.notify(f"Error: {e}", timeout=3)

            self.app.push_screen(RenameDialog(path.name), handle_rename)

        def action_delete(self):
            self._highlight_key("d")
            if self.active_panel == "left":
                selected = self.selected_left.copy()
            else:
                selected = self.selected_right.copy()

            used_explicit_selection = bool(selected)

            if not selected:
                list_view = self.query_one(f"#{self.active_panel}-list", ListView)
                if list_view.highlighted_child and isinstance(list_view.highlighted_child, FileItem):
                    item = list_view.highlighted_child
                    if not item.is_parent:
                        selected = {item.path}

            if not selected:
                self.notify("No files selected", timeout=2)
                return

            items = list(selected)
            count = len(items)
            message = f"Delete '{items[0].name}'?" if count == 1 else f"Delete {count} items?"

            def handle_confirm(confirmed: bool):
                if confirmed:
                    errors = []
                    for item_path in items:
                        try:
                            if item_path.is_dir():
                                shutil.rmtree(item_path)
                            else:
                                item_path.unlink()
                        except Exception as e:
                            errors.append(f"{item_path.name}: {e}")

                    if errors:
                        self.notify(f"Errors: {len(errors)}", timeout=3)
                    else:
                        self.notify(f"Deleted {count} item(s)", timeout=2)

                    if used_explicit_selection:
                        self.selected_left.clear()
                        self.selected_right.clear()
                    self._refresh_single_panel(self.active_panel)

            self.app.push_screen(ConfirmDialog("Delete", message), handle_confirm)

        def action_view_file(self):
            self._highlight_key("v")
            for screen in self.app.screen_stack:
                if isinstance(screen, (FileViewerScreen, EnvEditorScreen)):
                    screen.dismiss()
                    return

            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if not list_view.highlighted_child:
                self.notify("No file selected", timeout=2)
                return

            item = list_view.highlighted_child
            if not isinstance(item, FileItem) or item.is_parent:
                return

            if item.path.is_dir():
                self.notify("Cannot view directory", timeout=2)
                return

            # Use env editor for .env files
            if item.path.name.startswith('.env') or item.path.suffix == '.env':
                self.app.push_screen(EnvEditorScreen(item.path))
            else:
                self.app.push_screen(FileViewerScreen(item.path))

        def action_edit_nano(self):
            """Open selected file in nano editor."""
            self._highlight_key("e")
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            if not list_view.highlighted_child:
                self.notify("No file selected", timeout=2)
                return

            item = list_view.highlighted_child
            if not isinstance(item, FileItem) or item.is_parent:
                return

            if item.path.is_dir():
                self.notify("Cannot edit directory", timeout=2)
                return

            with self.app.suspend():
                subprocess.run(["nano", str(item.path)])

        def action_fzf_files(self) -> None:
            """Fuzzy find files in active panel using fzf."""
            self._highlight_key("^F")
            # Get the active panel's path
            current_path = self.left_path if self.active_panel == "left" else self.right_path

            with self.app.suspend():
                fd_check = subprocess.run(["which", "fd"], capture_output=True)
                if fd_check.returncode == 0:
                    cmd = f"fd --type f --hidden -E .git -E .venv -E node_modules -E __pycache__ . '{current_path}' 2>/dev/null | fzf --preview 'head -100 {{}}'"
                else:
                    cmd = f"find '{current_path}' -type f 2>/dev/null | fzf --preview 'head -100 {{}}'"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                selected = result.stdout.strip()

            if selected:
                path = Path(selected).resolve()
                if path.is_file():
                    # Navigate to parent directory in active panel and highlight file
                    parent = path.parent
                    if self.active_panel == "left":
                        if parent != self.left_path:
                            self.left_path = parent
                            self._refresh_panel("left")
                        # Find and select the file in the left panel
                        list_view = self.query_one("#left-list", ListView)
                    else:
                        if parent != self.right_path:
                            self.right_path = parent
                            self._refresh_panel("right")
                        # Find and select the file in the right panel
                        list_view = self.query_one("#right-list", ListView)

                    # Find the file in the list and highlight it
                    for i, item in enumerate(list_view.children):
                        if hasattr(item, 'path') and item.path.resolve() == path:
                            list_view.index = i
                            break

                    self.notify(f"Found: {path.name}", timeout=1)


    # ═══════════════════════════════════════════════════════════════════════════════
    # Main Application
    # ═══════════════════════════════════════════════════════════════════════════════

    class LstimeApp(App):
        """TUI application for directory time listing."""

        CSS = """
        Screen {
            background: $surface;
        }

        * {
            scrollbar-size: 1 1;
        }

        Footer {
            dock: bottom;
            height: 1;
        }

        #status {
            dock: top;
            height: 1;
            background: $primary-darken-2;
            color: $text;
            padding: 0 1;
        }

        #main-container {
            height: 1fr;
        }

        #list-panel {
            width: 2fr;
            border: round $border;
            margin: 0 0 0 1;
            border-title-align: left;
            border-title-color: $text-muted;
            border-title-background: $surface;
        }

        #list-panel:focus-within {
            border: round $primary;
            border-title-color: $primary;
        }

        DataTable {
            height: 1fr;
        }

        DataTable > .datatable--cursor {
            background: $secondary;
        }

        #preview-panel {
            width: 1fr;
            border: round $border;
            margin: 0 1 0 0;
            padding: 1 2;
            border-title-align: left;
            border-title-color: $text-muted;
            border-title-background: $surface;
        }

        #preview-panel:focus-within {
            border: round $primary;
            border-title-color: $primary;
        }

        #preview-title {
            text-style: bold;
            color: $text;
            margin-bottom: 1;
        }

        #preview-content {
            color: $text-muted;
        }

        .preview-label {
            color: $text-muted;
        }

        .preview-value {
            color: $text;
        }

        FileViewer {
            background: $surface;
        }

        #file-content {
            background: $surface;
        }

        #md-content {
            background: $surface;
        }

        #help-bar {
            dock: bottom;
            height: 1;
            background: $surface;
            color: $text-muted;
            text-align: center;
            padding: 0 1;
        }
        """

        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("Q", "quit_cd", "Quit+CD"),
            Binding("t", "toggle_time", "Toggle Time"),
            Binding("c", "sort_created", "Created"),
            Binding("a", "sort_accessed", "Accessed"),
            Binding("r", "reverse", "Reverse"),
            Binding("h", "toggle_hidden", "Hidden"),
            Binding("y", "copy_path", "Copy Path"),
            Binding("e", "show_tree", "Tree"),
            Binding("[", "grow_preview", "Shrink"),
            Binding("]", "shrink_preview", "Grow"),
            Binding("f", "toggle_fullscreen", "Fullscreen"),
            Binding("g", "toggle_position", "g=jump"),
            Binding("home", "go_first", "First", priority=True),
            Binding("end", "go_last", "Last", priority=True),
            Binding("m", "file_manager", "Manager"),
            Binding("v", "view_file", "View"),
            Binding("ctrl+f", "fzf_files", "Find", priority=True),
            Binding("/", "fzf_grep", "Grep", priority=True),
            Binding("tab", "toggle_focus", "Switch"),
            Binding("enter", "enter_dir", "Enter"),
            Binding("backspace", "go_parent", "Parent"),
            Binding("d", "delete_item", "Delete"),
            Binding("R", "rename_item", "Rename"),
            Binding("o", "open_system", "Open"),
            Binding("E", "edit_nano", "Edit"),
        ]

        preview_width = reactive(30)
        fullscreen_panel = reactive(None)  # None, "list", or "preview"

        def __init__(self, path: Path = None):
            # Get the theme BEFORE super().__init__() for proper initialization
            self._initial_theme = get_textual_theme()
            super().__init__()
            self.theme = self._initial_theme
            self.start_path = path or Path.cwd()  # Store initial path for home icon
            self.path = self.start_path
            self.entries: list[DirEntry] = []
            self._visible_entries: list[DirEntry] = []
            self.sort_by = "created"
            self.reverse_order = True
            self.show_hidden = False
            self._preview_timer = None  # For debouncing preview updates
            config = load_config()
            self.preview_width = config.get("preview_width", 30)
            self.show_hidden = config.get("show_hidden", False)

        def compose(self) -> ComposeResult:
            yield Static(id="status")
            with Horizontal(id="main-container"):
                list_panel = Vertical(id="list-panel")
                list_panel.border_title = "Files"
                with list_panel:
                    yield HomeIcon("main")
                    yield DataTable(id="file-table")
                preview_panel = Vertical(id="preview-panel")
                preview_panel.border_title = "Preview"
                with preview_panel:
                    yield FileViewer(id="file-viewer")
            yield HelpBar([
                ("^F", "find"), ("/", "grep"), ("y", "path"), ("o", "open"),
                ("e", "tree"), ("m", "mgr"), ("v", "view"), ("E", "edit"),
                ("t", "time"), ("r", "rev"), ("h", "hid"), ("f", "full"),
                ("g", "jump"), ("d", "del"), ("R", "ren"), ("q", "quit"), ("Q", "quit+cd")
            ], id="help-bar")

        def on_mount(self) -> None:
            # Apply theme after mount to ensure it takes effect
            # Re-read the theme from config in case it changed during startup
            current_theme = get_textual_theme()
            if self.theme != current_theme:
                self.theme = current_theme
            elif self._initial_theme and self.theme != self._initial_theme:
                self.theme = self._initial_theme

            self.load_entries()
            self.setup_table()
            self.refresh_table()
            self._apply_panel_widths()

        def _highlight_key(self, key: str):
            """Highlight a key in the help bar."""
            try:
                self.query_one("#help-bar", HelpBar).highlight(key)
            except:
                pass

        def on_home_icon_clicked(self, message: HomeIcon.Clicked) -> None:
            """Handle click on home icon to navigate to initial path."""
            if message.panel == "main":
                self.path = self.start_path
                self.load_entries()
                self.refresh_table()
                self.notify(f"Home: {self.start_path.name or self.start_path}", timeout=1)

        def load_entries(self) -> None:
            self.entries = get_dir_entries(self.path)

        def setup_table(self) -> None:
            table = self.query_one("#file-table", DataTable)
            table.cursor_type = "row"
            table.zebra_stripes = False
            table.add_column("Name", width=40, key="name")
            table.add_column("Time", width=14, key="time")

        def refresh_table(self) -> None:
            table = self.query_one("#file-table", DataTable)
            table.clear()

            entries = self.entries
            if not self.show_hidden:
                entries = [e for e in entries if not e.name.startswith('.')]

            # Sort: dot directories first, then regular directories, then files
            if self.sort_by == "created":
                entries = sorted(entries, key=lambda e: (
                    not e.is_dir,  # dirs first
                    not e.name.startswith('.') if e.is_dir else True,  # dot dirs first among dirs
                    -e.created.timestamp() if self.reverse_order else e.created.timestamp()
                ))
            else:
                entries = sorted(entries, key=lambda e: (
                    not e.is_dir,  # dirs first
                    not e.name.startswith('.') if e.is_dir else True,  # dot dirs first among dirs
                    -e.accessed.timestamp() if self.reverse_order else e.accessed.timestamp()
                ))

            self._visible_entries = entries

            for entry in entries:
                time_val = entry.created if self.sort_by == "created" else entry.accessed
                if entry.is_dir:
                    name = Text("/" + entry.name, style="bold cyan")
                else:
                    name = Text(entry.name)
                table.add_row(name, format_time(time_val))

            self.update_status()
            if self._visible_entries:
                self.update_preview(0)

        def update_status(self) -> None:
            status = self.query_one("#status", Static)
            sort_label = "Creation Time" if self.sort_by == "created" else "Access Time"
            order_label = "(newest first)" if self.reverse_order else "(oldest first)"
            hidden_label = "[hidden]" if self.show_hidden else ""

            visible = len([e for e in self.entries if self.show_hidden or not e.name.startswith('.')])
            total = len(self.entries)

            path_str = str(self.path)
            if len(path_str) > 40:
                path_str = "..." + path_str[-37:]

            status.update(f" {path_str}  |  {sort_label} {order_label}  |  {visible}/{total} {hidden_label}")

        def _apply_panel_widths(self) -> None:
            preview = self.query_one("#preview-panel", Vertical)
            list_panel = self.query_one("#list-panel", Vertical)
            if self.fullscreen_panel == "list":
                preview.styles.width = "0%"
                preview.styles.display = "none"
                list_panel.styles.display = "block"
                list_panel.styles.width = "100%"
            elif self.fullscreen_panel == "preview":
                list_panel.styles.width = "0%"
                list_panel.styles.display = "none"
                preview.styles.display = "block"
                preview.styles.width = "100%"
            else:
                preview.styles.display = "block"
                list_panel.styles.display = "block"
                preview.styles.width = f"{self.preview_width}%"
                list_panel.styles.width = f"{100 - self.preview_width}%"

        def _save_config(self) -> None:
            config = load_config()
            config["preview_width"] = self.preview_width
            config["show_hidden"] = self.show_hidden
            save_config(config)

        def action_toggle_time(self) -> None:
            self._highlight_key("t")
            self.sort_by = "accessed" if self.sort_by == "created" else "created"
            self.refresh_table()

        def action_sort_created(self) -> None:
            self.sort_by = "created"
            self.refresh_table()

        def action_sort_accessed(self) -> None:
            self.sort_by = "accessed"
            self.refresh_table()

        def action_reverse(self) -> None:
            self._highlight_key("r")
            self.reverse_order = not self.reverse_order
            self.refresh_table()

        def action_toggle_hidden(self) -> None:
            self._highlight_key("h")
            self.show_hidden = not self.show_hidden
            self._save_config()
            self.refresh_table()

        def action_copy_path(self) -> None:
            self._highlight_key("y")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                try:
                    entry = self._visible_entries[table.cursor_row]
                    full_path = str(entry.path.absolute())
                    subprocess.run(["pbcopy"], input=full_path.encode(), check=True)
                    self.notify(f"Copied: {full_path}")
                except (IndexError, subprocess.CalledProcessError):
                    self.notify("Failed to copy path", severity="error")

        def action_show_tree(self) -> None:
            self._highlight_key("e")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                try:
                    entry = self._visible_entries[table.cursor_row]
                    if entry.is_dir:
                        viewer = self.query_one("#file-viewer", FileViewer)
                        content = self._preview_tree(entry.path)
                        static = viewer.query_one("#file-content", Static)
                        static.display = True
                        viewer.query_one("#md-content").display = False
                        static.update(content)
                    else:
                        self.notify("Not a directory", severity="warning")
                except IndexError:
                    pass

        def action_shrink_preview(self) -> None:
            if self.preview_width > 10:
                self.preview_width -= 5
                self._apply_panel_widths()
                self._save_config()

        def action_grow_preview(self) -> None:
            if self.preview_width < 70:
                self.preview_width += 5
                self._apply_panel_widths()
                self._save_config()

        def action_toggle_fullscreen(self) -> None:
            self._highlight_key("f")
            table = self.query_one("#file-table", DataTable)
            viewer = self.query_one("#file-viewer", FileViewer)

            # Determine which panel is active
            if table.has_focus:
                active = "list"
            elif viewer.has_focus:
                active = "preview"
            else:
                active = "list"  # default to list

            # Toggle fullscreen for the active panel
            if self.fullscreen_panel == active:
                self.fullscreen_panel = None
                self.notify("Normal view", timeout=1)
            else:
                self.fullscreen_panel = active
                self.notify(f"Fullscreen: {active} (f to restore)", timeout=1)

            self._apply_panel_widths()

        def action_toggle_position(self) -> None:
            self._highlight_key("g")
            table = self.query_one("#file-table", DataTable)
            if self._visible_entries:
                current = table.cursor_row if table.cursor_row is not None else 0
                if current == 0:
                    table.move_cursor(row=len(self._visible_entries) - 1)
                else:
                    table.move_cursor(row=0)

        def action_go_first(self) -> None:
            """Go to first item (Home key). Delegates to DualPanelScreen if active."""
            if isinstance(self.screen, DualPanelScreen):
                self.screen.action_go_first()
                return
            table = self.query_one("#file-table", DataTable)
            if self._visible_entries:
                table.move_cursor(row=0)

        def action_go_last(self) -> None:
            """Go to last item (End key). Delegates to DualPanelScreen if active."""
            if isinstance(self.screen, DualPanelScreen):
                self.screen.action_go_last()
                return
            table = self.query_one("#file-table", DataTable)
            if self._visible_entries:
                table.move_cursor(row=len(self._visible_entries) - 1)

        def action_toggle_focus(self) -> None:
            table = self.query_one("#file-table", DataTable)
            viewer = self.query_one("#file-viewer", FileViewer)
            if table.has_focus:
                viewer.focus()
            else:
                table.focus()

        def action_file_manager(self) -> None:
            self._highlight_key("m")
            self.push_screen(DualPanelScreen(self.path))

        def action_view_file(self) -> None:
            self._highlight_key("v")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                entry = self._visible_entries[table.cursor_row]
                if not entry.is_dir:
                    # Use env editor for .env files
                    if entry.path.name.startswith('.env') or entry.path.suffix == '.env':
                        self.push_screen(EnvEditorScreen(entry.path))
                    else:
                        self.push_screen(FileViewerScreen(entry.path))
                else:
                    self.notify("Cannot view directory", timeout=2)

        def action_fzf_files(self) -> None:
            self._highlight_key("^F")
            with self.suspend():
                fd_check = subprocess.run(["which", "fd"], capture_output=True)
                if fd_check.returncode == 0:
                    cmd = f"fd --type f --hidden -E .git -E .venv -E node_modules -E __pycache__ . '{self.path}' 2>/dev/null | fzf --preview 'head -100 {{}}'"
                else:
                    cmd = f"find '{self.path}' -type f 2>/dev/null | fzf --preview 'head -100 {{}}'"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                selected = result.stdout.strip()

            if selected:
                path = Path(selected).resolve()
                if path.is_file():
                    # Navigate to parent directory and highlight file
                    if path.parent != self.path:
                        self.path = path.parent
                        self.load_entries()
                        self.refresh_table()
                    # Find and select the file
                    for i, entry in enumerate(self._visible_entries):
                        if entry.path.resolve() == path:
                            table = self.query_one("#file-table", DataTable)
                            table.move_cursor(row=i)
                            break
                    self.query_one("#file-viewer", FileViewer).load_file(path)
                    self.notify(f"Opened: {path.name}", timeout=1)

        def action_fzf_grep(self) -> None:
            self._highlight_key("/")
            with self.suspend():
                result = subprocess.run(
                    f'rg -n --color=always "" "{self.path}" 2>/dev/null | fzf --ansi --preview "echo {{}} | cut -d: -f1 | xargs head -100"',
                    shell=True, capture_output=True, text=True
                )
                selected = result.stdout.strip()

            if selected:
                parts = selected.split(":", 2)
                if len(parts) >= 2:
                    file_path = Path(parts[0]).resolve()
                    if file_path.is_file():
                        if file_path.parent != self.path:
                            self.path = file_path.parent
                            self.load_entries()
                            self.refresh_table()
                        for i, entry in enumerate(self._visible_entries):
                            if entry.path.resolve() == file_path:
                                table = self.query_one("#file-table", DataTable)
                                table.move_cursor(row=i)
                                break
                        self.query_one("#file-viewer", FileViewer).load_file(file_path)
                        self.notify(f"Opened: {file_path.name}:{parts[1]}", timeout=1)

        def action_enter_dir(self) -> None:
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                entry = self._visible_entries[table.cursor_row]
                if entry.is_dir:
                    self.path = entry.path
                    self.load_entries()
                    self.refresh_table()
                    self.notify(f"/{entry.name}", timeout=1)

        def action_go_parent(self) -> None:
            if self.path.parent != self.path:
                old_path = self.path
                self.path = self.path.parent
                self.load_entries()
                self.refresh_table()
                # Try to select the old directory
                for i, entry in enumerate(self._visible_entries):
                    if entry.path == old_path:
                        table = self.query_one("#file-table", DataTable)
                        table.move_cursor(row=i)
                        break
                self.notify(f"/{self.path.name or self.path}", timeout=1)

        def action_delete_item(self) -> None:
            self._highlight_key("d")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is None or not self._visible_entries:
                self.notify("No item selected", timeout=2)
                return

            entry = self._visible_entries[table.cursor_row]
            message = f"Delete '{entry.name}'?"

            def handle_confirm(confirmed: bool):
                if confirmed:
                    try:
                        if entry.is_dir:
                            shutil.rmtree(entry.path)
                        else:
                            entry.path.unlink()
                        self.notify(f"Deleted: {entry.name}", timeout=2)
                        self.load_entries()
                        self.refresh_table()
                    except Exception as e:
                        self.notify(f"Error: {e}", timeout=3)

            self.push_screen(ConfirmDialog("Delete", message), handle_confirm)

        def action_rename_item(self) -> None:
            self._highlight_key("R")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is None or not self._visible_entries:
                self.notify("No item selected", timeout=2)
                return

            entry = self._visible_entries[table.cursor_row]

            def handle_rename(new_name: str | None):
                if new_name:
                    try:
                        new_path = entry.path.parent / new_name
                        entry.path.rename(new_path)
                        self.notify(f"Renamed to: {new_name}", timeout=2)
                        self.load_entries()
                        self.refresh_table()
                    except Exception as e:
                        self.notify(f"Error: {e}", timeout=3)

            self.push_screen(RenameDialog(entry.name), handle_rename)

        def action_open_system(self) -> None:
            self._highlight_key("o")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                entry = self._visible_entries[table.cursor_row]
                subprocess.run(["open", str(entry.path)])
                self.notify(f"Opened: {entry.name}", timeout=1)

        def action_edit_nano(self) -> None:
            """Open selected file in nano editor."""
            self._highlight_key("E")
            table = self.query_one("#file-table", DataTable)
            if table.cursor_row is not None and self._visible_entries:
                entry = self._visible_entries[table.cursor_row]
                if not entry.is_dir:
                    with self.suspend():
                        subprocess.run(["nano", str(entry.path)])
                    # Refresh preview after editing
                    self.update_preview(table.cursor_row)
                else:
                    self.notify("Cannot edit directory", timeout=2)

        def action_quit_cd(self) -> None:
            """Quit and write current directory to temp file for shell to cd."""
            self._highlight_key("Q")
            try:
                LASTDIR_FILE.write_text(str(self.path))
            except OSError:
                pass
            self.exit()

        def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
            # Debounce preview updates - only load after user stops navigating
            if hasattr(self, '_preview_timer') and self._preview_timer:
                self._preview_timer.stop()
            row = event.cursor_row  # Capture value, not reference
            self._preview_timer = self.set_timer(0.1, lambda r=row: self.update_preview(r))

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            """Handle row selection (Enter key) - navigate into directories."""
            if event.cursor_row is not None and self._visible_entries:
                try:
                    entry = self._visible_entries[event.cursor_row]
                    if entry.is_dir:
                        self.path = entry.path
                        self.load_entries()
                        self.refresh_table()
                        self.notify(f"/{entry.name}", timeout=1)
                except IndexError:
                    pass

        def update_preview(self, row_index: int) -> None:
            viewer = self.query_one("#file-viewer", FileViewer)

            if row_index is None or not self._visible_entries or row_index >= len(self._visible_entries):
                viewer.clear()
                return

            entry = self._visible_entries[row_index]

            if entry.is_dir:
                content = self._preview_tree(entry.path)
                static = viewer.query_one("#file-content", Static)
                static.display = True
                viewer.query_one("#md-content").display = False
                static.update(content)
                viewer.scroll_home()
            else:
                viewer.load_file(entry.path)

        def _preview_tree(self, path: Path, max_depth: int = 3, max_items: int = 100) -> str:
            lines = [f"[bold magenta]/{path.name}[/]", ""]
            count = [0]
            tree_lines = []

            def add_tree(p: Path, prefix: str = "", depth: int = 0):
                if count[0] >= max_items or depth > max_depth:
                    return
                try:
                    entries = get_dir_entries(p)
                    if not self.show_hidden:
                        entries = [e for e in entries if not e.name.startswith('.')]
                    # Sort: dot directories first, then regular directories, then files
                    if self.sort_by == "created":
                        entries = sorted(entries, key=lambda e: (
                            not e.is_dir,  # dirs first
                            not e.name.startswith('.') if e.is_dir else True,  # dot dirs first among dirs
                            -e.created.timestamp() if self.reverse_order else e.created.timestamp()
                        ))
                    else:
                        entries = sorted(entries, key=lambda e: (
                            not e.is_dir,  # dirs first
                            not e.name.startswith('.') if e.is_dir else True,  # dot dirs first among dirs
                            -e.accessed.timestamp() if self.reverse_order else e.accessed.timestamp()
                        ))

                    for i, entry in enumerate(entries):
                        if count[0] >= max_items:
                            tree_lines.append((f"{prefix}[dim]... truncated[/]", "", False, ""))
                            return
                        is_last = i == len(entries) - 1
                        connector = "└── " if is_last else "├── "
                        time_val = entry.created if self.sort_by == "created" else entry.accessed
                        time_str = format_time(time_val)
                        name = ("/" if entry.is_dir else "") + entry.name
                        tree_lines.append((f"{prefix}{connector}", name, entry.is_dir, time_str))
                        count[0] += 1
                        if entry.is_dir:
                            next_prefix = prefix + ("    " if is_last else "│   ")
                            add_tree(entry.path, next_prefix, depth + 1)
                except PermissionError:
                    tree_lines.append((f"{prefix}[red]Permission denied[/]", "", False, ""))

            add_tree(path)

            max_name = 25
            for item in tree_lines:
                if len(item) == 4:
                    _, name, _, _ = item
                    if len(name) > max_name:
                        max_name = min(len(name), 30)

            for item in tree_lines:
                if len(item) == 4:
                    prefix, name, is_dir, time_str = item
                    display_name = name[:max_name-3] + "..." if len(name) > max_name else name
                    color = "cyan" if is_dir else "white"
                    padding = max_name - len(display_name)
                    lines.append(f"{prefix}[{color}]{display_name}[/]{' ' * padding} [dim]{time_str:>12}[/]")
                else:
                    lines.append(item[0])

            if count[0] >= max_items:
                lines.append(f"\n[dim]Showing {max_items} items (truncated)[/]")

            return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Rich Fallback Implementation
# ═══════════════════════════════════════════════════════════════════════════════

def rich_display(path: Path = None, sort_by: str = "created", reverse: bool = True, show_hidden: bool = False):
    """Display directory listing using Rich (non-interactive fallback)."""
    if not HAS_RICH:
        print("Error: Neither 'textual' nor 'rich' is installed.")
        print("Install with: pip install textual rich")
        sys.exit(1)

    console = Console()
    path = path or Path.cwd()
    entries = get_dir_entries(path)

    if not show_hidden:
        entries = [e for e in entries if not e.name.startswith('.')]

    if sort_by == "created":
        entries = sorted(entries, key=lambda e: e.created, reverse=reverse)
        time_label = "Created"
    else:
        entries = sorted(entries, key=lambda e: e.accessed, reverse=reverse)
        time_label = "Accessed"

    table = Table(
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="dim",
        show_lines=False,
        padding=(0, 1),
    )

    table.add_column("Name", style="white", no_wrap=True, min_width=30)
    table.add_column(time_label, style="green", justify="right")
    table.add_column("Size", style="yellow", justify="right")

    for entry in entries:
        time_val = entry.created if sort_by == "created" else entry.accessed

        if entry.is_dir:
            name = f"[bold blue]{entry.name}/[/]"
            size = "-"
        else:
            name = entry.name
            size = format_size(entry.size)

        table.add_row(name, format_time(time_val), size)

    order_str = "newest first" if reverse else "oldest first"
    console.print()
    console.print(Panel(
        f"[bold]{path}[/]\n[dim]{len(entries)} items | Sorted by {time_label.lower()} ({order_str})[/]",
        title="[cyan]lstime[/]",
        border_style="cyan",
        padding=(0, 1),
    ))
    console.print(table)
    console.print("[dim]Tip: Run with --tui for interactive mode, or use -a for access time[/]")


# ═══════════════════════════════════════════════════════════════════════════════
# Plain Text Fallback
# ═══════════════════════════════════════════════════════════════════════════════

def plain_display(path: Path = None, sort_by: str = "created", reverse: bool = True, show_hidden: bool = False):
    """Plain text display without any dependencies."""
    path = path or Path.cwd()
    entries = get_dir_entries(path)

    if not show_hidden:
        entries = [e for e in entries if not e.name.startswith('.')]

    if sort_by == "created":
        entries = sorted(entries, key=lambda e: e.created, reverse=reverse)
        time_label = "Created"
    else:
        entries = sorted(entries, key=lambda e: e.accessed, reverse=reverse)
        time_label = "Accessed"

    order_str = "newest first" if reverse else "oldest first"
    print(f"\n  lstime - {path}")
    print(f"  {len(entries)} items | Sorted by {time_label.lower()} ({order_str})")
    print("  " + "=" * 60)
    print(f"  {'Name':<35} {time_label:>15} {'Size':>8}")
    print("  " + "-" * 60)

    for entry in entries:
        time_val = entry.created if sort_by == "created" else entry.accessed
        name = entry.name + ("/" if entry.is_dir else "")
        if len(name) > 34:
            name = name[:31] + "..."

        size = "-" if entry.is_dir else format_size(entry.size)
        print(f"  {name:<35} {format_time(time_val):>15} {size:>8}")

    print()


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def print_help():
    """Print help message."""
    help_text = """
lstime - Directory Time Listing Tool

Usage: lstime [OPTIONS] [PATH]

Options:
  -c, --created     Sort by creation time (default)
  -a, --accessed    Sort by last access time
  -r, --reverse     Reverse sort order (oldest first)
  -H, --hidden      Show hidden files
  --tui             Force interactive TUI mode
  --no-tui          Force non-interactive mode
  -h, --help        Show this help message

Interactive TUI Shortcuts:
  t                 Toggle between creation/access time
  c                 Sort by creation time
  a                 Sort by access time
  r                 Reverse sort order
  h                 Toggle hidden files
  y                 Copy selected path to clipboard
  e                 Show recursive tree in preview
  [                 Shrink preview panel
  ]                 Grow preview panel
  f                 Toggle fullscreen (hide preview)
  g                 Toggle first/last position
  m                 Open dual-panel file manager
  v                 View file in modal
  Ctrl+F            Fuzzy file search (fzf)
  /                 Grep search (rg + fzf)
  Tab               Switch focus (list/preview)
  Enter             Navigate into directory
  Backspace         Go to parent directory
  d                 Delete file/directory
  R                 Rename file/directory
  o                 Open with system app
  q                 Quit
  Q                 Quit and sync shell directory

File Manager (m) Shortcuts:
  Tab               Switch panels
  Space             Toggle selection
  c                 Copy to other panel
  r                 Rename
  d                 Delete
  a                 Select all/none
  s                 Toggle sort (name/time)
  h                 Go to home (start path)
  i                 Sync panels
  v                 View file
  /                 Search (fzf)
  g                 Toggle first/last
  q/Esc             Close file manager

Examples:
  lstime                    # List current dir by creation time
  lstime -a                 # List by access time
  lstime --tui ~/Documents  # Interactive mode for Documents
  lstime -rH                # Oldest first, show hidden
"""
    print(help_text)


def main():
    """Main entry point."""
    args = sys.argv[1:]

    path = None
    sort_by = "created"
    reverse = True
    show_hidden = False
    force_tui = None

    i = 0
    while i < len(args):
        arg = args[i]

        if arg in ("-h", "--help"):
            print_help()
            sys.exit(0)
        elif arg in ("-c", "--created"):
            sort_by = "created"
        elif arg in ("-a", "--accessed"):
            sort_by = "accessed"
        elif arg in ("-r", "--reverse"):
            reverse = not reverse
        elif arg in ("-H", "--hidden"):
            show_hidden = True
        elif arg == "--tui":
            force_tui = True
        elif arg == "--no-tui":
            force_tui = False
        elif not arg.startswith("-"):
            path = Path(arg).expanduser().resolve()
        else:
            print(f"Unknown option: {arg}")
            print("Use --help for usage information")
            sys.exit(1)

        i += 1

    if path and not path.exists():
        print(f"Error: Path does not exist: {path}")
        sys.exit(1)

    use_tui = force_tui if force_tui is not None else (HAS_TEXTUAL and sys.stdout.isatty())

    if use_tui and HAS_TEXTUAL:
        app = LstimeApp(path)
        app.sort_by = sort_by
        app.reverse_order = reverse
        app.show_hidden = show_hidden
        app.run()
    elif HAS_RICH:
        rich_display(path, sort_by, reverse, show_hidden)
    else:
        plain_display(path, sort_by, reverse, show_hidden)


if __name__ == "__main__":
    main()
