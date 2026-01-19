#!/usr/bin/env python3
"""Workflow Chain System - Visual pipeline orchestrator for multi-project workflows."""

import asyncio
import subprocess
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import (
    Header, Footer, ListView, ListItem, Static, Label,
    Input, TextArea, ProgressBar, Button
)
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import Screen, ModalScreen
from textual.reactive import reactive
from textual.timer import Timer

from config_panel import get_textual_theme, get_footer_position, get_show_header
from workflow_models import (
    WorkflowChain, WorkflowNode, NodeStatus,
    STATUS_ICONS, STATUS_COLORS
)
from workflow_storage import (
    load_workflows, save_workflow, delete_workflow, get_workflow,
    create_workflow, duplicate_workflow, migrate_from_dependencies
)
from workflow_executor import WorkflowOrchestrator, TmuxExecutor, WorkflowLogger
from favorites import load_favorites

# Default directories to scan for projects
DEFAULT_ROOTS = [
    Path.home() / "personal",
    Path.home() / "work",
]


def get_project_directories(roots: list[Path] = None) -> list[Path]:
    """Get all project directories from root dirs."""
    if roots is None:
        roots = DEFAULT_ROOTS

    directories = []
    for root in roots:
        if root.exists() and root.is_dir():
            for item in sorted(root.iterdir()):
                if item.is_dir() and not item.name.startswith("."):
                    directories.append(item)
    return directories


def fuzzy_match(query: str, text: str) -> bool:
    """Simple fuzzy matching - all query chars must appear in order."""
    if not query:
        return True
    query = query.lower()
    text = text.lower()
    query_idx = 0
    for char in text:
        if char == query[query_idx]:
            query_idx += 1
            if query_idx == len(query):
                return True
    return False


# ---------------------------------------------------------------------------
# Custom Widgets
# ---------------------------------------------------------------------------

class WorkflowItem(ListItem):
    """List item for workflow display."""

    def __init__(self, workflow: WorkflowChain):
        super().__init__()
        self.workflow = workflow

    def compose(self) -> ComposeResult:
        completed, total = self.workflow.progress
        status = "✓" if self.workflow.is_complete() else f"{completed}/{total}"
        yield Static(f"  {self.workflow.name} [{status}]")


class NodeItem(ListItem):
    """List item for workflow node display."""

    def __init__(self, node: WorkflowNode, index: int):
        super().__init__()
        self.node = node
        self.index = index

    def compose(self) -> ComposeResult:
        icon = STATUS_ICONS.get(self.node.status, "?")
        duration = f" ({self.node.duration_str})" if self.node.duration_str else ""
        yield Static(f"  {self.index}. {icon} {self.node.project_name}{duration}")


class FavoriteItem(ListItem):
    """List item for favorite folder selection."""

    def __init__(self, path: str, show_parent: bool = True):
        super().__init__()
        self.path = path
        self.show_parent = show_parent

    def compose(self) -> ComposeResult:
        p = Path(self.path)
        name = p.name
        if self.show_parent:
            parent = p.parent.name
            yield Static(f"  📁 {parent}/{name}")
        else:
            yield Static(f"  📁 {name}")


# ---------------------------------------------------------------------------
# Chain Diagram Widget
# ---------------------------------------------------------------------------

class ChainDiagram(Static):
    """Visual representation of workflow chain."""

    def __init__(self, chain: WorkflowChain = None, **kwargs):
        super().__init__(**kwargs)
        self.chain = chain

    def update_chain(self, chain: WorkflowChain):
        self.chain = chain
        self.refresh_diagram()

    def refresh_diagram(self):
        if not self.chain or not self.chain.nodes:
            self.update("No nodes in chain")
            return

        lines = []
        
        for i, node in enumerate(self.chain.nodes):
            icon = STATUS_ICONS.get(node.status, "?")
            color = STATUS_COLORS.get(node.status, "white")
            name = node.project_name or "(no project)"
            status_text = node.status.value

            # Simple format: number, icon, name, status
            lines.append(f"[{color}]{i+1}. {icon} {name}[/]")
            lines.append(f"   Status: {status_text}")
            if node.duration_str:
                lines.append(f"   Duration: {node.duration_str}")
            
            # Arrow to next node
            if i < len(self.chain.nodes) - 1:
                lines.append("      ↓")

        self.update("\n".join(lines))


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------

