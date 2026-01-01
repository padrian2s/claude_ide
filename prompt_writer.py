#!/usr/bin/env python3
"""Prompt Writer - A full-screen text editor for writing prompts using Textual."""

import json
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, Header, Footer, TextArea, Button, Label, RadioSet, RadioButton, LoadingIndicator, OptionList, ListView, ListItem
from textual.widgets.option_list import Option
from textual.containers import Vertical, Horizontal, Container
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import work, on
from textual.worker import Worker, WorkerState
from textual.message import Message

# Optional: Anthropic API for AI enhancement
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

CORPUS_FILE = Path(__file__).parent / "prompt_words.txt"
LEARNED_FILE = Path(__file__).parent / ".prompt_learned_words.txt"
PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPTS_DIR.mkdir(exist_ok=True)


def load_word_corpus() -> set[str]:
    """Load words from corpus file + learned words."""
    words = set()
    if CORPUS_FILE.exists():
        for line in CORPUS_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line.lower())
    if LEARNED_FILE.exists():
        for line in LEARNED_FILE.read_text().splitlines():
            line = line.strip()
            if line:
                words.add(line.lower())
    return words


def save_learned_words(words: set[str]):
    """Save learned words to file."""
    existing = set()
    if LEARNED_FILE.exists():
        existing = set(w.lower() for w in LEARNED_FILE.read_text().splitlines())
    new_words = words - existing
    if new_words:
        with open(LEARNED_FILE, "a") as f:
            for word in sorted(new_words):
                f.write(f"{word}\n")


CORPUS_WORDS = load_word_corpus()


