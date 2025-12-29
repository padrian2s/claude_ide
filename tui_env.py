#!/usr/bin/env python3
"""TUI Demo launcher - tmux with tree + terminal + lizard-tui as separate windows."""

import atexit
import os
import signal
import subprocess
from pathlib import Path

SESSION = f"tui-demo-{os.getpid()}"
SCRIPT_DIR = Path(__file__).parent
TREE_SCRIPT = SCRIPT_DIR / "tree_view.py"
LIZARD_SCRIPT = SCRIPT_DIR / "lizard_tui.py"
CONFIG_SCRIPT = SCRIPT_DIR / "config_panel.py"

# Import config to get saved theme
from config_panel import get_theme_colors


def main():
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

    # Create Window 2 = Terminal 2
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:2", "-n", "Term2"])

    # Create Window 3 = Tree + Viewer
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:3", "-n", "Tree"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:3",
        f" python3 '{TREE_SCRIPT}'", "Enter"
    ])

    # Create Window 4 = Lizard TUI
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:4", "-n", "Lizard"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:4",
        f" python3 '{LIZARD_SCRIPT}'", "Enter"
    ])

    # Create Window 5 = Glow
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:5", "-n", "Glow"])
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:5", " glow", "Enter"])

    # Create Window 9 = Config
    subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:9", "-n", "Config"])
    subprocess.run([
        "tmux", "send-keys", "-t", f"{SESSION}:9",
        f" python3 '{CONFIG_SCRIPT}'", "Enter"
    ])

    # Load saved theme
    theme = get_theme_colors()

    # Enable focus events for focus tracking
    subprocess.run(["tmux", "set-option", "-t", SESSION, "focus-events", "on"])

    # Set up focus indicator variable (global so hooks can modify it)
    subprocess.run(["tmux", "set-option", "-g", "@focus", ""])

    # Hooks to update focus indicator
    subprocess.run(["tmux", "set-hook", "-g", "client-focus-in",
        "set-option -g @focus ''"])
    subprocess.run(["tmux", "set-hook", "-g", "client-focus-out",
        "set-option -g @focus 'UNFOCUSED '"])

    # Status bar
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "on"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-interval", "1"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-style", f"bg={theme['bg']},fg={theme['fg']}"])
    subprocess.run(["tmux", "set-window-option", "-t", SESSION, "window-status-format", " F#I:#W "])
    subprocess.run(["tmux", "set-window-option", "-t", SESSION, "window-status-current-format", "#[bg=cyan,fg=black,bold] F#I:#W #[default]"])
    subprocess.run([
        "tmux", "set-option", "-t", SESSION, "status-format[0]",
        "#{@focus}#{@passthrough}#[align=centre]"
        "#{W:"
        "#{?window_active,#[bg=cyan#,fg=black#,bold] F#{window_index}:#{window_name} #[default], F#{window_index}:#{window_name} }"
        "} F10:Exit F12:Keys"
    ])
    # Hide F9:Config from automatic list (it shows in #{W} already)

    # Key passthrough mode variable (empty = normal, has value = passthrough)
    subprocess.run(["tmux", "set-option", "-t", SESSION, "@passthrough", ""])

    # Bind F-keys to windows
    subprocess.run(["tmux", "bind-key", "-n", "F1", "select-window", "-t", f"{SESSION}:1"])
    subprocess.run(["tmux", "bind-key", "-n", "F2", "select-window", "-t", f"{SESSION}:2"])
    subprocess.run(["tmux", "bind-key", "-n", "F3", "select-window", "-t", f"{SESSION}:3"])
    subprocess.run(["tmux", "bind-key", "-n", "F4", "select-window", "-t", f"{SESSION}:4"])
    subprocess.run(["tmux", "bind-key", "-n", "F5", "select-window", "-t", f"{SESSION}:5"])
    subprocess.run(["tmux", "bind-key", "-n", "F9", "select-window", "-t", f"{SESSION}:9"])

    # F10 = Exit (kill session)
    subprocess.run(["tmux", "bind-key", "-n", "F10", "kill-session", "-t", SESSION])

    # Shift+Arrow keys to navigate windows (always active, even in passthrough mode)
    subprocess.run(["tmux", "bind-key", "-n", "S-Left", "previous-window"])
    subprocess.run(["tmux", "bind-key", "-n", "S-Right", "next-window"])

    # F12 = Toggle key passthrough mode
    # When passthrough is ON: F-keys go to the app, status shows "PASSTHROUGH"
    # When passthrough is OFF: F-keys switch windows (normal mode)
    toggle_cmd = (
        f"if-shell -F '#{{@passthrough}}' "
        f"'set-option -t {SESSION} @passthrough \"\" ; "
        f"bind-key -n F1 select-window -t {SESSION}:1 ; "
        f"bind-key -n F2 select-window -t {SESSION}:2 ; "
        f"bind-key -n F3 select-window -t {SESSION}:3 ; "
        f"bind-key -n F4 select-window -t {SESSION}:4 ; "
        f"bind-key -n F5 select-window -t {SESSION}:5 ; "
        f"bind-key -n F9 select-window -t {SESSION}:9 ; "
        f"bind-key -n F10 kill-session -t {SESSION}' "
        f"'set-option -t {SESSION} @passthrough \"PASSTHROUGH \" ; "
        f"unbind-key -n F1 ; unbind-key -n F2 ; unbind-key -n F3 ; "
        f"unbind-key -n F4 ; unbind-key -n F5 ; unbind-key -n F9 ; "
        f"unbind-key -n F10'"
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


if __name__ == "__main__":
    main()
