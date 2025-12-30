#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
uv run --project "$SCRIPT_DIR" python3 tui_env.py
