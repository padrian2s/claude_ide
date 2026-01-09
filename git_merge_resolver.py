#!/usr/bin/env python3
"""Three-way Git merge conflict resolver with AI-assisted suggestions."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import NamedTuple

import anthropic
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    ProgressBar,
    Static,
    TextArea,
)
from textual import work

# =============================================================================
# Data Models
# =============================================================================


@dataclass
class ConflictHunk:
    """Represents a single conflict region in a file."""

    id: int
    start_line: int
    end_line: int
    base_content: str  # Common ancestor
    ours_content: str  # Local changes (HEAD)
    theirs_content: str  # Incoming changes
    resolved: bool = False
    resolution: str = ""
    resolution_type: str = ""  # "ours", "theirs", "both", "manual", "ai"


@dataclass
class ConflictFile:
    """A file with merge conflicts."""

    path: Path
    hunks: list[ConflictHunk] = field(default_factory=list)
    original_content: str = ""

    @property
    def resolved_count(self) -> int:
        return sum(1 for h in self.hunks if h.resolved)

    @property
    def is_fully_resolved(self) -> bool:
        return all(h.resolved for h in self.hunks)


# =============================================================================
# Word-Level Diff Engine
# =============================================================================


class DiffWord(NamedTuple):
    """A word with its origin source."""

    text: str
    source: str  # "base", "ours", "theirs", "common"


class WordDiffer:
    """Computes word-level diffs between three versions (base, ours, theirs).

    Provides colored markup showing the origin of each word in a merged view.
    """

    # Colors for each source
    COLORS = {
        "base": "bright_black",
        "ours": "green",
        "theirs": "yellow",
        "common": "white",
        "conflict": "red",
    }

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Split text into tokens (words and whitespace/punctuation)."""
        if not text:
            return []
        # Split on word boundaries while preserving whitespace and punctuation
        return re.findall(r'\S+|\s+', text)

    @classmethod
    def diff_two(cls, a: str, b: str) -> list[tuple[str, str, str]]:
        """Compute diff between two texts, returning (tag, a_text, b_text) tuples.

        Tags: 'equal', 'replace', 'insert', 'delete'
        """
        a_tokens = cls.tokenize(a)
        b_tokens = cls.tokenize(b)

        matcher = SequenceMatcher(None, a_tokens, b_tokens)
        result = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            a_chunk = ''.join(a_tokens[i1:i2])
            b_chunk = ''.join(b_tokens[j1:j2])
            result.append((tag, a_chunk, b_chunk))

        return result

    @classmethod
    def three_way_diff(
        cls, base: str, ours: str, theirs: str
    ) -> list[DiffWord]:
        """Compute three-way diff and return words with their sources.

        Uses a simpler, more reliable approach: compare ours and theirs directly,
        using base only to determine if a change came from one side.
        """
        # Simple approach: just diff ours vs theirs and color by source
        if not base:
            return cls._diff_ours_theirs(ours, theirs)

        # Tokenize all three
        base_tokens = cls.tokenize(base)
        ours_tokens = cls.tokenize(ours)
        theirs_tokens = cls.tokenize(theirs)

        # If ours == theirs, everything is common
        if ours == theirs:
            return [DiffWord(ours, "common")] if ours else []

        # Use SequenceMatcher to diff ours vs theirs
        matcher = SequenceMatcher(None, ours_tokens, theirs_tokens)
        result = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            ours_chunk = ''.join(ours_tokens[i1:i2])
            theirs_chunk = ''.join(theirs_tokens[j1:j2])

            if tag == 'equal':
                # Same in both - mark as common
                if ours_chunk:
                    result.append(DiffWord(ours_chunk, "common"))
            elif tag == 'replace':
                # Different - show both with their colors
                if ours_chunk:
                    result.append(DiffWord(ours_chunk, "ours"))
                if theirs_chunk:
                    result.append(DiffWord(theirs_chunk, "theirs"))
            elif tag == 'delete':
                # Only in ours
                if ours_chunk:
                    result.append(DiffWord(ours_chunk, "ours"))
            elif tag == 'insert':
                # Only in theirs
                if theirs_chunk:
                    result.append(DiffWord(theirs_chunk, "theirs"))

        return result

    @classmethod
    def _diff_ours_theirs(cls, ours: str, theirs: str) -> list[DiffWord]:
        """Two-way diff when base is not available."""
        diff_ops = cls.diff_two(ours, theirs)
        result = []

        for tag, ours_text, theirs_text in diff_ops:
            if tag == 'equal':
                if ours_text:
                    result.append(DiffWord(ours_text, "common"))
            elif tag == 'replace':
                if ours_text:
                    result.append(DiffWord(ours_text, "ours"))
                if theirs_text:
                    result.append(DiffWord(theirs_text, "theirs"))
            elif tag == 'delete':
                if ours_text:
                    result.append(DiffWord(ours_text, "ours"))
            elif tag == 'insert':
                if theirs_text:
                    result.append(DiffWord(theirs_text, "theirs"))

        return result

    @classmethod
    def render_merged_view(cls, base: str, ours: str, theirs: str) -> str:
        """Render a colored merged view showing word origins.

        Returns Rich-formatted text with colors indicating source:
        - Green: from ours (left panel)
        - Yellow: from theirs (right panel)
        - White: common to both
        - Gray: unchanged from base
        """
        words = cls.three_way_diff(base, ours, theirs)

        parts = []
        for word in words:
            color = cls.COLORS.get(word.source, "white")
            # Escape Rich markup in text
            escaped = word.text.replace("[", "\\[").replace("]", "\\]")
            parts.append(f"[{color}]{escaped}[/]")

        return "".join(parts)

    @classmethod
    def render_side_by_side(
        cls, base: str, ours: str, theirs: str, width: int = 40
    ) -> tuple[str, str, str]:
        """Render three versions with diff highlighting.

        Returns (base_markup, ours_markup, theirs_markup) with changed
        regions highlighted.
        """
        base_lines = base.split('\n') if base else ['(empty)']
        ours_lines = ours.split('\n') if ours else ['(empty)']
        theirs_lines = theirs.split('\n') if theirs else ['(empty)']

        # Highlight changes in ours vs base
        ours_markup = cls._highlight_changes(base, ours, "green", "bold green")

        # Highlight changes in theirs vs base
        theirs_markup = cls._highlight_changes(base, theirs, "yellow", "bold yellow")

        # Base stays neutral
        base_escaped = base.replace("[", "\\[").replace("]", "\\]") if base else "(empty)"
        base_markup = f"[bright_black]{base_escaped}[/]"

        return base_markup, ours_markup, theirs_markup

    @classmethod
    def render_convergence_view(
        cls, base: str, ours: str, theirs: str, panel_width: int = 25
    ) -> str:
        """Render a convergence view showing left/middle/right merging to center.

        Visual layout:
        ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
        │ OURS (left) │   │    BASE     │   │THEIRS(right)│
        │   green     │ → │    gray     │ ← │   yellow    │
        └─────────────┘   └─────────────┘   └─────────────┘
                          ↓↓↓↓↓↓↓↓↓↓↓↓↓
                    ┌─────────────────────────┐
                    │    MERGED (center)      │
                    │  [green]ours[/] [white]common[/] [yellow]theirs[/]  │
                    └─────────────────────────┘
        """
        # Get lines from each version
        ours_lines = ours.split('\n') if ours else ['(empty)']
        base_lines = base.split('\n') if base else ['(empty)']
        theirs_lines = theirs.split('\n') if theirs else ['(empty)']

        # Get merged words with color info
        merged_words = cls.three_way_diff(base, ours, theirs)

        # Build the output
        output_lines = []

        # Header row
        output_lines.append(
            f"[green]{'═' * panel_width}[/]   "
            f"[bright_black]{'═' * panel_width}[/]   "
            f"[yellow]{'═' * panel_width}[/]"
        )
        output_lines.append(
            f"[bold green]{'OURS (LEFT)':^{panel_width}}[/]   "
            f"[bold bright_black]{'BASE (MIDDLE)':^{panel_width}}[/]   "
            f"[bold yellow]{'THEIRS (RIGHT)':^{panel_width}}[/]"
        )
        output_lines.append(
            f"[green]{'─' * panel_width}[/]   "
            f"[bright_black]{'─' * panel_width}[/]   "
            f"[yellow]{'─' * panel_width}[/]"
        )

        # Content rows - align all three panels
        max_lines = max(len(ours_lines), len(base_lines), len(theirs_lines))

        for i in range(max_lines):
            # Get line from each, pad if needed
            ours_line = ours_lines[i] if i < len(ours_lines) else ''
            base_line = base_lines[i] if i < len(base_lines) else ''
            theirs_line = theirs_lines[i] if i < len(theirs_lines) else ''

            # Truncate and pad to panel width
            ours_display = cls._truncate_pad(ours_line, panel_width)
            base_display = cls._truncate_pad(base_line, panel_width)
            theirs_display = cls._truncate_pad(theirs_line, panel_width)

            # Escape Rich markup
            ours_display = ours_display.replace("[", "\\[").replace("]", "\\]")
            base_display = base_display.replace("[", "\\[").replace("]", "\\]")
            theirs_display = theirs_display.replace("[", "\\[").replace("]", "\\]")

            output_lines.append(
                f"[green]{ours_display}[/]   "
                f"[bright_black]{base_display}[/]   "
                f"[yellow]{theirs_display}[/]"
            )

        # Convergence arrows
        arrow_width = panel_width * 3 + 6
        output_lines.append("")
        output_lines.append(f"[cyan]{'↘':>{panel_width}}   {'↓':^{panel_width}}   {'↙':<{panel_width}}[/]")
        output_lines.append(f"[cyan]{' ' * panel_width}   {'↓':^{panel_width}}   {' ' * panel_width}[/]")

        # Merged result header
        merged_width = panel_width * 3 + 6
        output_lines.append(f"[bold cyan]{'═' * merged_width}[/]")
        output_lines.append(f"[bold cyan]{'MERGED RESULT (CENTER)':^{merged_width}}[/]")
        output_lines.append(f"[cyan]{'─' * merged_width}[/]")

        # Render merged content with colors
        merged_content = cls._render_merged_words(merged_words)
        for line in merged_content.split('\n'):
            output_lines.append(f"  {line}")

        output_lines.append(f"[cyan]{'═' * merged_width}[/]")

        # Legend
        output_lines.append("")
        output_lines.append(
            f"[dim]Legend:[/] [green]■ from left (ours)[/]  "
            f"[yellow]■ from right (theirs)[/]  "
            f"[white]■ common[/]  "
            f"[bright_black]■ base[/]"
        )

        return '\n'.join(output_lines)

    @classmethod
    def _truncate_pad(cls, text: str, width: int) -> str:
        """Truncate or pad text to exact width."""
        if len(text) > width - 1:
            return text[:width - 2] + '…'
        return text.ljust(width)

    @classmethod
    def _render_merged_words(cls, words: list[DiffWord]) -> str:
        """Render merged words with Rich color markup."""
        parts = []
        for word in words:
            color = cls.COLORS.get(word.source, "white")
            escaped = word.text.replace("[", "\\[").replace("]", "\\]")
            parts.append(f"[{color}]{escaped}[/]")
        return ''.join(parts)

    @classmethod
    def _highlight_changes(
        cls, base: str, modified: str, base_color: str, change_color: str
    ) -> str:
        """Highlight parts of modified that differ from base."""
        if not base:
            # All new content
            escaped = modified.replace("[", "\\[").replace("]", "\\]")
            return f"[{change_color}]{escaped}[/]"

        diff_ops = cls.diff_two(base, modified)
        parts = []

        for tag, _, mod_text in diff_ops:
            if not mod_text:
                continue
            escaped = mod_text.replace("[", "\\[").replace("]", "\\]")
            if tag == 'equal':
                parts.append(f"[{base_color}]{escaped}[/]")
            else:
                parts.append(f"[{change_color}]{escaped}[/]")

        return "".join(parts)

    @classmethod
    def ai_merge(
        cls,
        base: str,
        local: str,
        server: str,
        file_ext: str = "",
    ) -> str:
        """Lightweight AI merge for complex conflicts.

        Uses Claude Haiku for fast, cheap merging that produces
        human-readable, syntactically correct results.
        """
        # Skip AI for identical content
        if local == server:
            return local

        # Skip AI for empty content
        if not local and not server:
            return ""
        if not local:
            return server
        if not server:
            return local

        # Build concise prompt
        lang_hint = f" ({file_ext})" if file_ext else ""
        prompt = f"""Merge these code changes{lang_hint}. Output ONLY the merged code, no explanation.

BASE:
{base[:1500] if base else '(none)'}

LOCAL:
{local[:1500]}

SERVER:
{server[:1500]}

Merged code:"""

        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-3-haiku-20240307",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.content[0].text.strip()

            # Remove markdown code blocks if present
            if result.startswith("```"):
                lines = result.split("\n")
                lines = lines[1:]  # Remove first ```
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                result = "\n".join(lines)

            return result

        except Exception as e:
            # Fallback to simple concatenation on error
            return f"// AI merge failed: {e}\n// LOCAL:\n{local}\n// SERVER:\n{server}"


