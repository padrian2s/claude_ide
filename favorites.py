#!/usr/bin/env python3
"""Favorites panel - browse folders from ~/work and ~/personal, mark favorites, copy path to clipboard."""

import json
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Static, Label, Input
from textual.containers import Horizontal, Vertical

FAVORITES_FILE = Path(__file__).parent / ".tui_favorites.json"
SOURCE_DIRS = [Path.home() / "work", Path.home() / "personal"]


def load_favorites() -> set:
    """Load favorites from file."""
    if FAVORITES_FILE.exists():
        try:
            return set(json.loads(FAVORITES_FILE.read_text()))
        except Exception:
            pass
    return set()


def save_favorites(favorites: set):
    """Save favorites to file."""
    FAVORITES_FILE.write_text(json.dumps(sorted(favorites), indent=2))


def copy_to_clipboard(text: str):
    """Copy text to clipboard using pbcopy (macOS)."""
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))


def get_folders() -> list[Path]:
    """Get all immediate subdirectories from source dirs."""
    folders = []
    for source in SOURCE_DIRS:
        if source.exists() and source.is_dir():
            for item in sorted(source.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    folders.append(item)
    return folders


class FolderItem(ListItem):
    """A folder item in the list."""

    def __init__(self, path: Path, is_favorite: bool = False, show_star: bool = True):
        super().__init__()
        self.path = path
        self.is_favorite = is_favorite
        self.show_star = show_star

    def compose(self) -> ComposeResult:
        parent = self.path.parent.name
        if self.show_star:
            star = "★" if self.is_favorite else "☆"
            yield Static(f" {star}  {parent}/{self.path.name}")
        else:
            yield Static(f" ★  {parent}/{self.path.name}")


class FavoritesPanel(App):
    """Favorites browser with clipboard copy."""

    CSS = """
    Screen {
        background: $surface;
    }
    #main {
        height: 1fr;
    }
    #left-panel {
        width: 50%;
        height: 100%;
    }
    #right-panel {
        width: 50%;
        height: 100%;
    }
    .panel-title {
        height: 1;
        background: $primary;
        text-align: center;
        text-style: bold;
    }
    #folder-list {
        height: 1fr;
        border: solid gray;
    }
    #folder-list:focus {
        border: solid green;
    }
    #fav-list {
        height: 1fr;
        border: solid gray;
    }
    #fav-list:focus {
        border: solid yellow;
    }
    #search-box {
        height: 1;
        display: none;
        background: $boost;
    }
    #search-box.visible {
        display: block;
    }
    #search-input {
        width: 100%;
    }
    #info {
        height: 3;
        padding: 1;
        background: $primary-background;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:hover {
        background: $accent;
    }
    ListView:focus > ListItem.--highlight {
        background: $accent;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("enter", "add_favorite", "Add ★"),
        ("space", "copy_path", "Copy"),
        ("x", "remove_favorite", "Remove ★"),
        ("tab", "toggle_focus", "Switch Panel"),
        ("r", "refresh", "Refresh"),
        ("/", "start_search", "Search"),
        ("escape", "cancel_search", "Cancel"),
    ]

    def __init__(self):
        super().__init__()
        self.favorites = load_favorites()
        self.all_folders: list[Path] = []
        self.search_active = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Input(placeholder="Type to filter...", id="search-input")
        with Horizontal(id="main"):
            with Vertical(id="left-panel"):
                yield Label(" All Folders ", classes="panel-title")
                yield ListView(id="folder-list")
            with Vertical(id="right-panel"):
                yield Label(" ★ Favorites ", classes="panel-title")
                yield ListView(id="fav-list")
        yield Static("", id="info")
        yield Footer()

    def on_mount(self):
        self.title = "Favorites"
        self.sub_title = "/:search  Enter:add ★  Space:copy  x:remove  TAB:switch  q:quit"
        self.query_one("#search-input", Input).display = False
        self.refresh_lists()
        self.query_one("#folder-list", ListView).focus()

    def refresh_lists(self, filter_text: str = ""):
        """Refresh both lists with optional filter."""
        self.all_folders = get_folders()

        # Filter folders if search active
        if filter_text:
            filter_lower = filter_text.lower()
            folders = [f for f in self.all_folders if filter_lower in f.name.lower()]
        else:
            folders = self.all_folders

        # All folders list
        folder_list = self.query_one("#folder-list", ListView)
        folder_list.clear()
        for folder in folders:
            is_fav = str(folder) in self.favorites
            folder_list.append(FolderItem(folder, is_fav, show_star=True))
        if folders:
            folder_list.index = 0

        # Favorites list (also filter if searching)
        fav_list = self.query_one("#fav-list", ListView)
        fav_list.clear()
        for fav_path in sorted(self.favorites):
            path = Path(fav_path)
            if path.exists():
                if not filter_text or filter_text.lower() in path.name.lower():
                    fav_list.append(FolderItem(path, is_favorite=True, show_star=False))
        if fav_list.children:
            fav_list.index = 0

        self.update_info()

    def update_info(self):
        """Update info panel with current selection."""
        info = self.query_one("#info", Static)

        # Check which list is focused
        folder_list = self.query_one("#folder-list", ListView)
        fav_list = self.query_one("#fav-list", ListView)

        if folder_list.has_focus and folder_list.highlighted_child:
            item = folder_list.highlighted_child
            if isinstance(item, FolderItem):
                status = "★ FAVORITE" if item.is_favorite else "Press Enter to add"
                info.update(f"{item.path}  {status}")
        elif fav_list.has_focus and fav_list.highlighted_child:
            item = fav_list.highlighted_child
            if isinstance(item, FolderItem):
                info.update(f"{item.path}  Press Enter to copy")
        else:
            info.update("TAB to switch panels")

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        """Update info when selection changes."""
        self.update_info()

    def action_toggle_focus(self):
        """Switch focus between panels."""
        folder_list = self.query_one("#folder-list", ListView)
        fav_list = self.query_one("#fav-list", ListView)
        if folder_list.has_focus:
            fav_list.focus()
        else:
            folder_list.focus()
        self.update_info()

    def action_add_favorite(self):
        """Add selected folder to favorites."""
        folder_list = self.query_one("#folder-list", ListView)
        info = self.query_one("#info", Static)

        if folder_list.has_focus and folder_list.highlighted_child:
            item = folder_list.highlighted_child
            if isinstance(item, FolderItem):
                path_str = str(item.path)
                if path_str not in self.favorites:
                    self.favorites.add(path_str)
                    save_favorites(self.favorites)
                    idx = folder_list.index
                    self.refresh_lists()
                    folder_list.index = idx
                    folder_list.focus()
                    info.update(f"Added: {item.path}")

    def action_copy_path(self):
        """Copy selected path to clipboard."""
        folder_list = self.query_one("#folder-list", ListView)
        fav_list = self.query_one("#fav-list", ListView)
        info = self.query_one("#info", Static)

        # Copy from whichever panel is focused
        if folder_list.has_focus and folder_list.highlighted_child:
            item = folder_list.highlighted_child
        elif fav_list.has_focus and fav_list.highlighted_child:
            item = fav_list.highlighted_child
        else:
            return

        if isinstance(item, FolderItem):
            copy_to_clipboard(str(item.path))
            info.update(f"Copied: {item.path}")

    def action_remove_favorite(self):
        """Remove from favorites."""
        fav_list = self.query_one("#fav-list", ListView)
        info = self.query_one("#info", Static)

        if fav_list.highlighted_child:
            item = fav_list.highlighted_child
            if isinstance(item, FolderItem):
                path_str = str(item.path)
                self.favorites.discard(path_str)
                save_favorites(self.favorites)
                idx = max(0, fav_list.index - 1) if fav_list.index else 0
                self.refresh_lists()
                if self.favorites:
                    fav_list.index = idx
                    fav_list.focus()
                info.update(f"Removed: {item.path}")

    def action_refresh(self):
        """Refresh both lists."""
        search_input = self.query_one("#search-input", Input)
        self.refresh_lists(search_input.value if self.search_active else "")

    def action_start_search(self):
        """Start search mode."""
        self.search_active = True
        search_input = self.query_one("#search-input", Input)
        search_input.display = True
        search_input.value = ""
        search_input.focus()

    def action_cancel_search(self):
        """Cancel search and restore full list."""
        if self.search_active:
            self.search_active = False
            search_input = self.query_one("#search-input", Input)
            search_input.display = False
            search_input.value = ""
            self.refresh_lists()
            self.query_one("#folder-list", ListView).focus()

    def on_input_changed(self, event: Input.Changed):
        """Filter list as user types."""
        if self.search_active:
            self.refresh_lists(event.value)

    def on_input_submitted(self, event: Input.Submitted):
        """Select first match and close search."""
        self.search_active = False
        search_input = self.query_one("#search-input", Input)
        search_input.display = False
        folder_list = self.query_one("#folder-list", ListView)
        folder_list.focus()


if __name__ == "__main__":
    app = FavoritesPanel()
    app.run()
