#!/bin/bash
# Claude IDE - Multi-window terminal IDE using tmux

ORIG_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

show_help() {
    cat << 'EOF'
tui - Claude IDE launcher

Usage:
  tui                      Start in current directory (auto-named session)
  tui <path>               Start in given directory (auto-named session)
  tui <name> <path>        Start/attach to named session in given directory

Options:
  -h, --help               Show this help message
  --no-attach              Create session without attaching (for ttyd/external use)

Examples:
  tui                      Start IDE in current directory
  tui ~/projects/myapp     Start IDE in myapp directory
  tui myapp ~/projects/myapp
                           Create or attach to session 'myapp'

Session behavior:
  - Auto-named sessions (no name given) are killed when you detach
  - Named sessions persist after detach and can be reattached
  - Running 'tui myapp ...' again attaches to existing 'myapp' session

Key bindings (while in IDE):
  F1-F9                    Switch windows (Terminal, Tree, Apps...)
  Ctrl+H                   Show full keyboard shortcuts help
  F10                      Exit session
EOF
}

# Parse arguments
NO_ATTACH=""
ARGS=()

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            show_help
            exit 0
            ;;
        --no-attach)
            NO_ATTACH="--no-attach"
            ;;
        *)
            ARGS+=("$arg")
            ;;
    esac
done

if [ ${#ARGS[@]} -eq 0 ]; then
    # No args: use original directory (captured before cd)
    uv run --project "$SCRIPT_DIR" python3 tui_env.py "$ORIG_DIR" $NO_ATTACH
elif [ ${#ARGS[@]} -eq 1 ]; then
    # One arg: directory path
    uv run --project "$SCRIPT_DIR" python3 tui_env.py "${ARGS[0]}" $NO_ATTACH
else
    # Two args: session name and directory
    uv run --project "$SCRIPT_DIR" python3 tui_env.py "${ARGS[0]}" "${ARGS[1]}" $NO_ATTACH
fi
