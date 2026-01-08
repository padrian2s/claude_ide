#!/usr/bin/env python3
"""Path navigation popup for tmux status bar."""
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime


def get_git_info(path: str) -> dict | None:
    """Get git branch and status info for path. Returns None if not a git repo."""
    try:
        # Check if in a git repo
        result = subprocess.run(
            ["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None

        # Get branch name
        result = subprocess.run(
            ["git", "-C", path, "branch", "--show-current"],
            capture_output=True, text=True, timeout=2
        )
        branch = result.stdout.strip()

        # If empty (detached HEAD), get short commit hash
        if not branch:
            result = subprocess.run(
                ["git", "-C", path, "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=2
            )
            branch = result.stdout.strip()[:7] if result.stdout.strip() else "HEAD"

        # Check if dirty (has uncommitted changes)
        result = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=2
        )
        is_dirty = bool(result.stdout.strip())

        return {
            "branch": branch,
            "is_main": branch in ("main", "master"),
            "is_dirty": is_dirty
        }
    except (subprocess.TimeoutExpired, Exception):
        return None


def get_pane_path():
    """Get current pane's working directory."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{pane_current_path}"],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def get_project_path():
    """Get the IDE's project directory (consistent across all windows)."""
    result = subprocess.run(
        ["tmux", "show-option", "-v", "@start_dir"],
        capture_output=True, text=True
    )
    path = result.stdout.strip()
    # Fallback to pane path if @start_dir not set
    return path if path else get_pane_path()

def get_dirs_sorted(path: str, sort_by: str = "name") -> list[tuple[str, str]]:
    """Get directories in path sorted by criteria.
    Returns list of (display_name, full_path) tuples.
    """
    p = Path(path)
    if not p.exists():
        return []

    dirs = []
    try:
        for item in p.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                try:
                    stat = item.stat()
                    dirs.append({
                        'name': item.name,
                        'path': str(item),
                        'mtime': stat.st_mtime,
                        'ctime': stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_ctime,
                        'atime': stat.st_atime,
                    })
                except (PermissionError, OSError):
                    continue
    except PermissionError:
        return []

    # Sort based on criteria
    if sort_by == "name":
        dirs.sort(key=lambda x: x['name'].lower())
    elif sort_by == "modified":
        dirs.sort(key=lambda x: x['mtime'], reverse=True)
    elif sort_by == "created":
        dirs.sort(key=lambda x: x['ctime'], reverse=True)
    elif sort_by == "accessed":
        dirs.sort(key=lambda x: x['atime'], reverse=True)

    return [(d['name'], d['path']) for d in dirs]


def _change_dir_and_reload(path: str):
    """Change the IDE's working directory without restarting.
    
    This will:
    1. Update @start_dir tmux variable
    2. Exit Claude with /exit
    3. cd to new directory and restart Claude
    """
    # Get current session name
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    session = result.stdout.strip()
    
    # Update @start_dir for the session
    subprocess.run(["tmux", "set-option", "-t", session, "@start_dir", path])
    
    # Send /exit to Claude
    subprocess.run([
        "tmux", "send-keys", "-t", f"{session}:1",
        "/exit", "Enter"
    ])
    
    # After delay (3s for Claude to exit), cd to new path and restart Claude
    subprocess.run([
        "tmux", "run-shell", "-b",
        f"sleep 3 && tmux send-keys -t {session}:1 \" cd '{path}' && clear && claude\" Enter"
    ])

def show_path_menu():
    """Show popup menu with directory browser.
    
    Modes:
    - send: Send the full path to the terminal (default)
    - cd: Change directory and reload Claude
    """
    # Start from parent of tmux home directory (@start_dir) to show sibling dirs
    project_path = get_project_path()
    if not project_path:
        project_path = os.path.expanduser("~")
    browse_path = str(Path(project_path).parent)

    home = os.path.expanduser("~")

    sort_modes = ["name", "modified", "created", "accessed"]
    sort_idx = 0
    action_mode = "send"  # "send" = send path, "cd" = change directory

    while True:
        sort_mode = sort_modes[sort_idx]
        
        # Get directories
        dirs = get_dirs_sorted(browse_path, sort_mode)

        # Build display list
        lines = []
        # Add parent navigation
        parent = str(Path(browse_path).parent)
        if browse_path != "/":
            lines.append(f"..  (up to {parent})")

        # Add directories with metadata
        for name, full_path in dirs:
            try:
                stat = Path(full_path).stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                lines.append(f"{name:<40} {mtime}")
            except:
                lines.append(name)

        if not lines:
            lines.append("(empty)")

        # Show current path in header, controls at bottom
        display_path = browse_path.replace(home, "~") if browse_path.startswith(home) else browse_path
        
        # Mode indicator
        mode_indicator = "[SEND PATH]" if action_mode == "send" else "[CD+RELOAD]"
        bottom_label = f" [t]oggle:{mode_indicator} | ^S:sort({sort_mode}) "

        fzf_input = "\n".join(lines)

        result = subprocess.run(
            [
                "fzf",
                "--height=100%",
                "--layout=reverse",
                "--header", display_path,
                "--border=bottom",
                "--border-label", bottom_label,
                "--border-label-pos=bottom",
                "--prompt=select> ",
                "--expect=t,ctrl-s,left,right,enter",
                "--no-sort",  # We handle sorting ourselves
            ],
            input=fzf_input,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            # User cancelled
            return

        output_lines = result.stdout.strip().split("\n")
        if len(output_lines) < 1:
            return

        key = output_lines[0]
        selected = output_lines[1] if len(output_lines) > 1 else ""

        # Handle key presses
        if key == "ctrl-s":
            # Cycle through sort modes
            sort_idx = (sort_idx + 1) % len(sort_modes)
            continue
        elif key == "t":
            # Toggle action mode
            action_mode = "cd" if action_mode == "send" else "send"
            continue
        elif key == "left":
            # Go up one level
            if browse_path != "/":
                browse_path = str(Path(browse_path).parent)
            continue
        elif key == "right" or key == "enter":
            if not selected or selected == "(empty)":
                continue

            # Check if it's the parent navigation
            if selected.startswith(".."):
                if browse_path != "/":
                    browse_path = str(Path(browse_path).parent)
                continue

            # Extract directory name (before the date)
            dir_name = selected.split()[0] if selected else ""
            if not dir_name:
                continue

            selected_path = str(Path(browse_path) / dir_name)

            if key == "right":
                # Navigate into directory
                if Path(selected_path).is_dir():
                    browse_path = selected_path
                continue
            else:
                # Enter = select and perform action based on mode
                if action_mode == "send":
                    # Send path to terminal
                    subprocess.run(["tmux", "send-keys", "-t", ":1", selected_path])
                else:
                    # CD mode: change directory and reload Claude
                    _change_dir_and_reload(selected_path)
                return
        elif key == "":
            # Plain enter without expect key
            if not selected or selected == "(empty)":
                return
            if selected.startswith(".."):
                if browse_path != "/":
                    browse_path = str(Path(browse_path).parent)
                continue
            dir_name = selected.split()[0] if selected else ""
            if dir_name:
                selected_path = str(Path(browse_path) / dir_name)
                if action_mode == "send":
                    subprocess.run(["tmux", "send-keys", "-t", ":1", selected_path])
                else:
                    _change_dir_and_reload(selected_path)
            return

def format_status():
    """Format the current path for status bar display."""
    full_path = get_project_path()
    home = os.path.expanduser("~")

    # Replace home with ~
    display_path = full_path
    if full_path.startswith(home):
        display_path = "~" + full_path[len(home):]

    # Build the status string
    parts = []

    # Path (clickable to open directory browser)
    parts.append(f"#[dim]#[range=user|pathpopup]{display_path}#[norange]#[default]")

    # Git info (clickable to go to F7)
    git_info = get_git_info(full_path)
    if git_info:
        branch = git_info["branch"]
        is_main = git_info["is_main"]
        is_dirty = git_info["is_dirty"]

        # Icons: main=━, other branch=┣, dirty=●, clean=○
        if is_main:
            branch_icon = "━"  # main branch - straight line
            branch_display = ""  # don't show "main" name
        else:
            branch_icon = "┣"  # feature branch - branching line
            # Shorten branch name if too long
            branch_display = branch[:12] + "…" if len(branch) > 12 else branch

        status_icon = "●" if is_dirty else "○"  # dirty or clean

        # Color: dirty=yellow, clean=default dim
        if is_dirty:
            git_str = f"#[fg=yellow]#[range=user|gitwindow]{branch_icon}{branch_display}{status_icon}#[norange]#[default]"
        else:
            git_str = f"#[dim]#[range=user|gitwindow]{branch_icon}{branch_display}{status_icon}#[norange]#[default]"

        parts.append(git_str)

    return " ".join(parts)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "menu":
        show_path_menu()
    else:
        print(format_status())
