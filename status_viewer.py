#!/usr/bin/env python3
"""
Status Viewer - Display Claude Code session metrics
Redesigned with sqlit-inspired visual aesthetic
"""

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Static, ProgressBar
from textual.timer import Timer

from config_panel import get_textual_theme, get_footer_position, get_show_header

# Token pricing (USD per 1M tokens) - Claude models
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


class MetricItem(Static):
    """A single metric with label and value."""

    def __init__(self, label: str, value: str = "—", metric_id: str = "") -> None:
        super().__init__()
        self.label = label
        self._value = value
        self._metric_id = metric_id or label.lower().replace(" ", "-")

    def compose(self) -> ComposeResult:
        yield Static(f"[dim]{self.label}[/]", classes="metric-label")
        yield Static(self._value, classes="metric-value", id=f"val-{self._metric_id}")

    def update_value(self, value: str) -> None:
        self._value = value
        try:
            self.query_one(f"#val-{self._metric_id}", Static).update(value)
        except Exception:
            pass


class Panel(Container):
    """A styled panel container with border title - sqlit style."""

    def __init__(self, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        if title:
            self.border_title = title


class StatusViewer(App):
    """Status viewer with sqlit-inspired design."""

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "serena", "Serena"),
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
    ]

    session_data = reactive({})

    def __init__(self, project_path: str = None):
        footer_pos = get_footer_position()
        self.CSS = f"""
        Screen {{
            background: $background;
        }}
        * {{
            scrollbar-size: 1 1;
        }}

        #main-container {{
            padding: 1 2;
            height: 1fr;
        }}

        /* sqlit-style panels with rounded borders */
        Panel {{
            border: round $border;
            background: $background;
            padding: 0 1;
            margin-bottom: 1;
            height: auto;

            border-title-align: left;
            border-title-color: $primary;
            border-title-background: $background;
            border-title-style: bold;
        }}

        Panel:focus-within {{
            border: round $primary;
        }}

        /* Token usage panel - 2x2 grid */
        #tokens-panel {{
            height: auto;
        }}

        .metrics-grid {{
            layout: grid;
            grid-size: 2 2;
            grid-columns: 1fr 1fr;
            grid-rows: auto auto;
            height: auto;
            padding: 0;
        }}

        /* Session panel - 2x2 grid */
        #session-panel {{
            height: auto;
        }}

        /* Individual metric item */
        MetricItem {{
            height: 1;
            layout: horizontal;
            padding: 0;
        }}

        .metric-label {{
            width: auto;
            min-width: 12;
        }}

        .metric-value {{
            width: auto;
            color: $text;
            text-style: bold;
        }}

        /* Context bar panel */
        #context-panel {{
            height: auto;
            padding: 1;
        }}

        #context-info {{
            height: 1;
            layout: horizontal;
        }}

        #context-label {{
            width: 1fr;
        }}

        #context-pct {{
            width: auto;
            text-style: bold;
        }}

        #context-bar {{
            height: 1;
            margin-top: 0;
        }}

        ProgressBar > .bar--bar {{
            color: $success;
        }}

        ProgressBar > .bar--complete {{
            color: $primary;
        }}

        .context-warning #context-bar > .bar--bar {{
            color: $warning;
        }}

        .context-critical #context-bar > .bar--bar {{
            color: $error;
        }}

        /* Info panel */
        #info-panel {{
            height: auto;
        }}

        .info-row {{
            height: 1;
            layout: horizontal;
        }}

        .info-label {{
            width: 10;
            color: $text-muted;
        }}

        .info-value {{
            width: 1fr;
        }}

        /* Status bar at bottom */
        #status-bar {{
            dock: bottom;
            height: 1;
            background: $surface-darken-1;
            color: $text-muted;
            padding: 0 2;
            content-align: right middle;
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
        with Container(id="main-container"):
            # Token Usage Panel
            with Panel(title="Token Usage", id="tokens-panel"):
                with Horizontal(classes="metrics-grid"):
                    yield MetricItem("Input", "—", "input")
                    yield MetricItem("Output", "—", "output")
                    yield MetricItem("Cache Read", "—", "cache-read")
                    yield MetricItem("Cache Write", "—", "cache-write")

            # Session Panel
            with Panel(title="Session", id="session-panel"):
                with Horizontal(classes="metrics-grid"):
                    yield MetricItem("Total", "—", "total")
                    yield MetricItem("Cost", "—", "cost")
                    yield MetricItem("Messages", "—", "messages")
                    yield MetricItem("Duration", "—", "duration")

            # Context Panel
            with Panel(title="Context Window", id="context-panel"):
                with Horizontal(id="context-info"):
                    yield Static("0K / 200K", id="context-label")
                    yield Static("0%", id="context-pct")
                yield ProgressBar(total=100, show_eta=False, show_percentage=False, id="context-bar")

            # Info Panel
            with Panel(title="Session Info", id="info-panel"):
                with Horizontal(classes="info-row"):
                    yield Static("Model", classes="info-label")
                    yield Static("—", classes="info-value", id="model-info")
                with Horizontal(classes="info-row"):
                    yield Static("Project", classes="info-label")
                    yield Static("—", classes="info-value", id="project-info")
                with Horizontal(classes="info-row"):
                    yield Static("Branch", classes="info-label")
                    yield Static("—", classes="info-value", id="git-info")
                with Horizontal(classes="info-row"):
                    yield Static("Session", classes="info-label")
                    yield Static("—", classes="info-value", id="session-id")

        yield Static("Updated: —", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Claude Code Status"
        self.sub_title = "Session Metrics"
        self.action_refresh()
        self._timer = self.set_interval(5.0, self.action_refresh)

    def get_project_sessions_dir(self) -> Path | None:
        """Find the sessions directory for the current project."""
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None

        project_key = self.project_path.replace("/", "-")
        if project_key.startswith("-"):
            project_key = project_key[1:]

        sessions_dir = claude_dir / f"-{project_key}"
        if sessions_dir.exists():
            return sessions_dir

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

                        if record.get("type") == "user":
                            last_user = record

                        if record.get("type") == "assistant":
                            data["message_count"] += 1
                            msg = record.get("message", {})
                            usage = msg.get("usage", {})

                            data["total_input_tokens"] += usage.get("input_tokens", 0)
                            data["total_output_tokens"] += usage.get("output_tokens", 0)
                            data["total_cache_read_tokens"] += usage.get("cache_read_input_tokens", 0)
                            data["total_cache_write_tokens"] += usage.get("cache_creation_input_tokens", 0)

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

            if last_assistant:
                msg = last_assistant.get("message", {})
                usage = msg.get("usage", {})
                data["input_tokens"] = usage.get("input_tokens", 0)
                data["output_tokens"] = usage.get("output_tokens", 0)
                data["cache_read_tokens"] = usage.get("cache_read_input_tokens", 0)
                data["cache_write_tokens"] = usage.get("cache_creation_input_tokens", 0)

                if last_user:
                    last_asst_ts = last_assistant.get("timestamp", "")
                    last_user_ts = last_user.get("timestamp", "")
                    if last_user_ts > last_asst_ts:
                        user_msg = last_user.get("message", {})
                        if isinstance(user_msg, dict):
                            content = user_msg.get("content", [])
                            content_str = str(content) if isinstance(content, list) else str(content)
                        else:
                            content_str = str(user_msg)
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

        # Update token metrics
        metrics = list(self.query(MetricItem))
        for m in metrics:
            if m._metric_id == "input":
                m.update_value(self.format_tokens(data["total_input_tokens"]))
            elif m._metric_id == "output":
                m.update_value(self.format_tokens(data["total_output_tokens"]))
            elif m._metric_id == "cache-read":
                m.update_value(self.format_tokens(data["total_cache_read_tokens"]))
            elif m._metric_id == "cache-write":
                m.update_value(self.format_tokens(data["total_cache_write_tokens"]))
            elif m._metric_id == "total":
                m.update_value(self.format_tokens(total_tokens))
            elif m._metric_id == "cost":
                m.update_value(f"${cost:.4f}")
            elif m._metric_id == "messages":
                m.update_value(str(data["message_count"]))
            elif m._metric_id == "duration":
                m.update_value(self.format_duration(data))

        # Update context bar
        model = data.get("model", "default")
        context_size = CONTEXT_WINDOW.get(model, CONTEXT_WINDOW["default"])
        context_used = (
            data["input_tokens"] +
            data["cache_read_tokens"] +
            data["cache_write_tokens"] +
            data["pending_tokens"]
        )
        context_pct = min(100, (context_used / context_size) * 100)

        self.query_one("#context-label", Static).update(
            f"{self.format_tokens(context_used)} / {self.format_tokens(context_size)}"
        )
        self.query_one("#context-pct", Static).update(f"{context_pct:.0f}%")

        context_bar = self.query_one("#context-bar", ProgressBar)
        context_bar.update(progress=context_pct)

        # Update color based on usage
        context_panel = self.query_one("#context-panel")
        context_panel.remove_class("context-warning", "context-critical")
        if context_pct >= 90:
            context_panel.add_class("context-critical")
        elif context_pct >= 70:
            context_panel.add_class("context-warning")

        # Update info panel
        model_name = data["model"].replace("claude-", "").replace("-20251101", "").replace("-20250514", "")
        self.query_one("#model-info", Static).update(model_name)
        self.query_one("#project-info", Static).update(Path(self.project_path).name)
        self.query_one("#git-info", Static).update(data.get("git_branch") or self.get_git_branch())
        session_id = data['session_id'][:8] + "..." if data["session_id"] else "—"
        self.query_one("#session-id", Static).update(session_id)

        # Update status bar
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#status-bar", Static).update(f"Updated: {now}")

    def action_serena(self) -> None:
        """Open Serena dashboard in browser for current project."""
        import webbrowser
        import urllib.request

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
