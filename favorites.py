#!/usr/bin/env python3
"""Favorites panel - browse folders from configurable root dirs, mark favorites, copy path to clipboard."""

import json
import os
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Static, Label, Input, TextArea
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from config_panel import get_textual_theme, get_footer_position, get_show_header

CONFIG_FILE = Path(__file__).parent / ".tui_favorites.json"
DEPS_FILE = Path(__file__).parent / ".tui_dependencies.json"
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


def load_dependencies() -> dict:
    """Load all project dependencies from file."""
    if DEPS_FILE.exists():
        try:
            return json.loads(DEPS_FILE.read_text())
        except Exception:
            pass
    return {}


def save_dependencies(deps: dict):
    """Save all project dependencies to file."""
    DEPS_FILE.write_text(json.dumps(deps, indent=2))


def get_project_deps(project_path: str) -> tuple[list[str], str]:
    """Get dependency chain and instructions for a project."""
    deps = load_dependencies()
    data = deps.get(project_path, {})
    # Handle old format (list) and new format (dict)
    if isinstance(data, list):
        return data, ""
    return data.get("chain", []), data.get("instructions", "")


def save_project_deps(project_path: str, dep_chain: list[str], instructions: str = ""):
    """Save dependency chain and instructions for a project."""
    deps = load_dependencies()
    if dep_chain or instructions:
        deps[project_path] = {"chain": dep_chain, "instructions": instructions}
    elif project_path in deps:
        del deps[project_path]
    save_dependencies(deps)


def has_project_deps(project_path: str) -> bool:
    """Check if a project has dependencies defined."""
    chain, instructions = get_project_deps(project_path)
    return bool(chain) or bool(instructions)


def get_claude_md_content(folder_path: str) -> str | None:
    """Get CLAUDE.md content from a folder if it exists."""
    claude_md = Path(folder_path) / "CLAUDE.md"
    if claude_md.exists():
        try:
            return claude_md.read_text()
        except Exception:
            pass
    return None


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
        dialog.border_subtitle = ""
        with dialog:
            yield Label(self.message, id="confirm-message")

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class AdminScreen(ModalScreen):
    """Admin screen to manage root folders - sqlit style."""

    CSS = """
    * {
        scrollbar-size: 1 1;
    }
    AdminScreen {
        align: center middle;
        background: transparent;
    }
    #admin-dialog {
        width: 60;
        height: 16;
        border: round $primary;
        background: $background;
        padding: 1;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #roots-list {
        height: 1fr;
        border: round $border;
        background: $background;
    }
    #roots-list:focus {
        border: round $primary;
    }
    #admin-input {
        margin-top: 1;
        border: round $border;
    }
    #admin-input:focus {
        border: round $primary;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
    ]

    def __init__(self, roots: list[Path]):
        super().__init__()
        self.roots = roots

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="admin-dialog")
        dialog.border_title = "Root Folders"
        dialog.border_subtitle = ""
        with dialog:
            yield ListView(id="roots-list")
            yield Input(placeholder="Enter path, press Enter to add", id="admin-input")

    def on_mount(self):
        self.refresh_roots()
        self.query_one("#admin-input", Input).focus()

    def refresh_roots(self):
        roots_list = self.query_one("#roots-list", ListView)
        roots_list.clear()
        for root in self.roots:
            roots_list.append(RootItem(root))

    def action_close(self):
        self.dismiss(self.roots)

    def on_input_submitted(self, event: Input.Submitted):
        """Handle Enter key in input to add root."""
        path_str = event.value.strip()
        if path_str:
            path = Path(path_str).expanduser()
            if path not in self.roots:
                self.roots.append(path)
                self.refresh_roots()
            event.input.value = ""

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle Enter on list item to delete."""
        if isinstance(event.item, RootItem):
            path = event.item.path
            if path in self.roots:
                self.roots.remove(path)
                self.refresh_roots()


class DepItem(ListItem):
    """A dependency item in the chain."""

    def __init__(self, path: str, index: int, has_claude_md: bool = False):
        super().__init__()
        self.dep_path = path
        self.index = index
        self.has_claude_md = has_claude_md

    def compose(self) -> ComposeResult:
        icon = "📄" if self.has_claude_md else "📁"
        name = Path(self.dep_path).name
        yield Static(f" {self.index + 1}. {icon} {name}")


