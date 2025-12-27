#!/bin/bash
cd "$(dirname "$0")"
tmux kill-session -t tui-demo 2>/dev/null
python3 tui_demo.py
