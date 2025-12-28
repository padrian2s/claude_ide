#!/usr/bin/env python3
"""TUI Demo launcher - tmux with tree + terminal + lizard-tui as separate windows."""

import os
import subprocess
from pathlib import Path

SESSION = "tui-demo"
SCRIPT_DIR = Path(__file__).parent
TREE_SCRIPT = SCRIPT_DIR / "tree_view.py"
LIZARD_SCRIPT = SCRIPT_DIR / "lizard_tui.py"


def main():
    # Kill existing session
    subprocess.run(["tmux", "kill-session", "-t", SESSION],
                   stderr=subprocess.DEVNULL)

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

    # Status bar - simple, no colors
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status", "on"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-style", "bg=default,fg=default"])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-left", ""])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-right", ""])
    subprocess.run(["tmux", "set-option", "-t", SESSION, "status-justify", "centre"])
    subprocess.run(["tmux", "set-window-option", "-t", SESSION, "window-status-format", " F#I:#W "])
    subprocess.run(["tmux", "set-window-option", "-t", SESSION, "window-status-current-format", " [F#I:#W] "])
    subprocess.run([
        "tmux", "set-option", "-t", SESSION, "status-format[0]",
        "#[align=centre]#{W: F#{window_index}:#{window_name} }"
    ])

    # Bind F1/F2/F3/F4 to windows 1/2/3/4
    subprocess.run(["tmux", "bind-key", "-n", "F1", "select-window", "-t", f"{SESSION}:1"])
    subprocess.run(["tmux", "bind-key", "-n", "F2", "select-window", "-t", f"{SESSION}:2"])
    subprocess.run(["tmux", "bind-key", "-n", "F3", "select-window", "-t", f"{SESSION}:3"])
    subprocess.run(["tmux", "bind-key", "-n", "F4", "select-window", "-t", f"{SESSION}:4"])
    subprocess.run(["tmux", "bind-key", "-n", "F5", "select-window", "-t", f"{SESSION}:5"])

    # Select terminal window (1)
    subprocess.run(["tmux", "select-window", "-t", f"{SESSION}:1"])

    # Attach
    os.execvp("tmux", ["tmux", "attach-session", "-t", SESSION])


if __name__ == "__main__":
    main()
