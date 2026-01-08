#!/usr/bin/env python3
"""Quick input popup for sending text to F1 terminal with AI enhancement."""

import os
import re
import subprocess
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, TextArea, Label, Button, RadioButton, RadioSet, Input, ListView, ListItem
from textual.containers import Vertical, Horizontal
from textual.screen import ModalScreen
from textual.binding import Binding
from textual import work

from config_panel import get_textual_theme, get_theme_colors

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
    """Extract words (3+ letters, including Unicode)."""
    return set(re.findall(r'\b\w{3,}\b', text, re.UNICODE))


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

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("1", "select_1", "Little", show=False),
        Binding("2", "select_2", "Medium", show=False),
        Binding("3", "select_3", "Deep", show=False),
        Binding("4", "select_4", "Aggressive", show=False),
    ]

    def __init__(self):
        # Build CSS with theme colors before super().__init__()
        theme_colors = get_theme_colors()
        bg = theme_colors['bg']
        fg = theme_colors['fg']
        self.CSS = f"""
        EnhanceDialog {{
            align: center middle;
        }}
        #enhance-dialog {{
            width: 50;
            height: auto;
            border: solid {fg};
            background: {bg};
            color: {fg};
            padding: 1 2;
        }}
        #enhance-title {{
            text-align: center;
            text-style: bold;
            padding: 1;
            background: {bg};
            color: {fg};
        }}
        RadioSet {{
            width: 100%;
            padding: 1;
            background: {bg};
            color: {fg};
        }}
        RadioButton {{
            background: {bg};
            color: {fg};
        }}
        #enhance-buttons {{
            align: center middle;
            padding-top: 1;
            background: {bg};
        }}
        #enhance-buttons Button {{
            margin: 0 1;
        }}
        Label {{
            background: {bg};
            color: {fg};
        }}
        Vertical {{
            background: {bg};
        }}
        Horizontal {{
            background: {bg};
        }}
        """
        super().__init__()

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

    BINDINGS = [
        Binding("y", "accept", "Accept"),
        Binding("n", "reject", "Reject"),
        Binding("escape", "reject", "Cancel"),
    ]

    def __init__(self, text: str = "", streaming: bool = False):
        # Build CSS with theme colors before super().__init__()
        theme_colors = get_theme_colors()
        bg = theme_colors['bg']
        fg = theme_colors['fg']
        self.CSS = f"""
        PreviewDialog {{
            align: center middle;
        }}
        #preview-dialog {{
            width: 90%;
            height: 90%;
            border: solid {fg};
            background: {bg};
            color: {fg};
        }}
        #preview-title {{
            text-align: center;
            text-style: bold;
            padding: 1;
            background: {fg};
            color: {bg};
        }}
        #preview-scroll {{
            height: 1fr;
            border: none;
            margin: 1;
            background: {bg};
        }}
        #preview-area {{
            width: 100%;
            padding: 1;
            background: {bg};
            color: {fg};
        }}
        #preview-status {{
            text-align: center;
            padding: 1;
            color: {fg};
            background: {bg};
        }}
        #preview-buttons {{
            align: center middle;
            padding: 1;
            height: auto;
            background: {bg};
        }}
        #preview-buttons Button {{
            margin: 0 2;
        }}
        Static {{
            background: {bg};
            color: {fg};
        }}
        Label {{
            background: {bg};
            color: {fg};
        }}
        TextArea {{
            background: {bg};
            color: {fg};
        }}
        Vertical {{
            background: {bg};
        }}
        Horizontal {{
            background: {bg};
        }}
        VerticalScroll {{
            background: {bg};
        }}
        """
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


def load_claude_history(project_path: str | None = None) -> list[str]:
    """Load prompts from Claude Code history, optionally filtered by project."""
    history_file = Path.home() / ".claude" / "history.jsonl"
    if not history_file.exists():
        return []
    try:
        import json
        prompts = []
        for line in history_file.read_text().strip().split("\n"):
            if line.strip():
                entry = json.loads(line)
                # Filter by project if specified
                if project_path:
                    entry_project = entry.get("project", "")
                    if entry_project != project_path:
                        continue
                display = entry.get("display", "").strip()
                if display:
                    prompts.append(display)
        return prompts
    except Exception:
        return []


