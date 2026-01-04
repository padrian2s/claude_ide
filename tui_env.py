#!/usr/bin/env python3
"""Claude IDE launcher - tmux with tree + terminal + lizard-tui as separate windows."""

import atexit
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

SESSION = f"claude-ide-{os.getpid()}"
# Get the start directory from command line arg, default to cwd
START_DIR = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
SCRIPT_DIR = Path(__file__).parent
TREE_SCRIPT = SCRIPT_DIR / "tree_view.py"
LIZARD_SCRIPT = SCRIPT_DIR / "lizard_tui.py"
CONFIG_SCRIPT = SCRIPT_DIR / "config_panel.py"
FAVORITES_SCRIPT = SCRIPT_DIR / "favorites.py"
PROMPT_SCRIPT = SCRIPT_DIR / "prompt_writer.py"
STATUS_SCRIPT = SCRIPT_DIR / "status_viewer.py"
QUICK_INPUT_SCRIPT = SCRIPT_DIR / "quick_input.py"
SHORTCUTS_FILE = SCRIPT_DIR / "shortcuts.json"


def load_shortcuts():
    """Load keyboard shortcuts from JSON file."""
    with open(SHORTCUTS_FILE) as f:
        return json.load(f)


def generate_help_text(shortcuts_data):
    """Generate help popup text from shortcuts JSON."""
    help_popup = shortcuts_data.get("help_popup", {})
    sections = help_popup.get("sections", [])

    lines = ["", "                    \u2328  KEYBOARD SHORTCUTS", ""]

    for section in sections:
        lines.append(f"  {section['title']}")
        for item in section["items"]:
            key = item["key"]
            desc = item["description"]
            # Pad key to align descriptions
            lines.append(f"    {key:<16}{desc}")
        lines.append("")

    lines.append("                Press ? or Esc to close")
    return "\n".join(lines)


def get_status_suffix(shortcuts_data):
    """Get status bar suffix from shortcuts JSON."""
    global_shortcuts = shortcuts_data.get("contexts", {}).get("global", {}).get("shortcuts", {})

    f10_label = global_shortcuts.get("F10", {}).get("label", "Exit")
    f12_label = global_shortcuts.get("F12", {}).get("label", "Keys")

    return f"F10:{f10_label} ?:Help F12:{f12_label}"


# Import config to get saved theme and position
from config_panel import get_theme_colors, get_status_position
from upgrader import auto_upgrade


