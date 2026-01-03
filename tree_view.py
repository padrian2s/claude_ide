#!/usr/bin/env python3
"""Tree view with file viewer using Textual - split layout."""

import base64
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

# Session paths config file
SESSION_PATHS_FILE = Path(__file__).parent / ".tui_session_paths.json"


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
    SESSION_PATHS_FILE.write_text(json.dumps(data, indent=2))


from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Static, Header, Markdown, ListView, ListItem, Label, ProgressBar, Input
from textual.widgets._directory_tree import DirEntry
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import ModalScreen
from rich.syntax import Syntax
from rich.text import Text
from rich.console import Group

from config_panel import get_border_style


def format_size(size: int) -> str:
    """Format file size in human readable format, right-aligned to 6 chars."""
    if size < 1024:
        return f"{size:>5}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:>5.1f}K"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):>5.1f}M"
    else:
        return f"{size / (1024 * 1024 * 1024):>5.1f}G"


# Width for name column to align sizes (narrow / wide)
NAME_WIDTH_NARROW = 25
NAME_WIDTH_WIDE = 50


class SizedDirectoryTree(DirectoryTree):
    """DirectoryTree with file sizes displayed."""

    name_width = NAME_WIDTH_NARROW

    def render_label(self, node, base_style, style):
        """Render label with right-aligned size column."""
        path = node.data.path
        label = Text()
        name = str(node.label)
        width = self.name_width

        # Get icon and name
        if path.is_dir():
            icon = "📁 " if node.is_expanded else "📂 "
            label.append(icon)
            label.append(name, style=style)
        else:
            icon = "📄 "

            # Truncate or pad name to fixed width
            if len(name) > width:
                name = name[:width-1] + "…"

            label.append(icon)
            label.append(f"{name:<{width}}", style=style)

            # Add right-aligned size
            try:
                size = path.stat().st_size
                size_str = format_size(size)
                label.append(f" {size_str}", style="dim")
            except (OSError, PermissionError):
                label.append("      ?", style="dim")

        return label


class FileItem(ListItem):
    """A file/directory item for the dual panel."""

    def __init__(self, path: Path, is_selected: bool = False, is_parent: bool = False):
        super().__init__()
        self.path = path
        self.is_selected = is_selected
        self.is_parent = is_parent

    def compose(self) -> ComposeResult:
        yield Static(self._render_content(), id="item-content", markup=False)

    def _render_content(self) -> str:
        # Parent directory shows as ".."
        if self.is_parent:
            return "   📁 .."

        is_dir = self.path.is_dir()
        icon = "📁" if is_dir else "📄"
        mark = "●" if self.is_selected else " "
        name = self.path.name or str(self.path)

        try:
            size = "" if is_dir else format_size(self.path.stat().st_size)
        except:
            size = ""

        return f"{mark} {icon} {name:<30} {size}"

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
        icon = "📁" if is_dir else "📄"
        try:
            size = "" if is_dir else format_size(self.path.stat().st_size)
        except:
            size = ""
        yield Static(f" {icon} {self.path.name:<35} {size}")


