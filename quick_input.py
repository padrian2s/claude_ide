#!/usr/bin/env python3
"""Quick input popup for sending text to F1 terminal with autocomplete."""

import subprocess
from pathlib import Path

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

SCRIPT_DIR = Path(__file__).parent
CORPUS_FILE = SCRIPT_DIR / "prompt_words.txt"
LEARNED_FILE = SCRIPT_DIR / ".prompt_learned_words.txt"


def load_words() -> list[str]:
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
    return sorted(words)


class NumberedCompleter(Completer):
    """Completer that shows numbered suggestions (1, 2, 3)."""

    def __init__(self, words: list[str]):
        self.words = words
        self.last_completions = []  # Store last completions for quick access

    def get_completions(self, document, complete_event):
        word = document.get_word_before_cursor().lower()
        if not word:
            self.last_completions = []
            return

        # Find matching words
        matches = []
        for w in self.words:
            if word in w:  # match_middle
                matches.append(w)
            if len(matches) >= 10:  # Limit results
                break

        self.last_completions = matches

        # Yield completions with numbers
        for i, match in enumerate(matches):
            num = str(i + 1) if i < 9 else " "
            yield Completion(
                match,
                start_position=-len(word),
                display=HTML(f"<b>{num}</b> {match}"),
                display_meta="",
            )


def main():
    bindings = KeyBindings()
    words = load_words()
    completer = NumberedCompleter(words)

    @bindings.add(Keys.Escape)
    def _(event):
        """Exit on Escape."""
        event.app.exit()

    def apply_completion(event, index: int):
        """Apply completion by index directly."""
        buff = event.app.current_buffer

        # If complete_state exists, use it
        if buff.complete_state and buff.complete_state.completions:
            completions = list(buff.complete_state.completions)
            if index < len(completions):
                buff.go_to_completion(index)
                buff.complete_state = None
                return True

        # Otherwise, use cached completions from completer
        if index < len(completer.last_completions):
            word = buff.document.get_word_before_cursor()
            if word:
                # Delete current word and insert completion
                buff.delete_before_cursor(len(word))
                buff.insert_text(completer.last_completions[index])
                return True

        return False

    @bindings.add("1")
    def _(event):
        if not apply_completion(event, 0):
            event.app.current_buffer.insert_text("1")

    @bindings.add("2")
    def _(event):
        if not apply_completion(event, 1):
            event.app.current_buffer.insert_text("2")

    @bindings.add("3")
    def _(event):
        if not apply_completion(event, 2):
            event.app.current_buffer.insert_text("3")

    @bindings.add("4")
    def _(event):
        if not apply_completion(event, 3):
            event.app.current_buffer.insert_text("4")

    @bindings.add("5")
    def _(event):
        if not apply_completion(event, 4):
            event.app.current_buffer.insert_text("5")

    try:
        text = prompt(
            "→ F1: ",
            key_bindings=bindings,
            completer=completer,
            complete_while_typing=True,
            multiline=False,
        )

        if text and text.strip():
            # Send text to F1 (window 1)
            subprocess.run(
                ["tmux", "send-keys", "-t", ":1", "-l", text.strip()],
                capture_output=True
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", ":1", "Enter"],
                capture_output=True
            )
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