def get_current_project() -> str | None:
    """Get current project path from tmux or cwd."""
    try:
        result = subprocess.run(
            ["tmux", "show-option", "-v", "@start_dir"],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return str(Path.cwd())


class QuickInputApp(App):
    """Simple quick input - uses terminal theme colors."""

    BINDINGS = [
        Binding("ctrl+o", "hist_prev", "^O", priority=True),
        Binding("ctrl+l", "hist_next", "^L", priority=True),
        Binding("tab", "complete", "Tab", priority=True),
        Binding("ctrl+s", "send", "Send", priority=True),
        Binding("ctrl+g", "enhance", "AI", priority=True),
        Binding("escape", "quit", "Quit", priority=True),
    ]

    def __init__(self):
        # Build CSS with theme colors before super().__init__()
        theme_colors = get_theme_colors()
        bg = theme_colors['bg']
        fg = theme_colors['fg']
        self.CSS = f"""
        Screen {{ 
            layers: base overlay; 
            background: {bg}; 
            color: {fg}; 
        }}
        TextArea {{ 
            background: {bg}; 
            color: {fg}; 
        }}
        TextArea > .text-area--cursor {{
            background: {fg};
            color: {bg};
        }}
        #input {{ 
            border: none; 
            height: 1fr; 
            layer: base; 
            background: {bg}; 
            color: {fg}; 
        }}
        #input.history {{ 
            text-opacity: 60%; 
        }}
        #autocomplete {{
            layer: overlay;
            background: transparent;
            text-opacity: 70%;
            height: 1;
            width: 100%;
            color: {fg};
        }}
        #status {{ 
            dock: bottom; 
            height: 1; 
            layer: base; 
            text-opacity: 70%; 
            background: {bg}; 
            color: {fg}; 
        }}
        Static {{
            background: {bg};
            color: {fg};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        self.words = sorted(load_words())
        self.history = []
        self.hist_idx = -1
        self.loading = False
        self.suggestion = ""

    def compose(self) -> ComposeResult:
        yield TextArea(id="input", soft_wrap=True)
        yield Static("", id="autocomplete")
        yield Static("^O/^L:Hist  Tab:Complete  ^S:Send  ^G:AI  Esc:Quit", id="status")

    def on_mount(self):
        self.history = load_claude_history(get_current_project())
        self.query_one("#input").focus()

    def action_hist_prev(self):
        self._hist_prev()

    def action_hist_next(self):
        self._hist_next()

    def on_text_area_changed(self, event: TextArea.Changed):
        if self.loading:
            return
        # Exit history mode only if user is typing (not navigating history)
        if self.hist_idx >= 0:
            # Check if text differs from current history item
            current_hist = self.history[-(self.hist_idx + 1)] if self.history else ""
            if event.text_area.text != current_hist:
                self.hist_idx = -1
                self.query_one("#input", TextArea).remove_class("history")
        # Save complete words (not the word currently being typed)
        text = event.text_area.text
        # Extract words except the last one (which may be incomplete)
        if ' ' in text or '\n' in text:
            # Get all text except last word
            last_space = max(text.rfind(' '), text.rfind('\n'))
            complete_text = text[:last_space] if last_space > 0 else ""
            if complete_text:
                new_words = extract_new_words(complete_text)
                if new_words:
                    saved = save_learned_words(new_words, set(self.words))
                    if saved > 0:
                        self.words = sorted(load_words())
        # Autocomplete
        self._update_suggestion()

    def _update_suggestion(self):
        ta = self.query_one("#input", TextArea)
        auto = self.query_one("#autocomplete", Static)
        # Get current line text up to cursor
        row, col = ta.cursor_location
        lines = ta.text.split("\n")
        if row >= len(lines):
            self.suggestion = ""
            auto.update("")
            auto.styles.display = "none"
            return
        line = lines[row][:col]
        match = re.search(r'(\w{2,})$', line)
        if not match:
            self.suggestion = ""
            auto.update("")
            auto.styles.display = "none"
            return
        word = match.group(1).lower()
        matches = [w for w in self.words if w.startswith(word) and w != word]
        if matches:
            self.suggestion = matches[0]
            # Calculate visual row (account for wrapped lines)
            width = ta.size.width - 1  # TextArea width
            visual_row = 0
            for i in range(row):
                line_len = len(lines[i]) if i < len(lines) else 0
                visual_row += max(1, (line_len + width - 1) // width) if width > 0 else 1
            # Add current line's visual rows up to cursor
            visual_row += col // width if width > 0 else 0
            visual_col = col % width if width > 0 else col

            padding = " " * (visual_col + 1)
            auto.update(f"{padding}{self.suggestion}")
            auto.styles.offset = (0, visual_row + 1)
            auto.styles.display = "block"
        else:
            self.suggestion = ""
            auto.update("")
            auto.styles.display = "none"

    def action_complete(self):
        if not self.suggestion:
            return
        ta = self.query_one("#input", TextArea)
        row, col = ta.cursor_location
        lines = ta.text.split("\n")
        if row >= len(lines):
            return
        line = lines[row]
        # Find word before cursor
        before = line[:col]
        after = line[col:]
        match = re.search(r'(\w+)$', before)
        if match:
            before = before[:-len(match.group(1))]
        new_line = before + self.suggestion + " " + after
        lines[row] = new_line
        new_col = len(before) + len(self.suggestion) + 1
        self.loading = True
        ta.text = "\n".join(lines)
        ta.cursor_location = (row, new_col)
        self.loading = False
        self.suggestion = ""
        auto = self.query_one("#autocomplete", Static)
        auto.update("")
        auto.styles.display = "none"

    def _hist_prev(self):
        if not self.history or self.hist_idx >= len(self.history) - 1:
            return
        self.hist_idx += 1
        self._load_history()

    def _hist_next(self):
        if self.hist_idx < 0:
            return
        if self.hist_idx == 0:
            self.hist_idx = -1
            self.loading = True
            ta = self.query_one("#input", TextArea)
            ta.text = ""
            ta.remove_class("history")
            self.loading = False
            self._update_status()
            return
        self.hist_idx -= 1
        self._load_history()

    def _load_history(self):
        self.loading = True
        ta = self.query_one("#input", TextArea)
        ta.text = self.history[-(self.hist_idx + 1)]
        ta.add_class("history")
        self.loading = False
        self.suggestion = ""
        auto = self.query_one("#autocomplete", Static)
        auto.update("")
        auto.styles.display = "none"
        self._update_status()

    def _update_status(self):
        s = self.query_one("#status", Static)
        if self.hist_idx >= 0:
            s.update(f"[{len(self.history)-self.hist_idx}/{len(self.history)}] ^O/^L:Hist  ^S:Send  ^G:AI")
        else:
            s.update("^O/^L:Hist  Tab:Complete  ^S:Send  ^G:AI  Esc:Quit")

    def action_quit(self):
        self.exit()

    def action_send(self):
        text = self.query_one("#input", TextArea).text.strip()
        if not text:
            return
        save_learned_words(extract_new_words(text), set(self.words))
        subprocess.run(["tmux", "send-keys", "-t", ":1", "-l", text], capture_output=True)
        subprocess.run(["tmux", "send-keys", "-t", ":1", "Enter"], capture_output=True)
        self.exit()

    def action_enhance(self):
        if not HAS_ANTHROPIC or not os.environ.get("ANTHROPIC_API_KEY"):
            self.notify("Need ANTHROPIC_API_KEY")
            return
        text = self.query_one("#input", TextArea).text.strip()
        if not text:
            return
        self.notify("Enhancing...")
        self._do_enhance(text)

    @work(thread=True)
    def _do_enhance(self, text: str):
        try:
            client = anthropic.Anthropic()
            accumulated = ""
            with client.messages.stream(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{"role": "user", "content": ENHANCE_PROMPTS["medium"].format(text=text)}]
            ) as stream:
                for chunk in stream.text_stream:
                    accumulated += chunk
                    self.call_from_thread(self._set_text, accumulated)
            # Move cursor to end when done
            self.call_from_thread(self._move_cursor_end)
        except Exception as e:
            self.call_from_thread(self.notify, str(e)[:40])

    def _set_text(self, text: str):
        self.query_one("#input", TextArea).text = text

    def _move_cursor_end(self):
        ta = self.query_one("#input", TextArea)
        lines = ta.text.split("\n")
        last_line = len(lines) - 1
        last_col = len(lines[-1]) if lines else 0
        ta.cursor_location = (last_line, last_col)


def main():
    app = QuickInputApp()
    app.run()


if __name__ == "__main__":
    main()