class SearchDialog(ModalScreen):
    """Popup search dialog - fzf style."""

    CSS = """
    SearchDialog {
        align: center middle;
    }
    #search-dialog {
        width: 60;
        height: 20;
        border: solid cyan;
        background: $surface;
    }
    #search-title {
        height: 1;
        padding: 0 1;
        background: $primary;
    }
    #search-input {
        margin: 0 1;
    }
    #search-results {
        height: 1fr;
        margin: 0 1 1 1;
        border: solid gray;
    }
    #search-results:focus {
        border: solid cyan;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "select_first", "Select First"),
    ]

    def __init__(self, items: list[Path]):
        super().__init__()
        self.all_items = items
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="search-dialog"):
            yield Label(" 🔍 Search (case-sensitive)", id="search-title")
            yield Input(placeholder="Type to filter...", id="search-input")
            yield ListView(id="search-results")

    def on_mount(self):
        self._refresh_results()
        self.query_one("#search-input", Input).focus()

    def _refresh_results(self):
        results = self.query_one("#search-results", ListView)
        results.clear()
        for path in self.all_items:
            if not self.filter_text or self.filter_text in path.name:
                results.append(SearchItem(path))

    def on_input_changed(self, event: Input.Changed):
        self.filter_text = event.value
        self._refresh_results()

    def on_input_submitted(self, event: Input.Submitted):
        """Enter in input - select first result."""
        results = self.query_one("#search-results", ListView)
        if results.children:
            results.index = 0
            item = results.children[0]
            if isinstance(item, SearchItem):
                self.dismiss(item.path)

    def on_list_view_selected(self, event: ListView.Selected):
        """Enter on item - return it."""
        if isinstance(event.item, SearchItem):
            self.dismiss(event.item.path)

    def action_cancel(self):
        self.dismiss(None)

    def action_select_first(self):
        """Tab - auto-select if single result, otherwise focus list to choose."""
        results = self.query_one("#search-results", ListView)
        if not results.children:
            return
        
        if len(results.children) == 1:
            # Single result - auto-select and close
            item = results.children[0]
            if isinstance(item, SearchItem):
                self.dismiss(item.path)
        else:
            # Multiple results - focus list for user to choose
            results.index = 0
            results.focus()


class ConfirmDialog(ModalScreen):
    """Confirmation dialog."""

    CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: 10;
        border: solid red;
        background: $surface;
        padding: 1 2;
    }
    #confirm-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #confirm-message {
        text-align: center;
        margin-bottom: 1;
    }
    #confirm-buttons {
        align: center middle;
        height: 3;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
    ]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.dialog_title = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.dialog_title, id="confirm-title")
            yield Label(self.message, id="confirm-message")
            yield Label("[y] Yes  [n] No  [Esc] Cancel", id="confirm-buttons")

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class RenameDialog(ModalScreen):
    """Rename dialog with input."""

    CSS = """
    RenameDialog {
        align: center middle;
    }
    #rename-dialog {
        width: 80%;
        max-width: 100;
        height: auto;
        border: double cyan;
        background: $surface;
        padding: 1 2;
    }
    #rename-title {
        text-align: center;
        text-style: bold;
        color: cyan;
        margin-bottom: 1;
    }
    #rename-input {
        margin-bottom: 1;
        border: solid white;
    }
    #rename-help {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_name: str):
        super().__init__()
        self.current_name = current_name

    def compose(self) -> ComposeResult:
        with Vertical(id="rename-dialog"):
            yield Label("✏ Rename", id="rename-title")
            yield Input(value=self.current_name, id="rename-input")
            yield Label("[Enter] Confirm  [Esc] Cancel", id="rename-help")

    def on_mount(self):
        input_widget = self.query_one("#rename-input", Input)
        input_widget.focus()
        # Select filename without extension
        name = self.current_name
        if "." in name and not name.startswith("."):
            dot_pos = name.rfind(".")
            input_widget.selection = (0, dot_pos)
        else:
            input_widget.selection = (0, len(name))

    def on_input_submitted(self, event: Input.Submitted):
        new_name = event.value.strip()
        if new_name and new_name != self.current_name:
            self.dismiss(new_name)
        else:
            self.dismiss(None)

    def action_cancel(self):
        self.dismiss(None)


