#!/usr/bin/env python3
"""
Lizard TUI - A Terminal User Interface for visualizing Lizard code complexity analysis.
"""

import subprocess
import sys
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import (
    Header,
    Footer,
    DataTable,
    Static,
    Input,
    Label,
    Button,
    TabbedContent,
    TabPane,
    ProgressBar,
)
from textual.reactive import reactive
from textual import work
from rich.text import Text


class LoadingScreen(ModalScreen):
    """Modal screen showing loading indicator."""

    BINDINGS = [
        Binding("ctrl+q", "app.quit", "Quit"),
    ]

    CSS = """
    LoadingScreen {
        align: center middle;
    }

    #loading-box {
        width: 40;
        height: 7;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #loading-title {
        text-align: center;
        text-style: bold;
        color: $primary;
    }

    #loading-path {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }

    #loading-spinner {
        text-align: center;
        color: $warning;
    }
    """

    def __init__(self, path: str = "", **kwargs):
        super().__init__(**kwargs)
        self.path = path
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.frame = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="loading-box"):
            yield Static("Analyzing...", id="loading-title")
            yield Static(self.spinner_frames[0], id="loading-spinner")
            # Truncate path if too long
            display_path = self.path if len(self.path) < 34 else "..." + self.path[-31:]
            yield Static(display_path, id="loading-path")

    def on_mount(self) -> None:
        self.set_interval(0.1, self._update_spinner)

    def _update_spinner(self) -> None:
        self.frame = (self.frame + 1) % len(self.spinner_frames)
        self.query_one("#loading-spinner", Static).update(self.spinner_frames[self.frame])


