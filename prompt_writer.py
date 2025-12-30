#!/usr/bin/env python3
"""Prompt Writer - A full-screen text editor for writing prompts using prompt-toolkit."""

import json
from datetime import datetime
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, WindowAlign
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.widgets import TextArea, Frame, SearchToolbar
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import Condition

# Config and prompts storage
PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPTS_DIR.mkdir(exist_ok=True)

# Custom style
STYLE = Style.from_dict({
    'frame.border': '#888888',
    'frame.label': 'bold #00aaff',
    'status': 'reverse',
    'status.key': 'bold #ffaa00',
    'title': 'bold #00ff00',
    'info': '#888888',
    'saved': '#00ff00 bold',
    'filename': '#ffaa00',
})


class PromptWriter:
    """Full-screen prompt writing application."""

    def __init__(self):
        self.filename = None
        self.saved = True
        self.status_message = ""
        self.show_help = False

        # Search toolbar
        self.search_toolbar = SearchToolbar()

        # Main text area
        self.text_area = TextArea(
            text="",
            multiline=True,
            scrollbar=True,
            line_numbers=True,
            search_field=self.search_toolbar,
            focus_on_click=True,
        )

        # Track changes
        self.text_area.buffer.on_text_changed += self._on_text_changed

        # Key bindings
        self.kb = KeyBindings()
        self._setup_keybindings()

        # Layout
        self.layout = self._create_layout()

        # Application
        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            style=STYLE,
            full_screen=True,
            mouse_support=True,
        )

    def _on_text_changed(self, _):
        """Mark as unsaved when text changes."""
        self.saved = False

    def _setup_keybindings(self):
        """Setup key bindings."""
        kb = self.kb

        @kb.add('c-q')
        def exit_(event):
            """Exit application."""
            if not self.saved:
                self.status_message = "Unsaved changes! Press Ctrl+Q again to quit or Ctrl+S to save"
                if hasattr(self, '_quit_pending') and self._quit_pending:
                    event.app.exit()
                self._quit_pending = True
            else:
                event.app.exit()

        @kb.add('c-s')
        def save_(event):
            """Save prompt to file."""
            self._quit_pending = False
            self._save_prompt()

        @kb.add('c-n')
        def new_(event):
            """New prompt."""
            self._quit_pending = False
            if not self.saved:
                self.status_message = "Unsaved changes! Save first (Ctrl+S) or discard (Ctrl+Shift+N)"
            else:
                self._new_prompt()

        @kb.add('c-o')
        def open_(event):
            """Open prompt list."""
            self._quit_pending = False
            self._list_prompts()

        @kb.add('c-h')
        def toggle_help_(event):
            """Toggle help."""
            self._quit_pending = False
            self.show_help = not self.show_help

        @kb.add('c-d')
        def insert_date_(event):
            """Insert current date."""
            self._quit_pending = False
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            self.text_area.buffer.insert_text(date_str)

        @kb.add('c-t')
        def insert_template_(event):
            """Insert prompt template."""
            self._quit_pending = False
            template = """# Prompt Title

## Context
[Describe the context or background]

## Task
[What do you want the AI to do?]

## Requirements
- Requirement 1
- Requirement 2

## Output Format
[How should the response be formatted?]

## Examples (optional)
[Provide examples if helpful]
"""
            self.text_area.buffer.insert_text(template)

        @kb.add('escape')
        def clear_status_(event):
            """Clear status message."""
            self._quit_pending = False
            self.status_message = ""
            self.show_help = False

    def _get_title_bar(self):
        """Get title bar text."""
        modified = "*" if not self.saved else ""
        fname = self.filename or "untitled"
        return [
            ('class:title', ' Prompt Writer '),
            ('class:info', ' | '),
            ('class:filename', f'{fname}{modified}'),
        ]

    def _get_status_bar(self):
        """Get status bar text."""
        if self.status_message:
            return [('class:saved', f' {self.status_message} ')]

        line = self.text_area.document.cursor_position_row + 1
        col = self.text_area.document.cursor_position_col + 1
        total_lines = len(self.text_area.text.split('\n'))
        char_count = len(self.text_area.text)

        return [
            ('class:status.key', ' ^S'),
            ('class:status', ':Save '),
            ('class:status.key', '^O'),
            ('class:status', ':Open '),
            ('class:status.key', '^N'),
            ('class:status', ':New '),
            ('class:status.key', '^T'),
            ('class:status', ':Template '),
            ('class:status.key', '^H'),
            ('class:status', ':Help '),
            ('class:status.key', '^Q'),
            ('class:status', ':Quit '),
            ('class:status', f' | L:{line}/{total_lines} C:{col} | {char_count} chars'),
        ]

    def _get_help_text(self):
        """Get help panel text."""
        if not self.show_help:
            return []
        return [
            ('class:title', '\n Keyboard Shortcuts:\n\n'),
            ('class:status.key', ' Ctrl+S  '), ('', 'Save prompt\n'),
            ('class:status.key', ' Ctrl+O  '), ('', 'Open/list prompts\n'),
            ('class:status.key', ' Ctrl+N  '), ('', 'New prompt\n'),
            ('class:status.key', ' Ctrl+T  '), ('', 'Insert template\n'),
            ('class:status.key', ' Ctrl+D  '), ('', 'Insert date/time\n'),
            ('class:status.key', ' Ctrl+F  '), ('', 'Find text\n'),
            ('class:status.key', ' Ctrl+H  '), ('', 'Toggle this help\n'),
            ('class:status.key', ' Ctrl+Q  '), ('', 'Quit\n'),
            ('class:status.key', ' Escape  '), ('', 'Clear message\n'),
        ]

    def _create_layout(self):
        """Create the application layout."""
        # Title bar
        title_bar = Window(
            content=FormattedTextControl(self._get_title_bar),
            height=1,
            style='class:title',
        )

        # Help panel (conditional)
        help_window = Window(
            content=FormattedTextControl(self._get_help_text),
            width=30,
            style='class:info',
        )

        # Main content with optional help
        @Condition
        def show_help_condition():
            return self.show_help

        main_content = VSplit([
            Frame(self.text_area, title='Prompt'),
            Window(width=1, char='|', style='class:frame.border'),
            help_window,
        ], padding=0)

        main_content_no_help = Frame(self.text_area, title='Prompt')

        # Status bar
        status_bar = Window(
            content=FormattedTextControl(self._get_status_bar),
            height=1,
            style='class:status',
        )

        # Combine with conditional help
        body = HSplit([
            title_bar,
            VSplit([
                Frame(self.text_area, title='Prompt'),
                Window(
                    content=FormattedTextControl(self._get_help_text),
                    width=Condition(lambda: 30 if self.show_help else 0),
                ),
            ]),
            self.search_toolbar,
            status_bar,
        ])

        return Layout(body, focused_element=self.text_area)

    def _save_prompt(self):
        """Save current prompt to file."""
        if not self.filename:
            # Generate filename from first line or timestamp
            first_line = self.text_area.text.split('\n')[0].strip()
            if first_line.startswith('#'):
                first_line = first_line.lstrip('#').strip()
            if first_line:
                # Sanitize filename
                safe_name = "".join(c if c.isalnum() or c in ' -_' else '_' for c in first_line[:40])
                self.filename = f"{safe_name}.md"
            else:
                self.filename = f"prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        filepath = PROMPTS_DIR / self.filename
        filepath.write_text(self.text_area.text)
        self.saved = True
        self.status_message = f"Saved: {self.filename}"

    def _new_prompt(self):
        """Start a new prompt."""
        self.text_area.text = ""
        self.filename = None
        self.saved = True
        self.status_message = "New prompt"

    def _list_prompts(self):
        """List saved prompts in status."""
        prompts = list(PROMPTS_DIR.glob("*.md"))
        if prompts:
            names = [p.name for p in sorted(prompts, key=lambda x: x.stat().st_mtime, reverse=True)[:5]]
            self.status_message = f"Recent: {', '.join(names)} (edit prompt_writer.py for full browser)"
        else:
            self.status_message = "No saved prompts yet"

    def run(self):
        """Run the application."""
        self.app.run()


def main():
    """Main entry point."""
    writer = PromptWriter()
    writer.run()


if __name__ == "__main__":
    main()