# =============================================================================
# Git Integration
# =============================================================================


class ConflictDetector:
    """Detects conflicted files from git status."""

    def __init__(self, repo_path: Path | None = None):
        self.repo_path = repo_path or Path.cwd()

    def get_conflicted_files(self) -> list[Path]:
        """Get list of files with unmerged conflicts."""
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        if result.returncode != 0:
            return []
        return [
            self.repo_path / f.strip()
            for f in result.stdout.strip().split("\n")
            if f.strip()
        ]

    def get_base_version(self, file_path: Path) -> str:
        """Get common ancestor version using git show :1:file."""
        try:
            rel_path = file_path.relative_to(self.repo_path)
        except ValueError:
            rel_path = file_path
        result = subprocess.run(
            ["git", "show", f":1:{rel_path}"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.stdout if result.returncode == 0 else ""

    def get_ours_version(self, file_path: Path) -> str:
        """Get our version using git show :2:file."""
        try:
            rel_path = file_path.relative_to(self.repo_path)
        except ValueError:
            rel_path = file_path
        result = subprocess.run(
            ["git", "show", f":2:{rel_path}"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.stdout if result.returncode == 0 else ""

    def get_theirs_version(self, file_path: Path) -> str:
        """Get their version using git show :3:file."""
        try:
            rel_path = file_path.relative_to(self.repo_path)
        except ValueError:
            rel_path = file_path
        result = subprocess.run(
            ["git", "show", f":3:{rel_path}"],
            capture_output=True,
            text=True,
            cwd=self.repo_path,
        )
        return result.stdout if result.returncode == 0 else ""


class ConflictParser:
    """Parses conflict markers into structured hunks."""

    CONFLICT_START = "<<<<<<"
    CONFLICT_BASE = "||||||"
    CONFLICT_SEP = "======"
    CONFLICT_END = ">>>>>>"

    def parse_file(self, file_path: Path, base_content: str = "") -> ConflictFile:
        """Parse a file with conflict markers into structured hunks."""
        content = file_path.read_text()
        hunks = []
        hunk_id = 0

        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            if line.startswith(self.CONFLICT_START):
                hunk_start = i
                ours_lines = []
                base_lines = []
                theirs_lines = []

                i += 1
                # Collect "ours" section
                while i < len(lines):
                    if lines[i].startswith(self.CONFLICT_BASE):
                        break
                    if lines[i].startswith(self.CONFLICT_SEP):
                        break
                    ours_lines.append(lines[i])
                    i += 1

                # Check for base section (diff3 style)
                if i < len(lines) and lines[i].startswith(self.CONFLICT_BASE):
                    i += 1
                    while i < len(lines) and not lines[i].startswith(self.CONFLICT_SEP):
                        base_lines.append(lines[i])
                        i += 1

                # Skip separator
                if i < len(lines) and lines[i].startswith(self.CONFLICT_SEP):
                    i += 1

                # Collect "theirs" section
                while i < len(lines) and not lines[i].startswith(self.CONFLICT_END):
                    theirs_lines.append(lines[i])
                    i += 1

                hunk = ConflictHunk(
                    id=hunk_id,
                    start_line=hunk_start + 1,
                    end_line=i + 1,
                    base_content="\n".join(base_lines),
                    ours_content="\n".join(ours_lines),
                    theirs_content="\n".join(theirs_lines),
                )
                hunks.append(hunk)
                hunk_id += 1
            i += 1

        return ConflictFile(path=file_path, hunks=hunks, original_content=content)


# =============================================================================
# AI Integration
# =============================================================================


class ConflictAIResolver:
    """AI-powered conflict resolution suggestions using Claude API."""

    SYSTEM_PROMPT = """You are an expert at resolving Git merge conflicts.
Your task is to analyze a merge conflict and suggest the best resolution.

You will be given:
- BASE: The common ancestor version (if available)
- OURS: The local changes (from HEAD/current branch)
- THEIRS: The incoming changes (from the branch being merged)
- CONTEXT: Surrounding code for understanding

Guidelines:
- Understand the intent of both changes
- Preserve functionality from both sides when possible
- Follow the code style of the surrounding context
- Return ONLY the resolved code, no explanations or markdown
- If changes conflict semantically, combine them logically
- Preserve comments and documentation"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required")
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def suggest_resolution(
        self,
        hunk: ConflictHunk,
        context_before: str = "",
        context_after: str = "",
        file_path: str = "",
    ) -> str:
        """Generate AI suggestion for resolving a conflict hunk."""
        prompt = f"""File: {file_path}

CONTEXT BEFORE:
{context_before[-500:] if context_before else "(none)"}

--- CONFLICT START ---

BASE (common ancestor):
{hunk.base_content or "(not available)"}

OURS (local changes):
{hunk.ours_content}

THEIRS (incoming changes):
{hunk.theirs_content}

--- CONFLICT END ---

CONTEXT AFTER:
{context_after[:500] if context_after else "(none)"}

Provide the resolved code that best combines or chooses between these changes. Return ONLY the code, no explanations:"""

        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        response = message.content[0].text.strip()
        # Remove any markdown code blocks if present
        if response.startswith("```"):
            lines = response.split("\n")
            # Remove first line (```python or ```)
            lines = lines[1:]
            # Remove last line if it's ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines)
        return response


# =============================================================================
# UI Widgets
# =============================================================================


class FileItem(ListItem):
    """A conflicted file item in the sidebar."""

    def __init__(self, conflict_file: ConflictFile):
        super().__init__()
        self.conflict_file = conflict_file

    def compose(self) -> ComposeResult:
        resolved = self.conflict_file.resolved_count
        total = len(self.conflict_file.hunks)
        if self.conflict_file.is_fully_resolved:
            icon = "[green]✓[/]"
        else:
            icon = "[yellow]![/]"
        name = self.conflict_file.path.name
        yield Static(f" {icon} {name} ({resolved}/{total})")


# =============================================================================
# Modal Dialogs
# =============================================================================


class LoadingDialog(ModalScreen):
    """Loading dialog with spinner."""

    CSS = """
    LoadingDialog {
        align: center middle;
        background: transparent;
    }
    #loading-box {
        width: 50;
        height: 7;
        border: round $primary;
        background: $surface;
        padding: 1 2;
        border-title-align: center;
    }
    #loading-spinner {
        text-align: center;
        width: 100%;
    }
    """

    SPINNER_FRAMES = [
        "⠋ Analyzing conflict...",
        "⠙ Analyzing conflict...",
        "⠹ Analyzing conflict...",
        "⠸ Analyzing conflict...",
        "⠼ Analyzing conflict...",
        "⠴ Analyzing conflict...",
        "⠦ Analyzing conflict...",
        "⠧ Analyzing conflict...",
        "⠇ Analyzing conflict...",
        "⠏ Analyzing conflict...",
    ]

    def __init__(self, message: str = "Processing..."):
        super().__init__()
        self.message = message
        self._frame = 0
        self._timer = None

    def compose(self) -> ComposeResult:
        box = Vertical(id="loading-box")
        box.border_title = "AI Suggestion"
        with box:
            yield Label(self.SPINNER_FRAMES[0], id="loading-spinner")

    def on_mount(self):
        self._timer = self.set_interval(0.1, self._animate)

    def _animate(self):
        self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
        spinner = self.query_one("#loading-spinner", Label)
        spinner.update(self.SPINNER_FRAMES[self._frame])

    def on_unmount(self):
        if self._timer:
            self._timer.stop()


class AISuggestionDialog(ModalScreen):
    """Modal showing AI-suggested resolution."""

    CSS = """
    AISuggestionDialog {
        align: center middle;
        background: transparent;
    }
    #ai-dialog {
        width: 90%;
        height: 85%;
        border: round $primary;
        background: $background;
        padding: 1;
        border-title-align: left;
        border-title-color: $primary;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    #comparison {
        height: 1fr;
    }
    .compare-panel {
        width: 50%;
        border: round $border;
        padding: 1;
        margin: 0 1;
    }
    #original-panel {
        border-title-color: $warning;
    }
    #suggested-panel {
        border-title-color: $success;
    }
    """

    BINDINGS = [
        ("a", "accept", "Accept"),
        ("e", "edit", "Edit"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, hunk: ConflictHunk, suggestion: str):
        super().__init__()
        self.hunk = hunk
        self.suggestion = suggestion

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="ai-dialog")
        dialog.border_title = "AI Suggestion"
        dialog.border_subtitle = "a:Accept · e:Edit · Esc:Cancel"
        with dialog:
            with Horizontal(id="comparison"):
                original = Vertical(id="original-panel", classes="compare-panel")
                original.border_title = "Original (Ours | Theirs)"
                with original:
                    with VerticalScroll():
                        content = f"[bold cyan]OURS:[/]\n{self.hunk.ours_content}\n\n[bold yellow]THEIRS:[/]\n{self.hunk.theirs_content}"
                        yield Static(content)

                suggested = Vertical(id="suggested-panel", classes="compare-panel")
                suggested.border_title = "AI Suggestion"
                with suggested:
                    with VerticalScroll():
                        yield Static(self.suggestion, markup=False)

    def action_accept(self):
        self.dismiss({"action": "accept", "suggestion": self.suggestion})

    def action_edit(self):
        self.dismiss({"action": "edit", "suggestion": self.suggestion})

    def action_cancel(self):
        self.dismiss(None)


class ManualEditDialog(ModalScreen):
    """Dialog for manually editing conflict resolution."""

    CSS = """
    ManualEditDialog {
        align: center middle;
        background: transparent;
    }
    #edit-dialog {
        width: 90%;
        height: 85%;
        border: round $primary;
        background: $background;
        padding: 1;
        border-title-align: left;
        border-title-color: $primary;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    #edit-area {
        height: 1fr;
        border: round $border;
    }
    #reference-panel {
        height: 30%;
        border: round $border;
        margin-top: 1;
        border-title-color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, hunk: ConflictHunk, prefill: str = ""):
        super().__init__()
        self.hunk = hunk
        self.prefill = prefill or hunk.ours_content

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="edit-dialog")
        dialog.border_title = "Manual Edit"
        dialog.border_subtitle = "Ctrl+S:Save · Esc:Cancel"
        with dialog:
            yield TextArea(self.prefill, id="edit-area")
            ref = Vertical(id="reference-panel")
            ref.border_title = "Reference (Ours | Theirs)"
            with ref:
                with VerticalScroll():
                    content = f"[cyan]OURS:[/] {self.hunk.ours_content[:200]}...\n[yellow]THEIRS:[/] {self.hunk.theirs_content[:200]}..."
                    yield Static(content)

    def action_save(self):
        area = self.query_one("#edit-area", TextArea)
        self.dismiss({"action": "save", "content": area.text})

    def action_cancel(self):
        self.dismiss(None)