class LegendScreen(ModalScreen):
    """Modal screen showing acronym legend."""

    BINDINGS = [
        Binding("ctrl+q", "app.quit", "Quit"),
        Binding("escape", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
    ]

    CSS = """
    LegendScreen {
        align: center middle;
    }

    #legend-container {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #legend-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
    }

    #legend-content {
        height: auto;
    }

    #legend-footer {
        text-align: center;
        color: $text-muted;
        padding-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="legend-container"):
            yield Static("LEGEND", id="legend-title")
            yield Static(self._render_legend(), id="legend-content")
            yield Static("Press ESC or ? to close", id="legend-footer")

    def _render_legend(self) -> Text:
        text = Text()

        entries = [
            ("CCN", "Cyclomatic Complexity Number",
             "Number of linearly independent paths through code. Lower is better."),
            ("NLOC", "Non-commenting Lines of Code",
             "Lines of code excluding comments and blank lines."),
            ("Tokens", "Token Count",
             "Number of tokens (keywords, operators, identifiers) in function."),
            ("Params", "Parameter Count",
             "Number of parameters the function accepts."),
            ("Length", "Function Length",
             "Total lines including comments and blanks."),
        ]

        for acronym, full_name, desc in entries:
            text.append(f"{acronym}", style="bold cyan")
            text.append(f" - {full_name}\n", style="bold white")
            text.append(f"  {desc}\n\n", style="dim")

        text.append("─" * 46 + "\n", style="dim")
        text.append("COMPLEXITY LEVELS\n", style="bold white")
        text.append("Low    ", style="dim")
        text.append("█ 1-5   ", style="green")
        text.append("Simple, easy to test\n", style="dim")
        text.append("Medium ", style="dim")
        text.append("█ 6-10  ", style="yellow")
        text.append("Moderate complexity\n", style="dim")
        text.append("High   ", style="dim")
        text.append("█ 11-15 ", style="#ff8800")
        text.append("Consider refactoring\n", style="dim")
        text.append("Crit   ", style="dim")
        text.append("█ >15   ", style="red")
        text.append("Hard to test/maintain\n", style="dim")

        return text


@dataclass
class FunctionMetrics:
    """Metrics for a single function."""
    nloc: int
    ccn: int
    token_count: int
    param_count: int
    length: int
    name: str
    start_line: int
    end_line: int
    file_path: str

    @property
    def complexity_level(self) -> str:
        """Return complexity level based on CCN."""
        if self.ccn <= 5:
            return "low"
        elif self.ccn <= 10:
            return "medium"
        elif self.ccn <= 15:
            return "high"
        else:
            return "critical"


@dataclass
class FileMetrics:
    """Metrics for a single file."""
    nloc: int
    avg_nloc: float
    avg_ccn: float
    avg_token: float
    function_count: int
    file_path: str


@dataclass
class LizardResult:
    """Complete Lizard analysis result."""
    functions: list[FunctionMetrics]
    files: list[FileMetrics]
    total_nloc: int
    avg_nloc: float
    avg_ccn: float
    avg_token: float
    function_count: int
    warning_count: int


def parse_lizard_output(output: str) -> LizardResult:
    """Parse Lizard's text output into structured data."""
    functions = []
    files = []

    # Parse function metrics
    # Format: NLOC    CCN   token  PARAM  length  location
    func_pattern = re.compile(
        r'^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(.+?)@(\d+)-(\d+)@(.+)$'
    )

    # Parse file metrics
    # Format: NLOC    Avg.NLOC  AvgCCN  Avg.token  function_cnt    file
    file_pattern = re.compile(
        r'^\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(.+)$'
    )

    # Parse total metrics
    total_pattern = re.compile(
        r'^\s*(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)'
    )

    in_function_section = False
    in_file_section = False
    in_total_section = False

    total_nloc = 0
    avg_nloc = 0.0
    avg_ccn = 0.0
    avg_token = 0.0
    function_count = 0
    warning_count = 0

    for line in output.split('\n'):
        line = line.strip()

        if 'NLOC    CCN   token  PARAM  length  location' in line:
            in_function_section = True
            in_file_section = False
            in_total_section = False
            continue
        elif 'NLOC    Avg.NLOC  AvgCCN  Avg.token  function_cnt    file' in line:
            in_function_section = False
            in_file_section = True
            in_total_section = False
            continue
        elif 'Total nloc' in line:
            in_function_section = False
            in_file_section = False
            in_total_section = True
            continue
        elif line.startswith('=') or line.startswith('-') or not line:
            continue
        elif 'No thresholds exceeded' in line or 'thresholds exceeded' in line:
            in_file_section = False
            continue

        if in_function_section:
            match = func_pattern.match(line)
            if match:
                functions.append(FunctionMetrics(
                    nloc=int(match.group(1)),
                    ccn=int(match.group(2)),
                    token_count=int(match.group(3)),
                    param_count=int(match.group(4)),
                    length=int(match.group(5)),
                    name=match.group(6),
                    start_line=int(match.group(7)),
                    end_line=int(match.group(8)),
                    file_path=match.group(9),
                ))

        elif in_file_section:
            match = file_pattern.match(line)
            if match:
                files.append(FileMetrics(
                    nloc=int(match.group(1)),
                    avg_nloc=float(match.group(2)),
                    avg_ccn=float(match.group(3)),
                    avg_token=float(match.group(4)),
                    function_count=int(match.group(5)),
                    file_path=match.group(6),
                ))

        elif in_total_section:
            match = total_pattern.match(line)
            if match:
                total_nloc = int(match.group(1))
                avg_nloc = float(match.group(2))
                avg_ccn = float(match.group(3))
                avg_token = float(match.group(4))
                function_count = int(match.group(5))
                warning_count = int(match.group(6))

    return LizardResult(
        functions=functions,
        files=files,
        total_nloc=total_nloc,
        avg_nloc=avg_nloc,
        avg_ccn=avg_ccn,
        avg_token=avg_token,
        function_count=function_count,
        warning_count=warning_count,
    )


def run_lizard(path: str, extra_args: list[str] = None) -> str:
    """Run Lizard on the given path and return output."""
    cmd = ["lizard", path, "-V"]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout + result.stderr


class SummaryWidget(Static):
    """Widget displaying summary statistics."""

    def __init__(self, result: Optional[LizardResult] = None, **kwargs):
        super().__init__(**kwargs)
        self.result = result

    def compose(self) -> ComposeResult:
        yield Static(self._render_summary(), id="summary-content")

    def _render_summary(self) -> Text:
        if not self.result:
            return Text("No data", style="dim")

        r = self.result
        text = Text()

        # Stats
        text.append("NLOC ", style="dim")
        text.append(f"{r.total_nloc:,}", style="bold white")
        text.append("  Funcs ", style="dim")
        text.append(f"{r.function_count}", style="bold white")
        text.append("  Files ", style="dim")
        text.append(f"{len(r.files)}\n", style="bold white")

        text.append("─" * 24 + "\n", style="dim")

        # Averages
        text.append("Avg: ", style="dim")
        text.append(f"NLOC {r.avg_nloc:.0f}", style="white")
        text.append(" │ ", style="dim")
        ccn_color = "green" if r.avg_ccn <= 5 else "yellow" if r.avg_ccn <= 10 else "red"
        text.append(f"CCN {r.avg_ccn:.1f}\n", style=f"bold {ccn_color}")

        # Warnings
        if r.warning_count > 0:
            text.append(f"⚠ {r.warning_count} warnings\n", style="bold red")

        text.append("─" * 24 + "\n", style="dim")

        # Complexity distribution with bars
        if r.functions:
            low = sum(1 for f in r.functions if f.ccn <= 5)
            medium = sum(1 for f in r.functions if 5 < f.ccn <= 10)
            high = sum(1 for f in r.functions if 10 < f.ccn <= 15)
            critical = sum(1 for f in r.functions if f.ccn > 15)
            total = len(r.functions)

            def bar(count, color):
                width = int((count / total) * 12) if total > 0 else 0
                return ("█" * width).ljust(12)

            text.append("Low    ", style="dim")
            text.append(bar(low, "green"), style="green")
            text.append(f" {low}\n", style="bold green")

            text.append("Med    ", style="dim")
            text.append(bar(medium, "yellow"), style="yellow")
            text.append(f" {medium}\n", style="bold yellow")

            text.append("High   ", style="dim")
            text.append(bar(high, "#ff8800"), style="#ff8800")
            text.append(f" {high}\n", style="bold #ff8800")

            text.append("Crit   ", style="dim")
            text.append(bar(critical, "red"), style="red")
            text.append(f" {critical}\n", style="bold red")

        return text

    def update_result(self, result: LizardResult):
        self.result = result
        self.query_one("#summary-content", Static).update(self._render_summary())


class LizardTUI(App):
    """Main TUI application for Lizard visualization."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        height: 100%;
    }

    #input-container {
        height: 3;
        padding: 0 1;
        background: $primary-background;
    }

    #filter-container {
        height: 3;
        padding: 0 1;
        background: $primary-background-darken-1;
    }

    #filter-label {
        width: auto;
        padding: 1 1 0 0;
    }

    #filter-input {
        width: 1fr;
    }

    #path-input {
        width: 1fr;
    }

    #analyze-btn {
        width: auto;
        min-width: 12;
    }

    #content-container {
        height: 1fr;
    }

    #summary-pane {
        width: 28;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
    }

    #tables-container {
        width: 1fr;
    }

    #code-preview {
        width: 2fr;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
        overflow: auto;
        display: none;
    }

    #code-preview.visible {
        display: block;
    }

    #code-preview-content {
        width: auto;
        min-width: 100%;
    }

    DataTable {
        height: 1fr;
    }

    .complexity-low {
        color: $success;
    }

    .complexity-medium {
        color: $warning;
    }

    .complexity-high {
        color: #ff8800;
    }

    .complexity-critical {
        color: $error;
        text-style: bold;
    }

    #loading-indicator {
        height: 3;
        content-align: center middle;
        background: $primary-background;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    #status-bar {
        height: 1;
        dock: bottom;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+o", "browse_dirs", "Folders"),
        Binding("ctrl+f", "browse_all", "Files"),
        Binding("c", "copy_critical", "Copy Crit"),
        Binding("1", "sort_ccn", "Sort CCN"),
        Binding("2", "sort_nloc", "Sort NLOC"),
        Binding("3", "sort_name", "Sort Name"),
        Binding("question_mark", "show_legend", "Legend"),
        Binding("escape", "clear_filter", "Clear"),
    ]

    result: reactive[Optional[LizardResult]] = reactive(None)
    current_sort: reactive[str] = reactive("ccn")
    filter_text: reactive[str] = reactive("")
    is_loading: reactive[bool] = reactive(False)

    def __init__(self, initial_path: str = "."):
        super().__init__()
        self.initial_path = initial_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="main-container"):
            with Horizontal(id="input-container"):
                yield Input(
                    placeholder="Enter path to analyze...",
                    value=self.initial_path,
                    id="path-input",
                )
                yield Button("Analyze", id="analyze-btn", variant="primary")

            with Horizontal(id="filter-container"):
                yield Label("Filter: ", id="filter-label")
                yield Input(
                    placeholder="Filter functions by name or file...",
                    id="filter-input",
                )

            yield Static("Press Enter or click Analyze to start", id="loading-indicator")

            with Horizontal(id="content-container"):
                yield SummaryWidget(id="summary-pane")

                with TabbedContent(id="tables-container"):
                    with TabPane("Files", id="files-tab"):
                        yield DataTable(id="files-table", cursor_type="row")
                    with TabPane("Functions", id="functions-tab"):
                        yield DataTable(id="functions-table", cursor_type="row")

                with ScrollableContainer(id="code-preview"):
                    yield Static("Select a function to preview code", id="code-preview-content")

            yield Static("Ready", id="status-bar")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize tables on mount."""
        # Setup functions table
        func_table = self.query_one("#functions-table", DataTable)
        func_table.add_columns(
            "CCN", "NLOC", "File", "Function", "Lines"
        )

        # Setup files table
        file_table = self.query_one("#files-table", DataTable)
        file_table.add_columns(
            "NLOC", "Avg NLOC", "Avg CCN", "Avg Tokens", "Functions", "File"
        )

        # Auto-analyze if path provided
        if self.initial_path and self.initial_path != ".":
            self.run_analysis(self.initial_path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "analyze-btn":
            path = self.query_one("#path-input", Input).value
            self.run_analysis(path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input."""
        if event.input.id == "path-input":
            self.run_analysis(event.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input change for filtering."""
        if event.input.id == "filter-input":
            self.filter_text = event.value
            self.update_tables()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        """Show/hide code preview based on active tab."""
        code_preview = self.query_one("#code-preview")
        if event.pane.id == "functions-tab":
            code_preview.add_class("visible")
        else:
            code_preview.remove_class("visible")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Show code preview when function row is highlighted."""
        if event.data_table.id != "functions-table":
            return

        if not self.result or not hasattr(self, '_displayed_functions'):
            return

        row_index = event.cursor_row
        if row_index < 0 or row_index >= len(self._displayed_functions):
            return

        func = self._displayed_functions[row_index]
        self._show_code_preview(func)

    def _show_code_preview(self, func: FunctionMetrics) -> None:
        """Display code preview for a function."""
        preview = self.query_one("#code-preview-content", Static)

        try:
            with open(func.file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            # Get function lines with some context
            start = max(0, func.start_line - 1)
            end = min(len(lines), func.end_line)

            text = Text()
            text.append(f"{Path(func.file_path).name}\n", style="bold cyan")
            text.append(f"{func.name} (CCN: {func.ccn})\n", style="bold white")
            text.append("─" * 40 + "\n", style="dim")

            for i, line in enumerate(lines[start:end], start=func.start_line):
                text.append(f"{i:4} ", style="dim")
                text.append(f"{line.rstrip()}\n", style="white")

            preview.update(text)
        except Exception as e:
            preview.update(f"Cannot read file: {e}")

    def run_analysis(self, path: str) -> None:
        """Run Lizard analysis."""
        self.push_screen(LoadingScreen(path=path))
        self._do_analysis(path)

    @work(exclusive=True, thread=True)
    def _do_analysis(self, path: str) -> None:
        """Run Lizard analysis in background thread."""
        try:
            output = run_lizard(path)
            result = parse_lizard_output(output)
            self.call_from_thread(self._analysis_complete, result)
        except Exception as e:
            self.call_from_thread(self._analysis_error, str(e))

    def _analysis_complete(self, result: LizardResult) -> None:
        """Handle analysis completion."""
        self.pop_screen()
        self.result = result
        self.update_tables()
        self.query_one("#summary-pane", SummaryWidget).update_result(self.result)
        self.update_status(f"Analyzed {len(result.files)} files, {result.function_count} functions")

    def _analysis_error(self, error: str) -> None:
        """Handle analysis error."""
        self.pop_screen()
        self.update_status(f"Error: {error}")

    def watch_is_loading(self, loading: bool) -> None:
        """Update loading indicator."""
        indicator = self.query_one("#loading-indicator", Static)
        if loading:
            indicator.update("Analyzing... Please wait")
            indicator.styles.display = "block"
        else:
            indicator.styles.display = "none"

    def update_status(self, message: str) -> None:
        """Update status bar."""
        self.query_one("#status-bar", Static).update(message)

    def update_tables(self) -> None:
        """Update data tables with current result."""
        if not self.result:
            return

        # Update functions table
        func_table = self.query_one("#functions-table", DataTable)
        func_table.clear()

        functions = self.result.functions

        # Apply filter
        if self.filter_text:
            filter_lower = self.filter_text.lower()
            functions = [f for f in functions if filter_lower in f.name.lower() or filter_lower in f.file_path.lower()]

        # Apply sort
        if self.current_sort == "ccn":
            functions = sorted(functions, key=lambda f: f.ccn, reverse=True)
        elif self.current_sort == "nloc":
            functions = sorted(functions, key=lambda f: f.nloc, reverse=True)
        elif self.current_sort == "name":
            functions = sorted(functions, key=lambda f: f.name.lower())

        # Store for code preview lookup
        self._displayed_functions = functions

        for func in functions:
            # Color code CCN
            ccn_text = Text(str(func.ccn))
            if func.ccn <= 5:
                ccn_text.stylize("green")
            elif func.ccn <= 10:
                ccn_text.stylize("yellow")
            elif func.ccn <= 15:
                ccn_text.stylize("#ff8800")
            else:
                ccn_text.stylize("bold red")

            # Shorten file path for display
            short_path = Path(func.file_path).name

            func_table.add_row(
                ccn_text,
                str(func.nloc),
                short_path,
                func.name,
                f"{func.start_line}-{func.end_line}",
            )

        # Update files table
        file_table = self.query_one("#files-table", DataTable)
        file_table.clear()

        files = self.result.files

        # Apply sort to files
        if self.current_sort == "ccn":
            files = sorted(files, key=lambda f: f.avg_ccn, reverse=True)
        elif self.current_sort == "nloc":
            files = sorted(files, key=lambda f: f.nloc, reverse=True)
        elif self.current_sort == "name":
            files = sorted(files, key=lambda f: f.file_path.lower())

        for file in files:
            # Color code avg CCN
            ccn_text = Text(f"{file.avg_ccn:.1f}")
            if file.avg_ccn <= 5:
                ccn_text.stylize("green")
            elif file.avg_ccn <= 10:
                ccn_text.stylize("yellow")
            elif file.avg_ccn <= 15:
                ccn_text.stylize("#ff8800")
            else:
                ccn_text.stylize("bold red")

            # Shorten path
            short_path = Path(file.file_path).name

            file_table.add_row(
                str(file.nloc),
                f"{file.avg_nloc:.1f}",
                ccn_text,
                f"{file.avg_token:.1f}",
                str(file.function_count),
                short_path,
            )

    def action_refresh(self) -> None:
        """Refresh analysis."""
        path = self.query_one("#path-input", Input).value
        self.run_analysis(path)

    def action_focus_filter(self) -> None:
        """Focus the path input for filtering."""
        self.query_one("#path-input", Input).focus()

    def action_sort_ccn(self) -> None:
        """Sort by CCN."""
        self.current_sort = "ccn"
        self.update_tables()
        self.update_status("Sorted by Cyclomatic Complexity (descending)")

    def action_sort_nloc(self) -> None:
        """Sort by NLOC."""
        self.current_sort = "nloc"
        self.update_tables()
        self.update_status("Sorted by NLOC (descending)")

    def action_sort_name(self) -> None:
        """Sort by name."""
        self.current_sort = "name"
        self.update_tables()
        self.update_status("Sorted by name")

    def action_clear_filter(self) -> None:
        """Clear filter."""
        self.filter_text = ""
        self.update_tables()

    def action_show_legend(self) -> None:
        """Show legend modal."""
        self.push_screen(LegendScreen())

    def action_copy_critical(self) -> None:
        """Copy critical functions to clipboard (excluding test files)."""
        import subprocess as sp

        if not self.result or not self.result.functions:
            self.update_status("No data to copy")
            return

        # Filter critical functions (CCN > 15), exclude test files
        critical = [
            f for f in self.result.functions
            if f.ccn > 15 and "test" not in f.file_path.lower()
        ]

        if not critical:
            self.update_status("No critical functions found (excluding tests)")
            return

        # Sort by CCN descending
        critical.sort(key=lambda f: f.ccn, reverse=True)

        # Format output
        lines = ["CRITICAL FUNCTIONS (CCN > 15)", "=" * 50, ""]
        for f in critical:
            lines.append(f"CCN {f.ccn:3} | {f.name}")
            lines.append(f"        | {f.file_path}:{f.start_line}-{f.end_line}")
            lines.append("")

        text = "\n".join(lines)

        # Copy to clipboard using pbcopy (macOS) or xclip (Linux)
        try:
            if sys.platform == "darwin":
                sp.run(["pbcopy"], input=text.encode(), check=True)
            else:
                sp.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
            self.update_status(f"Copied {len(critical)} critical functions to clipboard")
        except Exception as e:
            self.update_status(f"Clipboard error: {e}")

    def _browse_with_fzf(self, dirs_only: bool = False) -> None:
        """Browse for path using fzf."""
        import os
        import shutil
        import tempfile

        if not shutil.which("fzf"):
            self.update_status("fzf not found in PATH")
            return

        current = self.query_one("#path-input", Input).value
        start_dir = current if os.path.isdir(current) else os.path.dirname(current) or "."
        start_dir = os.path.abspath(start_dir)

        tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        tmp.close()

        prompt = "Folder: " if dirs_only else "Path: "

        with self.suspend():
            try:
                if shutil.which("fd"):
                    type_flag = "--type d" if dirs_only else "--type d --type f"
                    cmd = f"cd {start_dir!r} && fd {type_flag} 2>/dev/null | fzf --reverse --prompt={prompt!r} > {tmp.name!r}"
                else:
                    type_flag = "-type d" if dirs_only else "\\( -type f -o -type d \\)"
                    cmd = f"cd {start_dir!r} && find . {type_flag} 2>/dev/null | fzf --reverse --prompt={prompt!r} > {tmp.name!r}"
                os.system(cmd)
            except Exception:
                pass

        try:
            with open(tmp.name, 'r') as f:
                selected = f.read().strip()
            os.unlink(tmp.name)

            if selected:
                if not os.path.isabs(selected):
                    selected = os.path.join(start_dir, selected)
                selected = os.path.normpath(selected)

                path_input = self.query_one("#path-input", Input)
                path_input.value = selected
                self.run_analysis(selected)
        except Exception as e:
            self.update_status(f"fzf error: {e}")

    def action_browse_dirs(self) -> None:
        """Browse folders only with fzf (Ctrl+O)."""
        self._browse_with_fzf(dirs_only=True)

    def action_browse_all(self) -> None:
        """Browse files and folders with fzf (Ctrl+F)."""
        self._browse_with_fzf(dirs_only=False)


def main():
    """Main entry point."""
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    app = LizardTUI(initial_path=path)
    app.run()


if __name__ == "__main__":
    main()
