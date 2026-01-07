#!/usr/bin/env python3
"""
Lizard TUI - A Terminal User Interface for visualizing Lizard code complexity analysis.

Features:
- CSV-based parsing for reliable data extraction
- Configurable thresholds (CCN, NLOC, params, nesting)
- Language breakdown statistics
- Warnings view for threshold violations
- Extensions support (duplicates, word count, nested structures)
- Export to CSV, HTML, Checkstyle XML
"""

import csv
import json
import subprocess
import sys
import re
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widget import Widget
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
    Checkbox,
    RadioButton,
    RadioSet,
    ListView,
    ListItem,
    Select,
)
from textual.reactive import reactive
from textual import work
from rich.text import Text

from config_panel import get_textual_theme, get_theme_colors, get_footer_position, get_show_header

# =============================================================================
# Configuration and Data Structures
# =============================================================================

CONFIG_FILE = Path(__file__).parent / ".lizard_config.json"

LANGUAGE_MAP = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TSX",
    ".java": "Java",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".c": "C", ".h": "C/C++", ".hpp": "C++",
    ".go": "Go",
    ".rs": "Rust",
    ".swift": "Swift",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".lua": "Lua",
    ".r": "R", ".R": "R",
    ".pl": "Perl", ".pm": "Perl",
    ".vue": "Vue",
}


class ThresholdLevel(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


DEFAULT_EXCLUDE_PATTERNS = [
    "*/.venv/*",
    "*/venv/*",
    "*/.git/*",
    "*/__pycache__/*",
    "*/node_modules/*",
    "*/.tox/*",
    "*/.mypy_cache/*",
    "*/.pytest_cache/*",
    "*/dist/*",
    "*/build/*",
    "*/.eggs/*",
    "*.egg-info/*",
]


@dataclass
class AnalysisConfig:
    """User-configurable analysis settings."""
    ccn_threshold: int = 15
    nloc_threshold: int = 100
    params_threshold: int = 5
    ns_threshold: int = 4
    languages: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=lambda: DEFAULT_EXCLUDE_PATTERNS.copy())
    enable_duplicates: bool = False
    enable_wordcount: bool = False
    enable_ns: bool = True
    working_threads: int = 4

    def save(self):
        """Save config to file."""
        data = {
            "ccn_threshold": self.ccn_threshold,
            "nloc_threshold": self.nloc_threshold,
            "params_threshold": self.params_threshold,
            "ns_threshold": self.ns_threshold,
            "languages": self.languages,
            "exclude_patterns": self.exclude_patterns,
            "enable_duplicates": self.enable_duplicates,
            "enable_wordcount": self.enable_wordcount,
            "enable_ns": self.enable_ns,
            "working_threads": self.working_threads,
        }
        CONFIG_FILE.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls) -> "AnalysisConfig":
        """Load config from file."""
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
                return cls(
                    ccn_threshold=data.get("ccn_threshold", 15),
                    nloc_threshold=data.get("nloc_threshold", 100),
                    params_threshold=data.get("params_threshold", 5),
                    ns_threshold=data.get("ns_threshold", 4),
                    languages=data.get("languages", []),
                    exclude_patterns=data.get("exclude_patterns") or DEFAULT_EXCLUDE_PATTERNS.copy(),
                    enable_duplicates=data.get("enable_duplicates", False),
                    enable_wordcount=data.get("enable_wordcount", False),
                    enable_ns=data.get("enable_ns", True),
                    working_threads=data.get("working_threads", 4),
                )
            except (json.JSONDecodeError, KeyError):
                pass
        return cls()


@dataclass
class FunctionMetrics:
    """Metrics for a single function."""
    nloc: int
    ccn: int
    token_count: int
    param_count: int
    length: int
    name: str
    full_signature: str
    start_line: int
    end_line: int
    file_path: str
    nested_structures: int = 0

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

    def check_thresholds(self, config: AnalysisConfig) -> dict[str, ThresholdLevel]:
        """Check all thresholds and return violations."""
        def level(value: int, threshold: int) -> ThresholdLevel:
            if value <= threshold * 0.6:
                return ThresholdLevel.OK
            elif value <= threshold:
                return ThresholdLevel.WARNING
            return ThresholdLevel.CRITICAL

        return {
            "ccn": level(self.ccn, config.ccn_threshold),
            "nloc": level(self.nloc, config.nloc_threshold),
            "params": level(self.param_count, config.params_threshold),
            "ns": level(self.nested_structures, config.ns_threshold),
        }

    def has_violations(self, config: AnalysisConfig) -> bool:
        """Check if any threshold is exceeded."""
        return (
            self.ccn > config.ccn_threshold or
            self.nloc > config.nloc_threshold or
            self.param_count > config.params_threshold or
            (config.enable_ns and self.nested_structures > config.ns_threshold)
        )


@dataclass
class FileMetrics:
    """Metrics for a single file."""
    nloc: int
    avg_nloc: float
    avg_ccn: float
    avg_token: float
    function_count: int
    file_path: str
    language: str = ""


@dataclass
class LanguageBreakdown:
    """Per-language statistics."""
    language: str
    file_count: int
    total_nloc: int
    total_functions: int
    avg_ccn: float
    max_ccn: int
    warning_count: int


@dataclass
class DuplicateBlock:
    """Clone detection result."""
    locations: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(set(loc[0] for loc in self.locations))


@dataclass
class WordFrequency:
    """Word/identifier frequency."""
    word: str
    count: int
    files: list[str] = field(default_factory=list)


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
    languages: dict[str, LanguageBreakdown] = field(default_factory=dict)
    duplicates: list[DuplicateBlock] = field(default_factory=list)
    word_frequencies: list[WordFrequency] = field(default_factory=list)
    duplicate_rate: float = 0.0
    config: AnalysisConfig = field(default_factory=AnalysisConfig)


# =============================================================================
# Parsers
# =============================================================================

def detect_language(file_path: str) -> str:
    """Detect language from file extension."""
    suffix = Path(file_path).suffix.lower()
    return LANGUAGE_MAP.get(suffix, "Other")