class DependencyScreen(ModalScreen):
    """Screen to manage dependency chain for a project - sqlit style."""

    CSS = """
    * {
        scrollbar-size: 1 1;
    }
    DependencyScreen {
        align: center middle;
        background: transparent;
    }
    #dep-dialog {
        width: 70;
        height: 20;
        border: round $primary;
        background: $background;
        padding: 1;

        border-title-align: left;
        border-title-color: $primary;
        border-title-background: $background;
        border-title-style: bold;

        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
        border-subtitle-background: $background;
    }
    #dep-project {
        text-align: center;
        color: $text-muted;
        height: 1;
    }
    #dep-container {
        height: 1fr;
    }
    .list-panel {
        width: 50%;
        height: 100%;
        border: round $border;
        background: $background;
        margin: 0 1;

        border-title-align: left;
        border-title-color: $text-muted;
        border-title-background: $background;
    }
    .list-panel:focus-within {
        border: round $primary;
        border-title-color: $primary;
    }
    #available-list {
        height: 1fr;
        background: $background;
    }
    #chain-list {
        height: 1fr;
        background: $background;
    }
    #instructions-label {
        height: 1;
        margin-top: 1;
        text-style: bold;
    }
    #instructions {
        height: 3;
        border: round $border;
        background: $background;
    }
    #instructions:focus {
        border: round $primary;
    }
    ListView {
        background: $background;
    }
    ListItem.-highlight {
        background: $primary 30%;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("tab", "toggle_focus", "Switch"),
    ]

    def __init__(self, project_path: str, favorites: set):
        super().__init__()
        self.project_path = project_path
        self.favorites = favorites
        self.chain, self.instructions = get_project_deps(project_path)

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="dep-dialog")
        dialog.border_title = "Dependency Chain"
        dialog.border_subtitle = ""
        with dialog:
            yield Label(f"Project: {Path(self.project_path).name}", id="dep-project")
            with Horizontal(id="dep-container"):
                fav_panel = Vertical(classes="list-panel")
                fav_panel.border_title = "★ Favorites (Enter:Add)"
                with fav_panel:
                    yield ListView(id="available-list")
                chain_panel = Vertical(classes="list-panel")
                chain_panel.border_title = "→ Chain (Enter:Remove)"
                with chain_panel:
                    yield ListView(id="chain-list")
            yield Label("📝 Instructions:", id="instructions-label")
            yield TextArea(self.instructions, id="instructions")

    def on_mount(self):
        self.refresh_lists()
        self.query_one("#available-list", ListView).focus()

    def refresh_lists(self):
        # Available favorites (not in chain)
        avail_list = self.query_one("#available-list", ListView)
        avail_list.clear()
        for fav in sorted(self.favorites):
            if fav not in self.chain and fav != self.project_path:
                has_claude = get_claude_md_content(fav) is not None
                item = ListItem(Static(f" {'📄' if has_claude else '📁'} {Path(fav).name}"))
                item.fav_path = fav  # Store path on item
                avail_list.append(item)

        # Chain list
        chain_list = self.query_one("#chain-list", ListView)
        chain_list.clear()
        for i, dep in enumerate(self.chain):
            has_claude = get_claude_md_content(dep) is not None
            chain_list.append(DepItem(dep, i, has_claude))

    def action_toggle_focus(self):
        avail = self.query_one("#available-list", ListView)
        chain = self.query_one("#chain-list", ListView)
        instructions = self.query_one("#instructions", TextArea)
        if avail.has_focus:
            chain.focus()
        elif chain.has_focus:
            instructions.focus()
        else:
            avail.focus()

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle Enter key on list items."""
        avail = self.query_one("#available-list", ListView)
        chain = self.query_one("#chain-list", ListView)
        
        if event.list_view == avail:
            # Add to chain
            item = event.item
            if hasattr(item, 'fav_path'):
                self.chain.append(item.fav_path)
                self.refresh_lists()
        elif event.list_view == chain:
            # Remove from chain
            item = event.item
            if isinstance(item, DepItem) and item.dep_path in self.chain:
                self.chain.remove(item.dep_path)
                self.refresh_lists()

    def action_close(self):
        instructions_text = self.query_one("#instructions", TextArea).text
        save_project_deps(self.project_path, self.chain, instructions_text)
        self.dismiss((self.chain, instructions_text))


class FolderItem(ListItem):
    """A folder item in the list."""

    def __init__(self, path: Path, is_favorite: bool = False, show_star: bool = True, has_chain: bool = False):
        super().__init__()
        self.path = path
        self.is_favorite = is_favorite
        self.show_star = show_star
        self.has_chain = has_chain

    def compose(self) -> ComposeResult:
        parent = self.path.parent.name
        chain_icon = "🔗" if self.has_chain else "  "
        if self.show_star:
            star = "★" if self.is_favorite else "☆"
            yield Static(f" {star} {chain_icon} {parent}/{self.path.name}")
        else:
            yield Static(f" ★ {chain_icon} {parent}/{self.path.name}")