def main():
    # Auto-upgrade from git (preserves AI-modified files)
    auto_upgrade(silent=False)

    # Load shortcuts configuration
    shortcuts_data = load_shortcuts()

    # Get terminal size
    size = os.get_terminal_size()

    # Create session with base-index 1, first window is Terminal 1
    subprocess.run([
        "tmux", "new-session", "-d", "-s", SESSION,
        "-x", str(size.columns), "-y", str(size.lines),
        "-n", "Term1"
    ])
    # Set base-index to 1 immediately
    subprocess.run(["tmux", "set-option", "-t", SESSION, "base-index", "1"])
    # Renumber existing window from 0 to 1
    subprocess.run(["tmux", "move-window", "-t", f"{SESSION}:1"])
    # Change to user's start directory in Terminal 1 and start Claude
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:1",
        f" cd '{START_DIR}' && clear && claude", "Enter"
    ])
    # Store START_DIR in tmux variable for new terminals
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@start_dir", str(START_DIR)])

    # Apps at high window numbers (20-26) so dynamic terminals can use 2-19
    # Create Window 20 = Tree + Viewer
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:20", "-n", "Tree"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:20",
        f" uv run --project '{SCRIPT_DIR}' python3 '{TREE_SCRIPT}' '{START_DIR}'", "Enter"
    ])

    # Create Window 21 = Lizard TUI
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:21", "-n", "Lizard"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:21",
        f" uv run --project '{SCRIPT_DIR}' python3 '{LIZARD_SCRIPT}'", "Enter"
    ])

    # Create Window 22 = Glow
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:22", "-n", "Glow"])
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:22", " glow", "Enter"])

    # Create Window 23 = Favorites
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:23", "-n", "Favs"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:23",
        f" uv run --project '{SCRIPT_DIR}' python3 '{FAVORITES_SCRIPT}'", "Enter"
    ])

    # Create Window 24 = Prompt Writer
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:24", "-n", "Prompt"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:24",
        f" uv run --project '{SCRIPT_DIR}' python3 '{PROMPT_SCRIPT}'", "Enter"
    ])

    # Create Window 25 = Git (F7)
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:25", "-n", "Git"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:25",
        f" cd '{START_DIR}' && lazygit", "Enter"
    ])

    # Create Window 26 = Status Viewer (F8)
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:26", "-n", "Status"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:26",
        f" uv run --project '{SCRIPT_DIR}' python3 '{STATUS_SCRIPT}'", "Enter"
    ])

    # Create Window 27 = Config (F9)
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:27", "-n", "Config"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:27",
        f" uv run --project '{SCRIPT_DIR}' python3 '{CONFIG_SCRIPT}'", "Enter"
    ])

    # Load saved theme and position
    theme = get_theme_colors()
    status_position = get_status_position()

    # Enable focus events for focus tracking
    subprocess.run(["tmux", "set-option", "-t", SESSION, "focus-events", "on"])

    # Set up focus indicator variable (global so hooks can modify it)
    subprocess.run(["tmux", "set-option", "-g", "@focus", ""])

    # Hooks to update focus indicator
    subprocess.run(["tmux", "set-hook", "-g", "client-focus-in",
        "set-option -g @focus ''"])
    subprocess.run(["tmux", "set-hook", "-g", "client-focus-out",
        "set-option -g @focus 'UNFOCUSED '"])

    # Status bar - custom format to show F-keys properly (apps show as F2-F7 even though windows are 20-25)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "on"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-position", status_position])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-interval", "1"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-style", f"bg={theme['bg']},fg={theme['fg']}"])

    # Custom status format:
    # - F1 (window 1): show as "F1:Term1"
    # - Dynamic terminals (2-19): show just name (e.g., "T2")
    # - Apps (20-25): show as "F2:Tree", "F3:Lizard", etc.
    status_suffix = get_status_suffix(shortcuts_data)
    subprocess.run([
        "tmux", "set-option", "-t", SESSION, "status-format[0]",
        "#{@focus}#{@passthrough}#[align=centre]"
        "#{W:"
        "#{?#{==:#{window_index},1},"
        "#{?window_active,#[bg=cyan#,fg=black#,bold] F1:#{window_name} #[default], F1:#{window_name} },"
        "#{?#{e|<:#{window_index},20},"
        "#{?window_active,#[bg=cyan#,fg=black#,bold] #{window_name} #[default], #{window_name} },"
        "#{?window_active,#[bg=cyan#,fg=black#,bold] F#{e|-:#{window_index},18}:#{window_name} #[default], F#{e|-:#{window_index},18}:#{window_name} }"
        "}}"
        f"}} {status_suffix}"
    ])

    # Track terminal counter for auto-naming
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@term_count", "1"])

    # Key passthrough mode variable (empty = normal, has value = passthrough)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@passthrough", ""])

    # Clear stale key bindings from previous sessions (tmux bindings are global)
    for key in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12", "C-t"]:
        subprocess.run(["tmux", "unbind-key", "-n", key], stderr=subprocess.DEVNULL)

    # Bind F-keys: F1=Term1, F2-F7=Apps (windows 20-25)
    subprocess.run(["tmux", "bind-key", "-n", "F1", "select-window", "-t", f"{SESSION}:1"])
    subprocess.run(["tmux", "bind-key", "-n", "F2", "select-window", "-t", f"{SESSION}:20"])
    subprocess.run(["tmux", "bind-key", "-n", "F3", "select-window", "-t", f"{SESSION}:21"])
    subprocess.run(["tmux", "bind-key", "-n", "F4", "select-window", "-t", f"{SESSION}:22"])
    subprocess.run(["tmux", "bind-key", "-n", "F5", "select-window", "-t", f"{SESSION}:23"])
    subprocess.run(["tmux", "bind-key", "-n", "F6", "select-window", "-t", f"{SESSION}:24"])
    subprocess.run(["tmux", "bind-key", "-n", "F7", "select-window", "-t", f"{SESSION}:25"])
    subprocess.run(["tmux", "bind-key", "-n", "F8", "select-window", "-t", f"{SESSION}:26"])

    # F9 = Config
    subprocess.run(["tmux", "bind-key", "-n", "F9", "select-window", "-t", f"{SESSION}:27"])

    # F10 = Exit (kill session) with confirmation
    subprocess.run([
        "tmux", "bind-key", "-n", "F10",
        "confirm-before", "-p", "Exit session? (y/n)",
        f"kill-session -t {SESSION}"
    ])

    # ? = Show keyboard shortcuts help popup (generated from shortcuts.json)
    help_text = generate_help_text(shortcuts_data)
    help_popup = shortcuts_data.get("help_popup", {})
    popup_width = help_popup.get("width", 68)
    popup_height = help_popup.get("height", 27)
    subprocess.run([
        "tmux", "bind-key", "-n", "?",
        "display-popup", "-w", str(popup_width), "-h", str(popup_height),
        f"echo '{help_text}'"
    ])

    # Shift+Arrow keys to navigate windows (always active, even in passthrough mode)
    subprocess.run(["tmux", "bind-key", "-n", "S-Left", "previous-window"])
    subprocess.run(["tmux", "bind-key", "-n", "S-Right", "next-window"])

    # Ctrl+T = Create new terminal with auto-name T2, T3, etc.
    # Increments @term_count and creates window after the last terminal (before apps at 20+)
    # Also cd to start directory after creating the window
    subprocess.run([
        "tmux", "bind-key", "-n", "C-t",
        "run-shell",
        f"tmux set-option -t {SESSION} @term_count $(($(tmux show-option -t {SESSION} -v @term_count) + 1)) && "
        f"tmux new-window -t {SESSION} -n T$(tmux show-option -t {SESSION} -v @term_count) && "
        f"tmux send-keys -t {SESSION} \" cd '$(tmux show-option -t {SESSION} -v @start_dir)' && clear\" Enter"
    ])

    # Ctrl+W = Close current terminal (only dynamic ones, windows 2-19)
    subprocess.run([
        "tmux", "bind-key", "-n", "C-w",
        "if-shell", "-F", "#{&&:#{e|>:#{window_index},1},#{e|<:#{window_index},20}}",
        "kill-window",
        "display-message 'Cannot close this window'"
    ])

    # Ctrl+P = Quick input popup (sends to F1) with autocomplete
    subprocess.run([
        "tmux", "bind-key", "-n", "C-p",
        "display-popup", "-E", "-w", "70", "-h", "12",
        f"uv run python3 '{QUICK_INPUT_SCRIPT}'"
    ])

    # F12 = Toggle key passthrough mode
    # When passthrough is ON: F-keys go to the app, status shows "PASSTHROUGH"
    # When passthrough is OFF: F-keys switch windows (normal mode)
    toggle_cmd = (
        f"if-shell -F '#{{@passthrough}}' "
        f"'set-option -t {SESSION} @passthrough \"\" ; "
        f"bind-key -n F1 select-window -t {SESSION}:1 ; "
        f"bind-key -n F2 select-window -t {SESSION}:20 ; "
        f"bind-key -n F3 select-window -t {SESSION}:21 ; "
        f"bind-key -n F4 select-window -t {SESSION}:22 ; "
        f"bind-key -n F5 select-window -t {SESSION}:23 ; "
        f"bind-key -n F6 select-window -t {SESSION}:24 ; "
        f"bind-key -n F7 select-window -t {SESSION}:25 ; "
        f"bind-key -n F8 select-window -t {SESSION}:26 ; "
        f"bind-key -n F9 select-window -t {SESSION}:27 ; "
        f"bind-key -n F10 confirm-before -p \"Exit session? (y/n)\" \"kill-session -t {SESSION}\"' "
        f"'set-option -t {SESSION} @passthrough \"PASSTHROUGH \" ; "
        f"unbind-key -n F1 ; unbind-key -n F2 ; unbind-key -n F3 ; "
        f"unbind-key -n F4 ; unbind-key -n F5 ; unbind-key -n F6 ; "
        f"unbind-key -n F7 ; unbind-key -n F8 ; unbind-key -n F9 ; unbind-key -n F10'"
    )
    subprocess.run(["tmux", "bind-key", "-n", "F12", toggle_cmd])

    # Select terminal window (1)
    subprocess.run(["tmux", "select-window", "-t", f"{SESSION}:1"])

    # Register cleanup to kill session on exit
    def cleanup():
        subprocess.run(["tmux", "kill-session", "-t", SESSION], stderr=subprocess.DEVNULL)

    atexit.register(cleanup)
    signal.signal(signal.SIGHUP, lambda *_: cleanup())
    signal.signal(signal.SIGTERM, lambda *_: cleanup())

    # Attach (using subprocess so we regain control after detach/exit)
    subprocess.run(["tmux", "attach-session", "-t", SESSION])

    # Session ends here - cleanup runs via atexit

    # Session ends here - cleanup runs via atexit


if __name__ == "__main__":
    main()
