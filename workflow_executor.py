"""Workflow execution engine with tmux integration."""

import subprocess
import asyncio
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from workflow_models import WorkflowChain, WorkflowNode, NodeStatus
from workflow_storage import save_workflow, set_active_workflow, add_execution_history


class TmuxExecutor:
    """Manages workflow execution via dedicated 'claude-code' tmux session."""

    SESSION_NAME = "claude-code"

    def __init__(self):
        self.session = self.SESSION_NAME
        self.active_panes: dict[str, str] = {}  # node_id -> pane_id
        self._ensure_session_exists()

    def _ensure_session_exists(self):
        """Create the claude-code session if it doesn't exist."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            # Session doesn't exist, create it detached
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", self.session],
                capture_output=True, text=True
            )

    def _run_tmux(self, *args) -> subprocess.CompletedProcess:
        """Run a tmux command."""
        return subprocess.run(
            ["tmux"] + list(args),
            capture_output=True, text=True
        )

    def create_workflow_window(self, node: WorkflowNode) -> str:
        """Create or reuse a tmux window for workflow node execution."""
        window_name = f"wf-{node.id}"
        window_target = f"{self.session}:{window_name}"

        # Check if window already exists
        result = self._run_tmux("list-windows", "-t", self.session, "-F", "#{window_name}")
        existing_windows = result.stdout.strip().split("\n") if result.stdout.strip() else []

        if window_name in existing_windows:
            # Window exists - get its pane ID and reset it
            result = self._run_tmux(
                "list-panes", "-t", window_target,
                "-F", "#{pane_id}"
            )
            pane_id = result.stdout.strip().split("\n")[0] if result.stdout.strip() else ""
            
            if pane_id:
                # Send Ctrl+C to stop any running process, then clear
                self._run_tmux("send-keys", "-t", pane_id, "C-c")
                import time
                time.sleep(0.2)
                self._run_tmux("send-keys", "-t", pane_id, "C-c")
                time.sleep(0.2)
                # Change to the project directory
                self.send_text(pane_id, f"cd '{node.project_path}'")
                self.send_enter(pane_id)
                time.sleep(0.1)
                self._run_tmux("send-keys", "-t", pane_id, "clear", "Enter")
                time.sleep(0.1)
                
                self.active_panes[node.id] = pane_id
                return pane_id
        
        # Window doesn't exist - create new one
        result = self._run_tmux(
            "new-window", "-t", self.session,
            "-n", window_name,
            "-c", node.project_path,
            "-P", "-F", "#{pane_id}"
        )
        pane_id = result.stdout.strip()

        if pane_id:
            self.active_panes[node.id] = pane_id

        return pane_id

    def send_keys(self, pane_id: str, *keys):
        """Send keys to a tmux pane."""
        self._run_tmux("send-keys", "-t", pane_id, *keys)

    def send_text(self, pane_id: str, text: str):
        """Send literal text to a tmux pane."""
        # Use -l for literal text to avoid interpreting special chars
        self._run_tmux("send-keys", "-t", pane_id, "-l", text)

    def send_enter(self, pane_id: str):
        """Send Enter key to a tmux pane."""
        self._run_tmux("send-keys", "-t", pane_id, "Enter")

    def send_prompt_to_claude(self, pane_id: str, prompt: str):
        """Start claude and send a prompt."""
        import time
        
        # Method 1: Send claude command with prompt as heredoc
        # This is more reliable for multi-line prompts
        
        # Escape any single quotes in the prompt
        escaped_prompt = prompt.replace("'", "'\"'\"'")
        
        # Build command: claude 'prompt text'
        command = f"claude '{escaped_prompt}'"
        
        # Send the command
        self.send_text(pane_id, command)
        time.sleep(0.1)
        self.send_enter(pane_id)

    def capture_pane_output(self, pane_id: str, lines: int = 100) -> str:
        """Capture recent output from a pane."""
        result = self._run_tmux(
            "capture-pane", "-t", pane_id, "-p", "-S", f"-{lines}"
        )
        return result.stdout

    def get_pane_info(self, pane_id: str) -> dict:
        """Get detailed pane information."""
        result = self._run_tmux(
            "display-message", "-t", pane_id, "-p",
            "#{pane_pid}:#{pane_current_command}:#{window_name}"
        )
        parts = result.stdout.strip().split(":")
        if len(parts) >= 3:
            return {
                "pid": parts[0],
                "command": parts[1],
                "window_name": parts[2],
            }
        return {}

    def is_pane_idle(self, pane_id: str) -> bool:
        """Check if pane is back at shell prompt (command finished)."""
        info = self.get_pane_info(pane_id)
        command = info.get("command", "")
        return command in ("zsh", "bash", "fish", "-zsh", "-bash")

    def kill_window(self, window_name: str):
        """Kill a workflow window."""
        self._run_tmux("kill-window", "-t", f"{self.session}:{window_name}")

    def cleanup_old_windows(self, keep_node_ids: set[str] = None):
        """Remove workflow windows not in the keep list."""
        keep_node_ids = keep_node_ids or set()
        windows = self.list_workflow_windows()
        
        for window in windows:
            if window["node_id"] not in keep_node_ids:
                self.kill_window(window["name"])

    def list_workflow_windows(self) -> list[dict]:
        """List all workflow-related windows in claude-code session."""
        result = self._run_tmux(
            "list-windows", "-t", self.session,
            "-F", "#{window_name}:#{window_index}:#{pane_id}"
        )
        windows = []
        for line in result.stdout.strip().split("\n"):
            if line.startswith("wf-"):
                parts = line.split(":")
                if len(parts) >= 3:
                    windows.append({
                        "name": parts[0],
                        "index": parts[1],
                        "pane_id": parts[2],
                        "node_id": parts[0].replace("wf-", ""),
                    })
        return windows

    def focus_window(self, window_name: str):
        """Switch to a workflow window in claude-code session."""
        self._run_tmux("select-window", "-t", f"{self.session}:{window_name}")


class WorkflowOrchestrator:
    """Orchestrates workflow chain execution."""

    # Markers that indicate Claude session has ended
    COMPLETION_MARKERS = [
        "Session ended",
        "Goodbye!",
        "claude>",  # Back at prompt
        "❯",        # zsh prompt
        "$ ",       # bash prompt
    ]

    def __init__(self, chain: WorkflowChain, on_status_change: Callable = None):
        self.chain = chain
        self.executor = TmuxExecutor()  # Always uses claude-code session
        self.accumulated_context = chain.global_context
        self.on_status_change = on_status_change or (lambda: None)
        self._running = False
        self._paused = False

    def _build_prompt(self, node: WorkflowNode) -> str:
        """Build full prompt for a node."""
        parts = []

        # Global context
        if self.chain.global_context:
            parts.append(f"## Global Context\n{self.chain.global_context}")

        # Accumulated output from previous nodes
        if self.chain.propagate_output and self.accumulated_context != self.chain.global_context:
            parts.append(f"## Context from Previous Steps\n{self.accumulated_context}")

        # Node-specific prompt
        if node.prompt_template:
            parts.append(f"## Task\n{node.prompt_template}")

        # Context files
        if node.context_files:
            files_section = "## Relevant Files\n" + "\n".join(f"- {f}" for f in node.context_files)
            parts.append(files_section)

        # If no prompt parts, create a default prompt
        if not parts:
            parts.append(f"Work on the project at: {node.project_path}")

        return "\n\n".join(parts)

    def _check_node_completion(self, node: WorkflowNode) -> bool:
        """Check if a node has completed."""
        if not node.tmux_pane:
            return False

        # Check if shell is idle (command finished)
        if self.executor.is_pane_idle(node.tmux_pane):
            return True

        # Also check output for completion markers
        output = self.executor.capture_pane_output(node.tmux_pane, 20)
        return any(marker in output for marker in self.COMPLETION_MARKERS)

    def execute_node(self, node: WorkflowNode):
        """Execute a single workflow node."""
        # Create window in claude-code session
        pane_id = self.executor.create_workflow_window(node)
        if not pane_id:
            node.status = NodeStatus.FAILED
            node.error_message = "Failed to create tmux window"
            return

        node.tmux_pane = pane_id
        node.status = NodeStatus.RUNNING
        node.started_at = datetime.now().isoformat()

        # Build the prompt
        prompt = self._build_prompt(node)

        # Send prompt to claude using tmux send-keys
        self.executor.send_prompt_to_claude(pane_id, prompt)

        self.on_status_change()
        save_workflow(self.chain)

    def complete_node(self, node: WorkflowNode, success: bool = True):
        """Mark a node as completed."""
        node.completed_at = datetime.now().isoformat()

        if success:
            node.status = NodeStatus.COMPLETED
            # Capture output for context propagation
            if node.tmux_pane:
                node.output = self.executor.capture_pane_output(node.tmux_pane)
                if self.chain.propagate_output:
                    self.accumulated_context += f"\n\n## Output from {node.project_name}:\n{node.output[-2000:]}"
        else:
            node.status = NodeStatus.FAILED

        self.on_status_change()
        save_workflow(self.chain)

    async def run(self):
        """Execute the workflow chain asynchronously."""
        self._running = True
        set_active_workflow(self.chain.id)
        start_time = datetime.now()

        # Clean up old windows, keep only current workflow's nodes
        current_node_ids = {node.id for node in self.chain.nodes}
        self.executor.cleanup_old_windows(keep_node_ids=current_node_ids)

        try:
            while self._running and not self.chain.is_complete():
                if self._paused:
                    await asyncio.sleep(1)
                    continue

                # Start runnable nodes
                runnable = self.chain.get_runnable_nodes()
                for node in runnable:
                    self.execute_node(node)

                # Check running nodes for completion
                for node in self.chain.get_running_nodes():
                    if self._check_node_completion(node):
                        # Check output for errors
                        output = self.executor.capture_pane_output(node.tmux_pane, 50)
                        success = "error" not in output.lower() or "fixed" in output.lower()
                        self.complete_node(node, success)

                await asyncio.sleep(2)  # Poll interval

        finally:
            self._running = False
            set_active_workflow(None)

            # Record execution
            duration = (datetime.now() - start_time).total_seconds()
            status = "completed" if self.chain.is_complete() and not self.chain.has_failed() else "failed"
            add_execution_history(self.chain.id, status, duration)

    def run_sync(self):
        """Run workflow synchronously (blocking)."""
        asyncio.run(self.run())

    def stop(self):
        """Stop workflow execution."""
        self._running = False
        # Mark running nodes as failed
        for node in self.chain.get_running_nodes():
            node.status = NodeStatus.FAILED
            node.error_message = "Stopped by user"
            node.completed_at = datetime.now().isoformat()
        save_workflow(self.chain)
        self.on_status_change()

    def pause(self):
        """Pause workflow execution."""
        self._paused = True
        for node in self.chain.get_running_nodes():
            node.status = NodeStatus.PAUSED
        save_workflow(self.chain)
        self.on_status_change()

    def resume(self):
        """Resume paused workflow."""
        self._paused = False
        for node in self.chain.nodes:
            if node.status == NodeStatus.PAUSED:
                node.status = NodeStatus.RUNNING
        save_workflow(self.chain)
        self.on_status_change()

    def skip_node(self, node_id: str):
        """Skip a pending node."""
        node = self.chain.get_node_by_id(node_id)
        if node and node.status == NodeStatus.PENDING:
            node.status = NodeStatus.SKIPPED
            node.completed_at = datetime.now().isoformat()
            save_workflow(self.chain)
            self.on_status_change()

    def retry_node(self, node_id: str):
        """Retry a failed node."""
        node = self.chain.get_node_by_id(node_id)
        if node and node.status in (NodeStatus.FAILED, NodeStatus.SKIPPED):
            node.status = NodeStatus.PENDING
            node.output = ""
            node.error_message = ""
            node.started_at = None
            node.completed_at = None
            node.tmux_pane = None
            save_workflow(self.chain)
            self.on_status_change()

    def cleanup_windows(self):
        """Clean up workflow windows."""
        for window in self.executor.list_workflow_windows():
            self.executor.kill_window(window["name"])

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused


def get_workflow_status_line(chain: WorkflowChain) -> str:
    """Get a short status line for status bar display."""
    if not chain:
        return ""

    running = len(chain.get_running_nodes())
    completed, total = chain.progress

    if running > 0:
        return f"●{completed}/{total}"
    elif chain.is_complete():
        return f"✓{total}"
    else:
        return f"○{completed}/{total}"
