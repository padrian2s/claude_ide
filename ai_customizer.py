#!/usr/bin/env python3
"""AI-assisted code customization module for Claude IDE."""

import ast
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from difflib import unified_diff
from pathlib import Path

import anthropic

# Constants
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / "backups"

# Screen configurations: name -> (script, window_name, description)
# Window indices are detected dynamically by window name
SCREEN_CONFIGS = {
    "Tree View": {
        "script": "tree_view.py",
        "window_name": "Tree",
        "description": "File browser and viewer with dual-panel file manager",
    },
    "Lizard TUI": {
        "script": "lizard_tui.py",
        "window_name": "Lizard",
        "description": "Code complexity analyzer",
    },
    "Favorites": {
        "script": "favorites.py",
        "window_name": "Favs",
        "description": "Folder favorites browser",
    },
    "Prompt Writer": {
        "script": "prompt_writer.py",
        "window_name": "Prompt",
        "description": "Prompt writing tool with AI enhancement",
    },
    "Config Panel": {
        "script": "config_panel.py",
        "window_name": "Config",
        "description": "Theme and configuration settings",
    },
}


def get_window_index_by_name(window_name: str) -> int | None:
    """Get window index by searching for window name in current tmux session.

    Args:
        window_name: The name of the window to find

    Returns:
        Window index or None if not found
    """
    session = ScreenReloader.get_session_name()
    if not session:
        return None

    result = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_index}:#{window_name}"],
        capture_output=True,
        text=True,
    )

    for line in result.stdout.strip().split("\n"):
        if ":" in line:
            idx, name = line.split(":", 1)
            if name == window_name:
                return int(idx)
    return None


class CodeBackup:
    """Manages backup and restore of code files."""

    def __init__(self):
        BACKUP_DIR.mkdir(exist_ok=True)

    def create_backup(self, script_path: Path) -> Path:
        """Create a timestamped backup of the script.

        Args:
            script_path: Path to the script to backup

        Returns:
            Path to the created backup file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{script_path.stem}_{timestamp}.py.bak"
        backup_path = BACKUP_DIR / backup_name

        shutil.copy2(script_path, backup_path)
        return backup_path

    def restore_backup(self, backup_path: Path, original_path: Path) -> bool:
        """Restore a script from backup.

        Args:
            backup_path: Path to the backup file
            original_path: Path to restore to

        Returns:
            True if successful
        """
        shutil.copy2(backup_path, original_path)
        return True

    def list_backups(self, script_name: str) -> list[Path]:
        """List all backups for a given script.

        Args:
            script_name: Name of the script (e.g., 'tree_view')

        Returns:
            List of backup paths, sorted newest first
        """
        pattern = f"{script_name}_*.py.bak"
        backups = sorted(BACKUP_DIR.glob(pattern), reverse=True)
        return backups

    def cleanup_old_backups(self, script_name: str, keep: int = 5):
        """Remove old backups, keeping only the most recent ones.

        Args:
            script_name: Name of the script
            keep: Number of backups to keep
        """
        backups = self.list_backups(script_name)
        for backup in backups[keep:]:
            backup.unlink()


class CodeValidator:
    """Validates Python code syntax and safety."""

    # Patterns that should trigger warnings (not blocks)
    DANGEROUS_PATTERNS = [
        (r"\bos\.system\s*\(", "os.system() call detected"),
        (r"\bsubprocess\.[a-z]+\s*\([^)]*shell\s*=\s*True", "shell=True in subprocess"),
        (r"\beval\s*\(", "eval() detected"),
        (r"\bexec\s*\(", "exec() detected"),
        (r"\b__import__\s*\(", "dynamic __import__() detected"),
        (r"\bopen\s*\([^)]*['\"][wa]['\"]", "file write operation detected"),
        (r"\brm\s+-rf", "dangerous rm -rf detected"),
    ]

    def validate_syntax(self, code: str) -> tuple[bool, str]:
        """Check Python syntax validity.

        Args:
            code: Python source code to validate

        Returns:
            Tuple of (is_valid, message)
        """
        try:
            ast.parse(code)
            return True, "Syntax OK"
        except SyntaxError as e:
            return False, f"Syntax error at line {e.lineno}: {e.msg}"

    def check_dangerous_patterns(self, code: str) -> list[str]:
        """Check for potentially dangerous code patterns.

        Args:
            code: Python source code to check

        Returns:
            List of warning messages
        """
        warnings = []
        for pattern, message in self.DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                warnings.append(message)
        return warnings


class AICodeModifier:
    """Interfaces with Claude API for code modifications."""

    SYSTEM_PROMPT = """You are an expert Python developer specializing in Textual TUI applications.
Your task is to modify the provided code based on user requests.

Guidelines:
- Preserve existing functionality unless explicitly asked to remove it
- Follow Textual best practices for CSS and widgets
- Keep the code style consistent with the original
- Only modify what is necessary to fulfill the request
- Return ONLY the complete modified Python code
- Do NOT include explanations, markdown formatting, or code blocks
- The response should be valid Python code that can be directly written to a file

