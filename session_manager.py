#!/usr/bin/env python3
"""Session manager for Claude IDE - switch or kill sessions."""

import re
import subprocess
import sys
from datetime import datetime


def get_sessions():
    """Get list of claude-ide sessions with their info."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}|#{session_created}|#{session_attached}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.strip().split('\n'):
        if not line or '|' not in line:
            continue
        parts = line.split('|')
        if len(parts) >= 3 and parts[0].startswith('claude-ide-'):
            name = parts[0]
            created_ts = int(parts[1])
            attached = parts[2] == '1'
            created_dt = datetime.fromtimestamp(created_ts)
            sessions.append({
                'name': name,
                'created': created_dt,
                'attached': attached,
                'pid': name.replace('claude-ide-', '')
            })

    # Sort by creation time (newest first)
    sessions.sort(key=lambda x: x['created'], reverse=True)
    return sessions


def get_current_session():
    """Get the current session name."""
    result = subprocess.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def switch_session(name):
    """Switch to a session."""
    subprocess.run(["tmux", "switch-client", "-t", name])


def kill_session(name):
    """Kill a session."""
    subprocess.run(["tmux", "kill-session", "-t", name])


def main():
    """Main entry point - uses fzf for selection."""
    sessions = get_sessions()
    current = get_current_session()

    if not sessions:
        print("No claude-ide sessions found.")
        return

    if len(sessions) == 1 and sessions[0]['name'] == current:
        print("Only one session (current). Nothing to switch to.")
        return

    # Build fzf input with formatted session info
    lines = []
    for s in sessions:
        marker = "* " if s['name'] == current else "  "
        created_str = s['created'].strftime("%Y-%m-%d %H:%M:%S")
        attached_str = "(attached)" if s['attached'] else ""
        line = f"{marker}{s['name']}  |  {created_str}  {attached_str}"
        lines.append(line)

    # Header with instructions
    header = "Enter=Switch | Ctrl-D=Kill | Esc=Cancel"

    # Preview command: capture active pane content from session
    preview_cmd = """sess=$(echo {} | grep -o 'claude-ide-[0-9]*'); \
tmux capture-pane -t "$sess" -p 2>/dev/null"""

    # Run fzf with kill binding and preview (fullscreen)
    fzf_input = '\n'.join(lines)
    result = subprocess.run(
        [
            "fzf",
            "--ansi",
            "--header", header,
            "--expect", "ctrl-d",
            "--no-multi",
            "--reverse",
            "--height", "100%",
            "--border",
            "--prompt", "Session> ",
            "--preview", preview_cmd,
            "--preview-window", "right:70%",
        ],
        input=fzf_input,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return  # Cancelled

    output_lines = result.stdout.strip().split('\n')
    if not output_lines or not output_lines[-1]:
        return

    # With --expect, first line is the key pressed (empty for Enter), rest is selection
    if len(output_lines) >= 2:
        action = output_lines[0]  # 'ctrl-d' or empty for Enter
        selected_line = output_lines[1]
    else:
        action = ''
        selected_line = output_lines[0]

    # Extract session name from selected line
    # Format: "* claude-ide-12345  |  2024-01-07 ..." or "  claude-ide-12345  |  ..."
    # Find the session name (starts with claude-ide-)
    match = re.search(r'(claude-ide-\d+)', selected_line)
    if not match:
        return
    session_name = match.group(1)

    if action == 'ctrl-d':
        # Kill the session
        if session_name == current:
            print(f"Cannot kill current session. Use F10 to exit.")
        else:
            kill_session(session_name)
            print(f"Killed: {session_name}")
    else:
        # Switch to the session
        if session_name != current:
            switch_session(session_name)


if __name__ == "__main__":
    main()