class FavoritesPanel(App):
    """Favorites browser with clipboard copy."""

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("f", "add_favorite", "Add ★"),
        ("space", "copy_path", "Copy"),
        ("x", "remove_favorite", "Remove ★"),
        ("tab", "toggle_focus", "Switch Panel"),
        ("r", "refresh", "Refresh"),
        ("/", "start_search", "Search"),
        ("escape", "cancel_search", "Cancel"),
        ("a", "open_admin", "Admin"),
        ("d", "open_deps", "Deps"),
        ("c", "copy_chain", "Copy Chain"),
        ("s", "send_chain", "Send→F1"),
    ]

    def __init__(self):
        # Build CSS with footer position before super().__init__()
        footer_pos = get_footer_position()
        self.CSS = f"""
        Screen {{
            background: $background;
        }}
        * {{
            scrollbar-size: 1 1;
        }}
        #main {{
            height: 1fr;
            padding: 1;
        }}
        .panel {{
            width: 50%;
            height: 100%;
            border: round $border;
            background: $background;
            margin: 0 1;

            border-title-align: left;
            border-title-color: $text-muted;
            border-title-background: $background;
        }}
        .panel:focus-within {{
            border: round $primary;
            border-title-color: $primary;
        }}
        #folder-list {{
            height: 1fr;
            background: $background;
        }}
        #fav-list {{
            height: 1fr;
            background: $background;
        }}
        #search-input {{
            display: none;
            border: round $border;
            margin: 1;
        }}
        #search-input.visible {{
            display: block;
        }}
        #search-input:focus {{
            border: round $primary;
        }}
        #info {{
            height: 1;
            padding: 0 2;
            background: $surface;
            color: $text-muted;
        }}
        ListItem {{
            padding: 0 1;
            background: $background;
        }}
        ListItem.-highlight {{
            background: $primary 30%;
        }}
        ListView {{
            background: $background;
        }}
        Footer {{
            dock: {footer_pos};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        self.favorites = load_favorites()
        self.roots = load_roots()
        self.all_folders: list[Path] = []
        self.search_active = False

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=False)
        yield Input(placeholder="Type to filter...", id="search-input")
        with Horizontal(id="main"):
            left_panel = Vertical(id="left-panel", classes="panel")
            left_panel.border_title = "All Folders"
            with left_panel:
                yield ListView(id="folder-list")
            right_panel = Vertical(id="right-panel", classes="panel")
            right_panel.border_title = "★ Favorites"
            with right_panel:
                yield ListView(id="fav-list")
        yield Static("", id="info")
        yield Footer()

    def on_mount(self):
        self.title = "Favorites"
        self.sub_title = ""
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
            has_chain = has_project_deps(str(folder))
            folder_list.append(FolderItem(folder, is_fav, show_star=True, has_chain=has_chain))
        if folders:
            folder_list.index = 0

        # Favorites list (also filter if searching)
        fav_list = self.query_one("#fav-list", ListView)
        fav_list.clear()
        for fav_path in sorted(self.favorites):
            path = Path(fav_path)
            if path.exists():
                if not filter_text or filter_text.lower() in path.name.lower():
                    has_chain = has_project_deps(fav_path)
                    fav_list.append(FolderItem(path, is_favorite=True, show_star=False, has_chain=has_chain))
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
        search_input.add_class("visible")
        search_input.value = ""
        search_input.focus()

    def action_cancel_search(self):
        """Cancel search and restore full list."""
        if self.search_active:
            self.search_active = False
            search_input = self.query_one("#search-input", Input)
            search_input.remove_class("visible")
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
        search_input.remove_class("visible")
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

    def action_open_deps(self):
        """Open dependency screen for current project (cwd)."""
        info = self.query_one("#info", Static)
        project_path = os.getcwd()

        def handle_deps_result(result: tuple | None):
            if result is not None:
                chain, instructions = result
                info.update(f"Saved {len(chain)} deps for {Path(project_path).name}")
                self.refresh_lists()  # Update chain indicators

        self.push_screen(DependencyScreen(project_path, self.favorites), handle_deps_result)

    def action_copy_chain(self):
        """Quick copy instructions + paths from current project's dependency chain."""
        info = self.query_one("#info", Static)
        project_path = os.getcwd()

        chain, instructions = get_project_deps(project_path)
        if not chain and not instructions:
            info.update(f"No dependencies defined for {Path(project_path).name} (press 'd' to add)")
            return

        parts = []

        # Add custom instructions first
        if instructions:
            parts.append(instructions)

        # Add paths
        if chain:
            paths_section = "\n".join(f"- {dep}" for dep in chain)
            parts.append(paths_section)

        if parts:
            full_text = "\n\n".join(parts)
            copy_to_clipboard(full_text)
            info.update(f"Copied: instructions + {len(chain)} paths")
        else:
            info.update("Nothing to copy")

    def action_send_chain(self):
        """Send instructions + paths to F1 terminal via tmux."""
        info = self.query_one("#info", Static)
        project_path = os.getcwd()

        chain, instructions = get_project_deps(project_path)
        if not chain and not instructions:
            info.update(f"No dependencies defined for {Path(project_path).name} (press 'd' to add)")
            return

        parts = []

        # Add custom instructions first
        if instructions:
            parts.append(instructions)

        # Add paths
        if chain:
            paths_section = "\n".join(f"- {dep}" for dep in chain)
            parts.append(paths_section)

        if parts:
            full_text = "\n\n".join(parts)
            # Find current tmux session and send to window 1 (F1)
            try:
                # Get current session name
                result = subprocess.run(
                    ["tmux", "display-message", "-p", "#{session_name}"],
                    capture_output=True, text=True
                )
                session = result.stdout.strip()
                # Send keys to window 1 (F1 terminal)
                subprocess.run(
                    ["tmux", "send-keys", "-t", f"{session}:1", full_text],
                    check=True
                )
                info.update(f"Sent to F1: instructions + {len(chain)} paths")
            except Exception as e:
                info.update(f"Error: {e}")
        else:
            info.update("Nothing to send")

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