def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard (macOS)."""
    try:
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        process.communicate(text.encode("utf-8"))
        return True
    except Exception:
        return False


class AutocompleteTextArea(TextArea):
    """TextArea that supports autocomplete interception."""

    # Override to free up Ctrl+S for app-level save
    BINDINGS = [
        binding for binding in TextArea.BINDINGS
        if "ctrl+s" not in binding.key
    ]

    class AutocompleteKey(Message):
        """Message sent when an autocomplete key is pressed."""
        def __init__(self, key: str):
            super().__init__()
            self.key = key

    async def _on_key(self, event) -> None:
        """Intercept keys for autocomplete before default handling."""
        # Forward Ctrl+G, Ctrl+S, Ctrl+C to app actions (not consumed by TextArea)
        if event.key == "ctrl+g":
            self.app.action_enhance()
            event.prevent_default()
            event.stop()
            return
        if event.key == "ctrl+s":
            self.app.action_save()
            event.prevent_default()
            event.stop()
            return
        if event.key == "ctrl+c":
            self.app.action_copy_all()
            event.prevent_default()
            event.stop()
            return

        # Check if autocomplete is visible
        try:
            app = self.app
            dropdown = app.query_one("#autocomplete", AutocompleteDropdown)
            if dropdown.is_visible:
                if event.key in ("1", "2", "3", "tab", "escape", "up", "down"):
                    # Post message and stop the event
                    self.post_message(self.AutocompleteKey(event.key))
                    event.prevent_default()
                    event.stop()
                    return
        except Exception:
            pass
        # Let parent handle normally
        await super()._on_key(event)


class AutocompleteDropdown(Static):
    """Custom autocomplete dropdown for TextArea."""

    DEFAULT_CSS = """
    AutocompleteDropdown {
        layer: autocomplete;
        position: absolute;
        width: auto;
        height: auto;
        max-height: 10;
        min-width: 20;
        background: $surface;
        border: solid $primary;
        padding: 0 1;
        display: none;
    }
    AutocompleteDropdown.visible {
        display: block;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suggestions: list[str] = []
        self.highlighted_index = 0
        self.current_word = ""

    def show_suggestions(self, suggestions: list[str], word: str) -> None:
        """Show autocomplete suggestions."""
        self.suggestions = suggestions[:8]  # Max 8 suggestions
        self.current_word = word
        self.highlighted_index = 0
        if self.suggestions:
            self._render_suggestions()
            self.add_class("visible")
        else:
            self.hide()

    def hide(self) -> None:
        """Hide the dropdown."""
        self.remove_class("visible")
        self.suggestions = []

    def _render_suggestions(self) -> None:
        """Render the suggestions list."""
        lines = []
        for i, suggestion in enumerate(self.suggestions):
            shortcut = f"[bold yellow]{i + 1}[/]" if i < 3 else " "
            if i == self.highlighted_index:
                lines.append(f"{shortcut} [reverse]{suggestion}[/reverse]")
            else:
                lines.append(f"{shortcut} {suggestion}")
        self.update("\n".join(lines))

    def move_highlight(self, delta: int) -> None:
        """Move the highlight up or down."""
        if self.suggestions:
            self.highlighted_index = (self.highlighted_index + delta) % len(self.suggestions)
            self._render_suggestions()

    def get_selected(self) -> str | None:
        """Get the currently selected suggestion."""
        if self.suggestions and 0 <= self.highlighted_index < len(self.suggestions):
            return self.suggestions[self.highlighted_index]
        return None

    def get_by_index(self, index: int) -> str | None:
        """Get suggestion by index (0-based)."""
        if 0 <= index < len(self.suggestions):
            return self.suggestions[index]
        return None

    @property
    def is_visible(self) -> bool:
        return "visible" in self.classes


# AI Enhancement prompts by level
ENHANCE_PROMPTS = {
    "little": """Lightly improve this prompt. Only fix obvious grammar/spelling errors and minor clarity issues.
Keep the original style and structure intact. Make minimal changes.

Prompt to improve:
{text}

Return ONLY the improved prompt, nothing else.""",

    "medium": """Improve this prompt for clarity and effectiveness.
- Fix grammar and spelling
- Improve sentence structure
- Make instructions clearer
- Keep the same overall meaning and intent

Prompt to improve:
{text}

Return ONLY the improved prompt, nothing else.""",

    "deep": """Significantly enhance this prompt for maximum clarity and effectiveness.
- Fix all grammar and spelling
- Restructure for better flow
- Add clear sections if beneficial
- Make instructions specific and unambiguous
- Improve word choice for precision

Prompt to improve:
{text}

Return ONLY the improved prompt, nothing else.""",

    "aggressive": """Completely rewrite and optimize this prompt as an expert prompt engineer.
- Transform into a highly effective, well-structured prompt
- Add context, constraints, and output format sections if missing
- Use proven prompt engineering techniques
- Make it specific, clear, and impossible to misunderstand
- Structure with markdown for readability

Original prompt to transform:
{text}

Return ONLY the improved prompt, nothing else.""",
}


class EnhanceDialog(ModalScreen[str | None]):
    """Dialog to select enhancement level."""

    CSS = """
    EnhanceDialog {
        align: center middle;
    }
    #enhance-dialog {
        width: 50;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #enhance-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        color: $text;
    }
    RadioSet {
        width: 100%;
        padding: 1;
    }
    #enhance-buttons {
        align: center middle;
        padding-top: 1;
    }
    #enhance-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_1", "Little", show=False),
        Binding("2", "select_2", "Medium", show=False),
        Binding("3", "select_3", "Deep", show=False),
        Binding("4", "select_4", "Aggressive", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="enhance-dialog"):
            yield Label("✨ AI Enhancement Level", id="enhance-title")
            with RadioSet(id="level-select"):
                yield RadioButton("1: Little - Fix typos only", id="little", value=True)
                yield RadioButton("2: Medium - Improve clarity", id="medium")
                yield RadioButton("3: Deep - Restructure", id="deep")
                yield RadioButton("4: Aggressive - Full rewrite", id="aggressive")
            with Horizontal(id="enhance-buttons"):
                yield Button("Enhance", variant="primary", id="btn-enhance")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-enhance":
            radio_set = self.query_one("#level-select", RadioSet)
            if radio_set.pressed_button:
                self.dismiss(radio_set.pressed_button.id)
            else:
                self.dismiss("medium")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _select_and_go(self, level: str) -> None:
        self.dismiss(level)

    def action_select_1(self) -> None:
        self._select_and_go("little")

    def action_select_2(self) -> None:
        self._select_and_go("medium")

    def action_select_3(self) -> None:
        self._select_and_go("deep")

    def action_select_4(self) -> None:
        self._select_and_go("aggressive")


class PreviewDialog(ModalScreen[bool]):
    """Dialog to preview and accept/reject enhanced text."""

    CSS = """
    PreviewDialog {
        align: center middle;
    }
    #preview-dialog {
        width: 90%;
        height: 90%;
        border: thick $success;
        background: $surface;
    }
    #preview-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $primary;
        color: $text;
    }
    #preview-scroll {
        height: 1fr;
        border: solid $primary;
        margin: 1;
    }
    #preview-area {
        width: 100%;
        padding: 1;
    }
    #preview-status {
        text-align: center;
        padding: 1;
        color: $text-muted;
    }
    #preview-buttons {
        align: center middle;
        padding: 1;
        height: auto;
    }
    #preview-buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("y", "accept", "Accept"),
        Binding("n", "reject", "Reject"),
        Binding("escape", "reject", "Cancel"),
    ]

    def __init__(self, text: str = "", streaming: bool = False):
        super().__init__()
        self.preview_text = text
        self.streaming = streaming

    def compose(self) -> ComposeResult:
        from textual.containers import VerticalScroll
        with Vertical(id="preview-dialog"):
            yield Label("✨ Enhanced Prompt Preview", id="preview-title")
            with VerticalScroll(id="preview-scroll"):
                yield Static(self.preview_text, id="preview-area")
            yield Label("Streaming..." if self.streaming else "Review the enhanced prompt", id="preview-status")
            with Horizontal(id="preview-buttons"):
                yield Button("✓ Accept (Y)", variant="success", id="btn-accept")
                yield Button("✗ Reject (N)", variant="error", id="btn-reject")

    def update_text(self, text: str) -> None:
        """Update the preview text (for streaming)."""
        self.preview_text = text
        try:
            area = self.query_one("#preview-area", Static)
            area.update(text)
            # Auto-scroll to bottom
            scroll = self.query_one("#preview-scroll")
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def set_done(self) -> None:
        """Mark streaming as complete and enable editing."""
        self.streaming = False
        try:
            # Replace Static with editable TextArea
            scroll = self.query_one("#preview-scroll")
            static = self.query_one("#preview-area", Static)
            static.remove()

            # Add editable TextArea
            text_area = TextArea(self.preview_text, id="preview-editor")
            text_area.styles.width = "100%"
            text_area.styles.height = "100%"
            scroll.mount(text_area)
            text_area.focus()

            self.query_one("#preview-status", Label).update("Edit if needed, then Accept or Reject")
        except Exception:
            pass

    def get_final_text(self) -> str:
        """Get the final text (possibly edited)."""
        try:
            editor = self.query_one("#preview-editor", TextArea)
            return editor.text
        except Exception:
            return self.preview_text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-accept":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_accept(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


