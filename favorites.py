#!/usr/bin/env python3
"""Favorites panel - browse folders from configurable root dirs, mark favorites, copy path to clipboard."""

import json
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Static, Label, Input
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

CONFIG_FILE = Path(__file__).parent / ".tui_favorites.json"
DEFAULT_ROOTS = [str(Path.home() / "work"), str(Path.home() / "personal")]


def load_config() -> dict:
    """Load config from file."""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            # Migration: old format was just a list of favorites
            if isinstance(data, list):
                return {"favorites": data, "roots": DEFAULT_ROOTS}
            return data
        except Exception:
            pass
    return {"favorites": [], "roots": DEFAULT_ROOTS}


def save_config(config: dict):
    """Save config to file."""
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def load_favorites() -> set:
    """Load favorites from config."""
    return set(load_config().get("favorites", []))


def save_favorites(favorites: set):
    """Save favorites to config."""
    config = load_config()
    config["favorites"] = sorted(favorites)
    save_config(config)


def load_roots() -> list[Path]:
    """Load root folders from config."""
    config = load_config()
    return [Path(p) for p in config.get("roots", DEFAULT_ROOTS)]


def save_roots(roots: list[Path]):
    """Save root folders to config."""
    config = load_config()
    config["roots"] = [str(p) for p in roots]
    save_config(config)


def copy_to_clipboard(text: str):
    """Copy text to clipboard using pbcopy (macOS)."""
    process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    process.communicate(text.encode("utf-8"))


def get_folders(roots: list[Path]) -> list[Path]:
    """Get all immediate subdirectories from root dirs."""
    folders = []
    for source in roots:
        if source.exists() and source.is_dir():
            for item in sorted(source.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    folders.append(item)
    return folders


class RootItem(ListItem):
    """A root folder item."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def compose(self) -> ComposeResult:
        exists = "✓" if self.path.exists() else "✗"
        yield Static(f" {exists}  {self.path}")


class ConfirmDialog(ModalScreen):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmDialog { align: center middle; }
    #confirm-dialog { width: 40; height: 7; border: solid red; background: $surface; padding: 1; }
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


class AdminScreen(ModalScreen):
    """Admin screen to manage root folders."""

    CSS = """
    AdminScreen {
        align: center middle;
    }
    #admin-dialog {
        width: 70;
        height: 20;
        border: solid green;
        background: $surface;
        padding: 1;
    }
    #admin-title {
        text-align: center;
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }
    #roots-list {
        height: 1fr;
        border: solid gray;
    }
    #admin-input {
        margin-top: 1;
    }
    #admin-help {
        height: 1;
        margin-top: 1;
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("d", "delete_root", "Delete"),
        ("enter", "add_root", "Add"),
    ]

    def __init__(self, roots: list[Path]):
        super().__init__()
        self.roots = roots

    def compose(self) -> ComposeResult:
        with Vertical(id="admin-dialog"):
            yield Label("⚙ Root Folders", id="admin-title")
            yield ListView(id="roots-list")
            yield Input(placeholder="Add folder path (e.g. ~/projects)", id="admin-input")
            yield Label("Enter:add  d:delete  Esc:close", id="admin-help")

    def on_mount(self):
        self.refresh_roots()

    def refresh_roots(self):
        roots_list = self.query_one("#roots-list", ListView)
        roots_list.clear()
        for root in self.roots:
            roots_list.append(RootItem(root))

    def action_close(self):
        self.dismiss(self.roots)

    def action_delete_root(self):
        roots_list = self.query_one("#roots-list", ListView)
        if roots_list.highlighted_child and isinstance(roots_list.highlighted_child, RootItem):
            path = roots_list.highlighted_child.path
            if path in self.roots:
                self.roots.remove(path)
                self.refresh_roots()

    def action_add_root(self):
        input_widget = self.query_one("#admin-input", Input)
        path_str = input_widget.value.strip()
        if path_str:
            path = Path(path_str).expanduser()
            if path not in self.roots:
                self.roots.append(path)
                self.refresh_roots()
            input_widget.value = ""


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
        ("a", "open_admin", "Admin"),
    ]

    def __init__(self):
        super().__init__()
        self.favorites = load_favorites()
        self.roots = load_roots()
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
        self.sub_title = "/:search  Enter:★  Space:copy  x:remove  a:admin  q:quit"
        self.query_one("#search-input", Input).display = False
        self.refresh_lists()
        self.query_one("#folder-list", ListView).focus()

    def refresh_lists(self, filter_text: str = ""):
        """Refresh both lists with optional filter."""
        self.all_folders = get_folders(self.roots)

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

    def action_open_admin(self):
        """Open admin screen to manage root folders."""
        def handle_admin_result(roots: list[Path] | None):
            if roots is not None:
                self.roots = roots
                save_roots(roots)
                self.refresh_lists()

        self.push_screen(AdminScreen(list(self.roots)), handle_admin_result)

    def action_quit(self):
        """Quit with confirmation."""
        def handle_confirm(confirmed: bool):
            if confirmed:
                self.exit()
        self.push_screen(ConfirmDialog("Quit", "Exit application?"), handle_confirm)


def main():
    FavoritesPanel().run()


if __name__ == "__main__":
    main()
