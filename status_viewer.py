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

from config_panel import get_textual_theme, get_footer_position, get_show_header

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
    """A compact metric display - just label: value on one line."""

    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        self.title = title
        self._value = value
        self._id = "val-" + title.lower().replace(' ', '-').replace('.', '')

    def compose(self) -> ComposeResult:
        yield Static(f"[dim]{self.title}:[/] [bold]{self._value}[/]", id=self._id)

    def update_value(self, value: str) -> None:
        self._value = value
        try:
            val_widget = self.query_one(f"#{self._id}", Static)
            val_widget.update(f"[dim]{self.title}:[/] [bold]{value}[/]")
        except Exception:
            pass


class StatusViewer(App):
    """Status viewer application."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "serena", "Serena"),
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    ]

    session_data = reactive({})

    def __init__(self, project_path: str = None):
        # Build CSS with footer position before super().__init__()
        footer_pos = get_footer_position()
        self.CSS = f"""
        Screen {{
            background: $surface;
        }}

        #main-container {{
            padding: 0 2;
        }}

        .section-title {{
            text-style: bold;
            color: $primary;
            height: 1;
            margin-top: 1;
        }}

        .metrics-row {{
            height: auto;
            layout: grid;
            grid-size: 4;
            grid-columns: 1fr 1fr 1fr 1fr;
        }}

        MetricBox {{
            height: 1;
            padding: 0;
        }}

        #session-info {{
            height: auto;
            margin-top: 1;
        }}

        #session-info Static {{
            height: 1;
        }}

        #last-update {{
            dock: bottom;
            height: 1;
            color: $text-muted;
            text-align: right;
            padding-right: 2;
        }}

        #context-section {{
            height: auto;
            margin-top: 1;
        }}

        #context-label {{
            height: 1;
        }}

        #context-bar {{
            height: 1;
            width: 100%;
        }}

        #context-bar > .bar--bar {{
            color: $success;
        }}

        #context-bar > .bar--complete {{
            color: $warning;
        }}

        .context-warning #context-bar > .bar--bar {{
            color: $warning;
        }}

        .context-critical #context-bar > .bar--bar {{
            color: $error;
        }}

        Footer {{
            dock: {footer_pos};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()
        self.project_path = project_path or os.getcwd()
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=True)
        with Container(id="main-container"):
            yield Static("TOKEN USAGE", classes="section-title")
            with Horizontal(classes="metrics-row"):
                yield MetricBox("Input", "—")
                yield MetricBox("Output", "—")
                yield MetricBox("Cache Read", "—")
                yield MetricBox("Cache Write", "—")

            yield Static("SESSION", classes="section-title")
            with Horizontal(classes="metrics-row"):
                yield MetricBox("Total", "—")
                yield MetricBox("Cost", "—")
                yield MetricBox("Messages", "—")
                yield MetricBox("Duration", "—")

            yield Static("CONTEXT", classes="section-title")
            with Vertical(id="context-section"):
                yield Static("—% (0K / 200K)", id="context-label")
                yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="context-bar")

            with Vertical(id="session-info"):
                yield Static("[dim]Model:[/] —", id="model-info")
                yield Static("[dim]Project:[/] —", id="project-info")
                yield Static("[dim]Branch:[/] —", id="git-info")
                yield Static("[dim]Session:[/] —", id="session-id")

            yield Static("Updated: —", id="last-update")
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
        context_used = (
            data["input_tokens"] +
            data["cache_read_tokens"] +
            data["cache_write_tokens"] +
            data["pending_tokens"]
        )
        context_pct = min(100, (context_used / context_size) * 100)

        pending_str = ""
        if data["pending_tokens"] > 0:
            pending_str = f" +~{self.format_tokens(data['pending_tokens'])}"

        context_label = self.query_one("#context-label", Static)
        context_label.update(
            f"{context_pct:.1f}% ({self.format_tokens(context_used)} / {self.format_tokens(context_size)}){pending_str}"
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

        # Update session info with Rich markup
        model_name = data["model"].replace("claude-", "").replace("-20251101", "").replace("-20250514", "")
        self.query_one("#model-info", Static).update(f"[dim]Model:[/] {model_name}")
        self.query_one("#project-info", Static).update(f"[dim]Project:[/] {Path(self.project_path).name}")
        self.query_one("#git-info", Static).update(f"[dim]Branch:[/] {data.get('git_branch') or self.get_git_branch()}")
        session_id = data['session_id'][:8] + "..." if data["session_id"] else "—"
        self.query_one("#session-id", Static).update(f"[dim]Session:[/] {session_id}")

        # Update timestamp
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#last-update", Static).update(f"[dim]Updated:[/] {now}")

    def action_serena(self) -> None:
        """Open Serena dashboard in browser for current project."""
        import webbrowser
        import urllib.request
        import json

        # Scan ports 24282-24290 and find the one with matching project path
        for port in range(24282, 24291):
            try:
                resp = urllib.request.urlopen(f"http://localhost:{port}/get_config_overview", timeout=0.5)
                data = json.loads(resp.read().decode())
                active_path = data.get("active_project", {}).get("path", "")
                if active_path == self.project_path:
                    webbrowser.open(f"http://localhost:{port}/dashboard/")
                    return
            except Exception:
                continue

        # Fallback: open first available dashboard
        for port in range(24282, 24291):
            try:
                urllib.request.urlopen(f"http://localhost:{port}/dashboard/", timeout=0.5)
                webbrowser.open(f"http://localhost:{port}/dashboard/")
                return
            except Exception:
                continue

        self.notify("Serena not running", severity="warning")


def main():
    import sys
    project_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    app = StatusViewer(project_path=project_path)
    app.run()


if __name__ == "__main__":
    main()
