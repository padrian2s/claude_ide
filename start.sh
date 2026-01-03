#!/bin/bash
# Capture the directory where the TUI was invoked
START_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
uv run --project "$SCRIPT_DIR" python3 tui_env.py "$START_DIR"