class ConfirmDialog(ModalScreen[bool]):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: auto;
        border: solid $error;
        background: $surface;
        padding: 1 2;
    }
    #confirm-title {
        text-align: center;
        text-style: bold;
        padding: 1;
    }
    #confirm-buttons {
        align: center middle;
        padding-top: 1;
    }
    #confirm-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(f"{self.title_text}: {self.message}", id="confirm-title")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes (Y)", variant="error", id="btn-yes")
                yield Button("No (N)", variant="default", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TemplateDialog(ModalScreen[str | None]):
    """Dialog to insert a template."""

    CSS = """
    TemplateDialog {
        align: center middle;
    }
    #template-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #template-title {
        text-align: center;
        text-style: bold;
        padding: 1;
    }
    RadioSet {
        width: 100%;
        padding: 1;
    }
    #template-buttons {
        align: center middle;
        padding-top: 1;
    }
    """

    TEMPLATES = {
        "basic": """# Prompt Title

## Context
[Describe the context or background]

## Task
[What do you want the AI to do?]

## Requirements
- Requirement 1
- Requirement 2

## Output Format
[How should the response be formatted?]
""",
        "role": """You are a [ROLE] with expertise in [DOMAIN].

## Task
[What should the AI do?]

## Guidelines
- Guideline 1
- Guideline 2

## Output
[Expected output format]
""",
        "cot": """I need help with [TASK].

Let's think step by step:

1. First, consider [ASPECT 1]
2. Then, analyze [ASPECT 2]
3. Finally, determine [CONCLUSION]

Please provide your reasoning and final answer.
""",
        "code": """## Task
Write code that [DESCRIPTION].

## Requirements
- Language: [LANGUAGE]
- Must handle: [EDGE CASES]
- Performance: [REQUIREMENTS]

## Examples
Input: [EXAMPLE INPUT]
Output: [EXAMPLE OUTPUT]
""",
    }

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="template-dialog"):
            yield Label("📝 Insert Template", id="template-title")
            with RadioSet(id="template-select"):
                yield RadioButton("Basic Prompt Structure", id="basic", value=True)
                yield RadioButton("Role-Based Prompt", id="role")
                yield RadioButton("Chain of Thought", id="cot")
                yield RadioButton("Code Generation", id="code")
            with Horizontal(id="template-buttons"):
                yield Button("Insert", variant="primary", id="btn-insert")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-insert":
            radio_set = self.query_one("#template-select", RadioSet)
            if radio_set.pressed_button:
                self.dismiss(self.TEMPLATES.get(radio_set.pressed_button.id, ""))
            else:
                self.dismiss(self.TEMPLATES["basic"])
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)



