#!/usr/bin/env python3
"""Tree view with file viewer using Textual - split layout."""

import os
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Static, Header
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.reactive import reactive


class FileViewer(VerticalScroll):
    """Scrollable file content viewer with syntax highlighting."""

    file_path = reactive(None)

    def compose(self) -> ComposeResult:
        yield Static("", id="file-content")

    def load_file(self, path: Path):
        self.file_path = path
        content_widget = self.query_one("#file-content", Static)

        try:
            with open(path, 'r', errors='replace') as f:
                lines = f.read().splitlines()

            # Build content with line numbers
            content = []
            for i, line in enumerate(lines, 1):
                # Escape markup characters
                safe_line = line.replace("[", "\\[").replace("]", "\\]")
                content.append(f"[dim]{i:4}[/dim] {safe_line}")

            header = f"[bold magenta]{path.name}[/] [dim]({len(lines)} lines)[/dim]\n[dim]{'─' * 50}[/dim]\n"
            content_widget.update(header + "\n".join(content))

        except Exception as e:
            content_widget.update(f"[red]Error: {e}[/red]")

        self.scroll_home()

    def clear(self):
        self.file_path = None
        self.query_one("#file-content", Static).update(
            "[dim]Select a file from the tree to view[/dim]"
        )


class TreeViewApp(App):
    CSS = """
    #main {
        width: 100%;
        height: 100%;
    }
    #tree-panel {
        width: 30%;
        height: 100%;
        border-right: solid $primary;
    }
    #viewer-panel {
        width: 70%;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("f1", "term1", "Term1"),
        Binding("f2", "term2", "Term2"),
        Binding("f4", "lizard", "Lizard"),
        Binding("tab", "toggle_focus", "Switch Panel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="tree-panel"):
                yield DirectoryTree(Path.cwd(), id="tree")
            with Vertical(id="viewer-panel"):
                yield FileViewer()

    def on_mount(self):
        tree = self.query_one("#tree", DirectoryTree)
        tree.focus()
        self.query_one(FileViewer).clear()
        self.title = "Tree + Viewer"
        self.sub_title = "r:refresh TAB:switch q:quit"

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected):
        viewer = self.query_one(FileViewer)
        viewer.load_file(event.path)

    def action_toggle_focus(self):
        tree = self.query_one("#tree", DirectoryTree)
        viewer = self.query_one(FileViewer)
        if tree.has_focus:
            viewer.focus()
        else:
            tree.focus()

    def action_refresh(self):
        tree = self.query_one("#tree", DirectoryTree)
        tree.reload()
        self.notify("Tree refreshed", timeout=1)

    def action_term1(self):
        os.system('tmux select-window -t tui-demo:1')

    def action_term2(self):
        os.system('tmux select-window -t tui-demo:2')

    def action_lizard(self):
        os.system('tmux select-window -t tui-demo:4')


if __name__ == "__main__":
    TreeViewApp().run()
