#!/usr/bin/env python3
"""Tree view with file viewer using Textual - split layout."""

import os
import subprocess
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Static, Header, Markdown
from textual.widgets._directory_tree import DirEntry
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.text import Text
from rich.console import Group


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
    }

    def load_file(self, path: Path):
        self.file_path = path
        is_markdown = path.suffix.lower() in self.MARKDOWN_EXTENSIONS

        static_widget = self.query_one("#file-content", Static)
        md_widget = self.query_one("#md-content", Markdown)

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
                suffix = path.suffix.lower()

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
                    # Plain text with line numbers
                    lines = code.splitlines()
                    content = []
                    for i, line in enumerate(lines, 1):
                        safe_line = line.replace("[", "\\[").replace("]", "\\]")
                        content.append(f"[dim]{i:4}[/dim] {safe_line}")
                    plain_content = Text("\n".join(content))
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


class TreeViewApp(App):
    CSS = """
    #main {
        width: 100%;
        height: 100%;
    }
    #tree-panel {
        width: 20%;
        height: 100%;
        border-right: solid $primary;
    }
    #tree-panel.expanded {
        width: 50%;
    }
    #viewer-panel {
        width: 80%;
        height: 100%;
    }
    #viewer-panel.shrunk {
        width: 50%;
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
        Binding("ctrl+p", "fzf_files", "Find File", priority=True),
        Binding("/", "fzf_grep", "Grep", priority=True),
        Binding("tab", "toggle_focus", "Switch Panel"),
        Binding("w", "toggle_width", "Wide"),
        Binding("o", "open_system", "Open"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="tree-panel"):
                yield SizedDirectoryTree(Path.cwd(), id="tree")
            with Vertical(id="viewer-panel"):
                yield FileViewer()

    def on_mount(self):
        tree = self.query_one("#tree", SizedDirectoryTree)
        tree.focus()
        self.query_one(FileViewer).clear()
        self.title = "Tree + Viewer"
        self.sub_title = "^P:find /:grep o:open w:wide r:refresh TAB:switch q:quit"

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
        """Toggle tree panel between narrow and wide."""
        tree_panel = self.query_one("#tree-panel")
        viewer_panel = self.query_one("#viewer-panel")
        tree = self.query_one("#tree", SizedDirectoryTree)

        tree_panel.toggle_class("expanded")
        viewer_panel.toggle_class("shrunk")

        # Update name width and refresh tree
        is_wide = tree_panel.has_class("expanded")
        tree.name_width = NAME_WIDTH_WIDE if is_wide else NAME_WIDTH_NARROW
        tree.refresh()

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
                if file_path.is_file():
                    self.query_one(FileViewer).load_file(file_path)
                    self.notify(f"Opened: {file_path.name}:{parts[1]}", timeout=1)


if __name__ == "__main__":
    TreeViewApp().run()