def parse_csv_output(csv_text: str, has_ns: bool = False) -> list[FunctionMetrics]:
    """Parse Lizard CSV output into FunctionMetrics."""
    functions = []
    reader = csv.reader(StringIO(csv_text))

    for row in reader:
        if len(row) < 11:
            continue
        try:
            # CSV: NLOC,CCN,tokens,params,length,location,file,short_name,full_sig,start,end[,NS]
            ns_value = 0
            if has_ns and len(row) > 11:
                try:
                    ns_value = int(row[11])
                except (ValueError, IndexError):
                    pass

            func = FunctionMetrics(
                nloc=int(row[0]),
                ccn=int(row[1]),
                token_count=int(row[2]),
                param_count=int(row[3]),
                length=int(row[4]),
                name=row[7],
                full_signature=row[8],
                start_line=int(row[9]),
                end_line=int(row[10]),
                file_path=row[6],
                nested_structures=ns_value,
            )
            functions.append(func)
        except (ValueError, IndexError):
            continue
    return functions


def aggregate_file_metrics(functions: list[FunctionMetrics]) -> list[FileMetrics]:
    """Aggregate function metrics into file metrics."""
    file_data: dict[str, list[FunctionMetrics]] = {}
    for func in functions:
        if func.file_path not in file_data:
            file_data[func.file_path] = []
        file_data[func.file_path].append(func)

    files = []
    for file_path, funcs in file_data.items():
        total_nloc = sum(f.nloc for f in funcs)
        avg_nloc = total_nloc / len(funcs) if funcs else 0
        avg_ccn = sum(f.ccn for f in funcs) / len(funcs) if funcs else 0
        avg_token = sum(f.token_count for f in funcs) / len(funcs) if funcs else 0

        files.append(FileMetrics(
            nloc=total_nloc,
            avg_nloc=avg_nloc,
            avg_ccn=avg_ccn,
            avg_token=avg_token,
            function_count=len(funcs),
            file_path=file_path,
            language=detect_language(file_path),
        ))

    return files


def calculate_language_breakdown(functions: list[FunctionMetrics], config: AnalysisConfig) -> dict[str, LanguageBreakdown]:
    """Calculate per-language statistics."""
    lang_data: dict[str, list[FunctionMetrics]] = {}

    for func in functions:
        lang = detect_language(func.file_path)
        if lang not in lang_data:
            lang_data[lang] = []
        lang_data[lang].append(func)

    result = {}
    for lang, funcs in lang_data.items():
        files = set(f.file_path for f in funcs)
        total_nloc = sum(f.nloc for f in funcs)
        avg_ccn = sum(f.ccn for f in funcs) / len(funcs) if funcs else 0
        max_ccn = max((f.ccn for f in funcs), default=0)
        warning_count = sum(1 for f in funcs if f.ccn > config.ccn_threshold)

        result[lang] = LanguageBreakdown(
            language=lang,
            file_count=len(files),
            total_nloc=total_nloc,
            total_functions=len(funcs),
            avg_ccn=avg_ccn,
            max_ccn=max_ccn,
            warning_count=warning_count,
        )

    return result


def parse_duplicate_output(output: str) -> tuple[list[DuplicateBlock], float]:
    """Parse duplicate extension output."""
    duplicates = []
    current_block: list[tuple[str, int, int]] = []
    duplicate_rate = 0.0

    for line in output.split('\n'):
        if 'Duplicate block:' in line or line.strip().startswith('Duplicate'):
            if current_block:
                duplicates.append(DuplicateBlock(locations=current_block))
            current_block = []
        elif ':' in line and '~' in line:
            # Parse: /path/file.py:123 ~ 456
            try:
                parts = line.strip().rsplit(':', 1)
                if len(parts) >= 2:
                    file_path = parts[0]
                    range_part = parts[1]
                    if '~' in range_part:
                        start_str, end_str = range_part.split('~')
                        current_block.append((file_path, int(start_str.strip()), int(end_str.strip())))
            except (ValueError, IndexError):
                pass
        elif 'Total duplicate rate:' in line or 'duplicate rate' in line.lower():
            match = re.search(r'([\d.]+)%', line)
            if match:
                duplicate_rate = float(match.group(1))

    if current_block:
        duplicates.append(DuplicateBlock(locations=current_block))

    return duplicates, duplicate_rate


def parse_wordcount_output(output: str) -> list[WordFrequency]:
    """Parse word count extension output."""
    words = []
    in_wordcount = False

    for line in output.split('\n'):
        if 'word' in line.lower() and 'count' in line.lower():
            in_wordcount = True
            continue
        if in_wordcount and line.strip():
            # Format: count word
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    count = int(parts[0])
                    word = parts[1]
                    words.append(WordFrequency(word=word, count=count))
                except ValueError:
                    pass

    return sorted(words, key=lambda w: w.count, reverse=True)


# =============================================================================
# Lizard Runner
# =============================================================================

def build_lizard_command(path: str, config: AnalysisConfig, output_format: str = "csv") -> list[str]:
    """Build Lizard command with all options."""
    cmd = ["lizard", path]

    # Output format
    if output_format == "csv":
        cmd.append("--csv")
    elif output_format == "html":
        cmd.append("-H")
    elif output_format == "xml":
        cmd.append("-X")
    elif output_format == "checkstyle":
        cmd.append("--checkstyle")

    # Thresholds
    cmd.extend(["-C", str(config.ccn_threshold)])
    cmd.extend(["-L", str(config.nloc_threshold)])
    cmd.extend(["-a", str(config.params_threshold)])

    # Extensions
    if config.enable_ns:
        cmd.append("-ENS")

    # Languages
    for lang in config.languages:
        cmd.extend(["-l", lang])

    # Exclude patterns
    for pattern in config.exclude_patterns:
        cmd.extend(["-x", pattern])

    # Performance
    cmd.extend(["-t", str(config.working_threads)])

    # Verbose for full signatures
    cmd.append("-V")

    return cmd


