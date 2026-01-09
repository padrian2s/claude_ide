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
PATH_SEGMENTS_SCRIPT = SCRIPT_DIR / "path_segments.py"
SESSION_MANAGER_SCRIPT = SCRIPT_DIR / "session_manager.py"
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

    lines.append("              Press Ctrl+H or Esc to close")
    return "\n".join(lines)


def get_status_suffix(shortcuts_data, icon_mode: bool = False):
    """Get status bar suffix from shortcuts JSON.

    Each shortcut is wrapped in #[range=user|key] to make it clickable.
    Click handlers are bound in main() to send the corresponding key.
    """
    global_shortcuts = shortcuts_data.get("contexts", {}).get("global", {}).get("shortcuts", {})

    if icon_mode:
        session_label = "⧉"
        f10_label = "⏻"
        help_label = "🔍"
        f12_label = "🔓"
    else:
        session_label = "Sess"
        f10_label = global_shortcuts.get("F10", {}).get("label", "Exit")
        help_label = "Help"
        f12_label = global_shortcuts.get("F12", {}).get("label", "Keys")

    # Wrap each shortcut in a clickable range
    return (
        f"#[range=user|session]^S:{session_label}#[norange] "
        f"#[range=user|f10]F10:{f10_label}#[norange] "
        f"#[range=user|help]^H:{help_label}#[norange] "
        f"#[range=user|f12]F12:{f12_label}#[norange]"
    )