class NewWorkflowDialog(ModalScreen):
    """Dialog for creating a new workflow."""

    CSS = """
    NewWorkflowDialog {
        align: center middle;
    }
    #new-dialog {
        width: 60;
        height: 12;
        border: round $primary;
        background: $background;
        padding: 1;
    }
    #name-input {
        margin: 1 0;
    }
    #buttons {
        margin-top: 1;
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-dialog"):
            yield Label("Create New Workflow")
            yield Input(placeholder="Workflow name...", id="name-input")
            with Horizontal(id="buttons"):
                yield Button("Create", variant="primary", id="create-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self):
        self.query_one("#name-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "create-btn":
            name = self.query_one("#name-input", Input).value.strip()
            if name:
                self.dismiss(name)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted):
        name = event.value.strip()
        self.dismiss(name if name else None)

    def action_cancel(self):
        self.dismiss(None)


class ConfirmDialog(ModalScreen):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmDialog {
        align: center middle;
    }
    #confirm-dialog {
        width: 50;
        height: 8;
        border: round $primary;
        background: $background;
        padding: 1;
    }
    #confirm-message {
        text-align: center;
        margin: 1;
    }
    #confirm-buttons {
        align: center middle;
    }
    """

    def __init__(self, title: str, message: str):
        super().__init__()
        self.title_text = title
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.title_text, id="confirm-title")
            yield Label(self.message, id="confirm-message")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes", variant="error", id="yes-btn")
                yield Button("No", variant="primary", id="no-btn")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes-btn")


DEFAULT_EXECUTION_FLOW_URL = "http://kubernetes.go.ro:3020/"


class ImportFromUrlDialog(ModalScreen):
    """Dialog for importing workflow from Execution Flow URL."""

    CSS = """
    ImportFromUrlDialog {
        align: center middle;
    }
    #import-dialog {
        width: 80;
        height: 12;
        border: round $primary;
        background: $background;
        padding: 1;
    }
    #url-input {
        margin: 1 0;
    }
    #import-buttons {
        margin-top: 1;
        align: center middle;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="import-dialog"):
            yield Label("Import from Execution Flow")
            yield Input(value=DEFAULT_EXECUTION_FLOW_URL, placeholder="URL...", id="url-input")
            with Horizontal(id="import-buttons"):
                yield Button("Import", variant="primary", id="import-btn")
                yield Button("Cancel", id="cancel-btn")

    def on_mount(self):
        inp = self.query_one("#url-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "import-btn":
            url = self.query_one("#url-input", Input).value.strip()
            if url:
                self.dismiss(url)
            else:
                self.dismiss(None)
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted):
        url = event.value.strip()
        self.dismiss(url if url else None)

    def action_cancel(self):
        self.dismiss(None)


class FzfDirectoryDialog(ModalScreen):
    """FZF-style directory picker dialog."""

    CSS = """
    FzfDirectoryDialog {
        align: center middle;
    }
    #fzf-dialog {
        width: 80%;
        height: 80%;
        border: round $primary;
        background: $background;
        padding: 1;
    }
    #fzf-title {
        height: 1;
        text-style: bold;
        margin-bottom: 1;
    }
    #fzf-input {
        height: 3;
        border: round $primary;
        margin-bottom: 1;
    }
    #fzf-count {
        height: 1;
        color: $text-muted;
        text-align: right;
    }
    #fzf-list {
        height: 1fr;
        background: $background;
        scrollbar-size: 1 1;
    }
    #fzf-help {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    ListItem {
        padding: 0 1;
        height: 1;
    }
    ListItem:hover {
        background: $primary 20%;
    }
    ListItem.-highlight {
        background: $primary 40%;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, exclude_paths: set[str] = None):
        super().__init__()
        self.exclude_paths = exclude_paths or set()
        self.all_directories: list[Path] = []
        self.filtered_directories: list[Path] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="fzf-dialog"):
            yield Label("📂 Select Directory (fzf)", id="fzf-title")
            yield Input(placeholder="Type to filter...", id="fzf-input")
            yield Static("", id="fzf-count")
            yield ListView(id="fzf-list")
            yield Static("Enter: Select  |  Esc: Cancel  |  ↑↓: Navigate", id="fzf-help")

    def on_mount(self):
        self.all_directories = get_project_directories()
        self.refresh_list()
        self.query_one("#fzf-input", Input).focus()

    def refresh_list(self, filter_text: str = ""):
        """Refresh directory list with filter."""
        if filter_text:
            self.filtered_directories = [
                d for d in self.all_directories
                if fuzzy_match(filter_text, d.name) or fuzzy_match(filter_text, f"{d.parent.name}/{d.name}")
            ]
        else:
            self.filtered_directories = self.all_directories.copy()

        # Exclude already-added paths
        self.filtered_directories = [
            d for d in self.filtered_directories
            if str(d) not in self.exclude_paths
        ]

        fzf_list = self.query_one("#fzf-list", ListView)
        fzf_list.clear()
        for directory in self.filtered_directories:
            fzf_list.append(FavoriteItem(str(directory), show_parent=True))

        # Update count
        shown = len(self.filtered_directories)
        total = len(self.all_directories)
        self.query_one("#fzf-count", Static).update(f"{shown}/{total} directories")

        # Auto-highlight first item
        if fzf_list.children:
            fzf_list.index = 0

    def on_input_changed(self, event: Input.Changed):
        self.refresh_list(event.value)

    def on_input_submitted(self, event: Input.Submitted):
        # Select highlighted item
        fzf_list = self.query_one("#fzf-list", ListView)
        if fzf_list.highlighted_child:
            item = fzf_list.highlighted_child
            if isinstance(item, FavoriteItem):
                self.dismiss(item.path)
        else:
            self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected):
        item = event.item
        if isinstance(item, FavoriteItem):
            self.dismiss(item.path)

    def action_cancel(self):
        self.dismiss(None)