def run_lizard(path: str, config: AnalysisConfig) -> LizardResult:
    """Run Lizard analysis synchronously."""
    # Run CSV output for main data
    csv_cmd = build_lizard_command(path, config, "csv")
    csv_result = subprocess.run(csv_cmd, capture_output=True, text=True)
    csv_output = csv_result.stdout

    functions = parse_csv_output(csv_output, has_ns=config.enable_ns)
    files = aggregate_file_metrics(functions)
    languages = calculate_language_breakdown(functions, config)

    # Run duplicate detection if enabled
    duplicates: list[DuplicateBlock] = []
    duplicate_rate = 0.0
    if config.enable_duplicates:
        dup_cmd = ["lizard", path, "-Eduplicate"]
        for pattern in config.exclude_patterns:
            dup_cmd.extend(["-x", pattern])
        dup_result = subprocess.run(dup_cmd, capture_output=True, text=True)
        duplicates, duplicate_rate = parse_duplicate_output(dup_result.stdout + dup_result.stderr)

    # Run word count if enabled
    word_frequencies: list[WordFrequency] = []
    if config.enable_wordcount:
        word_cmd = ["lizard", path, "-Ewordcount"]
        for pattern in config.exclude_patterns:
            word_cmd.extend(["-x", pattern])
        word_result = subprocess.run(word_cmd, capture_output=True, text=True)
        word_frequencies = parse_wordcount_output(word_result.stdout + word_result.stderr)

    # Calculate totals
    total_nloc = sum(f.nloc for f in functions)
    avg_nloc = total_nloc / len(functions) if functions else 0
    avg_ccn = sum(f.ccn for f in functions) / len(functions) if functions else 0
    avg_token = sum(f.token_count for f in functions) / len(functions) if functions else 0
    warning_count = sum(1 for f in functions if f.has_violations(config))

    return LizardResult(
        functions=functions,
        files=files,
        total_nloc=total_nloc,
        avg_nloc=avg_nloc,
        avg_ccn=avg_ccn,
        avg_token=avg_token,
        function_count=len(functions),
        warning_count=warning_count,
        languages=languages,
        duplicates=duplicates,
        word_frequencies=word_frequencies,
        duplicate_rate=duplicate_rate,
        config=config,
    )


# =============================================================================
# Export Functions
# =============================================================================

def export_to_csv(result: LizardResult, output_path: Path, mode: str = "functions"):
    """Export results to CSV."""
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        if mode == "functions":
            writer.writerow(["File", "Function", "NLOC", "CCN", "Tokens", "Params", "NS", "Start", "End", "Signature"])
            for func in result.functions:
                writer.writerow([
                    func.file_path, func.name, func.nloc, func.ccn,
                    func.token_count, func.param_count, func.nested_structures,
                    func.start_line, func.end_line, func.full_signature
                ])
        else:  # files
            writer.writerow(["File", "Language", "NLOC", "Functions", "Avg CCN", "Avg NLOC"])
            for file in result.files:
                writer.writerow([
                    file.file_path, file.language, file.nloc,
                    file.function_count, f"{file.avg_ccn:.1f}", f"{file.avg_nloc:.1f}"
                ])