# Import config to get saved theme and position
from config_panel import get_theme_colors, get_status_position, get_status_line, get_icon_mode, get_status_bar_format
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
        "-n", "❯"
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
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:22", f" glow '{START_DIR}'", "Enter"])

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

    # Store theme colors for new terminals (Ctrl+T)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@theme_bg", theme['bg']])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@theme_fg", theme['fg']])

    # Enable focus events for focus tracking
    subprocess.run(["tmux", "set-option", "-t", SESSION, "focus-events", "on"])

    # Set up focus indicator variable (session-specific)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@focus", ""])

    # Hooks to update focus indicator (session-specific)
    subprocess.run(["tmux", "set-hook", "-t", SESSION, "client-focus-in",
        f"set-option -t {SESSION} @focus ''"])
    subprocess.run(["tmux", "set-hook", "-t", SESSION, "client-focus-out",
        f"set-option -t {SESSION} @focus 'UNFOCUSED '"])

    # Status bar - custom format to show F-keys properly (apps show as F2-F7 even though windows are 20-25)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "on"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-position", status_position])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-interval", "1"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-style", f"bg={theme['bg']},fg={theme['fg']}"])

    # Enable mouse support for clicking on status bar windows
    subprocess.run(["tmux", "set-option", "-t", SESSION, "mouse", "on"])

    # Copy-on-select: auto copy to clipboard when mouse selection ends (macOS)
    # Add binding for both vi and emacs copy modes
    subprocess.run([
        "tmux", "bind-key", "-T", "copy-mode-vi", "MouseDragEnd1Pane",
        "send-keys", "-X", "copy-pipe-and-cancel", "pbcopy"
    ])
    subprocess.run([
        "tmux", "bind-key", "-T", "copy-mode", "MouseDragEnd1Pane",
        "send-keys", "-X", "copy-pipe-and-cancel", "pbcopy"
    ])

    # Apply theme colors to F1 terminal window
    subprocess.run(["tmux", "set-option", "-t", f"{SESSION}:1", "window-style", f"bg={theme['bg']},fg={theme['fg']}"])
    subprocess.run(["tmux", "set-option", "-t", f"{SESSION}:1", "window-active-style", f"bg={theme['bg']},fg={theme['fg']}"])

    # Apply theme colors to F4 (Glow), F6 (Prompt), F7 (Git) windows
    for win_idx in [22, 24, 25]:  # F4=Glow, F6=Prompt, F7=Git
        subprocess.run(["tmux", "set-option", "-t", f"{SESSION}:{win_idx}", "window-style", f"bg={theme['bg']},fg={theme['fg']}"])
        subprocess.run(["tmux", "set-option", "-t", f"{SESSION}:{win_idx}", "window-active-style", f"bg={theme['bg']},fg={theme['fg']}"])

    # Custom status format:
    # - Left: clickable path segments (current pane's directory)
    # - Center: window list with F-keys (text or icons based on config)
    # - Right: help and exit shortcuts
    # - #[range=window|X] makes each window clickable
    # - #[range=user|path:X] makes each path segment clickable
    icon_mode = get_icon_mode()
    status_suffix = get_status_suffix(shortcuts_data, icon_mode)
    status_content = get_status_bar_format(icon_mode, str(PATH_SEGMENTS_SCRIPT), status_suffix)
    subprocess.run([
        "tmux", "set-option", "-t", SESSION, "status-format[0]", status_content
    ])

    # Add horizontal line to status bar if configured
    status_line_pos = get_status_line()
    if status_line_pos in ("before", "after", "both"):
        line_format = f"#[fg={theme['fg']},dim]#{{=|-:─}}"
        if status_line_pos == "before":
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "2"])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[0]", line_format])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[1]", status_content])
        elif status_line_pos == "after":
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "2"])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[1]", line_format])
        else:  # both
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "3"])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[0]", line_format])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[1]", status_content])
            subprocess.run(["tmux", "set-option", "-t", SESSION, "status-format[2]", line_format])

    # Track terminal counter for auto-naming
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@term_count", "1"])

    # Key passthrough mode variable (empty = normal, has value = passthrough)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@passthrough", ""])

    # Clear stale key bindings from previous sessions (tmux bindings are global)
    for key in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12",
                "S-F1", "S-F2", "S-F3", "S-F4", "S-F5", "S-F6", "S-F7", "S-F8", "S-F9",
                "C-t", "C-h", "C-x", "C-p", "C-s", "C-w", "S-Left", "S-Right"]:
        subprocess.run(["tmux", "unbind-key", "-n", key], stderr=subprocess.DEVNULL)
    # Also clear mouse binding that might reference dead session
    subprocess.run(["tmux", "unbind-key", "-T", "root", "MouseUp1Status"], stderr=subprocess.DEVNULL)

    # Bind F-keys: F1=Term1, F2-F9=Apps (windows 20-27)
    # Use `:N` syntax for current session (session-agnostic bindings)
    subprocess.run(["tmux", "bind-key", "-n", "F1", "select-window", "-t", ":1"])

    # Shift+F1-F9 to access terminal windows directly (F1=window 1, T2=window 2, etc.)
    # Try to select window; if it doesn't exist, create it
    # Use #{session_name} for dynamic session reference in run-shell
    subprocess.run(["tmux", "bind-key", "-n", "S-F1", "select-window", "-t", ":1"])
    for i in range(2, 10):
        # Capture current directory and session, then check if window exists and select or create
        subprocess.run([
            "tmux", "bind-key", "-n", f"S-F{i}",
            "run-shell",
            "d=$(tmux display -p '#{pane_current_path}'); "
            "s=$(tmux display -p '#{session_name}'); "
            f"tmux list-windows -t \"$s\" | grep -q '^{i}:' && "
            f"tmux select-window -t \"$s\":{i} || "
            f"tmux new-window -t \"$s\":{i} -n T{i} -c \"$d\""
        ])
    subprocess.run(["tmux", "bind-key", "-n", "F2", "select-window", "-t", ":20"])
    subprocess.run(["tmux", "bind-key", "-n", "F3", "select-window", "-t", ":21"])
    subprocess.run(["tmux", "bind-key", "-n", "F4", "select-window", "-t", ":22"])
    subprocess.run(["tmux", "bind-key", "-n", "F5", "select-window", "-t", ":23"])
    subprocess.run(["tmux", "bind-key", "-n", "F6", "select-window", "-t", ":24"])
    subprocess.run(["tmux", "bind-key", "-n", "F7", "select-window", "-t", ":25"])
    subprocess.run(["tmux", "bind-key", "-n", "F8", "select-window", "-t", ":26"])

    # F9 = Config
    subprocess.run(["tmux", "bind-key", "-n", "F9", "select-window", "-t", ":27"])

    # F10 = Exit (kill session) with confirmation
    # Use #{client_session} for dynamic session detection (works across multiple sessions)
    subprocess.run([
        "tmux", "bind-key", "-n", "F10",
        "confirm-before", "-p", "Exit session? (y/n)",
        "kill-session"  # Kills current session without needing -t
    ])

    # Ctrl+H = Show keyboard shortcuts help popup (generated from shortcuts.json)
    help_text = generate_help_text(shortcuts_data)
    help_popup = shortcuts_data.get("help_popup", {})
    popup_width = help_popup.get("width", 68)
    popup_height = help_popup.get("height", 27)
    subprocess.run([
        "tmux", "bind-key", "-n", "C-h",
        "display-popup", "-w", str(popup_width), "-h", str(popup_height),
        f"echo '{help_text}'"
    ])

    # Shift+Arrow keys to navigate all windows (always active, even in passthrough mode)
    subprocess.run(["tmux", "bind-key", "-n", "S-Left", "previous-window"])
    subprocess.run(["tmux", "bind-key", "-n", "S-Right", "next-window"])

    # Ctrl+S = Session manager popup (switch or kill sessions) - fullscreen
    subprocess.run([
        "tmux", "bind-key", "-n", "C-s",
        "display-popup", "-E", "-w", "100%", "-h", "100%",
        f"uv run python3 '{SESSION_MANAGER_SCRIPT}'"
    ])


    # Ctrl+T = Create new terminal with auto-name T2, T3, etc.
    # Increments @term_count and creates window after the last terminal (before apps at 20+)
    # Starts in current directory (captured before window creation) and applies theme colors
    # Use #{session_name} for dynamic session reference
    subprocess.run([
        "tmux", "bind-key", "-n", "C-t",
        "run-shell",
        "s=$(tmux display -p '#{session_name}') && "
        "current_dir=$(tmux display -p '#{pane_current_path}') && "
        "tmux set-option -t \"$s\" @term_count $(($(tmux show-option -t \"$s\" -v @term_count) + 1)) && "
        "tmux new-window -t \"$s\" -n T$(tmux show-option -t \"$s\" -v @term_count) -c \"$current_dir\" && "
        "tmux set-option -w window-style \"bg=$(tmux show-option -t \"$s\" -v @theme_bg),fg=$(tmux show-option -t \"$s\" -v @theme_fg)\" && "
        "tmux set-option -w window-active-style \"bg=$(tmux show-option -t \"$s\" -v @theme_bg),fg=$(tmux show-option -t \"$s\" -v @theme_fg)\" && "
        "tmux send-keys \" clear\" Enter"
    ])

    # Ctrl+X = Close current terminal (only dynamic ones, windows 2-19)
    # Leaves Ctrl+W free for Claude Code and other apps
    subprocess.run([
        "tmux", "bind-key", "-n", "C-x",
        "if-shell", "-F", "#{&&:#{e|>:#{window_index},1},#{e|<:#{window_index},20}}",
        "kill-window",
        "display-message 'Cannot close this window'"
    ])

    # Ctrl+P = Quick input popup (sends to F1) with autocomplete and AI enhancement
    popup_style = f"bg={theme['bg']},fg={theme['fg']}"
    subprocess.run([
        "tmux", "bind-key", "-n", "C-p",
        "display-popup", "-E", "-w", "80%", "-h", "30%",
        "-s", popup_style, "-S", popup_style,
        f"uv run python3 '{QUICK_INPUT_SCRIPT}'"
    ])

    # F12 = Toggle key passthrough mode
    # When passthrough is ON: F-keys go to the app, status shows "PASSTHROUGH"
    # When passthrough is OFF: F-keys switch windows (normal mode)
    # Use `:N` syntax for current session window selection (session-agnostic)
    toggle_cmd = (
        "if-shell -F '#{@passthrough}' "
        "'set-option @passthrough \"\" ; "
        "bind-key -n F1 select-window -t :1 ; "
        "bind-key -n F2 select-window -t :20 ; "
        "bind-key -n F3 select-window -t :21 ; "
        "bind-key -n F4 select-window -t :22 ; "
        "bind-key -n F5 select-window -t :23 ; "
        "bind-key -n F6 select-window -t :24 ; "
        "bind-key -n F7 select-window -t :25 ; "
        "bind-key -n F8 select-window -t :26 ; "
        "bind-key -n F9 select-window -t :27 ; "
        "bind-key -n F10 confirm-before -p \"Exit session? (y/n)\" \"kill-session\"' "
        "'set-option @passthrough \"PASSTHROUGH \" ; "
        "unbind-key -n F1 ; unbind-key -n F2 ; unbind-key -n F3 ; "
        "unbind-key -n F4 ; unbind-key -n F5 ; unbind-key -n F6 ; "
        "unbind-key -n F7 ; unbind-key -n F8 ; unbind-key -n F9 ; unbind-key -n F10'"
    )
    subprocess.run(["tmux", "bind-key", "-n", "F12", toggle_cmd])

    # Mouse click handlers for status bar shortcuts
    # When clicking on #[range=user|X], #{mouse_status_range} contains X
    # Clicking on window names (range=window|X) automatically selects the window
    # For user-defined ranges, we dispatch to the appropriate action
    # pathpopup opens a popup menu to select parent directory
    # Use session-agnostic commands (no hardcoded session name)
    subprocess.run([
        "tmux", "bind-key", "-T", "root", "MouseUp1Status",
        "run-shell",
        "case '#{mouse_status_range}' in "
        f"session) tmux display-popup -E -w 100% -h 100% \"uv run python3 '{SESSION_MANAGER_SCRIPT}'\" ;; "
        "f10) tmux confirm-before -p 'Exit session? (y/n)' 'kill-session' ;; "
        "help) tmux send-keys C-h ;; "
        "f12) tmux send-keys F12 ;; "
        f"pathpopup) tmux display-popup -E -w 60% -h 50% \"uv run python3 '{PATH_SEGMENTS_SCRIPT}' menu\" ;; "
        "gitwindow) tmux select-window -t :25 ;; "
        "*) tmux select-window -t '#{mouse_window}' 2>/dev/null || true ;; "
        "esac"
    ])

    # Select terminal window (1)
    subprocess.run(["tmux", "select-window", "-t", f"{SESSION}:1"])

    # Register cleanup to kill session on exit
    cleanup_done = False

    def cleanup():
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        # Check if session still exists before cleanup
        result = subprocess.run(
            ["tmux", "has-session", "-t", SESSION],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL
        )
        if result.returncode != 0:
            # Session already dead (e.g., killed via F10), nothing to do
            # Key bindings are now session-agnostic, so they remain valid for other sessions
            return

        # Kill the session (bindings are session-agnostic and remain valid)
        subprocess.run(["tmux", "kill-session", "-t", SESSION], stderr=subprocess.DEVNULL)

        # Only unbind keys if no other claude-ide sessions exist
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#{session_name}"],
            capture_output=True, text=True, stderr=subprocess.DEVNULL
        )
        remaining_sessions = [s for s in result.stdout.strip().split('\n') if s.startswith('claude-ide-')]
        if not remaining_sessions:
            # Last IDE session, unbind global keys
            for key in ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F12",
                        "S-F1", "S-F2", "S-F3", "S-F4", "S-F5", "S-F6", "S-F7", "S-F8", "S-F9",
                        "C-t", "C-h", "C-x", "C-p", "C-s", "S-Left", "S-Right"]:
                subprocess.run(["tmux", "unbind-key", "-n", key], stderr=subprocess.DEVNULL)
            subprocess.run(["tmux", "unbind-key", "-T", "root", "MouseUp1Status"], stderr=subprocess.DEVNULL)

    def signal_handler(signum, frame):
        cleanup()
        sys.exit(0)

    atexit.register(cleanup)
    signal.signal(signal.SIGHUP, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Attach (using subprocess so we regain control after detach/exit)
    subprocess.run(["tmux", "attach-session", "-t", SESSION])

    # Session ends here - cleanup runs via atexit

    # Session ends here - cleanup runs via atexit


if __name__ == "__main__":
    main()