Important Textual patterns:
- CSS is defined in the CSS class variable
- Key bindings use the BINDINGS list with Binding objects
- Widgets are composed in compose() method
- Actions are defined as action_* methods
- Modal screens use ModalScreen and dismiss()
"""

    def __init__(self, api_key: str | None = None):
        """Initialize with API key.

        Args:
            api_key: Anthropic API key. If None, will try environment variable.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "API key required. Set ANTHROPIC_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def generate_modification(
        self, original_code: str, user_prompt: str, screen_context: str
    ) -> tuple[str, str]:
        """Generate code modification using Claude API.

        Args:
            original_code: The current source code
            user_prompt: User's description of desired changes
            screen_context: Description of the screen being modified

        Returns:
            Tuple of (modified_code, explanation)
        """
        message = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            system=self.SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"""Screen: {screen_context}

Current code:
{original_code}

Requested changes: {user_prompt}

Return the complete modified Python code only. No markdown, no explanations, just the code.""",
                }
            ],
        )

        # Extract text from response
        response_text = message.content[0].text

        # Clean up any markdown code blocks if present
        modified_code = self._extract_code(response_text)

        return modified_code, ""

    def _extract_code(self, text: str) -> str:
        """Extract Python code from response, handling markdown if present.

        Args:
            text: Response text that may contain markdown

        Returns:
            Clean Python code
        """
        # Check for markdown code blocks
        code_block_pattern = r"```(?:python)?\n?(.*?)```"
        matches = re.findall(code_block_pattern, text, re.DOTALL)

        if matches:
            # Return the largest code block (likely the main code)
            return max(matches, key=len).strip()

        # No code blocks, return as-is (already clean code)
        return text.strip()


class ScreenReloader:
    """Hot-reloads screens via tmux."""

    # Class-level cache for session name
    _cached_session: str | None = None

    def __init__(self, session_name: str | None = None):
        self.script_dir = SCRIPT_DIR
        if session_name:
            ScreenReloader._cached_session = session_name

    @classmethod
    def get_session_name(cls) -> str:
        """Get the current tmux session name.

        Returns:
            Session name string
        """
        if cls._cached_session is None:
            # Try multiple methods to get session name
            # Method 1: tmux display-message
            result = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True,
                text=True,
            )
            session = result.stdout.strip()

            if not session:
                # Method 2: List sessions and find claude-ide
                result = subprocess.run(
                    ["tmux", "list-sessions", "-F", "#{session_name}"],
                    capture_output=True,
                    text=True,
                )
                sessions = result.stdout.strip().split("\n")
                for s in sessions:
                    if s.startswith("claude-ide-"):
                        session = s
                        break

            cls._cached_session = session
        return cls._cached_session or ""

    def reload_screen(self, window_index: int, script_path: Path) -> tuple[bool, str]:
        """Kill and restart the process in the specified window.

        Args:
            window_index: tmux window index
            script_path: Path to the script to run

        Returns:
            Tuple of (success, message)
        """
        session = self.get_session_name()
        if not session:
            return False, "No tmux session found"

        target = f"{session}:{window_index}"

        # Check if window exists
        result = subprocess.run(
            ["tmux", "list-windows", "-t", session, "-F", "#{window_index}"],
            capture_output=True,
            text=True,
        )
        windows = result.stdout.strip().split("\n")
        if str(window_index) not in windows:
            return False, f"Window {window_index} not found in session"

        # Get pane PID
        result = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
            capture_output=True,
            text=True,
        )
        pane_pid = result.stdout.strip()

        if pane_pid:
            # Find and kill child processes (the actual Python app)
            result = subprocess.run(
                ["pgrep", "-P", pane_pid],
                capture_output=True,
                text=True,
            )
            child_pids = result.stdout.strip().split("\n")
            for pid in child_pids:
                if pid:
                    subprocess.run(["kill", pid], capture_output=True)

        time.sleep(0.3)

        # Clear and restart
        subprocess.run(["tmux", "send-keys", "-t", target, "clear", "Enter"])
        time.sleep(0.1)

        # Restart the script (leading space prevents shell history)
        cmd = f" uv run --project '{self.script_dir}' python3 '{script_path}'"
        subprocess.run(["tmux", "send-keys", "-t", target, cmd, "Enter"])

        return True, f"Reloaded window {window_index}"


def create_diff(original: str, modified: str, filename: str = "code.py") -> str:
    """Create a unified diff between original and modified code.

    Args:
        original: Original source code
        modified: Modified source code
        filename: Filename to show in diff header

    Returns:
        Unified diff string
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff = unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    )

    return "".join(diff)


def get_api_key() -> str | None:
    """Get API key from environment or config.

    Returns:
        API key string or None if not found
    """
    # Check environment first
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key

    # Check config file
    import json

    config_file = SCRIPT_DIR / ".tui_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
            if key := config.get("api_key"):
                return key
        except Exception:
            pass

    return None


def get_screen_path(screen_name: str) -> Path | None:
    """Get the full path to a screen's script.

    Args:
        screen_name: Name of the screen (e.g., 'Tree View')

    Returns:
        Path to the script or None if not found
    """
    config = SCREEN_CONFIGS.get(screen_name)
    if config:
        return SCRIPT_DIR / config["script"]
    return None