# Claude Code history file
CLAUDE_HISTORY_FILE = Path.home() / ".claude" / "history.jsonl"


def load_claude_prompts() -> dict[str, list[dict]]:
    """Load prompts from Claude Code history, grouped by project.
    
    Returns:
        Dict mapping project name to list of prompts with display and timestamp.
    """
    if not CLAUDE_HISTORY_FILE.exists():
        return {}
    
    prompts_by_project: dict[str, list[dict]] = {}
    
    try:
        with open(CLAUDE_HISTORY_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if 'display' not in obj:
                        continue
                    
                    display = obj['display'].strip()
                    # Skip empty or command-only prompts
                    if not display or display.startswith('/clear') or len(display) < 5:
                        continue
                    
                    project = obj.get('project', 'Unknown')
                    # Extract just the project name from path
                    project_name = Path(project).name if project else 'Unknown'
                    
                    timestamp = obj.get('timestamp', 0)
                    
                    if project_name not in prompts_by_project:
                        prompts_by_project[project_name] = []
                    
                    prompts_by_project[project_name].append({
                        'display': display[:200] + '...' if len(display) > 200 else display,
                        'full_display': display,
                        'timestamp': timestamp,
                        'project_path': project,
                    })
                except json.JSONDecodeError:
                    continue
    except Exception:
        return {}
    
    # Sort prompts within each project by timestamp (newest first)
    for project in prompts_by_project:
        prompts_by_project[project].sort(key=lambda x: x['timestamp'], reverse=True)
    
    return prompts_by_project


class ProjectItem(ListItem):
    """A project item in the list."""
    
    def __init__(self, project_name: str, count: int) -> None:
        super().__init__()
        self.project_name = project_name
        self.count = count
    
    def compose(self) -> ComposeResult:
        yield Label(f"📁 {self.project_name} ({self.count})")


class PromptItem(ListItem):
    """A prompt item in the list."""
    
    def __init__(self, prompt: dict, index: int) -> None:
        super().__init__()
        self.prompt = prompt
        self.index = index
    
    def compose(self) -> ComposeResult:
        # Format timestamp
        ts = self.prompt.get('timestamp', 0)
        if ts:
            from datetime import datetime as dt
            date_str = dt.fromtimestamp(ts / 1000).strftime('%m/%d %H:%M')
        else:
            date_str = ''
        
        display = self.prompt.get('display', '')[:80]
        yield Label(f"{date_str} | {display}")


class ClaudePromptsDialog(ModalScreen[str | None]):
    """Dialog to browse Claude Code prompts by project."""

    CSS = """
    ClaudePromptsDialog {
        align: center middle;
    }
    #prompts-dialog {
        width: 90%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #prompts-title {
        text-align: center;
        text-style: bold;
        padding: 1;
        color: $text;
    }
    #prompts-container {
        height: 1fr;
    }
    #projects-panel {
        width: 30%;
        height: 100%;
        border: solid $primary-lighten-2;
    }
    #prompts-panel {
        width: 70%;
        height: 100%;
        border: solid $primary-lighten-2;
    }
    .panel-title {
        text-align: center;
        text-style: bold;
        background: $primary;
        padding: 0 1;
    }
    ListView {
        height: 1fr;
    }
    ListItem {
        padding: 0 1;
    }
    ListItem:hover {
        background: $surface-lighten-1;
    }
    ListView:focus > ListItem.--highlight {
        background: $primary;
    }
    #preview-panel {
        height: 8;
        border: solid $secondary;
        padding: 1;
        overflow-y: auto;
    }
    #preview-text {
        width: 100%;
    }
    #prompts-buttons {
        height: 3;
        align: center middle;
        padding-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "select", "Select"),
        Binding("tab", "switch_panel", "Switch Panel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.prompts_by_project = load_claude_prompts()
        self.current_project: str | None = None
        self.current_prompt: dict | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="prompts-dialog"):
            yield Label("📋 Claude Code Prompts", id="prompts-title")
            with Horizontal(id="prompts-container"):
                with Vertical(id="projects-panel"):
                    yield Label("Projects", classes="panel-title")
                    yield ListView(id="projects-list")
                with Vertical(id="prompts-panel"):
                    yield Label("Prompts", classes="panel-title")
                    yield ListView(id="prompts-list")
            with Vertical(id="preview-panel"):
                yield Static("Select a prompt to preview", id="preview-text")
            with Horizontal(id="prompts-buttons"):
                yield Button("Insert", variant="primary", id="btn-insert")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        # Populate projects list
        projects_list = self.query_one("#projects-list", ListView)
        
        # Sort projects by prompt count
        sorted_projects = sorted(
            self.prompts_by_project.items(),
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        for project_name, prompts in sorted_projects:
            projects_list.append(ProjectItem(project_name, len(prompts)))
        
        projects_list.focus()
        
        if not self.prompts_by_project:
            self.query_one("#preview-text", Static).update("No prompts found in ~/.claude/history.jsonl")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle selection in either list."""
        item = event.item
        
        if isinstance(item, ProjectItem):
            # Project selected - show its prompts
            self.current_project = item.project_name
            self._populate_prompts(item.project_name)
            # Focus prompts list
            self.query_one("#prompts-list", ListView).focus()
        
        elif isinstance(item, PromptItem):
            # Prompt selected - insert it
            self.current_prompt = item.prompt
            self.dismiss(item.prompt.get('full_display', ''))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Update preview when highlighting changes."""
        item = event.item
        preview = self.query_one("#preview-text", Static)
        
        if isinstance(item, ProjectItem):
            count = len(self.prompts_by_project.get(item.project_name, []))
            preview.update(f"Project: {item.project_name}\nPrompts: {count}\n\nPress Enter to view prompts")
        
        elif isinstance(item, PromptItem):
            self.current_prompt = item.prompt
            full_text = item.prompt.get('full_display', '')[:500]
            preview.update(full_text)

    def _populate_prompts(self, project_name: str) -> None:
        """Populate the prompts list for a project."""
        prompts_list = self.query_one("#prompts-list", ListView)
        prompts_list.clear()
        
        prompts = self.prompts_by_project.get(project_name, [])
        for i, prompt in enumerate(prompts[:50]):  # Limit to 50 prompts
            prompts_list.append(PromptItem(prompt, i))

    def action_switch_panel(self) -> None:
        """Switch focus between panels."""
        projects = self.query_one("#projects-list", ListView)
        prompts = self.query_one("#prompts-list", ListView)
        
        if projects.has_focus:
            prompts.focus()
        else:
            projects.focus()

    def action_select(self) -> None:
        """Select current item."""
        if self.current_prompt:
            self.dismiss(self.current_prompt.get('full_display', ''))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-insert":
            if self.current_prompt:
                self.dismiss(self.current_prompt.get('full_display', ''))
            else:
                self.notify("No prompt selected", severity="warning")
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class PromptWriter(App):
    """Full-screen prompt writing application."""

    CSS = """
    Screen {
        background: $surface;
        layers: base autocomplete;
    }
    #editor-container {
        height: 1fr;
        padding: 0 1;
        layer: base;
    }
    #main-editor {
        height: 100%;
    }
    #status-bar {
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    #status-left {
        width: 1fr;
    }
    #status-right {
        width: auto;
    }
    #autocomplete {
        layer: autocomplete;
        width: auto;
        min-width: 25;
        max-width: 40;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+c", "copy_all", "Copy", priority=True),
        Binding("ctrl+n", "new", "New", priority=True),
        Binding("ctrl+g", "enhance", "AI", priority=True),
        Binding("ctrl+t", "template", "Tmpl", priority=True),
        Binding("ctrl+b", "browse_prompts", "Browse", priority=True),
        Binding("ctrl+d", "insert_date", "Date", show=False),
        Binding("ctrl+space", "trigger_autocomplete", "Autocomplete", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.filename: str | None = None
        self.saved = True
        self.learned_words: set[str] = set()
        self.enhanced_text = ""
        self.preview_dialog: PreviewDialog | None = None
        self.all_words: set[str] = set(CORPUS_WORDS)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="editor-container"):
            yield AutocompleteTextArea(id="main-editor", language="markdown", show_line_numbers=True)
            yield AutocompleteDropdown(id="autocomplete")
        with Horizontal(id="status-bar"):
            yield Label("", id="status-left")
            yield Label("", id="status-right")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Prompt Writer"
        self.sub_title = "New prompt"
        self.update_status()
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        editor.focus()

    def on_autocomplete_text_area_autocomplete_key(self, event: AutocompleteTextArea.AutocompleteKey) -> None:
        """Handle autocomplete key events from the TextArea."""
        dropdown = self.query_one("#autocomplete", AutocompleteDropdown)

        if event.key == "escape":
            dropdown.hide()
        elif event.key == "tab":
            suggestion = dropdown.get_selected()
            if suggestion:
                self._apply_suggestion(suggestion)
        elif event.key == "down":
            dropdown.move_highlight(1)
        elif event.key == "up":
            dropdown.move_highlight(-1)
        elif event.key in ("1", "2", "3"):
            idx = int(event.key) - 1
            suggestion = dropdown.get_by_index(idx)
            if suggestion:
                self._apply_suggestion(suggestion)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.saved = False
        self.update_status()
        # Learn words and save immediately
        text = event.text_area.text
        words = set(re.findall(r'\b[a-zA-Z]{4,}\b', text))
        new_words = {w.lower() for w in words if w.lower() not in CORPUS_WORDS and w.lower() not in self.learned_words}

        if new_words:
            self.learned_words.update(new_words)
            self.all_words.update(new_words)
            # Save immediately so words are available next time
            save_learned_words(new_words)

        # Update autocomplete suggestions
        self._update_autocomplete()

    def _get_current_word(self) -> str:
        """Get the word currently being typed."""
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        text = editor.text
        cursor = editor.cursor_location

        # Get text up to cursor
        lines = text.split('\n')
        if cursor[0] < len(lines):
            line = lines[cursor[0]]
            col = min(cursor[1], len(line))
            text_before = line[:col]

            # Find word being typed
            match = re.search(r'[a-zA-Z]+$', text_before)
            if match:
                return match.group()
        return ""

    def _get_suggestions(self, prefix: str) -> list[str]:
        """Get autocomplete suggestions for prefix."""
        if len(prefix) < 2:
            return []

        prefix_lower = prefix.lower()
        matches = []
        for word in self.all_words:
            if word.lower().startswith(prefix_lower) and word.lower() != prefix_lower:
                matches.append(word)

        return sorted(matches, key=str.lower)[:8]

    def _update_autocomplete(self) -> None:
        """Update autocomplete dropdown based on current word."""
        dropdown = self.query_one("#autocomplete", AutocompleteDropdown)
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        current_word = self._get_current_word()

        if len(current_word) >= 2:
            suggestions = self._get_suggestions(current_word)
            if suggestions:
                # Position dropdown near cursor
                cursor_row, cursor_col = editor.cursor_location
                # Account for line numbers (approx 5 chars) and some padding
                line_number_width = 5 if editor.show_line_numbers else 0
                # Position: row below cursor, column at word start
                x_offset = line_number_width + cursor_col - len(current_word) + 1
                y_offset = cursor_row + 2  # +2 for header and 1-based positioning

                dropdown.styles.offset = (x_offset, y_offset)
                dropdown.show_suggestions(suggestions, current_word)
                return

        dropdown.hide()

    def _apply_suggestion(self, suggestion: str) -> None:
        """Apply the selected suggestion."""
        dropdown = self.query_one("#autocomplete", AutocompleteDropdown)
        if not suggestion or not dropdown.current_word:
            return

        editor = self.query_one("#main-editor", AutocompleteTextArea)
        current_word = dropdown.current_word

        # Delete current word and insert suggestion
        for _ in range(len(current_word)):
            editor.action_delete_left()
        editor.insert(suggestion)
        dropdown.hide()

    def action_trigger_autocomplete(self) -> None:
        """Manually trigger autocomplete."""
        self._update_autocomplete()

    def update_status(self) -> None:
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        text = editor.text
        lines = len(text.split('\n'))
        chars = len(text)
        modified = "*" if not self.saved else ""
        fname = self.filename or "untitled"
        learned = f" +{len(self.learned_words)}" if self.learned_words else ""

        self.query_one("#status-left", Label).update(f"{fname}{modified}")
        self.query_one("#status-right", Label).update(f"L:{lines} C:{chars}{learned}")
        self.sub_title = f"{fname}{modified}"

    def action_quit_app(self) -> None:
        if not self.saved:
            self.push_screen(
                ConfirmDialog("Quit", "Unsaved changes. Exit anyway?"),
                self._handle_quit
            )
        else:
            self._do_quit()

    def _handle_quit(self, confirmed: bool) -> None:
        if confirmed:
            self._do_quit()

    def _do_quit(self) -> None:
        # Save learned words
        if self.learned_words:
            save_learned_words(self.learned_words)
        self.exit()

    def action_save(self) -> None:
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        text = editor.text

        if not self.filename:
            first_line = text.split('\n')[0].strip()
            if first_line.startswith('#'):
                first_line = first_line.lstrip('#').strip()
            if first_line:
                safe_name = "".join(c if c.isalnum() or c in ' -_' else '_' for c in first_line[:40])
                self.filename = f"{safe_name}.md"
            else:
                self.filename = f"prompt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        filepath = PROMPTS_DIR / self.filename
        filepath.write_text(text)
        self.saved = True

        # Save learned words
        if self.learned_words:
            save_learned_words(self.learned_words)
            count = len(self.learned_words)
            self.notify(f"Saved: {self.filename} (+{count} words)", timeout=3)
        else:
            self.notify(f"Saved: {self.filename}", timeout=3)

        self.update_status()

    def action_copy_all(self) -> None:
        """Copy all text to system clipboard."""
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        text = editor.text
        if text:
            if copy_to_clipboard(text):
                lines = len(text.split('\n'))
                chars = len(text)
                self.notify(f"Copied: {lines} lines, {chars} chars", timeout=2)
            else:
                self.notify("Failed to copy", severity="error", timeout=3)
        else:
            self.notify("Nothing to copy", severity="warning", timeout=2)

    def action_new(self) -> None:
        if not self.saved:
            self.push_screen(
                ConfirmDialog("New", "Discard unsaved changes?"),
                self._handle_new
            )
        else:
            self._do_new()

    def _handle_new(self, confirmed: bool) -> None:
        if confirmed:
            self._do_new()

    def _do_new(self) -> None:
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        editor.load_text("")
        self.filename = None
        self.saved = True
        self.update_status()
        self.notify("New prompt", timeout=2)

    def action_template(self) -> None:
        self.push_screen(TemplateDialog(), self._handle_template)

    def _handle_template(self, template: str | None) -> None:
        if template:
            editor = self.query_one("#main-editor", AutocompleteTextArea)
            editor.insert(template)


    def action_browse_prompts(self) -> None:
        """Open Claude prompts browser dialog."""
        self.push_screen(ClaudePromptsDialog(), self._handle_prompt_selection)

    def _handle_prompt_selection(self, prompt_text: str | None) -> None:
        """Handle prompt selection from browser."""
        if prompt_text:
            editor = self.query_one("#main-editor", AutocompleteTextArea)
            editor.insert(prompt_text)
            self.saved = False
            self.update_status()
            self.notify("Prompt inserted", timeout=2)

    def action_insert_date(self) -> None:
        editor = self.query_one("#main-editor", AutocompleteTextArea)
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        editor.insert(date_str)

    def action_enhance(self) -> None:
        if not HAS_ANTHROPIC:
            self.notify("Install anthropic: pip install anthropic", severity="error", timeout=5)
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            self.notify("Set ANTHROPIC_API_KEY environment variable", severity="error", timeout=5)
            return

        editor = self.query_one("#main-editor", AutocompleteTextArea)
        if not editor.text.strip():
            self.notify("No text to enhance", severity="warning", timeout=3)
            return

        self.push_screen(EnhanceDialog(), self._handle_enhance_level)

    def _handle_enhance_level(self, level: str | None) -> None:
        if level:
            self.enhanced_text = ""
            self.preview_dialog = PreviewDialog("", streaming=True)
            self.push_screen(self.preview_dialog, self._handle_preview)
            self._run_enhancement(level)

    @work(thread=True)
    def _run_enhancement(self, level: str) -> None:
        """Run AI enhancement with streaming."""
        try:
            client = anthropic.Anthropic()
            editor = self.query_one("#main-editor", AutocompleteTextArea)
            prompt = ENHANCE_PROMPTS[level].format(text=editor.text)

            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            ) as stream:
                for text in stream.text_stream:
                    self.enhanced_text += text
                    if self.preview_dialog:
                        self.call_from_thread(self.preview_dialog.update_text, self.enhanced_text)

            if self.preview_dialog:
                self.call_from_thread(self.preview_dialog.set_done)

        except Exception as e:
            self.call_from_thread(self.notify, f"Error: {str(e)[:50]}", severity="error", timeout=5)
            if self.preview_dialog:
                self.call_from_thread(self.preview_dialog.dismiss, False)

    def _handle_preview(self, accepted: bool) -> None:
        if accepted and self.preview_dialog:
            # Get possibly edited text from preview dialog
            final_text = self.preview_dialog.get_final_text()
            if final_text:
                editor = self.query_one("#main-editor", AutocompleteTextArea)
                editor.load_text(final_text)
                self.saved = False
                self.update_status()
                self.notify("Enhancement applied!", timeout=3)
            else:
                self.notify("No text to apply", severity="warning", timeout=2)
        else:
            self.notify("Enhancement cancelled", timeout=2)
        self.preview_dialog = None
        self.enhanced_text = ""


def main():
    """Main entry point."""
    app = PromptWriter()
    app.run()


if __name__ == "__main__":
    main()