class DualPanelScreen(ModalScreen):
    """Dual panel file manager for copying files."""

    # Session persistence - class variables to remember paths, sort, and cursor per panel
    _session_left_path: Path = None
    _session_right_path: Path = None
    _session_sort_left: bool = False  # False = name, True = date
    _session_sort_right: bool = False
    _session_left_index: int = 1  # Start on first real item (skip ..)
    _session_right_index: int = 1
    _initial_start_path: Path = None  # Original path when tool started

    CSS = """
    DualPanelScreen {
        align: center middle;
    }
    #dual-container {
        width: 95%;
        height: 90%;
        background: $surface;
        border: solid $primary;
    }
    #dual-title {
        height: 1;
        text-align: center;
        text-style: bold;
        background: $primary;
    }
    #panels {
        height: 1fr;
    }
    .panel {
        width: 50%;
        height: 100%;
        border: solid gray;
    }
    .panel:focus-within {
        border: solid green;
    }
    .panel-header {
        height: 1;
        background: $primary-background;
        padding: 0 1;
    }
    .panel-list {
        height: 1fr;
    }
    #progress-container {
        height: 3;
        padding: 0 1;
        display: none;
    }
    #progress-container.visible {
        display: block;
    }
    #help-bar {
        height: 1;
        background: $primary-background;
        text-align: center;
    }
    ListItem {
        padding: 0;
    }
    """

    BINDINGS = [
        ("escape", "cancel_or_close", "Close"),
        ("q", "close", "Close"),
        Binding("ctrl+s", "start_search", "Search", priority=True),
        ("tab", "switch_panel", "Switch"),
        ("space", "toggle_select", "Select"),
        ("backspace", "go_up", "Up"),
        ("c", "copy_selected", "Copy"),
        ("a", "select_all", "All"),
        ("s", "toggle_sort", "Sort"),
        ("r", "rename", "Rename"),
        ("d", "delete", "Delete"),
        Binding("g", "toggle_position", "g=jump"),
        ("pageup", "page_up", "PgUp"),
        ("pagedown", "page_down", "PgDn"),
        ("h", "go_home", "Home"),
        ("i", "sync_panels", "Sync"),
        ("v", "view_file", "View"),
    ]

    def __init__(self, start_path: Path = None):
        super().__init__()
        # Store initial start path (only once, when tool first starts)
        if DualPanelScreen._initial_start_path is None:
            DualPanelScreen._initial_start_path = start_path or Path.cwd()

        home_key = str(DualPanelScreen._initial_start_path)

        # Load saved paths from config (keyed by home path)
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

        # Use session paths if available, otherwise defaults
        if DualPanelScreen._session_left_path:
            self.left_path = DualPanelScreen._session_left_path
        else:
            self.left_path = start_path or Path.cwd()

        if DualPanelScreen._session_right_path:
            self.right_path = DualPanelScreen._session_right_path
        else:
            self.right_path = Path.home()

        self.sort_left = DualPanelScreen._session_sort_left
        self.sort_right = DualPanelScreen._session_sort_right
        self.selected_left: set[Path] = set()
        self.selected_right: set[Path] = set()
        self.active_panel = "left"
        self.copying = False

    def compose(self) -> ComposeResult:
        with Vertical(id="dual-container"):
            yield Label("File Manager", id="dual-title")
            with Horizontal(id="panels"):
                with Vertical(id="left-panel", classes="panel"):
                    yield Static("", id="left-path", classes="panel-header")
                    yield ListView(id="left-list", classes="panel-list")
                with Vertical(id="right-panel", classes="panel"):
                    yield Static("", id="right-path", classes="panel-header")
                    yield ListView(id="right-list", classes="panel-list")
            with Vertical(id="progress-container"):
                yield Static("", id="progress-text")
                yield ProgressBar(id="progress-bar", total=100)
            yield Label("^S:search  Space:sel  v:view  c:copy  r:ren  d:del  a:all  s:sort  h:home  i:sync  g:jump  q:close", id="help-bar")

    def on_mount(self):
        self.refresh_panels()
        self._update_title()
        # Restore cursor positions from session
        left_list = self.query_one("#left-list", ListView)
        right_list = self.query_one("#right-list", ListView)
        # Set left cursor (clamp to valid range)
        if left_list.children:
            max_left = len(left_list.children) - 1
            left_list.index = min(DualPanelScreen._session_left_index, max_left)
        # Set right cursor
        if right_list.children:
            max_right = len(right_list.children) - 1
            right_list.index = min(DualPanelScreen._session_right_index, max_right)
        left_list.focus()

    def _update_title(self):
        """Update title - sort shown per panel in headers."""
        self.query_one("#dual-title", Label).update("File Manager  \\[s:toggle sort\\]")

    def refresh_panels(self):
        """Refresh both panel contents."""
        self._refresh_panel("left", self.left_path, self.selected_left)
        self._refresh_panel("right", self.right_path, self.selected_right)

    def _refresh_panel(self, side: str, path: Path, selected: set):
        """Refresh a single panel."""
        list_view = self.query_one(f"#{side}-list", ListView)
        path_label = self.query_one(f"#{side}-path", Static)

        # Get sort setting for this panel
        sort_by_date = self.sort_left if side == "left" else self.sort_right

        # Show path with sort indicator
        sort_icon = "⏱" if sort_by_date else "🔤"
        path_label.update(f"{sort_icon} {path}")
        list_view.clear()

        try:
            # Add ".." parent directory entry
            if path.parent != path:
                list_view.append(FileItem(path.parent, is_selected=False, is_parent=True))

            # List contents with sorting
            all_items = [p for p in path.iterdir() if not p.name.startswith(".")]

            if sort_by_date:
                # Sort by access time (most recent first), dirs first
                def sort_key(p):
                    try:
                        atime = p.stat().st_atime
                    except:
                        atime = 0
                    return (not p.is_dir(), -atime)
            else:
                # Sort by name, dirs first
                def sort_key(p):
                    return (not p.is_dir(), p.name.lower())

            items = sorted(all_items, key=sort_key)
            for item in items:
                list_view.append(FileItem(item, item in selected))
        except PermissionError:
            pass

    def _refresh_single_panel(self, side: str):
        """Refresh only one panel and set cursor."""
        if side == "left":
            self._refresh_panel("left", self.left_path, self.selected_left)
        else:
            self._refresh_panel("right", self.right_path, self.selected_right)

        # Set cursor after refresh
        list_view = self.query_one(f"#{side}-list", ListView)
        self.set_timer(0.01, lambda: self._set_cursor(list_view))

    def _save_paths_to_config(self):
        """Save current paths to config file (called on every path change)."""
        home_key = str(DualPanelScreen._initial_start_path or Path.cwd())
        save_session_paths(home_key, self.left_path, self.right_path)

    def _set_cursor(self, list_view: ListView):
        """Set cursor to first real item."""
        if len(list_view.children) > 1:
            list_view.index = 1
        elif list_view.children:
            list_view.index = 0
        list_view.focus()

    def action_close(self):
        if not self.copying:
            # Save paths, sort settings, and cursor positions for session persistence
            DualPanelScreen._session_left_path = self.left_path
            DualPanelScreen._session_right_path = self.right_path
            DualPanelScreen._session_sort_left = self.sort_left
            DualPanelScreen._session_sort_right = self.sort_right
            # Save cursor positions
            left_list = self.query_one("#left-list", ListView)
            right_list = self.query_one("#right-list", ListView)
            DualPanelScreen._session_left_index = left_list.index if left_list.index is not None else 1
            DualPanelScreen._session_right_index = right_list.index if right_list.index is not None else 1
            # Save paths to config file (keyed by home path)
            home_key = str(DualPanelScreen._initial_start_path or Path.cwd())
            save_session_paths(home_key, self.left_path, self.right_path)
            self.dismiss()

    def action_cancel_or_close(self):
        """Close dialog if not copying."""
        if not self.copying:
            self.action_close()

    def action_start_search(self):
        """Open search dialog."""
        # Get items from active panel
        if self.active_panel == "left":
            path = self.left_path
        else:
            path = self.right_path

        try:
            items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            items = []

        def handle_result(selected_path: Path | None):
            if selected_path:
                # Navigate to selected item
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
                    # File selected - scroll to it in list
                    list_view = self.query_one(f"#{self.active_panel}-list", ListView)
                    for i, child in enumerate(list_view.children):
                        if isinstance(child, FileItem) and child.path == selected_path:
                            list_view.index = i
                            break
            # Refocus on list
            list_view = self.query_one(f"#{self.active_panel}-list", ListView)
            list_view.focus()

        self.app.push_screen(SearchDialog(items), handle_result)

    def action_toggle_sort(self):
        """Toggle sort for active panel only."""
        if self.active_panel == "left":
            self.sort_left = not self.sort_left
            DualPanelScreen._session_sort_left = self.sort_left
        else:
            self.sort_right = not self.sort_right
            DualPanelScreen._session_sort_right = self.sort_right
        # Refresh only active panel
        self._refresh_single_panel(self.active_panel)

    def action_switch_panel(self):
        """Switch focus between panels."""
        if self.active_panel == "left":
            self.active_panel = "right"
            self.query_one("#right-list", ListView).focus()
        else:
            self.active_panel = "left"
            self.query_one("#left-list", ListView).focus()

    def action_toggle_select(self):
        """Toggle selection of current item and move to next."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        selected = self.selected_left if self.active_panel == "left" else self.selected_right

        if list_view.highlighted_child and isinstance(list_view.highlighted_child, FileItem):
            item = list_view.highlighted_child
            # Don't select parent dir
            if item.path.name:
                if item.path in selected:
                    selected.discard(item.path)
                    item.update_selection(False)
                else:
                    selected.add(item.path)
                    item.update_selection(True)
                # Move to next item
                if list_view.index < len(list_view.children) - 1:
                    list_view.index += 1

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle Enter key - enter directory."""
        if isinstance(event.item, FileItem):
            item = event.item
            if item.path.is_dir():
                # Determine which panel based on the list's id
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
                # Refresh only the active panel
                self._refresh_single_panel(self.active_panel)
                self._save_paths_to_config()

    def action_go_up(self):
        """Go to parent directory."""
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
        """Reset active panel to initial start path (h key)."""
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
        """Set other panel to same path as active panel (i key)."""
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
        self.notify(f"Synced panels", timeout=1)

    def action_select_all(self):
        """Toggle select all / unselect all in current panel."""
        path = self.left_path if self.active_panel == "left" else self.right_path
        selected = self.selected_left if self.active_panel == "left" else self.selected_right

        try:
            all_items = {item for item in path.iterdir() if not item.name.startswith(".")}
            # If all are selected, unselect all; otherwise select all
            if all_items and all_items <= selected:
                selected.clear()
            else:
                selected.update(all_items)
        except:
            pass
        self._refresh_single_panel(self.active_panel)

    def action_select_none(self):
        """Clear selection in current panel."""
        if self.active_panel == "left":
            self.selected_left.clear()
        else:
            self.selected_right.clear()
        self._refresh_single_panel(self.active_panel)

    def action_go_first(self):
        """Go to first item in list."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if list_view.children:
            list_view.index = 0
            list_view.focus()
            list_view.scroll_home(animate=False)

    def action_go_last(self):
        """Go to last item in list."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if list_view.children:
            list_view.index = len(list_view.children) - 1
            list_view.focus()
            list_view.scroll_end(animate=False)

    def action_toggle_position(self):
        """Toggle between first and last item."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if list_view.children:
            current = list_view.index if list_view.index is not None else 0
            if current == 0:
                # At first, go to last
                list_view.index = len(list_view.children) - 1
                list_view.scroll_end(animate=False)
            else:
                # Go to first
                list_view.index = 0
                list_view.scroll_home(animate=False)
            list_view.focus()

    def action_page_up(self):
        """Move up by visible page size."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if list_view.children:
            current = list_view.index if list_view.index is not None else 0
            page_size = max(1, list_view.size.height - 2)
            new_index = max(0, current - page_size)
            list_view.index = new_index
            list_view.focus()

    def action_page_down(self):
        """Move down by visible page size."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if list_view.children:
            current = list_view.index if list_view.index is not None else 0
            page_size = max(1, list_view.size.height - 2)
            new_index = min(len(list_view.children) - 1, current + page_size)
            list_view.index = new_index
            list_view.focus()

    def action_copy_selected(self):
        """Copy selected files to other panel."""
        if self.copying:
            return

        # Get source and destination
        if self.active_panel == "left":
            selected = self.selected_left.copy()
            dest_path = self.right_path
        else:
            selected = self.selected_right.copy()
            dest_path = self.left_path

        used_explicit_selection = bool(selected)

        # If nothing selected, use highlighted item
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

        # Show progress
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
                    self.app.call_from_thread(
                        progress_text.update,
                        f"Copying: {src.name} ({i+1}/{total})"
                    )
                    self.app.call_from_thread(
                        progress_bar.update,
                        progress=int(((i + 0.5) / total) * 100)
                    )

                    if src.is_dir():
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dest)
                        
                    self.app.call_from_thread(
                        progress_bar.update,
                        progress=int(((i + 1) / total) * 100)
                    )
                except Exception as e:
                    self.app.call_from_thread(
                        self.notify,
                        f"Error copying {src.name}: {e}",
                        timeout=5
                    )

            self.app.call_from_thread(self._copy_complete)

        thread = threading.Thread(target=do_copy, daemon=True)
        thread.start()

    def _copy_complete(self):
        """Called when copy is complete."""
        self.copying = False
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_text = self.query_one("#progress-text", Static)
        progress_container = self.query_one("#progress-container")

        progress_bar.update(progress=100)
        progress_text.update("✓ Copy complete!")
        self.notify("Copy complete!", timeout=2)

        # Only clear selections if explicit selection was used
        if getattr(self, '_copy_used_explicit_selection', False):
            self.selected_left.clear()
            self.selected_right.clear()
        
        self.refresh_panels()

        # Hide progress after delay
        self.set_timer(2, lambda: progress_container.remove_class("visible"))


    def action_rename(self):
        """Rename the currently highlighted file/folder."""
        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if not list_view.highlighted_child:
            self.notify("No item to rename", timeout=2)
            return
        
        item = list_view.highlighted_child
        if not isinstance(item, FileItem):
            self.notify("Cannot rename this item", timeout=2)
            return
        
        if item.is_parent:
            self.notify("Cannot rename '..'", timeout=2)
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
        """Delete selected files/folders with confirmation."""
        # Get selected items or current item
        if self.active_panel == "left":
            selected = self.selected_left.copy()
            path = self.left_path
        else:
            selected = self.selected_right.copy()
            path = self.right_path
        
        # Track if explicit selection was used
        used_explicit_selection = bool(selected)
        
        # If nothing selected, use highlighted item
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
        
        if count == 1:
            message = f"Delete '{items[0].name}'?"
        else:
            message = f"Delete {count} items?"
        
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
                
                # Only clear selections if explicit selection was used
                if used_explicit_selection:
                    self.selected_left.clear()
                    self.selected_right.clear()
                self._refresh_single_panel(self.active_panel)
        
        self.app.push_screen(ConfirmDialog("⚠ Delete", message), handle_confirm)

    def action_view_file(self):
        """Toggle file viewer - open if closed, close if open."""
        # Check if FileViewerScreen is already open
        for screen in self.app.screen_stack:
            if isinstance(screen, FileViewerScreen):
                screen.dismiss()
                return

        list_view = self.query_one(f"#{self.active_panel}-list", ListView)
        if not list_view.highlighted_child:
            self.notify("No file selected", timeout=2)
            return

        item = list_view.highlighted_child
        if not isinstance(item, FileItem):
            return

        if item.is_parent:
            self.notify("Cannot view '..'", timeout=2)
            return

        if item.path.is_dir():
            self.notify("Cannot view directory", timeout=2)
            return

        # Image files - display with imgcat (iTerm2)
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.tiff', '.tif', '.svg'}
        if item.path.suffix.lower() in image_extensions:
            self._view_image(item.path)
            return

        self.app.push_screen(FileViewerScreen(item.path))

    def _view_image(self, path: Path):
        """Display image using imgcat (iTerm2) with suspend."""
        imgcat_path = "/Applications/iTerm.app/Contents/Resources/utilities/imgcat"

        def show_image():
            # Enable tmux passthrough for iTerm2 escape sequences
            in_tmux = os.environ.get("TMUX")
            if in_tmux:
                subprocess.run(["tmux", "set", "-p", "allow-passthrough", "on"],
                             capture_output=True)

            print(f"\n📷 {path.name}\n{'─' * 50}\n")
            subprocess.run([imgcat_path, str(path)])
            print("\n\nPress Enter to return...")
            input()

        if Path(imgcat_path).exists():
            with self.app.suspend():
                show_image()
        else:
            # Fallback: open with system viewer
            subprocess.run(["open", str(path)])
            self.notify(f"Opened: {path.name}", timeout=2)


class FileViewer(VerticalScroll):
    """Scrollable file content viewer with syntax highlighting."""

    file_path = reactive(None)
    MARKDOWN_EXTENSIONS = {'.md', '.markdown', '.mdown', '.mkd'}

    def compose(self) -> ComposeResult:
        yield Static("", id="file-content")
        yield Markdown("", id="md-content")

    def on_mount(self):
        self.query_one("#md-content").display = False

    # Map file extensions to lexer names
    LEXER_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.jsx': 'jsx',
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.html': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.md': 'markdown',
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'zsh',
        '.sql': 'sql',
        '.rs': 'rust',
        '.go': 'go',
        '.rb': 'ruby',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.toml': 'toml',
        '.xml': 'xml',
        '.vue': 'vue',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.lua': 'lua',
        '.r': 'r',
        '.dockerfile': 'dockerfile',
        '.hs': 'haskell',
        '.lhs': 'haskell',
        '.scala': 'scala',
        '.sc': 'scala',
        '.ex': 'elixir',
        '.exs': 'elixir',
        '.nim': 'nim',
        '.nims': 'nim',
        '.clj': 'clojure',
        '.cljs': 'clojure',
        '.erl': 'erlang',
        '.hrl': 'erlang',
        '.ml': 'ocaml',
        '.mli': 'ocaml',
        '.fs': 'fsharp',
        '.fsx': 'fsharp',
        '.zig': 'zig',
        '.dart': 'dart',
        '.groovy': 'groovy',
        '.gradle': 'groovy',
        '.pl': 'perl',
        '.pm': 'perl',
        '.tcl': 'tcl',
        '.v': 'v',
        '.cr': 'crystal',
        '.jl': 'julia',
    }

    def load_file(self, path: Path):
        self.file_path = path
        is_markdown = path.suffix.lower() in self.MARKDOWN_EXTENSIONS

        static_widget = self.query_one("#file-content", Static)
        md_widget = self.query_one("#md-content", Markdown)

        # Image extensions (can be displayed in iTerm2)
        image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp', '.tiff', '.tif'}

        # Binary file extensions that can't be displayed as text
        binary_extensions = {'.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
                           '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
                           '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.wav', '.flac',
                           '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}

        suffix = path.suffix.lower()

        # Display images using imgcat (iTerm2)
        if suffix in image_extensions:
            static_widget.display = True
            md_widget.display = False
            static_widget.update(f"[bold magenta]📷 {path.name}[/bold magenta]\n\n[dim]Press 'o' to open image, or use File Manager to view[/dim]")
            self.scroll_home()
            return

        if suffix in binary_extensions:
            static_widget.display = True
            md_widget.display = False
            static_widget.update(f"[yellow]Binary file: {path.name}[/yellow]\n\n[dim]Cannot display {suffix} files in viewer.[/dim]")
            self.scroll_home()
            return

        try:
            with open(path, 'r', errors='replace') as f:
                code = f.read()

            # Markdown files use dedicated Markdown widget
            if is_markdown:
                static_widget.display = False
                md_widget.display = True
                md_widget.update(code)
            else:
                static_widget.display = True
                md_widget.display = False

                line_count = len(code.splitlines())

                # Check for Dockerfile without extension
                lexer = self.LEXER_MAP.get(suffix)
                if lexer is None and path.name.lower() == 'dockerfile':
                    lexer = 'dockerfile'

                # Header
                header = Text()
                header.append(f"{path.name}", style="bold magenta")
                header.append(f" ({line_count} lines)", style="dim")
                header.append("\n" + "─" * 50 + "\n", style="dim")

                if lexer:
                    # Use syntax highlighting with header
                    syntax = Syntax(
                        code,
                        lexer,
                        theme="monokai",
                        line_numbers=True,
                        word_wrap=False,
                    )
                    static_widget.update(Group(header, syntax))
                else:
                    # Plain text with line numbers (no syntax highlighting)
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
        self.query_one("#file-content", Static).update(
            "[dim]Select a file from the tree to view[/dim]"
        )


class FileViewerScreen(ModalScreen):
    """Modal screen for viewing a file."""

    CSS = """
    FileViewerScreen {
        align: center middle;
    }
    #viewer-container {
        width: 95%;
        height: 95%;
        background: $surface;
        border: solid $primary;
    }
    #viewer-header {
        height: 1;
        background: $primary;
        text-align: center;
        text-style: bold;
    }
    #viewer-content {
        height: 1fr;
    }
    #viewer-help {
        height: 1;
        background: $primary-background;
        text-align: center;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("v", "close", "Close"),
    ]

    def __init__(self, file_path: Path):
        super().__init__()
        self.file_path = file_path

    def compose(self) -> ComposeResult:
        with Vertical(id="viewer-container"):
            yield Label(f"📄 {self.file_path.name}", id="viewer-header")
            yield FileViewer(id="viewer-content")
            yield Label("v/q/Esc: close  ↑↓: scroll", id="viewer-help")

    def on_mount(self):
        viewer = self.query_one("#viewer-content", FileViewer)
        viewer.load_file(self.file_path)

    def action_close(self):
        self.dismiss()


