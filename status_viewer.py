#!/usr/bin/env python3
"""
Status Viewer - Display Claude Code session metrics
Shows token usage, cost estimates, model info, and git status
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, ProgressBar
from textual.timer import Timer


# Token pricing (USD per 1M tokens) - Claude Opus 4.5
PRICING = {
    "claude-opus-4-5-20251101": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "default": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
}

# Context window sizes
CONTEXT_WINDOW = {
    "claude-opus-4-5-20251101": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "default": 200_000,
}


class MetricBox(Static):
    """A styled metric display box."""

    def __init__(self, title: str, value: str = "—", style_class: str = "") -> None:
        super().__init__()
        self.title = title
        self._value = value
        self._style_class = style_class

    def _make_id(self) -> str:
        """Create a valid CSS id from the title."""
        return "val-" + self.title.lower().replace(' ', '-').replace('.', '')

    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="metric-title")
        yield Static(self._value, classes="metric-value", id=self._make_id())

    def update_value(self, value: str) -> None:
        self._value = value
        try:
            val_widget = self.query_one(f"#{self._make_id()}", Static)
            val_widget.update(value)
        except Exception:
            pass


class StatusViewer(App):
    """Status viewer application."""

    CSS = """
    Screen {
        background: $surface;
    }

    #main-container {
        padding: 1 2;
    }

    .section-title {
        text-style: bold;
        color: $primary;
        padding: 1 0 0 0;
    }

    .metrics-row {
        height: auto;
        padding: 0 0 1 0;
    }

    MetricBox {
        width: 1fr;
        height: 5;
        border: solid $primary-darken-2;
        padding: 0 1;
        margin: 0 1 0 0;
    }

    .metric-title {
        color: $text-muted;
        text-style: italic;
    }

    .metric-value {
        color: $text;
        text-style: bold;
        text-align: center;
    }

    #session-info {
        height: auto;
        padding: 1;
        border: solid $primary-darken-3;
        margin-top: 1;
    }

    #session-info Static {
        height: auto;
    }

    .info-label {
        color: $text-muted;
    }

    .info-value {
        color: $text;
    }

    #last-update {
        dock: bottom;
        height: 1;
        color: $text-muted;
        text-align: right;
        padding-right: 2;
    }

    #context-section {
        height: auto;
        padding: 1;
        margin-top: 1;
    }

    #context-label {
        height: 1;
        margin-bottom: 1;
    }

    #context-bar {
        height: 1;
        width: 100%;
    }

    #context-bar > .bar--bar {
        color: $success;
    }

    #context-bar > .bar--complete {
        color: $warning;
    }

    .context-warning #context-bar > .bar--bar {
        color: $warning;
    }

    .context-critical #context-bar > .bar--bar {
        color: $error;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    ]

    session_data = reactive({})

    def __init__(self, project_path: str = None):
        super().__init__()
        self.project_path = project_path or os.getcwd()
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main-container"):
            yield Static("TOKEN USAGE", classes="section-title")
            with Horizontal(classes="metrics-row"):
                yield MetricBox("Input Tokens", "—")
                yield MetricBox("Output Tokens", "—")
                yield MetricBox("Cache Read", "—")
                yield MetricBox("Cache Write", "—")

            yield Static("SESSION METRICS", classes="section-title")
            with Horizontal(classes="metrics-row"):
                yield MetricBox("Total Tokens", "—")
                yield MetricBox("Est. Cost", "—")
                yield MetricBox("Messages", "—")
                yield MetricBox("Duration", "—")

            yield Static("CONTEXT WINDOW", classes="section-title")
            with Vertical(id="context-section"):
                yield Static("Context: —% used (0K / 200K)", id="context-label")
                yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="context-bar")

            with Vertical(id="session-info"):
                yield Static("Model: —", id="model-info")
                yield Static("Project: —", id="project-info")
                yield Static("Git Branch: —", id="git-info")
                yield Static("Session ID: —", id="session-id")

            yield Static("Last update: —", id="last-update")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Claude Code Status"
        self.sub_title = "Session Metrics"
        self.action_refresh()
        # Auto-refresh every 5 seconds
        self._timer = self.set_interval(5.0, self.action_refresh)

    def get_project_sessions_dir(self) -> Path | None:
        """Find the sessions directory for the current project."""
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None

        # Convert project path to Claude's naming convention
        project_key = self.project_path.replace("/", "-")
        if project_key.startswith("-"):
            project_key = project_key[1:]

        sessions_dir = claude_dir / f"-{project_key}"
        if sessions_dir.exists():
            return sessions_dir

        # Fallback: find most recently modified project dir
        project_dirs = sorted(claude_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for d in project_dirs:
            if d.is_dir() and not d.name.startswith("agent-"):
                return d
        return None

    def get_latest_session(self, sessions_dir: Path) -> Path | None:
        """Get the most recent session file."""
        session_files = [
            f for f in sessions_dir.iterdir()
            if f.suffix == ".jsonl" and not f.name.startswith("agent-")
        ]
        if not session_files:
            return None
        return max(session_files, key=lambda f: f.stat().st_mtime)

    def parse_session(self, session_file: Path) -> dict:
        """Parse session file and extract metrics."""
        data = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "pending_tokens": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_cache_write_tokens": 0,
            "message_count": 0,
            "model": "unknown",
            "git_branch": "",
            "cwd": "",
            "session_id": "",
            "first_timestamp": None,
            "last_timestamp": None,
        }

        last_assistant = None
        last_user = None

        try:
            with open(session_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())

                        # Track last user message for pending context estimate
                        if record.get("type") == "user":
                            last_user = record

                        if record.get("type") == "assistant":
                            data["message_count"] += 1
                            msg = record.get("message", {})
                            usage = msg.get("usage", {})

                            # Sum totals for cost calculation
                            data["total_input_tokens"] += usage.get("input_tokens", 0)
                            data["total_output_tokens"] += usage.get("output_tokens", 0)
                            data["total_cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
                            data["total_cache_write_tokens"] += usage.get("cache_creation_input_tokens", 0)

                            # Keep track of last assistant message for current context
                            last_assistant = record

                            if msg.get("model"):
                                data["model"] = msg["model"]
                            if record.get("gitBranch"):
                                data["git_branch"] = record["gitBranch"]
                            if record.get("cwd"):
                                data["cwd"] = record["cwd"]
                            if record.get("sessionId"):
                                data["session_id"] = record["sessionId"]

                            timestamp = record.get("timestamp")
                            if timestamp:
                                if data["first_timestamp"] is None:
                                    data["first_timestamp"] = timestamp
                                data["last_timestamp"] = timestamp

                    except json.JSONDecodeError:
                        continue

            # Get current context from last message
            if last_assistant:
                msg = last_assistant.get("message", {})
                usage = msg.get("usage", {})
                data["input_tokens"] = usage.get("input_tokens", 0)
                data["output_tokens"] = usage.get("output_tokens", 0)
                data["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
                data["cache_write_tokens"] = usage.get("cache_creation_input_tokens", 0)

                # Check if there's a pending user message after last assistant
                # This means Claude is currently processing and context is larger
                if last_user:
                    last_asst_ts = last_assistant.get("timestamp", "")
                    last_user_ts = last_user.get("timestamp", "")
                    if last_user_ts > last_asst_ts:
                        # Estimate pending context from user message
                        user_msg = last_user.get("message", {})
                        if isinstance(user_msg, dict):
                            content = user_msg.get("content", [])
                            if isinstance(content, list):
                                # Estimate tokens from content length
                                content_str = str(content)
                            else:
                                content_str = str(content)
                        else:
                            content_str = str(user_msg)
                        # Rough estimate: 1 token per 4 characters
                        pending_tokens = len(content_str) // 4
                        data["pending_tokens"] = pending_tokens

        except Exception as e:
            data["error"] = str(e)

        return data

    def calculate_cost(self, data: dict) -> float:
        """Calculate estimated cost based on total token usage."""
        model = data.get("model", "default")
        pricing = PRICING.get(model, PRICING["default"])

        cost = 0.0
        cost += (data["total_input_tokens"] / 1_000_000) * pricing["input"]
        cost += (data["total_output_tokens"] / 1_000_000) * pricing["output"]
        cost += (data["total_cache_read_tokens"] / 1_000_000) * pricing["cache_read"]
        cost += (data["total_cache_write_tokens"] / 1_000_000) * pricing["cache_write"]

        return cost

    def format_tokens(self, count: int) -> str:
        """Format token count with K/M suffix."""
        if count >= 1_000_000:
            return f"{count/1_000_000:.2f}M"
        elif count >= 1_000:
            return f"{count/1_000:.1f}K"
        return str(count)

    def format_duration(self, data: dict) -> str:
        """Calculate and format session duration."""
        if not data.get("first_timestamp") or not data.get("last_timestamp"):
            return "—"
        try:
            start = datetime.fromisoformat(data["first_timestamp"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(data["last_timestamp"].replace("Z", "+00:00"))
            delta = end - start

            hours, remainder = divmod(int(delta.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)

            if hours > 0:
                return f"{hours}h {minutes}m"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        except Exception:
            return "—"

    def get_git_branch(self) -> str:
        """Get current git branch."""
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=self.project_path,
                timeout=2
            )
            return result.stdout.strip() or "—"
        except Exception:
            return "—"

    def action_refresh(self) -> None:
        """Refresh metrics from session file."""
        sessions_dir = self.get_project_sessions_dir()
        if not sessions_dir:
            return

        session_file = self.get_latest_session(sessions_dir)
        if not session_file:
            return

        data = self.parse_session(session_file)
        cost = self.calculate_cost(data)
        total_tokens = (
            data["total_input_tokens"] +
            data["total_output_tokens"] +
            data["total_cache_read_tokens"] +
            data["total_cache_write_tokens"]
        )

        # Update metric boxes (show session totals)
        boxes = list(self.query(MetricBox))
        if len(boxes) >= 8:
            boxes[0].update_value(self.format_tokens(data["total_input_tokens"]))
            boxes[1].update_value(self.format_tokens(data["total_output_tokens"]))
            boxes[2].update_value(self.format_tokens(data["total_cache_read_tokens"]))
            boxes[3].update_value(self.format_tokens(data["total_cache_write_tokens"]))
            boxes[4].update_value(self.format_tokens(total_tokens))
            boxes[5].update_value(f"${cost:.4f}")
            boxes[6].update_value(str(data["message_count"]))
            boxes[7].update_value(self.format_duration(data))

        # Update context progress bar (current context from last message)
        model = data.get("model", "default")
        context_size = CONTEXT_WINDOW.get(model, CONTEXT_WINDOW["default"])
        # Current context = input + cache_read + cache_write + pending from last message
        context_used = (
            data["input_tokens"] +
            data["cache_read_tokens"] +
            data["cache_write_tokens"] +
            data["pending_tokens"]
        )
        context_pct = min(100, (context_used / context_size) * 100)

        # Show pending indicator if there's a pending user message
        pending_str = ""
        if data["pending_tokens"] > 0:
            pending_str = f" +~{self.format_tokens(data['pending_tokens'])} pending"

        context_label = self.query_one("#context-label", Static)
        context_label.update(
            f"Context: {context_pct:.1f}% used ({self.format_tokens(context_used)} / {self.format_tokens(context_size)}){pending_str}"
        )

        context_bar = self.query_one("#context-bar", ProgressBar)
        context_bar.update(progress=context_pct)

        # Update color based on usage level
        context_section = self.query_one("#context-section")
        context_section.remove_class("context-warning", "context-critical")
        if context_pct >= 90:
            context_section.add_class("context-critical")
        elif context_pct >= 70:
            context_section.add_class("context-warning")

        # Update session info
        model_name = data["model"].replace("claude-", "").replace("-20251101", "").replace("-20250514", "")
        self.query_one("#model-info", Static).update(f"Model: {model_name}")
        self.query_one("#project-info", Static).update(f"Project: {Path(self.project_path).name}")
        self.query_one("#git-info", Static).update(f"Git Branch: {data.get('git_branch') or self.get_git_branch()}")
        self.query_one("#session-id", Static).update(f"Session ID: {data['session_id'][:8]}..." if data["session_id"] else "Session ID: —")

        # Update timestamp
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#last-update", Static).update(f"Last update: {now}")


def main():
    import sys
    project_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    app = StatusViewer(project_path=project_path)
    app.run()


if __name__ == "__main__":
    main()