class WorkflowEditorScreen(Screen):
    """Simple workflow editor screen."""

    CSS = """
    #editor {
        padding: 1 2;
    }
    .field-label {
        height: 1;
        color: $text-muted;
        margin-top: 1;
    }
    .field-label:first-child {
        margin-top: 0;
    }
    #name-input {
        height: 1;
        background: $surface;
        border: none;
    }
    #context-input {
        height: 3;
        background: $surface;
        border: none;
    }
    #node-list {
        height: 8;
        background: $surface;
        border: none;
    }
    #prompt-input {
        height: 1;
        background: $surface;
        border: none;
    }
    Input:focus, TextArea:focus, ListView:focus {
        background: $primary 15%;
    }
    """

    BINDINGS = [
        ("ctrl+j", "save", "Save"),
        ("escape", "quit", "Cancel"),
        ("a", "add_node", "Add Node"),
        ("d", "delete_node", "Delete"),
        ("tab", "next_field", "Next"),
        ("shift+tab", "prev_field", "Prev"),
    ]

    def __init__(self, workflow: WorkflowChain):
        super().__init__()
        self.workflow = workflow
        self.selected_node: WorkflowNode = None
        self.fields = ["name-input", "context-input", "node-list", "prompt-input"]
        self.field_idx = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="editor"):
            yield Label("NAME", classes="field-label")
            yield Input(value=self.workflow.name, id="name-input")

            yield Label("CONTEXT", classes="field-label")
            yield TextArea(self.workflow.global_context, id="context-input")

            yield Label("NODES (a:add, d:delete)", classes="field-label")
            yield ListView(id="node-list")

            yield Label("NODE PROMPT", classes="field-label")
            yield Input(placeholder="Enter prompt for selected node...", id="prompt-input")
        yield Footer()

    def on_mount(self):
        self.title = f"Edit: {self.workflow.name or 'New Workflow'}"
        self.refresh_nodes()
        self.query_one("#name-input").focus()

    def refresh_nodes(self):
        node_list = self.query_one("#node-list", ListView)
        node_list.clear()
        for i, node in enumerate(self.workflow.nodes):
            node_list.append(NodeItem(node, i + 1))

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.item and isinstance(event.item, NodeItem):
            self.selected_node = event.item.node
            self.query_one("#prompt-input", Input).value = self.selected_node.prompt_template or ""

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "prompt-input" and self.selected_node:
            self.selected_node.prompt_template = event.value

    def action_next_field(self):
        self.field_idx = (self.field_idx + 1) % len(self.fields)
        self.query_one(f"#{self.fields[self.field_idx]}").focus()

    def action_prev_field(self):
        self.field_idx = (self.field_idx - 1) % len(self.fields)
        self.query_one(f"#{self.fields[self.field_idx]}").focus()

    def action_add_node(self):
        exclude = {n.project_path for n in self.workflow.nodes}

        def on_select(path: str | None):
            if path:
                depends = [self.workflow.nodes[-1].id] if self.workflow.nodes else []
                self.workflow.add_node(path, depends_on=depends)
                self.refresh_nodes()

        self.app.push_screen(FzfDirectoryDialog(exclude), on_select)

    def action_delete_node(self):
        if self.selected_node:
            self.workflow.remove_node(self.selected_node.id)
            self.selected_node = None
            self.query_one("#prompt-input", Input).value = ""
            self.refresh_nodes()

    def action_save(self):
        self.workflow.name = self.query_one("#name-input", Input).value
        self.workflow.global_context = self.query_one("#context-input", TextArea).text
        save_workflow(self.workflow)
        self.app.pop_screen()

    def action_quit(self):
        self.app.pop_screen()


