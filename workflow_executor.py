"""Workflow execution engine with tmux integration."""

import subprocess
import asyncio
import atexit
import json
import logging
import os
import re
import signal
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from workflow_models import WorkflowChain, WorkflowNode, NodeStatus
from workflow_storage import save_workflow, set_active_workflow, add_execution_history


# Workflow logs directory
WORKFLOW_LOGS_DIR = Path.home() / ".claude" / "workflow_logs"


class WorkflowLogger:
    """Per-workflow file logger."""

    def __init__(self, workflow_id: str, workflow_name: str = ""):
        self.workflow_id = workflow_id
        self.workflow_name = workflow_name
        self.log_file = WORKFLOW_LOGS_DIR / f"{workflow_id}.log"
        self._ensure_log_dir()
        self._setup_logger()

    def _ensure_log_dir(self):
        """Ensure log directory exists."""
        WORKFLOW_LOGS_DIR.mkdir(parents=True, exist_ok=True)

    def _setup_logger(self):
        """Set up file logger for this workflow."""
        self.logger = logging.getLogger(f"workflow.{self.workflow_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()  # Remove any existing handlers

        # File handler with detailed format
        handler = logging.FileHandler(self.log_file, mode='a')
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-7s | %(message)s',
            datefmt='%H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)

    def info(self, msg: str):
        self.logger.info(msg)

    def debug(self, msg: str):
        self.logger.debug(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def error(self, msg: str):
        self.logger.error(msg)

    def node_event(self, node_id: str, event: str, details: str = ""):
        """Log a node-specific event."""
        msg = f"[{node_id}] {event}"
        if details:
            msg += f" - {details}"
        self.logger.info(msg)

    def clear(self):
        """Clear the log file."""
        if self.log_file.exists():
            self.log_file.write_text("")

    @classmethod
    def get_log_path(cls, workflow_id: str) -> Path:
        """Get log file path for a workflow."""
        return WORKFLOW_LOGS_DIR / f"{workflow_id}.log"

    @classmethod
    def read_log(cls, workflow_id: str, tail_lines: int = 100) -> str:
        """Read last N lines from workflow log."""
        log_file = cls.get_log_path(workflow_id)
        if not log_file.exists():
            return "No logs yet."
        try:
            lines = log_file.read_text().splitlines()
            if tail_lines and len(lines) > tail_lines:
                lines = lines[-tail_lines:]
            return "\n".join(lines)
        except IOError:
            return "Error reading log file."

    @classmethod
    def write_error_file(cls, workflow_id: str, node_id: str, error_content: str):
        """Write error details to a dedicated error file for easy access."""
        error_file = WORKFLOW_LOGS_DIR / f"{workflow_id}_{node_id}.error"
        try:
            WORKFLOW_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            error_file.write_text(f"Workflow: {workflow_id}\nNode: {node_id}\nTime: {datetime.now().isoformat()}\n\n{error_content}")
        except IOError:
            pass

    @classmethod
    def get_error_file_path(cls, workflow_id: str, node_id: str) -> Path:
        """Get error file path for a node."""
        return WORKFLOW_LOGS_DIR / f"{workflow_id}_{node_id}.error"


def sanitize_session_name(name: str) -> str:
    """Sanitize workflow name for use as tmux session name."""
    # Remove/replace invalid characters for tmux session names
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', name.lower())
    # Collapse multiple dashes
    sanitized = re.sub(r'-+', '-', sanitized)
    # Trim to reasonable length
    return sanitized[:50].strip('-')


class HookManager:
    """Manages Claude Code hooks for workflow node completion detection."""

    # File to track installed hooks for cleanup
    HOOK_TRACKING_FILE = Path.home() / ".claude" / "workflow_hooks_tracking.json"

    # Directory for workflow state files
    WORKFLOW_STATE_DIR = Path.home() / ".claude" / "workflow_states"

    # Hook script template for Stop event - writes to state file
    STOP_HOOK_SCRIPT = '''#!/bin/bash
# Workflow orchestrator Stop hook - auto-generated
# Do not edit manually - will be cleaned up when workflow completes

# Read hook input from stdin
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')

# Avoid infinite loops
if [ "$STOP_ACTIVE" = "true" ]; then
    exit 0
fi

# Write completion state to file
STATE_DIR="$HOME/.claude/workflow_states"
WORKFLOW_ID="{workflow_id}"
NODE_ID="{node_id}"
STATE_FILE="$STATE_DIR/${{WORKFLOW_ID}}_${{NODE_ID}}.state"

mkdir -p "$STATE_DIR"

cat > "$STATE_FILE" << EOF
{{
    "workflow_id": "$WORKFLOW_ID",
    "node_id": "$NODE_ID",
    "project": "$(basename "$CWD")",
    "session_id": "$SESSION_ID",
    "status": "completed",
    "timestamp": "$(date -Iseconds)"
}}
EOF

exit 0
'''

    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.installed_hooks: dict[str, dict] = {}  # project_path -> hook info
        self._load_tracking()

    def _load_tracking(self):
        """Load hook tracking from file."""
        if self.HOOK_TRACKING_FILE.exists():
            try:
                with open(self.HOOK_TRACKING_FILE) as f:
                    data = json.load(f)
                    # Only load hooks for this workflow
                    self.installed_hooks = data.get(self.workflow_id, {})
            except (json.JSONDecodeError, IOError):
                self.installed_hooks = {}

    def _save_tracking(self):
        """Save hook tracking to file."""
        self.HOOK_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Load existing tracking for other workflows
        all_tracking = {}
        if self.HOOK_TRACKING_FILE.exists():
            try:
                with open(self.HOOK_TRACKING_FILE) as f:
                    all_tracking = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        # Update with our workflow's hooks
        if self.installed_hooks:
            all_tracking[self.workflow_id] = self.installed_hooks
        elif self.workflow_id in all_tracking:
            del all_tracking[self.workflow_id]

        with open(self.HOOK_TRACKING_FILE, 'w') as f:
            json.dump(all_tracking, f, indent=2)

    def check_existing_hooks(self, project_path: str) -> dict:
        """Check for existing Claude Code hooks in a project."""
        settings_file = Path(project_path) / ".claude" / "settings.json"
        local_settings_file = Path(project_path) / ".claude" / "settings.local.json"

        result = {
            "has_settings": settings_file.exists(),
            "has_local_settings": local_settings_file.exists(),
            "has_stop_hook": False,
            "our_hook_installed": False,
        }

        # Check settings.json for Stop hooks
        if settings_file.exists():
            try:
                with open(settings_file) as f:
                    settings = json.load(f)
                    hooks = settings.get("hooks", {})
                    stop_hooks = hooks.get("Stop", [])
                    result["has_stop_hook"] = len(stop_hooks) > 0
            except (json.JSONDecodeError, IOError):
                pass

        # Check if our hook is already installed
        hooks_dir = Path(project_path) / ".claude" / "hooks"
        our_hook_file = hooks_dir / f"wf-{self.workflow_id}-stop.sh"
        result["our_hook_installed"] = our_hook_file.exists()

        return result

    def install_hook(self, node: WorkflowNode) -> bool:
        """Install Stop hook for a workflow node."""
        project_path = Path(node.project_path)
        claude_dir = project_path / ".claude"
        hooks_dir = claude_dir / "hooks"
        settings_file = claude_dir / "settings.json"

        try:
            # Create directories
            hooks_dir.mkdir(parents=True, exist_ok=True)

            # Create hook script
            hook_script = self.STOP_HOOK_SCRIPT.format(
                workflow_id=self.workflow_id,
                node_id=node.id
            )
            hook_file = hooks_dir / f"wf-{self.workflow_id}-stop.sh"
            hook_file.write_text(hook_script)
            hook_file.chmod(0o755)  # Make executable

            # Update settings.json with hook reference
            settings = {}
            if settings_file.exists():
                try:
                    with open(settings_file) as f:
                        settings = json.load(f)
                except (json.JSONDecodeError, IOError):
                    settings = {}

            # Add our Stop hook
            if "hooks" not in settings:
                settings["hooks"] = {}
            if "Stop" not in settings["hooks"]:
                settings["hooks"]["Stop"] = []

            # Check if our hook is already registered
            # Use full path instead of $CLAUDE_PROJECT_DIR to avoid shell quoting issues
            our_hook_command = str(hook_file)
            hook_exists = any(
                hook_group.get("hooks", [{}])[0].get("command", "").find(f"wf-{self.workflow_id}") != -1
                for hook_group in settings["hooks"]["Stop"]
                if isinstance(hook_group, dict)
            )

            if not hook_exists:
                settings["hooks"]["Stop"].append({
                    "hooks": [{
                        "type": "command",
                        "command": our_hook_command,
                        "timeout": 10
                    }]
                })

                with open(settings_file, 'w') as f:
                    json.dump(settings, f, indent=2)

            # Track installed hook
            self.installed_hooks[node.project_path] = {
                "node_id": node.id,
                "hook_file": str(hook_file),
                "settings_file": str(settings_file),
                "installed_at": datetime.now().isoformat()
            }
            self._save_tracking()

            return True

        except (IOError, OSError) as e:
            print(f"Failed to install hook for {node.project_path}: {e}")
            return False

    def uninstall_hook(self, project_path: str) -> bool:
        """Remove installed hook from a project."""
        if project_path not in self.installed_hooks:
            return True

        hook_info = self.installed_hooks[project_path]

        try:
            # Remove hook script
            hook_file = Path(hook_info.get("hook_file", ""))
            if hook_file.exists():
                hook_file.unlink()

            # Remove from settings.json
            settings_file = Path(hook_info.get("settings_file", ""))
            if settings_file.exists():
                try:
                    with open(settings_file) as f:
                        settings = json.load(f)

                    # Remove our hook entries
                    if "hooks" in settings and "Stop" in settings["hooks"]:
                        settings["hooks"]["Stop"] = [
                            hook_group for hook_group in settings["hooks"]["Stop"]
                            if not any(
                                f"wf-{self.workflow_id}" in h.get("command", "")
                                for h in hook_group.get("hooks", [])
                            )
                        ]

                        # Clean up empty structures
                        if not settings["hooks"]["Stop"]:
                            del settings["hooks"]["Stop"]
                        if not settings["hooks"]:
                            del settings["hooks"]

                        with open(settings_file, 'w') as f:
                            json.dump(settings, f, indent=2)

                except (json.JSONDecodeError, IOError):
                    pass

            # Remove from tracking
            del self.installed_hooks[project_path]
            self._save_tracking()

            return True

        except (IOError, OSError) as e:
            print(f"Failed to uninstall hook for {project_path}: {e}")
            return False

    def cleanup_all_hooks(self):
        """Remove all hooks installed by this workflow."""
        paths = list(self.installed_hooks.keys())
        for project_path in paths:
            self.uninstall_hook(project_path)

    @classmethod
    def cleanup_workflow_hooks(cls, workflow_id: str):
        """Class method to cleanup hooks for a specific workflow."""
        manager = cls(workflow_id)
        manager.cleanup_all_hooks()

    @classmethod
    def cleanup_all_workflow_hooks(cls):
        """Clean up all tracked workflow hooks (for IDE exit)."""
        if not cls.HOOK_TRACKING_FILE.exists():
            return

        try:
            with open(cls.HOOK_TRACKING_FILE) as f:
                all_tracking = json.load(f)

            for workflow_id in list(all_tracking.keys()):
                manager = cls(workflow_id)
                manager.cleanup_all_hooks()

        except (json.JSONDecodeError, IOError):
            pass

    # State file methods for file-based completion detection

    def get_state_file_path(self, node_id: str) -> Path:
        """Get path to state file for a node."""
        return self.WORKFLOW_STATE_DIR / f"{self.workflow_id}_{node_id}.state"

    def ensure_state_dir(self):
        """Ensure state directory exists."""
        self.WORKFLOW_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def create_pending_state(self, node_id: str):
        """Create initial pending state file for a node."""
        self.ensure_state_dir()
        state_file = self.get_state_file_path(node_id)
        state = {
            "workflow_id": self.workflow_id,
            "node_id": node_id,
            "status": "running",
            "timestamp": datetime.now().isoformat()
        }
        with open(state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def read_node_state(self, node_id: str) -> Optional[dict]:
        """Read state file for a node. Returns None if not exists."""
        state_file = self.get_state_file_path(node_id)
        if not state_file.exists():
            return None
        try:
            with open(state_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def is_node_complete(self, node_id: str) -> bool:
        """Check if node has completed based on state file."""
        state = self.read_node_state(node_id)
        return state is not None and state.get("status") == "completed"

    def cleanup_state_file(self, node_id: str):
        """Remove state file for a node."""
        state_file = self.get_state_file_path(node_id)
        if state_file.exists():
            try:
                state_file.unlink()
            except OSError:
                pass

    def cleanup_all_state_files(self):
        """Remove all state files for this workflow."""
        if not self.WORKFLOW_STATE_DIR.exists():
            return
        for state_file in self.WORKFLOW_STATE_DIR.glob(f"{self.workflow_id}_*.state"):
            try:
                state_file.unlink()
            except OSError:
                pass


class TmuxExecutor:
    """Manages workflow execution via dedicated workflow tmux session."""

    def __init__(self, workflow_name: str = "default"):
        # Use wf-{project_name} convention for session naming
        self.session = f"wf-{sanitize_session_name(workflow_name)}"
        self.active_panes: dict[str, str] = {}  # node_id -> pane_id
        self._ensure_session_exists()

    def _ensure_session_exists(self):
        """Create the workflow session if it doesn't exist."""
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

    def _run_tmux(self, *args, log_errors: bool = False) -> subprocess.CompletedProcess:
        """Run a tmux command."""
        result = subprocess.run(
            ["tmux"] + list(args),
            capture_output=True, text=True
        )
        if log_errors and result.returncode != 0:
            import sys
            print(f"tmux {' '.join(args)} failed: {result.stderr}", file=sys.stderr)
        return result

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
        
        if result.returncode != 0:
            import sys
            print(f"Failed to create window: {result.stderr}", file=sys.stderr)
            return ""
            
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
        # Use wf-{workflow_name} session naming convention
        self.executor = TmuxExecutor(workflow_name=chain.name)
        # Initialize hook manager for node completion detection
        self.hook_manager = HookManager(workflow_id=chain.id)
        # Initialize per-workflow logger
        self.log = WorkflowLogger(workflow_id=chain.id, workflow_name=chain.name)
        self.accumulated_context = chain.global_context
        self.on_status_change = on_status_change or (lambda: None)
        self._running = False
        self._paused = False
        self._hooks_installed = False

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

    def _install_hooks_for_nodes(self):
        """Install Claude Code hooks for all nodes before execution."""
        self.log.info(f"Installing hooks for {len(self.chain.nodes)} nodes")
        for node in self.chain.nodes:
            if node.project_path:
                try:
                    # Always install/reinstall the hook to ensure file exists
                    # This handles cases where file was deleted but settings reference remains
                    result = self.hook_manager.install_hook(node)
                    if result:
                        self.log.info(f"[{node.id}] Hook installed for {node.project_name}")
                    else:
                        self.log.error(f"[{node.id}] Hook installation failed")
                except Exception as e:
                    self.log.error(f"[{node.id}] Hook installation error: {e}")
                    import traceback
                    self.log.error(f"[{node.id}] Traceback:\n{traceback.format_exc()}")

        self._hooks_installed = True
        self.log.info("Hook installation complete")

    def _cleanup_hooks(self):
        """Clean up all installed hooks."""
        if self._hooks_installed:
            self.hook_manager.cleanup_all_hooks()
            self._hooks_installed = False

    def _check_node_completion(self, node: WorkflowNode) -> bool:
        """Check if a node has completed via state file or tmux pane."""
        # Grace period: don't check completion for first 5 seconds
        # This prevents false positives when shell is still visible before Claude starts
        if node.started_at:
            started = datetime.fromisoformat(node.started_at)
            elapsed = (datetime.now() - started).total_seconds()
            if elapsed < 5:
                self.log.debug(f"[{node.id}] Grace period: {elapsed:.1f}s < 5s")
                return False

        # Primary: Check state file written by Stop hook
        if self.hook_manager.is_node_complete(node.id):
            self.log.node_event(node.id, "Completed via state file")
            return True

        # Fallback: Check tmux pane state
        if not node.tmux_pane:
            return False

        # Check if shell is idle (command finished)
        if self.executor.is_pane_idle(node.tmux_pane):
            self.log.node_event(node.id, "Completed via pane idle")
            return True

        # Also check output for completion markers
        output = self.executor.capture_pane_output(node.tmux_pane, 20)
        if any(marker in output for marker in self.COMPLETION_MARKERS):
            self.log.node_event(node.id, "Completed via output marker")
            return True

        return False

    def execute_node(self, node: WorkflowNode):
        """Execute a single workflow node."""
        self.log.info(f"[{node.id}] Starting execution for project={node.project_name}")

        # Create window in workflow session
        try:
            pane_id = self.executor.create_workflow_window(node)
        except Exception as e:
            node.status = NodeStatus.FAILED
            node.error_message = f"Failed to create tmux window: {e}"
            self.log.error(f"[{node.id}] {node.error_message}")
            import traceback
            self.log.error(f"[{node.id}] Traceback:\n{traceback.format_exc()}")
            return

        if not pane_id:
            node.status = NodeStatus.FAILED
            node.error_message = "Failed to create tmux window (no pane_id returned)"
            self.log.error(f"[{node.id}] {node.error_message}")
            return

        node.tmux_pane = pane_id
        node.status = NodeStatus.RUNNING
        node.started_at = datetime.now().isoformat()
        self.log.debug(f"[{node.id}] Tmux pane: {pane_id}")

        # Create pending state file for this node
        self.hook_manager.create_pending_state(node.id)
        self.log.debug(f"[{node.id}] State file created")

        # Build the prompt
        prompt = self._build_prompt(node)
        self.log.debug(f"[{node.id}] Prompt length: {len(prompt)} chars")

        # Send prompt to claude using tmux send-keys
        try:
            self.executor.send_prompt_to_claude(pane_id, prompt)
            self.log.info(f"[{node.id}] Claude started in pane={pane_id}")
        except Exception as e:
            node.status = NodeStatus.FAILED
            node.error_message = f"Failed to send prompt: {e}"
            self.log.error(f"[{node.id}] {node.error_message}")
            return

        self.on_status_change()
        save_workflow(self.chain)

    def complete_node(self, node: WorkflowNode, success: bool = True):
        """Mark a node as completed."""
        node.completed_at = datetime.now().isoformat()
        duration = node.duration_str

        if success:
            node.status = NodeStatus.COMPLETED
            self.log.info(f"[{node.id}] Completed successfully - duration={duration}")
            # Capture output for context propagation
            if node.tmux_pane:
                node.output = self.executor.capture_pane_output(node.tmux_pane)
                if self.chain.propagate_output:
                    self.accumulated_context += f"\n\n## Output from {node.project_name}:\n{node.output[-2000:]}"
        else:
            node.status = NodeStatus.FAILED
            error_info = f", error={node.error_message}" if node.error_message else ""
            self.log.error(f"[{node.id}] Failed - duration={duration}{error_info}")

        # Clean up state file (hook stays until workflow completes)
        self.hook_manager.cleanup_state_file(node.id)

        self.on_status_change()
        save_workflow(self.chain)

    async def run(self):
        """Execute the workflow chain asynchronously."""
        self._running = True
        set_active_workflow(self.chain.id)
        start_time = datetime.now()

        # Clear and start new log for this run
        self.log.clear()
        self.log.info(f"=== Workflow '{self.chain.name}' started ===")
        self.log.info(f"Nodes: {len(self.chain.nodes)}, Session: {self.executor.session}")

        # Install Claude Code hooks for all nodes before execution
        self._install_hooks_for_nodes()

        # Clean up old windows, keep only current workflow's nodes
        current_node_ids = {node.id for node in self.chain.nodes}
        self.executor.cleanup_old_windows(keep_node_ids=current_node_ids)

        try:
            loop_count = 0
            while self._running and not self.chain.is_complete():
                loop_count += 1
                self.log.debug(f"Poll loop #{loop_count}: running={self._running}, complete={self.chain.is_complete()}")

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
                        # Check output for errors - only check last 15 lines to avoid false positives
                        # from errors that Claude recovered from earlier in the session
                        output = self.executor.capture_pane_output(node.tmux_pane, 50)
                        last_lines = "\n".join(output.split('\n')[-15:]).lower()

                        # Success indicators - Claude completed the task
                        success_indicators = [
                            "ready to use", "successfully", "completed", "done",
                            "created", "updated", "fixed", "working", "finished"
                        ]
                        has_success = any(ind in last_lines for ind in success_indicators)

                        # Only check for errors in last lines, and ignore if success was indicated
                        has_error = "error" in last_lines and not has_success
                        success = not has_error

                        if not success:
                            # Log the detected error for debugging
                            self.log.warning(f"[{node.id}] Error detected in output")
                            # Find lines containing 'error' to show what triggered failure
                            error_lines = [
                                line.strip() for line in output.split('\n')
                                if 'error' in line.lower()
                            ][:5]  # Show first 5 error lines
                            for line in error_lines:
                                self.log.warning(f"[{node.id}] >> {line[:200]}")
                            node.error_message = error_lines[0][:200] if error_lines else "Error detected in output"

                            # Write full output to error file for debugging
                            full_output = self.executor.capture_pane_output(node.tmux_pane, 200)
                            WorkflowLogger.write_error_file(
                                self.chain.id,
                                node.id,
                                f"Error lines:\n" + "\n".join(error_lines) + f"\n\n--- Full pane output ---\n{full_output}"
                            )
                            error_file = WorkflowLogger.get_error_file_path(self.chain.id, node.id)
                            self.log.warning(f"[{node.id}] Error details written to: {error_file}")

                        self.complete_node(node, success)

                await asyncio.sleep(2)  # Poll interval

        except Exception as e:
            # Log the exception with full traceback
            import traceback
            tb = traceback.format_exc()
            self.log.error(f"Workflow execution failed: {e}")
            self.log.error(f"Traceback:\n{tb}")

            # Write exception to error file
            WorkflowLogger.write_error_file(
                self.chain.id,
                "workflow",
                f"Exception: {e}\n\nTraceback:\n{tb}"
            )

            # Mark running nodes as failed
            for node in self.chain.get_running_nodes():
                node.status = NodeStatus.FAILED
                node.error_message = str(e)
                node.completed_at = datetime.now().isoformat()
            save_workflow(self.chain)
            raise

        finally:
            self._running = False
            set_active_workflow(None)

            # Clean up any remaining hooks and state files when workflow completes
            # Individual node hooks/states are cleaned up in complete_node()
            if self.chain.is_complete():
                self._cleanup_hooks()
                self.hook_manager.cleanup_all_state_files()
                self.log.info("Hooks and state files cleaned up")

            # Record execution
            duration = (datetime.now() - start_time).total_seconds()
            status = "completed" if self.chain.is_complete() and not self.chain.has_failed() else "failed"
            add_execution_history(self.chain.id, status, duration)

            completed, total = self.chain.progress
            self.log.info(f"=== Workflow {status} === ({completed}/{total} nodes, {duration:.1f}s)")

    def run_sync(self):
        """Run workflow synchronously (blocking)."""
        asyncio.run(self.run())

    def stop(self):
        """Stop workflow execution."""
        self._running = False
        # Mark running nodes as failed and clean up their hooks/state
        for node in self.chain.get_running_nodes():
            node.status = NodeStatus.FAILED
            node.error_message = "Stopped by user"
            node.completed_at = datetime.now().isoformat()
            # Clean up hook and state file for this stopped node
            if node.project_path:
                self.hook_manager.uninstall_hook(node.project_path)
            self.hook_manager.cleanup_state_file(node.id)

        # Clean up any remaining hooks and state files
        self._cleanup_hooks()
        self.hook_manager.cleanup_all_state_files()

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
        """Clean up workflow windows and hooks."""
        for window in self.executor.list_workflow_windows():
            self.executor.kill_window(window["name"])
        # Also clean up hooks
        self._cleanup_hooks()

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
