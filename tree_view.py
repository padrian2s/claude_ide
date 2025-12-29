#!/usr/bin/env python3
"""Tree view with file viewer using Textual - split layout."""

import os
import subprocess
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Static, Header, Markdown
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.binding import Binding
from textual.reactive import reactive
from rich.syntax import Syntax
from rich.text import Text
from rich.console import Group


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
    #viewer-panel {
        width: 80%;
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
        Binding("ctrl+p", "fzf_files", "Find File", priority=True),
        Binding("/", "fzf_grep", "Grep", priority=True),
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
        self.sub_title = "^P:find /:grep r:refresh TAB:switch q:quit"

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