class TreeViewApp(App):
    CSS = """
    #main {
        width: 100%;
        height: 100%;
    }
    #tree-panel {
        height: 100%;
        border-right: solid $primary;
    }
    #viewer-panel {
        height: 100%;
    }
    DirectoryTree {
        width: 100%;
        height: 100%;
        background: $surface;
    }
    FileViewer {
        width: 100%;
        height: 100%;
        background: $surface;
        padding: 0 1;
    }
    #file-content {
        width: 100%;
    }
    #md-content {
        width: 100%;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+f", "fzf_files", "Find File", priority=True),
        Binding("/", "fzf_grep", "Grep", priority=True),
        Binding("tab", "toggle_focus", "Switch Panel"),
        Binding("w", "toggle_width", "Wide"),
        Binding("[", "shrink_tree", "Shrink"),
        Binding("]", "grow_tree", "Grow"),
        Binding("o", "open_system", "Open"),
        Binding("m", "file_manager", "Manager"),
        Binding("g", "toggle_position", "g=jump"),
        Binding("backspace", "go_parent", "Parent"),
    ]

    # Tree panel width in percent (10-80)
    tree_width = reactive(35)

    def __init__(self, start_path: Path = None):
        super().__init__()
        self.start_path = start_path or Path.cwd()
        # Apply border style from config
        border_style = get_border_style()
        if border_style != "solid":
            self.CSS = self.CSS.replace("border-right: solid", f"border-right: {border_style}")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="tree-panel"):
                yield SizedDirectoryTree(self.start_path, id="tree")
            with Vertical(id="viewer-panel"):
                yield FileViewer()

    def on_mount(self):
        tree = self.query_one("#tree", SizedDirectoryTree)
        tree.focus()
        self.query_one(FileViewer).clear()
        self.title = "Tree + Viewer"
        self.sub_title = "^F:find /:grep m:manager o:open w:wide []:resize g:jump q:quit"
        # Set initial panel widths
        self._update_panel_widths()

    def watch_tree_width(self, width: int):
        """Called when tree_width changes."""
        self._update_panel_widths()

    def _update_panel_widths(self):
        """Update panel widths based on tree_width."""
        try:
            tree_panel = self.query_one("#tree-panel")
            viewer_panel = self.query_one("#viewer-panel")
            tree = self.query_one("#tree", SizedDirectoryTree)

            tree_panel.styles.width = f"{self.tree_width}%"
            viewer_panel.styles.width = f"{100 - self.tree_width}%"

            # Update name width based on tree width
            tree.name_width = NAME_WIDTH_WIDE if self.tree_width >= 40 else NAME_WIDTH_NARROW
            tree.refresh()
        except Exception:
            pass  # Widgets not yet mounted

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected):
        viewer = self.query_one(FileViewer)
        viewer.load_file(event.path)

    def action_toggle_focus(self):
        tree = self.query_one("#tree", SizedDirectoryTree)
        viewer = self.query_one(FileViewer)
        if tree.has_focus:
            viewer.focus()
        else:
            tree.focus()

    def action_refresh(self):
        tree = self.query_one("#tree", SizedDirectoryTree)
        tree.reload()
        self.notify("Tree refreshed", timeout=1)

    def action_toggle_width(self):
        """Toggle tree panel between narrow (35%) and wide (50%)."""
        if self.tree_width < 50:
            self.tree_width = 50
        else:
            self.tree_width = 35
        self.notify(f"Tree: {self.tree_width}%", timeout=1)

    def action_shrink_tree(self):
        """Shrink tree panel by 5%."""
        if self.tree_width > 10:
            self.tree_width = max(10, self.tree_width - 5)
            self.notify(f"Tree: {self.tree_width}%", timeout=1)

    def action_grow_tree(self):
        """Grow tree panel by 5%."""
        if self.tree_width < 80:
            self.tree_width = min(80, self.tree_width + 5)
            self.notify(f"Tree: {self.tree_width}%", timeout=1)

    def action_open_system(self):
        """Open selected file/folder with system default app."""
        tree = self.query_one("#tree", SizedDirectoryTree)
        if tree.cursor_node and tree.cursor_node.data:
            path = tree.cursor_node.data.path
            subprocess.run(["open", str(path)])
            self.notify(f"Opened: {path.name}", timeout=1)

    def action_fzf_files(self):
        """Fuzzy find files with fzf."""
        with self.suspend():
            result = subprocess.run(
                ["fzf", "--preview", "head -100 {}"],
                capture_output=True,
                text=True
            )
            selected = result.stdout.strip()

        if selected:
            path = Path(selected).resolve()
            tree = self.query_one("#tree", SizedDirectoryTree)
            
            # Find node matching this path
            def find_node(node):
                if hasattr(node, 'data') and node.data and hasattr(node.data, 'path'):
                    try:
                        if node.data.path.resolve() == path:
                            return node
                    except:
                        pass
                for child in node.children:
                    found = find_node(child)
                    if found:
                        return found
                return None
            
            target_node = find_node(tree.root)
            
            if target_node:
                # Node exists - just select it
                tree.move_cursor(target_node)
                tree.scroll_to_node(target_node)
            else:
                # Node not found - change tree root to file's parent directory
                tree.path = path.parent
                
                # After tree reloads, try to select the file
                def select_after_reload():
                    node = find_node(tree.root)
                    if node:
                        tree.move_cursor(node)
                        tree.scroll_to_node(node)
                
                self.set_timer(0.2, select_after_reload)
            
            # Load the file in viewer
            if path.is_file():
                self.query_one(FileViewer).load_file(path)
                self.notify(f"Opened: {path.name}", timeout=1)

    def action_fzf_grep(self):
        """Grep with ripgrep + fzf."""
        with self.suspend():
            # rg outputs: file:line:content
            # fzf preview shows context around the match
            result = subprocess.run(
                'rg -n --color=always "" . 2>/dev/null | fzf --ansi --preview "echo {} | cut -d: -f1 | xargs head -100"',
                shell=True,
                capture_output=True,
                text=True
            )
            selected = result.stdout.strip()

        if selected:
            # Parse file:line:content
            parts = selected.split(":", 2)
            if len(parts) >= 2:
                file_path = Path(parts[0]).resolve()
                tree = self.query_one("#tree", SizedDirectoryTree)
                
                # Find node matching this path
                def find_node(node):
                    if hasattr(node, 'data') and node.data and hasattr(node.data, 'path'):
                        try:
                            if node.data.path.resolve() == file_path:
                                return node
                        except:
                            pass
                    for child in node.children:
                        found = find_node(child)
                        if found:
                            return found
                    return None
                
                target_node = find_node(tree.root)
                
                if target_node:
                    # Node exists - just select it
                    tree.move_cursor(target_node)
                    tree.scroll_to_node(target_node)
                else:
                    # Node not found - change tree root to file's parent directory
                    tree.path = file_path.parent
                    
                    # After tree reloads, try to select the file
                    def select_after_reload():
                        node = find_node(tree.root)
                        if node:
                            tree.move_cursor(node)
                            tree.scroll_to_node(node)
                    
                    self.set_timer(0.2, select_after_reload)
                
                # Load the file in viewer
                if file_path.is_file():
                    self.query_one(FileViewer).load_file(file_path)
                    self.notify(f"Opened: {file_path.name}:{parts[1]}", timeout=1)


    def action_toggle_position(self):
        """Toggle between first and last item in tree."""
        tree = self.query_one("#tree", SizedDirectoryTree)
        if tree.cursor_node:
            # Get all visible nodes
            def get_all_nodes(node, nodes=None):
                if nodes is None:
                    nodes = []
                nodes.append(node)
                if node.is_expanded:
                    for child in node.children:
                        get_all_nodes(child, nodes)
                return nodes
            
            all_nodes = get_all_nodes(tree.root)
            if all_nodes:
                current = tree.cursor_node
                first_node = all_nodes[0]
                last_node = all_nodes[-1]
                
                # Toggle: if at first, go to last; otherwise go to first
                if current == first_node:
                    tree.move_cursor(last_node)
                    tree.scroll_to_node(last_node)
                else:
                    tree.move_cursor(first_node)
                    tree.scroll_to_node(first_node)

    def action_go_parent(self):
        """Navigate to parent directory in tree."""
        tree = self.query_one("#tree", SizedDirectoryTree)
        current_path = tree.path
        parent_path = current_path.parent
        
        if parent_path != current_path:
            tree.path = parent_path
            self.notify(f"📁 {parent_path.name or parent_path}", timeout=1)

    def action_file_manager(self):
        """Open dual panel file manager."""
        tree = self.query_one("#tree", SizedDirectoryTree)
        start_path = self.start_path
        if tree.cursor_node and tree.cursor_node.data:
            node_path = tree.cursor_node.data.path
            start_path = node_path if node_path.is_dir() else node_path.parent
        self.push_screen(DualPanelScreen(start_path))

    def action_quit(self):
        """Quit with confirmation."""
        def handle_confirm(confirmed: bool):
            if confirmed:
                self.exit()
        self.push_screen(ConfirmDialog("Quit", "Exit application?"), handle_confirm)


def main():
    import sys
    start_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    TreeViewApp(start_path=start_path).run()


if __name__ == "__main__":
    main()