def export_to_html(result: LizardResult, output_path: Path):
    """Export results to HTML report."""
    # Generate function rows with color coding
    func_rows = []
    for func in sorted(result.functions, key=lambda f: f.ccn, reverse=True):
        row_class = ""
        if func.ccn > result.config.ccn_threshold:
            row_class = "critical"
        elif func.ccn > result.config.ccn_threshold * 0.6:
            row_class = "warning"
        else:
            row_class = "ok"

        func_rows.append(f"""
            <tr class="{row_class}">
                <td>{func.ccn}</td>
                <td>{func.nloc}</td>
                <td>{func.token_count}</td>
                <td>{func.param_count}</td>
                <td>{func.name}</td>
                <td>{Path(func.file_path).name}:{func.start_line}</td>
            </tr>""")

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Lizard Analysis Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
        h1 {{ color: #00d4ff; }}
        h2 {{ color: #ff6b6b; border-bottom: 1px solid #333; padding-bottom: 10px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #333; padding: 10px; text-align: left; }}
        th {{ background: #16213e; color: #00d4ff; }}
        .critical {{ background: rgba(255, 107, 107, 0.2); }}
        .warning {{ background: rgba(255, 193, 7, 0.2); }}
        .ok {{ background: rgba(0, 212, 255, 0.1); }}
        .summary {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }}
        .stat {{ background: #16213e; padding: 15px 25px; border-radius: 8px; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #00d4ff; }}
        .stat-label {{ color: #888; }}
    </style>
</head>
<body>
    <h1>Code Complexity Report</h1>

    <div class="summary">
        <div class="stat">
            <div class="stat-value">{result.total_nloc:,}</div>
            <div class="stat-label">Total NLOC</div>
        </div>
        <div class="stat">
            <div class="stat-value">{result.function_count}</div>
            <div class="stat-label">Functions</div>
        </div>
        <div class="stat">
            <div class="stat-value">{result.avg_ccn:.1f}</div>
            <div class="stat-label">Avg CCN</div>
        </div>
        <div class="stat">
            <div class="stat-value" style="color: {'#ff6b6b' if result.warning_count > 0 else '#00d4ff'}">{result.warning_count}</div>
            <div class="stat-label">Warnings</div>
        </div>
    </div>

    <h2>Functions by Complexity</h2>
    <table>
        <thead>
            <tr><th>CCN</th><th>NLOC</th><th>Tokens</th><th>Params</th><th>Function</th><th>Location</th></tr>
        </thead>
        <tbody>
            {''.join(func_rows[:100])}
        </tbody>
    </table>
    <p style="color: #888;">Showing top 100 functions by CCN. Thresholds: CCN&gt;{result.config.ccn_threshold}</p>

    <h2>Language Breakdown</h2>
    <table>
        <thead>
            <tr><th>Language</th><th>Files</th><th>Functions</th><th>NLOC</th><th>Avg CCN</th><th>Warnings</th></tr>
        </thead>
        <tbody>
            {''.join(f"<tr><td>{l.language}</td><td>{l.file_count}</td><td>{l.total_functions}</td><td>{l.total_nloc:,}</td><td>{l.avg_ccn:.1f}</td><td>{l.warning_count}</td></tr>" for l in sorted(result.languages.values(), key=lambda x: x.total_nloc, reverse=True))}
        </tbody>
    </table>

    <footer style="margin-top: 40px; color: #666; font-size: 0.9em;">
        Generated by Lizard TUI
    </footer>
</body>
</html>"""
    output_path.write_text(html)


def export_to_checkstyle(result: LizardResult, output_path: Path):
    """Export results to Checkstyle XML format."""
    from xml.etree.ElementTree import Element, SubElement, tostring
    from xml.dom import minidom

    root = Element("checkstyle", version="8.0")

    # Group by file
    file_funcs: dict[str, list[FunctionMetrics]] = {}
    for func in result.functions:
        if func.file_path not in file_funcs:
            file_funcs[func.file_path] = []
        file_funcs[func.file_path].append(func)

    for file_path, funcs in file_funcs.items():
        file_elem = SubElement(root, "file", name=file_path)

        for func in funcs:
            if func.has_violations(result.config):
                severity = "error" if func.ccn > result.config.ccn_threshold else "warning"
                msg = f"Function '{func.name}' has CCN={func.ccn}, NLOC={func.nloc}, params={func.param_count}"

                SubElement(file_elem, "error",
                    line=str(func.start_line),
                    column="1",
                    severity=severity,
                    message=msg,
                    source="lizard"
                )

    xml_str = minidom.parseString(tostring(root)).toprettyxml(indent="  ")
    output_path.write_text(xml_str)


# =============================================================================
# Modal Screens
# =============================================================================

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
        width: 55;
        height: auto;
        max-height: 85%;
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
             "Number of linearly independent paths through code."),
            ("NLOC", "Non-commenting Lines of Code",
             "Lines of code excluding comments and blank lines."),
            ("Tokens", "Token Count",
             "Number of tokens (keywords, operators, identifiers)."),
            ("Params", "Parameter Count",
             "Number of parameters the function accepts."),
            ("NS", "Nested Structures",
             "Maximum nesting depth of control structures."),
            ("Length", "Function Length",
             "Total lines including comments and blanks."),
        ]

        for acronym, full_name, desc in entries:
            text.append(f"{acronym}", style="bold cyan")
            text.append(f" - {full_name}\n", style="bold")
            text.append(f"  {desc}\n\n", style="dim")

        text.append("─" * 51 + "\n", style="dim")
        text.append("COMPLEXITY LEVELS\n", style="bold")
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

        text.append("\n─" * 51 + "\n", style="dim")
        text.append("KEY BINDINGS\n", style="bold")
        text.append("1-5  ", style="cyan")
        text.append("Switch tabs  ", style="dim")
        text.append("s    ", style="cyan")
        text.append("Cycle sort\n", style="dim")
        text.append("^S   ", style="cyan")
        text.append("Settings     ", style="dim")
        text.append("e    ", style="cyan")
        text.append("Export\n", style="dim")
        text.append("p    ", style="cyan")
        text.append("Toggle preview  ", style="dim")
        text.append("b    ", style="cyan")
        text.append("Toggle sidebar\n", style="dim")

        return text


class SettingsDialog(ModalScreen):
    """Threshold and analysis configuration dialog."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    SettingsDialog {
        align: center middle;
    }

    #settings-container {
        width: 55;
        height: 80%;
        max-height: 85%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #settings-scroll {
        height: 1fr;
    }

    #settings-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
        height: auto;
    }

    .section-label {
        color: $secondary;
        text-style: bold;
        padding-top: 1;
    }

    .setting-row {
        height: 3;
        padding: 0;
    }

    .setting-label {
        width: 12;
        padding: 1 0;
    }

    .setting-input {
        width: 1fr;
    }

    #settings-buttons {
        height: 3;
        padding-top: 1;
        dock: bottom;
    }

    #settings-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, config: AnalysisConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-container"):
            yield Static("ANALYSIS SETTINGS", id="settings-title")

            with ScrollableContainer(id="settings-scroll"):
                yield Static("Thresholds", classes="section-label")
                with Horizontal(classes="setting-row"):
                    yield Label("CCN:", classes="setting-label")
                    yield Input(str(self.config.ccn_threshold), id="ccn-threshold", classes="setting-input")
                with Horizontal(classes="setting-row"):
                    yield Label("NLOC:", classes="setting-label")
                    yield Input(str(self.config.nloc_threshold), id="nloc-threshold", classes="setting-input")
                with Horizontal(classes="setting-row"):
                    yield Label("Params:", classes="setting-label")
                    yield Input(str(self.config.params_threshold), id="params-threshold", classes="setting-input")
                with Horizontal(classes="setting-row"):
                    yield Label("Nesting:", classes="setting-label")
                    yield Input(str(self.config.ns_threshold), id="ns-threshold", classes="setting-input")

                yield Static("Extensions", classes="section-label")
                yield Checkbox("Nested Structures (-ENS)", id="enable-ns", value=self.config.enable_ns)
                yield Checkbox("Duplicate Detection (-Eduplicate)", id="enable-duplicates", value=self.config.enable_duplicates)
                yield Checkbox("Word Count (-Ewordcount)", id="enable-wordcount", value=self.config.enable_wordcount)

                yield Static("Exclude patterns (comma-sep)", classes="section-label")
                yield Input(",".join(self.config.exclude_patterns), id="exclude-input")

            with Horizontal(id="settings-buttons"):
                yield Button("Save", id="save-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._save_settings()
        else:
            self.dismiss(None)

    def _save_settings(self) -> None:
        try:
            self.config.ccn_threshold = int(self.query_one("#ccn-threshold", Input).value)
            self.config.nloc_threshold = int(self.query_one("#nloc-threshold", Input).value)
            self.config.params_threshold = int(self.query_one("#params-threshold", Input).value)
            self.config.ns_threshold = int(self.query_one("#ns-threshold", Input).value)
            self.config.enable_ns = self.query_one("#enable-ns", Checkbox).value
            self.config.enable_duplicates = self.query_one("#enable-duplicates", Checkbox).value
            self.config.enable_wordcount = self.query_one("#enable-wordcount", Checkbox).value

            exclude_text = self.query_one("#exclude-input", Input).value
            self.config.exclude_patterns = [p.strip() for p in exclude_text.split(",") if p.strip()]

            self.config.save()
            self.dismiss(self.config)
        except ValueError:
            pass

    def action_save(self) -> None:
        self._save_settings()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExportDialog(ModalScreen):
    """Export report dialog."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    ExportDialog {
        align: center middle;
    }

    #export-container {
        width: 45;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    #export-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        padding-bottom: 1;
    }

    #format-select {
        padding: 1 0;
    }

    #output-label {
        padding-top: 1;
    }

    #export-buttons {
        height: 3;
        padding-top: 1;
    }

    #export-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_format = "csv-functions"

    def compose(self) -> ComposeResult:
        with Vertical(id="export-container"):
            yield Static("EXPORT REPORT", id="export-title")

            with RadioSet(id="format-select"):
                yield RadioButton("CSV (Functions)", id="csv-functions", value=True)
                yield RadioButton("CSV (Files)", id="csv-files")
                yield RadioButton("HTML Report", id="html")
                yield RadioButton("Checkstyle XML", id="checkstyle")

            yield Label("Output filename:", id="output-label")
            yield Input("lizard_report", id="output-name")

            with Horizontal(id="export-buttons"):
                yield Button("Export", id="export-btn", variant="primary")
                yield Button("Cancel", id="cancel-btn")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.pressed:
            self.selected_format = event.pressed.id or "csv-functions"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-btn":
            filename = self.query_one("#output-name", Input).value
            self.dismiss((self.selected_format, filename))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


# =============================================================================
# Widgets
# =============================================================================

class ThresholdIndicator(Widget):
    """Visual threshold indicator with bar."""

    def __init__(self, label: str, value: int = 0, threshold: int = 15, **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.value = value
        self.threshold = threshold

    def compose(self) -> ComposeResult:
        yield Static(self._render(), id="indicator-content")

    def _render(self) -> Text:
        text = Text()
        pct = min(100, (self.value / self.threshold) * 100) if self.threshold > 0 else 0

        if pct <= 60:
            color = "green"
            symbol = "✓"
        elif pct <= 100:
            color = "yellow"
            symbol = "●"
        else:
            color = "red"
            symbol = "✗"

        text.append(f"{self.label}: ", style="dim")
        text.append(f"{self.value}", style=f"bold {color}")
        text.append(f"/{self.threshold} ", style="dim")
        text.append(symbol, style=color)

        bar_width = 8
        filled = int((min(pct, 100) / 100) * bar_width)
        text.append(" [", style="dim")
        text.append("█" * filled, style=color)
        text.append("░" * (bar_width - filled), style="dim")
        text.append("]", style="dim")

        return text

    def update_values(self, value: int, threshold: int):
        self.value = value
        self.threshold = threshold
        try:
            self.query_one("#indicator-content", Static).update(self._render())
        except Exception:
            pass


class LanguageBreakdownWidget(Widget):
    """Shows per-language statistics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.languages: dict[str, LanguageBreakdown] = {}

    def compose(self) -> ComposeResult:
        yield Static(self._render(), id="lang-content")

    def _render(self) -> Text:
        text = Text()
        text.append("LANGUAGES\n", style="bold cyan")
        text.append("─" * 26 + "\n", style="dim")

        if not self.languages:
            text.append("No data", style="dim")
            return text

        sorted_langs = sorted(
            self.languages.values(),
            key=lambda x: x.total_nloc,
            reverse=True
        )

        for lang in sorted_langs[:6]:
            ccn_color = "green" if lang.avg_ccn <= 5 else "yellow" if lang.avg_ccn <= 10 else "red"
            text.append(f"{lang.language[:8]:<8} ", style="cyan")
            text.append(f"{lang.file_count:>3}f ", style="dim")
            text.append(f"CCN {lang.avg_ccn:.1f}\n", style=ccn_color)

        if len(sorted_langs) > 6:
            text.append(f"  +{len(sorted_langs) - 6} more...\n", style="dim")

        return text

    def update_data(self, languages: dict[str, LanguageBreakdown]):
        self.languages = languages
        try:
            self.query_one("#lang-content", Static).update(self._render())
        except Exception:
            pass


class SummaryWidget(Widget):
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

        text.append("SUMMARY\n", style="bold cyan")
        text.append("─" * 26 + "\n", style="dim")

        text.append("NLOC ", style="dim")
        text.append(f"{r.total_nloc:,}\n", style="bold")
        text.append("Funcs ", style="dim")
        text.append(f"{r.function_count}\n", style="bold")
        text.append("Files ", style="dim")
        text.append(f"{len(r.files)}\n", style="bold")

        text.append("─" * 26 + "\n", style="dim")

        text.append("Avg CCN ", style="dim")
        ccn_color = "green" if r.avg_ccn <= 5 else "yellow" if r.avg_ccn <= 10 else "red"
        text.append(f"{r.avg_ccn:.1f}\n", style=f"bold {ccn_color}")

        text.append("Avg NLOC ", style="dim")
        text.append(f"{r.avg_nloc:.0f}\n", style="bold")

        if r.warning_count > 0:
            text.append("─" * 26 + "\n", style="dim")
            text.append(f"⚠ {r.warning_count} warnings\n", style="bold red")

        if r.duplicate_rate > 0:
            text.append(f"◉ {r.duplicate_rate:.1f}% duplicates\n", style="bold yellow")

        text.append("─" * 26 + "\n", style="dim")

        if r.functions:
            low = sum(1 for f in r.functions if f.ccn <= 5)
            medium = sum(1 for f in r.functions if 5 < f.ccn <= 10)
            high = sum(1 for f in r.functions if 10 < f.ccn <= 15)
            critical = sum(1 for f in r.functions if f.ccn > 15)
            total = len(r.functions)

            def bar(count):
                width = int((count / total) * 10) if total > 0 else 0
                return ("█" * width).ljust(10)

            text.append("Low    ", style="dim")
            text.append(bar(low), style="green")
            text.append(f" {low}\n", style="bold green")

            text.append("Med    ", style="dim")
            text.append(bar(medium), style="yellow")
            text.append(f" {medium}\n", style="bold yellow")

            text.append("High   ", style="dim")
            text.append(bar(high), style="#ff8800")
            text.append(f" {high}\n", style="bold #ff8800")

            text.append("Crit   ", style="dim")
            text.append(bar(critical), style="red")
            text.append(f" {critical}\n", style="bold red")

        return text

    def update_result(self, result: LizardResult):
        self.result = result
        try:
            self.query_one("#summary-content", Static).update(self._render_summary())
        except Exception:
            pass


# =============================================================================
# Main Application
# =============================================================================

class LizardTUI(App):
    """Main TUI application for Lizard visualization."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("ctrl+o", "browse_dirs", "Folders"),
        Binding("ctrl+f", "browse_all", "Files"),
        Binding("c", "copy_critical", "Copy Crit"),
        Binding("s", "cycle_sort", "Sort"),
        Binding("ctrl+s", "open_settings", "Settings"),
        Binding("e", "export", "Export"),
        Binding("p", "toggle_preview", "Preview"),
        Binding("b", "toggle_sidebar", "Sidebar"),
        Binding("1", "show_tab_1", "Functions"),
        Binding("2", "show_tab_2", "Files"),
        Binding("3", "show_tab_3", "Warnings"),
        Binding("4", "show_tab_4", "Duplicates"),
        Binding("5", "show_tab_5", "Words"),
        Binding("question_mark", "show_legend", "Legend"),
        Binding("escape", "clear_filter", "Clear"),
    ]

    result: reactive[Optional[LizardResult]] = reactive(None)
    current_sort: reactive[str] = reactive("ccn")
    filter_text: reactive[str] = reactive("")
    config: AnalysisConfig = AnalysisConfig.load()
    sort_options = ["ccn", "nloc", "name", "params", "tokens"]

    def __init__(self, initial_path: str = "."):
        # Build CSS with theme colors before super().__init__()
        theme_colors = get_theme_colors()
        bg = theme_colors['bg']
        fg = theme_colors['fg']
        footer_pos = get_footer_position()
        self.CSS = f"""
        Screen {{
            background: {bg};
            color: {fg};
        }}

        #main-container {{
            height: 100%;
        }}

        #toolbar {{
            height: 1;
            padding: 0 1;
            background: {bg};
        }}

        #path-input {{
            width: 1fr;
            height: 1;
            border: none;
        }}


        #content-area {{
            height: 1fr;
        }}

        #sidebar {{
            width: 30;
            border-right: solid {fg};
            background: {bg};
            padding: 1;
        }}

        #sidebar.collapsed {{
            width: 0;
            display: none;
        }}

        #main-panel {{
            width: 1fr;
        }}

        #filter-bar {{
            height: 1;
            padding: 0 1;
            background: {bg};
        }}

        #filter-input {{
            width: 1fr;
            border: none;
            height: 1;
            padding: 0;
        }}

        #sort-label {{
            width: auto;
            padding: 0 1;
        }}

        DataTable {{
            height: 1fr;
            background: {bg};
            color: {fg};
        }}

        #code-preview {{
            height: 40%;
            border-top: solid {fg};
            background: {bg};
            padding: 0 1;
            display: none;
        }}

        #code-preview.visible {{
            display: block;
        }}

        #code-preview-content {{
            width: auto;
            min-width: 100%;
        }}

        #status-bar {{
            height: 1;
            dock: bottom;
            background: {fg};
            color: {bg};
            padding: 0 1;
        }}

        #word-cloud-content {{
            padding: 1;
        }}

        #duplicates-list {{
            height: 1fr;
            background: {bg};
            color: {fg};
        }}

        .duplicate-item {{
            padding: 0 1;
        }}

        TabbedContent {{
            height: 1fr;
            background: {bg};
            color: {fg};
        }}

        TabPane {{
            padding: 0;
            background: {bg};
            color: {fg};
        }}

        ListView {{
            background: {bg};
            color: {fg};
        }}

        ListItem {{
            background: {bg};
            color: {fg};
        }}

        Static {{
            background: {bg};
            color: {fg};
        }}

        Input {{
            background: {bg};
            color: {fg};
        }}

        Button {{
            background: {bg};
            color: {fg};
        }}

        Footer {{
            dock: {footer_pos};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        self.initial_path = initial_path
        self._displayed_functions: list[FunctionMetrics] = []

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=True)

        with Vertical(id="main-container"):
            with Horizontal(id="toolbar"):
                yield Input(
                    placeholder="Enter path to analyze (Enter=run)...",
                    value=self.initial_path,
                    id="path-input",
                )

            with Horizontal(id="content-area"):
                with Vertical(id="sidebar"):
                    yield SummaryWidget(id="summary-widget")
                    yield LanguageBreakdownWidget(id="lang-widget")
                    yield Static("", id="threshold-section")

                with Vertical(id="main-panel"):
                    with Horizontal(id="filter-bar"):
                        yield Input(
                            placeholder="Filter by name or file...",
                            id="filter-input",
                        )
                        yield Label(f"Sort: {self.current_sort.upper()}", id="sort-label")

                    with TabbedContent(id="tabs-container"):
                        with TabPane("Functions", id="functions-tab"):
                            yield DataTable(id="functions-table", cursor_type="row")
                        with TabPane("Files", id="files-tab"):
                            yield DataTable(id="files-table", cursor_type="row")
                        with TabPane("Warnings", id="warnings-tab"):
                            yield DataTable(id="warnings-table", cursor_type="row")
                        with TabPane("Duplicates", id="duplicates-tab"):
                            yield Static("Enable duplicates in settings (Ctrl+S)", id="duplicates-content")
                        with TabPane("Words", id="words-tab"):
                            yield Static("Enable word count in settings (Ctrl+S)", id="word-cloud-content")

            with ScrollableContainer(id="code-preview"):
                yield Static("Select a function to preview code", id="code-preview-content")

            yield Static("Ready", id="status-bar")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize tables on mount."""
        self.title = "Lizard"
        self.sub_title = ""

        # Setup functions table
        func_table = self.query_one("#functions-table", DataTable)
        func_table.add_columns("CCN", "NLOC", "Tok", "Par", "NS", "Function", "File", "Lines")

        # Setup files table
        file_table = self.query_one("#files-table", DataTable)
        file_table.add_columns("NLOC", "Avg NLOC", "Avg CCN", "Avg Tok", "Funcs", "Lang", "File")

        # Setup warnings table
        warn_table = self.query_one("#warnings-table", DataTable)
        warn_table.add_columns("CCN", "NLOC", "Par", "NS", "Function", "File", "Violation")

        # Auto-analyze on startup
        if self.initial_path:
            self.run_analysis(self.initial_path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press (legacy - buttons removed)."""
        pass

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
        if event.pane.id in ("functions-tab", "warnings-tab"):
            code_preview.add_class("visible")
        else:
            code_preview.remove_class("visible")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Show code preview when function row is highlighted."""
        if event.data_table.id not in ("functions-table", "warnings-table"):
            return

        if not self.result or not self._displayed_functions:
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

            start = max(0, func.start_line - 1)
            end = min(len(lines), func.end_line)

            text = Text()
            text.append(f"{Path(func.file_path).name}\n", style="bold cyan")
            text.append(f"{func.full_signature}\n", style="bold")
            text.append(f"CCN: {func.ccn}  NLOC: {func.nloc}  Params: {func.param_count}  NS: {func.nested_structures}\n", style="dim")
            text.append("─" * 60 + "\n", style="dim")

            for i, line in enumerate(lines[start:end], start=func.start_line):
                text.append(f"{i:4} ", style="dim")
                text.append(f"{line.rstrip()}\n")

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
            result = run_lizard(path, self.config)
            self.call_from_thread(self._analysis_complete, result)
        except Exception as e:
            self.call_from_thread(self._analysis_error, str(e))

    def _analysis_complete(self, result: LizardResult) -> None:
        """Handle analysis completion."""
        self.pop_screen()
        self.result = result
        self.update_tables()

        # Update widgets
        self.query_one("#summary-widget", SummaryWidget).update_result(result)
        self.query_one("#lang-widget", LanguageBreakdownWidget).update_data(result.languages)

        # Update duplicates tab
        dup_content = self.query_one("#duplicates-content", Static)
        if result.duplicates:
            dup_text = Text()
            dup_text.append(f"Found {len(result.duplicates)} duplicate blocks ({result.duplicate_rate:.1f}%)\n\n", style="bold yellow")
            for i, dup in enumerate(result.duplicates[:20], 1):
                dup_text.append(f"Block {i}: {len(dup.locations)} locations\n", style="bold")
                for loc in dup.locations[:5]:
                    dup_text.append(f"  {Path(loc[0]).name}:{loc[1]}-{loc[2]}\n", style="dim")
                if len(dup.locations) > 5:
                    dup_text.append(f"  +{len(dup.locations) - 5} more...\n", style="dim")
                dup_text.append("\n")
            dup_content.update(dup_text)
        elif self.config.enable_duplicates:
            dup_content.update("No duplicates found")
        else:
            dup_content.update("Enable duplicates in settings (Ctrl+S)")

        # Update word cloud tab
        word_content = self.query_one("#word-cloud-content", Static)
        if result.word_frequencies:
            word_text = Text()
            word_text.append("Top Identifiers\n\n", style="bold cyan")
            for i, word in enumerate(result.word_frequencies[:50], 1):
                if i <= 10:
                    style = "bold white"
                elif i <= 25:
                    style = "white"
                else:
                    style = "dim"
                word_text.append(f"{word.count:>5} ", style="cyan")
                word_text.append(f"{word.word}\n", style=style)
            word_content.update(word_text)
        elif self.config.enable_wordcount:
            word_content.update("No words found")
        else:
            word_content.update("Enable word count in settings (Ctrl+S)")

        self.update_status(f"Analyzed {len(result.files)} files, {result.function_count} functions, {result.warning_count} warnings")

    def _analysis_error(self, error: str) -> None:
        """Handle analysis error."""
        self.pop_screen()
        self.update_status(f"Error: {error}")

    def update_status(self, message: str) -> None:
        """Update status bar."""
        self.query_one("#status-bar", Static).update(message)

    def update_tables(self) -> None:
        """Update data tables with current result."""
        if not self.result:
            return

        # Update sort label
        try:
            self.query_one("#sort-label", Label).update(f"Sort: {self.current_sort.upper()}")
        except Exception:
            pass

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
        elif self.current_sort == "params":
            functions = sorted(functions, key=lambda f: f.param_count, reverse=True)
        elif self.current_sort == "tokens":
            functions = sorted(functions, key=lambda f: f.token_count, reverse=True)

        self._displayed_functions = functions

        for func in functions:
            ccn_text = Text(str(func.ccn))
            if func.ccn <= 5:
                ccn_text.stylize("green")
            elif func.ccn <= 10:
                ccn_text.stylize("yellow")
            elif func.ccn <= 15:
                ccn_text.stylize("#ff8800")
            else:
                ccn_text.stylize("bold red")

            short_path = Path(func.file_path).name

            func_table.add_row(
                ccn_text,
                str(func.nloc),
                str(func.token_count),
                str(func.param_count),
                str(func.nested_structures),
                func.name,
                short_path,
                f"{func.start_line}-{func.end_line}",
            )

        # Update files table
        file_table = self.query_one("#files-table", DataTable)
        file_table.clear()

        files = self.result.files

        if self.current_sort == "ccn":
            files = sorted(files, key=lambda f: f.avg_ccn, reverse=True)
        elif self.current_sort == "nloc":
            files = sorted(files, key=lambda f: f.nloc, reverse=True)
        elif self.current_sort == "name":
            files = sorted(files, key=lambda f: f.file_path.lower())

        for file in files:
            ccn_text = Text(f"{file.avg_ccn:.1f}")
            if file.avg_ccn <= 5:
                ccn_text.stylize("green")
            elif file.avg_ccn <= 10:
                ccn_text.stylize("yellow")
            elif file.avg_ccn <= 15:
                ccn_text.stylize("#ff8800")
            else:
                ccn_text.stylize("bold red")

            short_path = Path(file.file_path).name

            file_table.add_row(
                str(file.nloc),
                f"{file.avg_nloc:.1f}",
                ccn_text,
                f"{file.avg_token:.1f}",
                str(file.function_count),
                file.language,
                short_path,
            )

        # Update warnings table
        warn_table = self.query_one("#warnings-table", DataTable)
        warn_table.clear()

        warnings = [f for f in self.result.functions if f.has_violations(self.config)]
        warnings = sorted(warnings, key=lambda f: f.ccn, reverse=True)

        for func in warnings:
            violations = []
            if func.ccn > self.config.ccn_threshold:
                violations.append(f"CCN>{self.config.ccn_threshold}")
            if func.nloc > self.config.nloc_threshold:
                violations.append(f"NLOC>{self.config.nloc_threshold}")
            if func.param_count > self.config.params_threshold:
                violations.append(f"Params>{self.config.params_threshold}")
            if self.config.enable_ns and func.nested_structures > self.config.ns_threshold:
                violations.append(f"NS>{self.config.ns_threshold}")

            ccn_text = Text(str(func.ccn), style="bold red")
            short_path = Path(func.file_path).name

            warn_table.add_row(
                ccn_text,
                str(func.nloc),
                str(func.param_count),
                str(func.nested_structures),
                func.name,
                short_path,
                ", ".join(violations),
            )

    # ==========================================================================
    # Actions
    # ==========================================================================

    def action_refresh(self) -> None:
        """Refresh analysis."""
        path = self.query_one("#path-input", Input).value
        self.run_analysis(path)

    def action_cycle_sort(self) -> None:
        """Cycle through sort options."""
        idx = self.sort_options.index(self.current_sort)
        self.current_sort = self.sort_options[(idx + 1) % len(self.sort_options)]
        self.update_tables()
        self.update_status(f"Sorted by {self.current_sort.upper()}")

    def action_clear_filter(self) -> None:
        """Clear filter."""
        self.query_one("#filter-input", Input).value = ""
        self.filter_text = ""
        self.update_tables()

    def action_show_legend(self) -> None:
        """Show legend modal."""
        self.push_screen(LegendScreen())

    def action_open_settings(self) -> None:
        """Open settings dialog."""
        def on_settings_close(new_config: Optional[AnalysisConfig]) -> None:
            if new_config:
                self.config = new_config
                self.update_status("Settings saved. Press 'r' to re-analyze.")

        self.push_screen(SettingsDialog(self.config), on_settings_close)

    def action_export(self) -> None:
        """Open export dialog."""
        if not self.result:
            self.update_status("No data to export. Run analysis first.")
            return

        def on_export_close(choice: Optional[tuple[str, str]]) -> None:
            if choice and self.result:
                format_id, filename = choice
                try:
                    if format_id == "csv-functions":
                        path = Path(filename + ".csv")
                        export_to_csv(self.result, path, "functions")
                    elif format_id == "csv-files":
                        path = Path(filename + ".csv")
                        export_to_csv(self.result, path, "files")
                    elif format_id == "html":
                        path = Path(filename + ".html")
                        export_to_html(self.result, path)
                    elif format_id == "checkstyle":
                        path = Path(filename + ".xml")
                        export_to_checkstyle(self.result, path)

                    self.update_status(f"Exported to {path}")
                except Exception as e:
                    self.update_status(f"Export error: {e}")

        self.push_screen(ExportDialog(), on_export_close)

    def action_toggle_preview(self) -> None:
        """Toggle code preview panel."""
        preview = self.query_one("#code-preview")
        preview.toggle_class("visible")

    def action_toggle_sidebar(self) -> None:
        """Toggle sidebar."""
        sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("collapsed")

    def action_show_tab_1(self) -> None:
        """Show Functions tab."""
        self.query_one("#tabs-container", TabbedContent).active = "functions-tab"

    def action_show_tab_2(self) -> None:
        """Show Files tab."""
        self.query_one("#tabs-container", TabbedContent).active = "files-tab"

    def action_show_tab_3(self) -> None:
        """Show Warnings tab."""
        self.query_one("#tabs-container", TabbedContent).active = "warnings-tab"

    def action_show_tab_4(self) -> None:
        """Show Duplicates tab."""
        self.query_one("#tabs-container", TabbedContent).active = "duplicates-tab"

    def action_show_tab_5(self) -> None:
        """Show Words tab."""
        self.query_one("#tabs-container", TabbedContent).active = "words-tab"

    def action_copy_critical(self) -> None:
        """Copy critical functions to clipboard (excluding test files)."""
        import subprocess as sp

        if not self.result or not self.result.functions:
            self.update_status("No data to copy")
            return

        critical = [
            f for f in self.result.functions
            if f.ccn > self.config.ccn_threshold and "test" not in f.file_path.lower()
        ]

        if not critical:
            self.update_status("No critical functions found (excluding tests)")
            return

        critical.sort(key=lambda f: f.ccn, reverse=True)

        lines = [f"CRITICAL FUNCTIONS (CCN > {self.config.ccn_threshold})", "=" * 50, ""]
        for f in critical:
            lines.append(f"CCN {f.ccn:3} | {f.name}")
            lines.append(f"        | {f.file_path}:{f.start_line}-{f.end_line}")
            lines.append("")

        text = "\n".join(lines)

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


# =============================================================================
# Entry Point
# =============================================================================

def main():
    """Main entry point."""
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    app = LizardTUI(initial_path=path)
    app.run()


if __name__ == "__main__":
    main()
