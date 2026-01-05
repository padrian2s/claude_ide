#!/usr/bin/env python3
"""Quick input popup for sending text to F1 terminal with AI enhancement."""

import os
import re
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea, Label, Button, RadioButton, RadioSet
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import work

# Optional: Anthropic API for AI enhancement
try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

SCRIPT_DIR = Path(__file__).parent
CORPUS_FILE = SCRIPT_DIR / "prompt_words.txt"
LEARNED_FILE = SCRIPT_DIR / ".prompt_learned_words.txt"


def load_words() -> set[str]:
    """Load words from corpus + learned files."""
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


def save_learned_words(new_words: set[str], corpus_words: set[str]) -> int:
    """Save new learned words to file."""
    if not new_words:
        return 0
    existing = set()
    if LEARNED_FILE.exists():
        existing = set(w.lower() for w in LEARNED_FILE.read_text().splitlines() if w.strip())
    words_to_save = {w.lower() for w in new_words
                     if w.lower() not in corpus_words and w.lower() not in existing}
    if words_to_save:
        with open(LEARNED_FILE, "a") as f:
            for word in sorted(words_to_save):
                f.write(f"{word}\n")
    return len(words_to_save)


def extract_new_words(text: str) -> set[str]:
    """Extract words (4+ letters) from text."""
    return set(re.findall(r'\b[a-zA-Z]{4,}\b', text))


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
            yield Label("AI Enhancement Level", id="enhance-title")
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
            yield Label("Enhanced Prompt Preview", id="preview-title")
            with VerticalScroll(id="preview-scroll"):
                yield Static(self.preview_text, id="preview-area")
            yield Label("Streaming..." if self.streaming else "Review the enhanced prompt", id="preview-status")
            with Horizontal(id="preview-buttons"):
                yield Button("Accept (Y)", variant="success", id="btn-accept")
                yield Button("Reject (N)", variant="error", id="btn-reject")

    def update_text(self, text: str) -> None:
        self.preview_text = text
        try:
            area = self.query_one("#preview-area", Static)
            area.update(text)
            scroll = self.query_one("#preview-scroll")
            scroll.scroll_end(animate=False)
        except Exception:
            pass

    def set_done(self) -> None:
        self.streaming = False
        try:
            scroll = self.query_one("#preview-scroll")
            static = self.query_one("#preview-area", Static)
            static.remove()
            text_area = TextArea(self.preview_text, id="preview-editor")
            text_area.styles.width = "100%"
            text_area.styles.height = "100%"
            scroll.mount(text_area)
            text_area.focus()
            self.query_one("#preview-status", Label).update("Edit if needed, then Accept or Reject")
        except Exception:
            pass

    def get_final_text(self) -> str:
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


class QuickInputApp(App):
    """Quick input popup with multiline support and AI enhancement."""

    CSS = """
    Screen {
        background: $surface;
    }
    #container {
        height: 100%;
        padding: 1;
    }
    #title {
        text-align: center;
        text-style: bold;
        padding: 1;
        background: $primary;
        margin-bottom: 1;
    }
    #editor {
        height: 1fr;
        border: solid $primary;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #buttons {
        height: 3;
        align: center middle;
        padding-top: 1;
    }
    #buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+g", "enhance", "AI Enhance", priority=True),
        Binding("ctrl+s", "send", "Send to F1", priority=True),
        Binding("escape", "quit_app", "Cancel", priority=True),
    ]

    def __init__(self):
        super().__init__()
        self.corpus_words = load_words()
        self.enhanced_text = ""
        self.preview_dialog: PreviewDialog | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="container"):
            yield Label("Quick Input -> F1", id="title")
            yield TextArea(id="editor", language="markdown")
            yield Label("Ctrl+G: AI Enhance | Ctrl+S: Send | Esc: Cancel", id="status")
            with Horizontal(id="buttons"):
                yield Button("AI Enhance (^G)", variant="warning", id="btn-enhance")
                yield Button("Send to F1 (^S)", variant="primary", id="btn-send")
                yield Button("Cancel (Esc)", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        editor = self.query_one("#editor", TextArea)
        editor.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-enhance":
            self.action_enhance()
        elif event.button.id == "btn-send":
            self.action_send()
        elif event.button.id == "btn-cancel":
            self.action_quit_app()

    def action_quit_app(self) -> None:
        self.exit()

    def action_send(self) -> None:
        editor = self.query_one("#editor", TextArea)
        text = editor.text.strip()
        if not text:
            self.notify("Nothing to send", severity="warning", timeout=2)
            return

        # Save learned words
        new_words = extract_new_words(text)
        save_learned_words(new_words, self.corpus_words)

        try:
            # Send to F1 (window 1)
            subprocess.run(
                ["tmux", "send-keys", "-t", ":1", "-l", text],
                capture_output=True, check=True
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", ":1", "Enter"],
                capture_output=True
            )
            self.exit()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error", timeout=3)

    def action_enhance(self) -> None:
        if not HAS_ANTHROPIC:
            self.notify("Install anthropic: pip install anthropic", severity="error", timeout=5)
            return
        if not os.environ.get("ANTHROPIC_API_KEY"):
            self.notify("Set ANTHROPIC_API_KEY environment variable", severity="error", timeout=5)
            return

        editor = self.query_one("#editor", TextArea)
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
        try:
            client = anthropic.Anthropic()
            editor = self.query_one("#editor", TextArea)
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
            final_text = self.preview_dialog.get_final_text()
            if final_text:
                editor = self.query_one("#editor", TextArea)
                editor.load_text(final_text)
                self.notify("Enhancement applied!", timeout=2)
        self.preview_dialog = None
        self.enhanced_text = ""


def main():
    app = QuickInputApp()
    app.run()


if __name__ == "__main__":
    main()