class PreviewDialog(ModalScreen):
    """Preview the fully merged file before saving."""

    CSS = """
    PreviewDialog {
        align: center middle;
        background: transparent;
    }
    #preview-dialog {
        width: 90%;
        height: 90%;
        border: round $primary;
        background: $background;
        padding: 1;
        border-title-align: left;
        border-title-color: $primary;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    #preview-scroll {
        height: 1fr;
        border: round $border;
    }
    """

    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, file_path: Path, merged_content: str):
        super().__init__()
        self.file_path = file_path
        self.merged_content = merged_content

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="preview-dialog")
        dialog.border_title = f"Preview: {self.file_path.name}"
        dialog.border_subtitle = "Ctrl+S:Save · Esc:Cancel"
        with dialog:
            with VerticalScroll(id="preview-scroll"):
                yield Static(self.merged_content, markup=False)

    def action_save(self):
        self.dismiss({"action": "save"})

    def action_cancel(self):
        self.dismiss(None)


class ConfirmDialog(ModalScreen):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmDialog {
        align: center middle;
        background: transparent;
    }
    #confirm-box {
        width: 60;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
        border-title-align: left;
        border-title-color: $warning;
    }
    #confirm-message {
        margin-bottom: 1;
    }
    #confirm-hint {
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        ("y", "confirm", "Yes"),
        ("n", "cancel", "No"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        box = Vertical(id="confirm-box")
        box.border_title = self.title_text
        with box:
            yield Static(self.message, id="confirm-message")
            yield Static("y:Yes · n:No", id="confirm-hint")

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


# =============================================================================
# Main Application
# =============================================================================


class MergeResolverApp(App):
    """Three-way Git merge conflict resolver."""

    TITLE = "Git Merge Resolver"

    CSS = """
    * {
        scrollbar-size: 1 1;
    }

    MergeResolverApp {
        background: $background;
    }

    /* File sidebar */
    #file-sidebar {
        width: 24;
        border: round $border;
        background: $surface;
        border-title-align: left;
        border-title-color: $text-muted;
        overflow: hidden;
    }
    #file-sidebar:focus-within {
        border: round $primary;
        border-title-color: $primary;
    }
    #file-sidebar.hidden {
        display: none;
    }
    #file-list {
        height: 1fr;
        background: $surface;
        overflow-y: auto;
        overflow-x: hidden;
    }

    /* Three panels: Local | Result | Server - IntelliJ style */
    #panels {
        height: 1fr;
        overflow: hidden;
    }
    .conflict-panel {
        width: 1fr;
        border-top: solid $border;
        border-bottom: solid $border;
        border-left: none;
        border-right: none;
        background: $background;
        border-title-align: center;
        border-title-style: bold;
        margin: 0;
        padding: 0 1;
        overflow-x: hidden;
        overflow-y: auto;
    }
    .conflict-panel > Static {
        width: 100%;
        overflow: hidden;
    }
    .conflict-panel:focus-within {
        border-top: solid $primary;
        border-bottom: solid $primary;
    }
    #local-panel {
        border-left: solid $border;
        border-title-color: $success;
    }
    #result-panel {
        border-left: solid $border;
        border-right: solid $border;
        border-title-color: $primary;
    }
    #server-panel {
        border-right: solid $border;
        border-title-color: $warning;
    }

    /* Status bar - compact single line */
    #status-bar {
        height: 1;
        background: $surface;
        padding: 0 1;
        overflow: hidden;
    }
    #hunk-info {
        width: auto;
        overflow: hidden;
    }
    #progress-info {
        width: auto;
        margin: 0 2;
        overflow: hidden;
    }
    #help-info {
        width: 1fr;
        text-align: right;
        color: $text-muted;
        overflow: hidden;
    }

    /* ListItem styling */
    ListItem {
        background: $surface;
        overflow: hidden;
        width: 100%;
    }
    ListItem > Static {
        overflow: hidden;
        width: 100%;
    }
    ListItem.-highlight {
        background: $primary 30%;
    }
    ListView {
        background: $surface;
        overflow-x: hidden;
    }
    ListView:focus ListItem.-highlight {
        background: $primary 40%;
    }
    """

    BINDINGS = [
        # Navigation
        ("j", "next_hunk", "Next hunk"),
        ("k", "prev_hunk", "Prev hunk"),
        ("n", "next_file", "Next file"),
        ("p", "prev_file", "Prev file"),
        Binding("tab", "cycle_focus", "Cycle focus"),
        # Resolution actions (IntelliJ style: left=local, right=server)
        ("l", "accept_local", "Accept local"),
        ("r", "accept_server", "Accept server"),
        ("b", "accept_both", "Accept both"),
        ("m", "manual_edit", "Manual edit"),
        ("a", "ai_suggest", "AI suggestion"),
        ("u", "undo_resolution", "Undo"),
        # File operations
        ("w", "preview_file", "Preview"),
        Binding("ctrl+s", "save_file", "Save", priority=True),
        ("R", "refresh", "Refresh"),
        # General
        ("f", "toggle_sidebar", "Files"),
        ("g", "toggle_position", "First/Last"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, repo_path: Path | None = None):
        super().__init__()
        self.repo_path = repo_path or Path.cwd()
        self.detector = ConflictDetector(self.repo_path)
        self.parser = ConflictParser()
        self.conflict_files: list[ConflictFile] = []
        self.current_file: ConflictFile | None = None
        self.current_hunk_idx: int = 0
        self._loading_dialog: LoadingDialog | None = None
        self._at_end = False  # For g key toggle
        self._merge_cache: dict[int, str] = {}  # Cache AI merge results
        self._pending_merges: set[int] = set()  # Track in-flight AI requests

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            sidebar = Vertical(id="file-sidebar")
            sidebar.border_title = "Files"
            with sidebar:
                yield ListView(id="file-list")

            # Three panels: Local | Result | Server (IntelliJ style)
            with Horizontal(id="panels"):
                local = VerticalScroll(id="local-panel", classes="conflict-panel")
                local.border_title = "◀ Local"
                with local:
                    yield Static("", id="local-content")

                result = VerticalScroll(id="result-panel", classes="conflict-panel")
                result.border_title = "Result"
                with result:
                    yield Static("", id="result-content")

                server = VerticalScroll(id="server-panel", classes="conflict-panel")
                server.border_title = "Server ▶"
                with server:
                    yield Static("", id="server-content")

        # Single compact status bar
        with Horizontal(id="status-bar"):
            yield Static("", id="hunk-info")
            yield Static("", id="progress-info")
            yield Static("j/k:hunk l:local r:server b:both m:edit a:AI f:files ^S:save", id="help-info")
        yield Footer()

    def on_mount(self):
        """Load conflicted files on startup."""
        self._load_conflicts()
        if not self.conflict_files:
            self.notify("No merge conflicts detected in repository", severity="warning", timeout=5)
        else:
            self.query_one("#file-list", ListView).focus()

    def _load_conflicts(self):
        """Detect and load all conflicted files."""
        paths = self.detector.get_conflicted_files()
        self.conflict_files = []

        for path in paths:
            try:
                # Get base version from git index
                base_content = self.detector.get_base_version(path)
                conflict_file = self.parser.parse_file(path, base_content)
                # If parser didn't get base from diff3 markers, use git's base
                if conflict_file.hunks:
                    for hunk in conflict_file.hunks:
                        if not hunk.base_content:
                            hunk.base_content = base_content
                    self.conflict_files.append(conflict_file)
            except Exception as e:
                self.notify(f"Error parsing {path.name}: {e}", severity="error")

        self._refresh_file_list()

        if self.conflict_files:
            self._select_file(self.conflict_files[0])

    def _refresh_file_list(self):
        """Refresh the file list sidebar."""
        file_list = self.query_one("#file-list", ListView)
        file_list.clear()
        for cf in self.conflict_files:
            file_list.append(FileItem(cf))

    def _select_file(self, conflict_file: ConflictFile):
        """Select a file and display its first hunk."""
        self.current_file = conflict_file
        self.current_hunk_idx = 0
        self._at_end = False
        self._display_current_hunk()

    def _format_with_line_numbers(
        self, content: str, start_line: int, color: str, line_color: str = "dim"
    ) -> str:
        """Format content with line numbers and color coding.

        Args:
            content: The code content to format
            start_line: Starting line number
            color: Rich color for the code (e.g., "cyan", "green", "yellow")
            line_color: Color for line numbers
        """
        if not content:
            return f"[dim](empty)[/]"

        lines = content.split("\n")
        formatted_lines = []
        line_num_width = len(str(start_line + len(lines)))

        for i, line in enumerate(lines):
            line_num = start_line + i
            # Escape any Rich markup in the line content
            escaped_line = line.replace("[", "\\[").replace("]", "\\]")
            formatted_lines.append(
                f"[{line_color}]{line_num:>{line_num_width}}[/] [{color}]│[/] [{color}]{escaped_line}[/]"
            )

        return "\n".join(formatted_lines)

    def _display_current_hunk(self):
        """Display the current hunk in IntelliJ-style: Local | Result | Server."""
        if not self.current_file or not self.current_file.hunks:
            self.query_one("#local-content", Static).update("[dim]No conflicts[/]")
            self.query_one("#result-content", Static).update("[dim]No conflicts[/]")
            self.query_one("#server-content", Static).update("[dim]No conflicts[/]")
            self.query_one("#hunk-info", Static).update("[dim]No conflicts[/]")
            return

        hunk = self.current_file.hunks[self.current_hunk_idx]

        # Left panel: Local changes (ours/HEAD) - green
        local_text = self._format_with_line_numbers(
            hunk.ours_content, hunk.start_line, "green", "dim green"
        )

        # Right panel: Server changes (theirs/incoming) - yellow
        server_text = self._format_with_line_numbers(
            hunk.theirs_content, hunk.start_line, "yellow", "dim yellow"
        )

        # Middle panel: Merged result with color-coded words
        if hunk.resolved:
            # Show the resolved content
            result_text = self._format_with_line_numbers(
                hunk.resolution, hunk.start_line, "white", "dim"
            )
        else:
            # Show word-level diff merge with colors indicating source
            result_text = self._render_merged_result(hunk)

        self.query_one("#local-content", Static).update(local_text)
        self.query_one("#result-content", Static).update(result_text)
        self.query_one("#server-content", Static).update(server_text)

        # Update panel titles
        self.query_one("#local-panel").border_title = "◀ Local"
        self.query_one("#server-panel").border_title = "Server ▶"

        if hunk.resolved:
            self.query_one("#result-panel").border_title = f"✓ Result [{hunk.resolution_type}]"
        else:
            self.query_one("#result-panel").border_title = "Result"

        # Update compact status bar
        total = len(self.current_file.hunks)
        resolved = self.current_file.resolved_count
        status = "[green]✓[/]" if hunk.resolved else "[yellow]●[/]"

        self.query_one("#hunk-info", Static).update(
            f"{status} Hunk {self.current_hunk_idx + 1}/{total}"
        )
        self.query_one("#progress-info", Static).update(
            f"[dim]{resolved}/{total} resolved[/]"
        )

    def _render_merged_result(self, hunk: ConflictHunk) -> str:
        """Render the merged result panel using lightweight AI merge."""
        # Create cache key from content hash
        cache_key = hash((hunk.base_content, hunk.ours_content, hunk.theirs_content))

        # Check if merge is in progress
        if cache_key in self._pending_merges:
            return "[dim]⟳ Generating AI merge...[/]"

        # Check cache first
        if cache_key in self._merge_cache:
            merged = self._merge_cache[cache_key]
        else:
            # Start async AI merge
            self._pending_merges.add(cache_key)
            self._request_ai_merge(hunk, cache_key)
            return "[dim]⟳ Generating AI merge...[/]"

        # Format with line numbers
        lines = merged.split("\n")
        formatted_lines = []
        line_num_width = len(str(hunk.start_line + len(lines)))

        for i, line in enumerate(lines):
            line_num = hunk.start_line + i
            # Escape Rich markup in merged content
            escaped_line = line.replace("[", "\\[").replace("]", "\\]")
            formatted_lines.append(f"[dim]{line_num:>{line_num_width}}[/] [cyan]│[/] {escaped_line}")

        return "\n".join(formatted_lines)

    @work(thread=True)
    def _request_ai_merge(self, hunk: ConflictHunk, cache_key: int) -> None:
        """Request AI merge in background thread."""
        try:
            # Get file extension for language hint
            ext = ""
            if self.current_file:
                ext = self.current_file.path.suffix

            # Call AI merge
            merged = WordDiffer.ai_merge(
                hunk.base_content,
                hunk.ours_content,
                hunk.theirs_content,
                ext,
            )

            # Update cache and UI on main thread
            self.call_from_thread(self._on_ai_merge_complete, cache_key, merged)

        except Exception as e:
            self.call_from_thread(
                self._on_ai_merge_complete,
                cache_key,
                f"// AI merge error: {e}",
            )

    def _on_ai_merge_complete(self, cache_key: int, merged: str) -> None:
        """Handle completed AI merge."""
        self._merge_cache[cache_key] = merged
        self._pending_merges.discard(cache_key)

        # Refresh display if still on same hunk
        if self.current_file and self.current_file.hunks:
            current_hunk = self.current_file.hunks[self.current_hunk_idx]
            current_key = hash((
                current_hunk.base_content,
                current_hunk.ours_content,
                current_hunk.theirs_content,
            ))
            if current_key == cache_key:
                self._display_current_hunk()

    def on_list_view_selected(self, event: ListView.Selected):
        """Handle file selection from sidebar."""
        if isinstance(event.item, FileItem):
            self._select_file(event.item.conflict_file)

    # =========================================================================
    # Navigation Actions
    # =========================================================================

    def action_next_hunk(self):
        """Move to next hunk."""
        if not self.current_file or not self.current_file.hunks:
            return
        if self.current_hunk_idx < len(self.current_file.hunks) - 1:
            self.current_hunk_idx += 1
            self._at_end = False
            self._display_current_hunk()

    def action_prev_hunk(self):
        """Move to previous hunk."""
        if not self.current_file:
            return
        if self.current_hunk_idx > 0:
            self.current_hunk_idx -= 1
            self._at_end = False
            self._display_current_hunk()

    def action_next_file(self):
        """Move to next conflicted file."""
        if not self.conflict_files:
            return
        if self.current_file:
            idx = self.conflict_files.index(self.current_file)
            if idx < len(self.conflict_files) - 1:
                self._select_file(self.conflict_files[idx + 1])
                # Update sidebar selection
                file_list = self.query_one("#file-list", ListView)
                file_list.index = idx + 1

    def action_prev_file(self):
        """Move to previous conflicted file."""
        if not self.conflict_files or not self.current_file:
            return
        idx = self.conflict_files.index(self.current_file)
        if idx > 0:
            self._select_file(self.conflict_files[idx - 1])
            file_list = self.query_one("#file-list", ListView)
            file_list.index = idx - 1

    def action_toggle_position(self):
        """Toggle between first and last hunk."""
        if not self.current_file or not self.current_file.hunks:
            return
        if self._at_end:
            self.current_hunk_idx = 0
            self._at_end = False
        else:
            self.current_hunk_idx = len(self.current_file.hunks) - 1
            self._at_end = True
        self._display_current_hunk()

    def action_cycle_focus(self):
        """Cycle focus between sidebar and panels."""
        file_list = self.query_one("#file-list", ListView)
        if file_list.has_focus:
            self.query_one("#result-panel").focus()
        else:
            file_list.focus()

    def action_toggle_sidebar(self):
        """Toggle file sidebar visibility."""
        sidebar = self.query_one("#file-sidebar")
        sidebar.toggle_class("hidden")
        # If hiding sidebar and it had focus, move focus to panels
        if sidebar.has_class("hidden"):
            self.query_one("#local-panel").focus()

    # =========================================================================
    # Resolution Actions
    # =========================================================================

    def _apply_resolution(self, resolution: str, resolution_type: str):
        """Apply a resolution to the current hunk."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        hunk.resolved = True
        hunk.resolution = resolution
        hunk.resolution_type = resolution_type
        self._display_current_hunk()
        self._refresh_file_list()
        self.notify(f"Resolved with {resolution_type}", timeout=2)

    def action_accept_local(self):
        """Accept local (HEAD) version."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        self._apply_resolution(hunk.ours_content, "local")

    def action_accept_server(self):
        """Accept server (incoming) version."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        self._apply_resolution(hunk.theirs_content, "server")

    def action_accept_both(self):
        """Accept both versions (local then server)."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        combined = hunk.ours_content + "\n" + hunk.theirs_content
        self._apply_resolution(combined, "both")

    def action_undo_resolution(self):
        """Undo the current hunk's resolution."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        if hunk.resolved:
            hunk.resolved = False
            hunk.resolution = ""
            hunk.resolution_type = ""
            self._display_current_hunk()
            self._refresh_file_list()
            self.notify("Resolution undone", timeout=2)

    def action_manual_edit(self):
        """Open manual edit dialog."""
        if not self.current_file or not self.current_file.hunks:
            return
        hunk = self.current_file.hunks[self.current_hunk_idx]
        prefill = hunk.resolution if hunk.resolved else hunk.ours_content

        def handle_result(result):
            if result and result.get("action") == "save":
                self._apply_resolution(result["content"], "manual")

        self.push_screen(ManualEditDialog(hunk, prefill), handle_result)

    # =========================================================================
    # AI Integration
    # =========================================================================

    def action_ai_suggest(self):
        """Request AI suggestion for current hunk."""
        if not self.current_file or not self.current_file.hunks:
            return

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            self.notify("ANTHROPIC_API_KEY not set", severity="error", timeout=5)
            return

        hunk = self.current_file.hunks[self.current_hunk_idx]
        self._loading_dialog = LoadingDialog()
        self.push_screen(self._loading_dialog)
        self._request_ai_suggestion(hunk)

    @work(thread=True)
    def _request_ai_suggestion(self, hunk: ConflictHunk):
        """Request AI suggestion in background thread."""
        try:
            resolver = ConflictAIResolver()
            # Get some context
            context_before = ""
            context_after = ""
            if self.current_file:
                lines = self.current_file.original_content.split("\n")
                if hunk.start_line > 1:
                    context_before = "\n".join(lines[max(0, hunk.start_line - 10) : hunk.start_line - 1])
                if hunk.end_line < len(lines):
                    context_after = "\n".join(lines[hunk.end_line : min(len(lines), hunk.end_line + 10)])

            suggestion = resolver.suggest_resolution(
                hunk=hunk,
                context_before=context_before,
                context_after=context_after,
                file_path=str(self.current_file.path) if self.current_file else "",
            )

            self.call_from_thread(self._show_ai_suggestion, hunk, suggestion)

        except Exception as e:
            self.call_from_thread(self._on_ai_error, str(e))

    def _show_ai_suggestion(self, hunk: ConflictHunk, suggestion: str):
        """Show AI suggestion dialog."""
        if self._loading_dialog:
            self.pop_screen()
            self._loading_dialog = None

        def handle_result(result):
            if result:
                if result.get("action") == "accept":
                    self._apply_resolution(result["suggestion"], "ai")
                elif result.get("action") == "edit":
                    # Open manual edit with AI suggestion prefilled
                    def handle_edit(edit_result):
                        if edit_result and edit_result.get("action") == "save":
                            self._apply_resolution(edit_result["content"], "ai+manual")

                    self.push_screen(ManualEditDialog(hunk, result["suggestion"]), handle_edit)

        self.push_screen(AISuggestionDialog(hunk, suggestion), handle_result)

    def _on_ai_error(self, error_msg: str):
        """Handle AI error."""
        if self._loading_dialog:
            self.pop_screen()
            self._loading_dialog = None
        self.notify(f"AI error: {error_msg}", severity="error", timeout=5)

    # =========================================================================
    # File Operations
    # =========================================================================

    def _generate_merged_content(self) -> str:
        """Generate the final merged file content."""
        if not self.current_file:
            return ""

        lines = self.current_file.original_content.split("\n")
        result_lines = []
        i = 0
        hunk_idx = 0

        while i < len(lines):
            line = lines[i]
            if line.startswith("<<<<<<"):
                # Insert resolved content for this hunk
                if hunk_idx < len(self.current_file.hunks):
                    hunk = self.current_file.hunks[hunk_idx]
                    if hunk.resolved:
                        result_lines.extend(hunk.resolution.split("\n"))
                    else:
                        # Keep original conflict markers for unresolved
                        while i < len(lines) and not lines[i].startswith(">>>>>>"):
                            result_lines.append(lines[i])
                            i += 1
                        if i < len(lines):
                            result_lines.append(lines[i])
                    hunk_idx += 1

                # Skip past the conflict markers
                while i < len(lines) and not lines[i].startswith(">>>>>>"):
                    i += 1
                i += 1  # Skip the >>>>>>> line
            else:
                result_lines.append(line)
                i += 1

        return "\n".join(result_lines)

    def action_preview_file(self):
        """Preview the merged file."""
        if not self.current_file:
            self.notify("No file selected", severity="warning")
            return

        if not self.current_file.is_fully_resolved:
            unresolved = len(self.current_file.hunks) - self.current_file.resolved_count
            self.notify(f"{unresolved} unresolved conflict(s)", severity="warning")

        merged = self._generate_merged_content()

        def handle_result(result):
            if result and result.get("action") == "save":
                self._do_save()

        self.push_screen(PreviewDialog(self.current_file.path, merged), handle_result)

    def action_save_file(self):
        """Save the resolved file."""
        if not self.current_file:
            self.notify("No file selected", severity="warning")
            return

        if not self.current_file.is_fully_resolved:
            unresolved = len(self.current_file.hunks) - self.current_file.resolved_count
            self.notify(f"Cannot save: {unresolved} unresolved conflict(s)", severity="error")
            return

        def handle_confirm(confirmed: bool):
            if confirmed:
                self._do_save()

        self.push_screen(
            ConfirmDialog("Save File", f"Save resolved conflicts to {self.current_file.path.name}?"),
            handle_confirm,
        )

    def _do_save(self):
        """Actually write the file."""
        if not self.current_file:
            return
        try:
            merged = self._generate_merged_content()
            self.current_file.path.write_text(merged)

            # Mark as resolved in git
            subprocess.run(
                ["git", "add", str(self.current_file.path)],
                cwd=self.current_file.path.parent,
            )

            self.notify(f"Saved and staged: {self.current_file.path.name}", timeout=3)

            # Remove from list and select next
            idx = self.conflict_files.index(self.current_file)
            self.conflict_files.remove(self.current_file)

            if self.conflict_files:
                next_idx = min(idx, len(self.conflict_files) - 1)
                self._select_file(self.conflict_files[next_idx])
            else:
                self.current_file = None
                self.notify("All conflicts resolved!", severity="information", timeout=5)

            self._refresh_file_list()

        except Exception as e:
            self.notify(f"Error saving: {e}", severity="error")

    def action_refresh(self):
        """Refresh conflict list from git."""
        self._load_conflicts()
        self.notify("Refreshed", timeout=2)


# =============================================================================
# Entry Point
# =============================================================================


def main():
    """Entry point."""
    repo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    app = MergeResolverApp(repo_path)
    app.run()


if __name__ == "__main__":
    main()