class ExecutionScreen(Screen):
    """Real-time workflow execution monitoring screen."""

    CSS = """
    #exec-header {
        height: 3;
        padding: 0 2;
        background: $surface;
    }
    #exec-title {
        text-style: bold;
    }
    #exec-status {
        color: $text-muted;
    }
    #exec-container {
        height: 1fr;
        padding: 1;
    }
    .node-box {
        border: round $border;
        padding: 1;
        margin: 1 0;
        height: auto;
    }
    .node-box.running {
        border: round blue;
    }
    .node-box.completed {
        border: round green;
    }
    .node-box.failed {
        border: round red;
    }
    #output-preview {
        height: 6;
        background: $surface;
        padding: 1;
        margin-top: 1;
    }
    #progress-container {
        height: 3;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("s", "stop", "Stop"),
        ("p", "pause", "Pause/Resume"),
        ("f", "focus_running", "Focus"),
        ("escape", "back", "Back"),
        ("q", "back", "Back"),
    ]

    def __init__(self, workflow: WorkflowChain):
        super().__init__()
        self.workflow = workflow
        self.orchestrator: WorkflowOrchestrator = None
        self.refresh_timer: Timer = None

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=False)

        with Vertical(id="exec-header"):
            yield Label(f"Chain: {self.workflow.name}", id="exec-title")
            yield Label("Status: Starting...", id="exec-status")

        yield ScrollableContainer(id="exec-container")

        with Horizontal(id="progress-container"):
            yield ProgressBar(id="progress", total=len(self.workflow.nodes))

        yield Footer()

    def on_mount(self):
        self.title = "Workflow Execution"
        self.refresh_display()

        # Start orchestrator (no callback - timer handles UI refresh)
        self.orchestrator = WorkflowOrchestrator(
            self.workflow,
            on_status_change=lambda: None  # Timer handles refresh
        )

        # Start execution using Textual's worker system
        self.run_worker(self.orchestrator.run(), exclusive=True)

        # Start refresh timer
        self.refresh_timer = self.set_interval(1.0, self.safe_refresh)

    def on_worker_state_changed(self, event):
        """Handle worker state changes to catch errors."""
        from textual.worker import WorkerState
        if event.state == WorkerState.ERROR:
            # Log the error
            if self.orchestrator:
                self.orchestrator.log.error(f"Worker error: {event.worker.error}")
            self.notify(f"Workflow error: {event.worker.error}", severity="error")
        elif event.state == WorkerState.CANCELLED:
            if self.orchestrator:
                self.orchestrator.log.warning("Worker cancelled")

    def safe_refresh(self):
        """Refresh display - called by timer and status changes."""
        try:
            self.refresh_display()
        except Exception:
            pass  # Ignore errors during refresh

    def refresh_display(self):
        """Update the execution display."""
        container = self.query_one("#exec-container", ScrollableContainer)
        container.remove_children()

        # Update status
        status_label = self.query_one("#exec-status", Label)
        running = len(self.workflow.get_running_nodes())
        completed, total = self.workflow.progress

        if self.workflow.is_complete():
            if self.workflow.has_failed():
                status_label.update("Status: Completed with errors")
            else:
                status_label.update("Status: Completed successfully")
        elif self.orchestrator and self.orchestrator.is_paused:
            status_label.update("Status: Paused")
        else:
            status_label.update(f"Status: Running ({running} active, {completed}/{total} done)")

        # Update progress bar
        progress = self.query_one("#progress", ProgressBar)
        progress.update(progress=completed)

        # Build node displays as text (uses dedicated claude-code session)
        executor = TmuxExecutor()
        for i, node in enumerate(self.workflow.nodes):
            icon = STATUS_ICONS.get(node.status, "?")
            color = STATUS_COLORS.get(node.status, "white")
            duration = f" ({node.duration_str})" if node.duration_str else ""
            pane_info = f" [tmux: {node.tmux_pane}]" if node.tmux_pane and node.status == NodeStatus.RUNNING else ""

            # Build node content as text
            lines = [f"[{color}]{i+1}. {icon} {node.project_name}{duration}{pane_info}[/]"]

            if node.prompt_template:
                prompt_preview = node.prompt_template[:80] + "..." if len(node.prompt_template) > 80 else node.prompt_template
                lines.append(f"   Prompt: {prompt_preview}")

            if node.status == NodeStatus.RUNNING and node.tmux_pane:
                # Show live output tail
                output = executor.capture_pane_output(node.tmux_pane, 5)
                if output.strip():
                    output_lines = output.strip().split("\n")[-3:]
                    lines.append("   " + "\n   ".join(output_lines))

            if node.error_message:
                lines.append(f"   [red]Error: {node.error_message}[/]")

            # Create a simple Static widget with the content
            node_widget = Static("\n".join(lines), classes=f"node-box {node.status.value}")
            container.mount(node_widget)

    def action_stop(self):
        if self.orchestrator:
            self.orchestrator.stop()
            self.refresh_display()

    def action_pause(self):
        if self.orchestrator:
            if self.orchestrator.is_paused:
                self.orchestrator.resume()
            else:
                self.orchestrator.pause()
            self.refresh_display()

    def action_focus_running(self):
        """Jump to tmux window of running node in claude-code session."""
        executor = TmuxExecutor()
        for node in self.workflow.get_running_nodes():
            if node.tmux_pane:
                window_name = f"wf-{node.id}"
                executor.focus_window(window_name)
                break

    def action_back(self):
        if self.refresh_timer:
            self.refresh_timer.stop()
        self.app.pop_screen()


class LogViewerScreen(Screen):
    """Screen to view workflow execution logs and tmux pane output."""

    CSS = """
    #log-viewer-main {
        height: 1fr;
        padding: 1;
    }
    .log-panel {
        width: 50%;
        height: 100%;
        border: round $border;
        margin: 0 1;
    }
    .log-panel:focus-within {
        border: round $primary;
    }
    .panel-content {
        height: 1fr;
        padding: 1;
        overflow-y: auto;
    }
    #log-header {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    #node-selector {
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("c", "clear", "Clear Logs"),
        ("y", "copy_logs", "Copy Logs"),
        ("left", "prev_node", "Prev Node"),
        ("right", "next_node", "Next Node"),
        ("f", "focus_pane", "Focus Pane"),
        ("escape", "back", "Back"),
        ("q", "back", "Back"),
    ]

    def __init__(self, workflow: WorkflowChain):
        super().__init__()
        self.workflow = workflow
        self.refresh_timer: Timer | None = None
        self.selected_node_idx = 0

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=False)

        yield Label(f"Logs: {self.workflow.name}", id="log-header")
        yield Static("", id="node-selector")

        with Horizontal(id="log-viewer-main"):
            with Vertical(classes="log-panel"):
                yield Label("Workflow Logs")
                with ScrollableContainer(classes="panel-content"):
                    yield Static("Loading...", id="log-content")

            with Vertical(classes="log-panel"):
                yield Label("Tmux Pane Preview", id="pane-label")
                with ScrollableContainer(classes="panel-content"):
                    yield Static("No pane active", id="pane-content")

        yield Footer()

    def on_mount(self):
        self.title = f"Logs - {self.workflow.name}"
        self.refresh_all()
        self.update_node_selector()
        # Auto-refresh every 2 seconds
        self.refresh_timer = self.set_interval(2, self.refresh_all)

    def get_nodes_with_panes(self) -> list:
        """Get nodes that have tmux panes assigned."""
        return [n for n in self.workflow.nodes if n.tmux_pane]

    def get_current_node(self):
        """Get the currently selected node."""
        nodes = self.get_nodes_with_panes()
        if nodes and 0 <= self.selected_node_idx < len(nodes):
            return nodes[self.selected_node_idx]
        # Fallback to any node if no panes
        if self.workflow.nodes:
            return self.workflow.nodes[min(self.selected_node_idx, len(self.workflow.nodes) - 1)]
        return None

    def update_node_selector(self):
        """Update the node selector display."""
        nodes = self.get_nodes_with_panes()
        selector = self.query_one("#node-selector", Static)
        
        if not nodes:
            selector.update("No active nodes (←/→ to switch nodes when running)")
            return
            
        node = self.get_current_node()
        if node:
            project_name = Path(node.project_path).name
            status = node.status
            selector.update(f"Node {self.selected_node_idx + 1}/{len(nodes)}: {project_name} [{status}] (←/→ to switch)")

    def capture_tmux_pane(self, pane_id: str, lines: int = 50) -> str:
        """Capture content from a tmux pane."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout.rstrip() or "(empty pane)"
            return f"Error: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "(timeout capturing pane)"
        except FileNotFoundError:
            return "(tmux not found)"
        except Exception as e:
            return f"(error: {e})"

    def refresh_all(self):
        """Refresh both log and pane content."""
        self.refresh_log()
        self.refresh_pane()

    def refresh_log(self):
        """Refresh log content from file."""
        log_content = WorkflowLogger.read_log(self.workflow.id, tail_lines=200)
        content_widget = self.query_one("#log-content", Static)
        content_widget.update(log_content)

    def refresh_pane(self):
        """Refresh tmux pane preview."""
        node = self.get_current_node()
        pane_widget = self.query_one("#pane-content", Static)
        pane_label = self.query_one("#pane-label", Label)
        
        if node and node.tmux_pane:
            project_name = Path(node.project_path).name
            pane_label.update(f"Tmux Pane: {project_name} ({node.tmux_pane})")
            content = self.capture_tmux_pane(node.tmux_pane)
            pane_widget.update(content)
        else:
            pane_label.update("Tmux Pane Preview")
            if node:
                pane_widget.update(f"Node '{Path(node.project_path).name}' has no active pane")
            else:
                pane_widget.update("No nodes in workflow")

    def action_refresh(self):
        self.refresh_all()

    def action_clear(self):
        """Clear the log file."""
        log_path = WorkflowLogger.get_log_path(self.workflow.id)
        if log_path.exists():
            log_path.write_text("")
        self.refresh_log()

    def action_copy_logs(self):
        """Copy workflow logs to clipboard."""
        log_content = WorkflowLogger.read_log(self.workflow.id, tail_lines=500)
        if log_content:
            try:
                subprocess.run(
                    ["pbcopy"],
                    input=log_content.encode(),
                    check=True,
                    timeout=2
                )
                self.notify("Logs copied to clipboard")
            except Exception as e:
                self.notify(f"Failed to copy: {e}", severity="error")
        else:
            self.notify("No logs to copy", severity="warning")

    def action_prev_node(self):
        """Select previous node."""
        nodes = self.get_nodes_with_panes() or self.workflow.nodes
        if nodes:
            self.selected_node_idx = (self.selected_node_idx - 1) % len(nodes)
            self.update_node_selector()
            self.refresh_pane()

    def action_next_node(self):
        """Select next node."""
        nodes = self.get_nodes_with_panes() or self.workflow.nodes
        if nodes:
            self.selected_node_idx = (self.selected_node_idx + 1) % len(nodes)
            self.update_node_selector()
            self.refresh_pane()

    def action_focus_pane(self):
        """Switch to the tmux pane in terminal."""
        node = self.get_current_node()
        if node and node.tmux_pane:
            try:
                subprocess.run(
                    ["tmux", "select-pane", "-t", node.tmux_pane],
                    capture_output=True,
                    timeout=2
                )
            except Exception:
                pass

    def action_back(self):
        if self.refresh_timer:
            self.refresh_timer.stop()
        self.app.pop_screen()


class WorkflowListScreen(Screen):
    """Main screen showing saved workflows."""

    CSS = """
    #wf-main {
        height: 1fr;
        padding: 1;
    }
    .wf-panel {
        width: 50%;
        height: 100%;
        border: round $border;
        margin: 0 1;
    }
    .wf-panel:focus-within {
        border: round $primary;
    }
    #workflow-list {
        height: 1fr;
    }
    #chain-preview {
        height: 1fr;
        padding: 1;
    }
    #info-bar {
        height: 1;
        padding: 0 2;
        background: $surface;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("n", "new_workflow", "New"),
        ("i", "import_from_url", "Import"),
        ("r", "run_workflow", "Run"),
        ("e", "edit_workflow", "Edit"),
        ("l", "view_logs", "Logs"),
        ("d", "delete_workflow", "Delete"),
        ("c", "duplicate_workflow", "Duplicate"),
        ("m", "migrate", "Migrate"),
        ("tab", "toggle_focus", "Switch"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.workflows: dict[str, WorkflowChain] = {}
        self.favorites = load_favorites()

    def compose(self) -> ComposeResult:
        if get_show_header():
            yield Header(show_clock=False)

        with Horizontal(id="wf-main"):
            with Vertical(classes="wf-panel"):
                yield Label("Saved Workflows")
                yield ListView(id="workflow-list")

            with Vertical(classes="wf-panel"):
                yield Label("Chain Preview")
                yield ChainDiagram(id="chain-preview")

        yield Static("", id="info-bar")
        yield Footer()

    def on_mount(self):
        self.title = "Workflow Chains"
        self.refresh_workflows()
        self.query_one("#workflow-list", ListView).focus()

    def on_screen_resume(self):
        """Refresh workflows when returning from editor screen."""
        self.refresh_workflows()

    def refresh_workflows(self):
        self.workflows = load_workflows()
        wf_list = self.query_one("#workflow-list", ListView)
        wf_list.clear()

        for wf in sorted(self.workflows.values(), key=lambda w: w.updated_at, reverse=True):
            wf_list.append(WorkflowItem(wf))

        # Auto-select first workflow after refresh completes
        if wf_list.children:
            self.call_later(self._select_first_workflow)
        
        if not self.workflows:
            info = self.query_one("#info-bar", Static)
            info.update("No workflows. Press 'n' to create or 'm' to migrate from dependencies.")

    def _select_first_workflow(self):
        """Update preview with first workflow without manipulating ListView."""
        if self.workflows:
            # Get first workflow (most recently updated)
            first_wf = sorted(self.workflows.values(), key=lambda w: w.updated_at, reverse=True)[0]
            diagram = self.query_one("#chain-preview", ChainDiagram)
            diagram.update_chain(first_wf)
            info = self.query_one("#info-bar", Static)
            info.update(f"{len(first_wf.nodes)} nodes | Created: {first_wf.created_at[:10]} | Updated: {first_wf.updated_at[:10]}")

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.item and isinstance(event.item, WorkflowItem):
            diagram = self.query_one("#chain-preview", ChainDiagram)
            diagram.update_chain(event.item.workflow)

            info = self.query_one("#info-bar", Static)
            wf = event.item.workflow
            info.update(f"{len(wf.nodes)} nodes | Created: {wf.created_at[:10]} | Updated: {wf.updated_at[:10]}")

    def get_selected_workflow(self) -> WorkflowChain | None:
        wf_list = self.query_one("#workflow-list", ListView)
        if wf_list.highlighted_child and isinstance(wf_list.highlighted_child, WorkflowItem):
            return wf_list.highlighted_child.workflow
        return None

    def action_new_workflow(self):
        def handle_result(name: str | None):
            if name:
                workflow = create_workflow(name)
                self.refresh_workflows()
                # Open editor
                self.app.push_screen(WorkflowEditorScreen(workflow))

        self.app.push_screen(NewWorkflowDialog(), handle_result)

    def action_import_from_url(self):
        """Import workflow from Execution Flow URL."""
        def handle_result(url: str | None):
            if url:
                info = self.query_one("#info-bar", Static)
                info.update(f"Importing from {url}...")
                try:
                    import urllib.request
                    import json as json_mod
                    with urllib.request.urlopen(url, timeout=10) as response:
                        data = json_mod.loads(response.read().decode())
                    workflow = WorkflowChain.from_dict(data)
                    workflow.id = str(__import__("uuid").uuid4())[:8]
                    save_workflow(workflow)
                    self.refresh_workflows()
                    info.update(f"Imported: {workflow.name}")
                except Exception as e:
                    info.update(f"Import failed: {e}")

        self.app.push_screen(ImportFromUrlDialog(), handle_result)

    def action_edit_workflow(self):
        workflow = self.get_selected_workflow()
        if workflow:
            self.app.push_screen(WorkflowEditorScreen(workflow))

    def action_run_workflow(self):
        workflow = self.get_selected_workflow()
        info = self.query_one("#info-bar", Static)
        
        if not workflow:
            info.update("No workflow selected. Select one first.")
            return
            
        if not workflow.nodes:
            info.update("Cannot run: workflow has no nodes. Press 'e' to edit.")
            return

        # Reset workflow before running
        info.update(f"Starting workflow: {workflow.name}...")
        workflow.reset()
        save_workflow(workflow)
        self.app.push_screen(ExecutionScreen(workflow))

    def action_delete_workflow(self):
        workflow = self.get_selected_workflow()
        if workflow:
            def handle_confirm(confirmed: bool):
                if confirmed:
                    delete_workflow(workflow.id)
                    self.refresh_workflows()

            self.app.push_screen(
                ConfirmDialog("Delete Workflow", f"Delete '{workflow.name}'?"),
                handle_confirm
            )

    def action_duplicate_workflow(self):
        workflow = self.get_selected_workflow()
        if workflow:
            duplicate_workflow(workflow.id)
            self.refresh_workflows()
            info = self.query_one("#info-bar", Static)
            info.update(f"Duplicated: {workflow.name}")

    def action_migrate(self):
        """Migrate existing dependency chains to workflows."""
        count = migrate_from_dependencies()
        self.refresh_workflows()
        info = self.query_one("#info-bar", Static)
        if count:
            info.update(f"Migrated {count} dependency chains to workflows")
        else:
            info.update("No dependency chains to migrate")

    def action_toggle_focus(self):
        wf_list = self.query_one("#workflow-list", ListView)
        wf_list.focus()

    def action_view_logs(self):
        """View logs for the selected workflow."""
        workflow = self.get_selected_workflow()
        if workflow:
            self.app.push_screen(LogViewerScreen(workflow))
        else:
            info = self.query_one("#info-bar", Static)
            info.update("No workflow selected. Select one to view logs.")

    def action_quit(self):
        self.app.exit()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class WorkflowChainApp(App):
    """Workflow Chain System - Visual pipeline orchestrator."""

    def __init__(self):
        footer_pos = get_footer_position()
        self.CSS = f"""
        Screen {{
            background: $background;
        }}
        * {{
            scrollbar-size: 1 1;
        }}
        Footer {{
            dock: {footer_pos};
        }}
        """
        super().__init__()
        self.theme = get_textual_theme()

    def on_mount(self):
        self.push_screen(WorkflowListScreen())


def main():
    app = WorkflowChainApp()
    app.run()


if __name__ == "__main__":
    main()
