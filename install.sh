#!/bin/bash
# TUI Environment Installer
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="tui"

# Colors
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
B='\033[0;34m'
C='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Symbols
CHECK="${G}✓${NC}"
CROSS="${R}✗${NC}"
ARROW="${C}→${NC}"
SPIN='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

clear

# Header
echo
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}    ${BOLD}TUI Environment Installer${NC}       ${C}│${NC}"
echo -e "${C}╰─────────────────────────────────────╯${NC}"
echo

# Spinner function
spin() {
    local pid=$1
    local msg=$2
    local i=0
    while kill -0 $pid 2>/dev/null; do
        printf "\r  ${C}${SPIN:i++%10:1}${NC} ${msg}..."
        sleep 0.1
    done
    wait $pid
    return $?
}

# Status line
status() {
    local icon=$1
    local msg=$2
    printf "\r  ${icon} ${msg}                    \n"
}

# Check OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    SHELL_RC="$HOME/.zshrc"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    SHELL_RC="$HOME/.bashrc"
    [[ -f "$HOME/.zshrc" ]] && SHELL_RC="$HOME/.zshrc"
else
    status "$CROSS" "Unsupported OS: $OSTYPE"
    exit 1
fi

echo -e "  ${DIM}Detected: $OS${NC}"
echo

# Step 1: Python
echo -e "${BOLD}Dependencies${NC}"
echo -e "${DIM}────────────${NC}"

if command -v python3 &> /dev/null; then
    PY_VER=$(python3 --version 2>&1 | cut -d' ' -f2)
    status "$CHECK" "Python 3 ${DIM}($PY_VER)${NC}"
else
    status "$CROSS" "Python 3 not found"
    echo -e "\n  ${Y}Install Python 3.8+ and try again${NC}\n"
    exit 1
fi

# Step 2: tmux
if command -v tmux &> /dev/null; then
    TMUX_VER=$(tmux -V | cut -d' ' -f2)
    status "$CHECK" "tmux ${DIM}($TMUX_VER)${NC}"
else
    printf "  ${C}⠋${NC} Installing tmux..."
    if [[ "$OS" == "macos" ]]; then
        brew install tmux > /dev/null 2>&1 &
    else
        (sudo apt-get update && sudo apt-get install -y tmux) > /dev/null 2>&1 &
    fi
    spin $! "Installing tmux"
    status "$CHECK" "tmux installed"
fi

# Step 3: Python packages
printf "  ${C}⠋${NC} Installing textual..."
pip3 install --quiet --upgrade textual 2>/dev/null &
spin $! "Installing textual"
status "$CHECK" "textual"

echo

# Step 4: Permissions
echo -e "${BOLD}Setup${NC}"
echo -e "${DIM}─────${NC}"

chmod +x "$SCRIPT_DIR/start.sh"
chmod +x "$SCRIPT_DIR/tui_demo.py"
chmod +x "$SCRIPT_DIR/tree_view.py"
chmod +x "$SCRIPT_DIR/lizard_tui.py" 2>/dev/null || true
status "$CHECK" "Scripts marked executable"

# Step 5: Create alias
ALIAS_LINE="alias $APP_NAME='$SCRIPT_DIR/start.sh'"

if grep -q "alias $APP_NAME=" "$SHELL_RC" 2>/dev/null; then
    # Update existing alias
    if [[ "$OS" == "macos" ]]; then
        sed -i '' "s|alias $APP_NAME=.*|$ALIAS_LINE|" "$SHELL_RC"
    else
        sed -i "s|alias $APP_NAME=.*|$ALIAS_LINE|" "$SHELL_RC"
    fi
    status "$CHECK" "Updated alias in ${DIM}$(basename $SHELL_RC)${NC}"
else
    # Add new alias
    echo "" >> "$SHELL_RC"
    echo "# TUI Environment" >> "$SHELL_RC"
    echo "$ALIAS_LINE" >> "$SHELL_RC"
    status "$CHECK" "Added alias to ${DIM}$(basename $SHELL_RC)${NC}"
fi

echo

# Done
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}  ${G}${BOLD}Installation complete!${NC}             ${C}│${NC}"
echo -e "${C}╰─────────────────────────────────────╯${NC}"
echo
echo -e "  ${BOLD}Quick start:${NC}"
echo -e "  ${ARROW} Run ${C}source $(basename $SHELL_RC)${NC} or open a new terminal"
echo -e "  ${ARROW} Then type ${C}${APP_NAME}${NC} to launch"
echo
echo -e "  ${BOLD}Keys:${NC}"
echo -e "  ${DIM}F1${NC} Terminal    ${DIM}F2${NC} Terminal 2"
echo -e "  ${DIM}F3${NC} File Tree   ${DIM}F4${NC} Lizard TUI"
echo -e "  ${DIM}Ctrl+B d${NC} Detach"
echo
