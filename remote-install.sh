#!/bin/bash
# Remote installer for TUI Environment
# Usage: curl -fsSL https://raw.githubusercontent.com/padrian2s/my_env/main/remote-install.sh | bash
set -e

# Colors
R='\033[0;31m'
G='\033[0;32m'
C='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

REPO="https://github.com/padrian2s/my_env.git"
INSTALL_DIR="$HOME/.tui-env"

echo
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}    ${BOLD}TUI Environment Installer${NC}       ${C}│${NC}"
echo -e "${C}╰─────────────────────────────────────╯${NC}"
echo

# Check for git
if ! command -v git &> /dev/null; then
    echo -e "  ${R}✗${NC} git is required but not installed"
    exit 1
fi

# Clone or update repo
if [ -d "$INSTALL_DIR" ]; then
    echo -e "  ${C}→${NC} Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet origin main
    echo -e "  ${G}✓${NC} Updated to latest version"
else
    echo -e "  ${C}→${NC} Cloning repository..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
    echo -e "  ${G}✓${NC} Cloned to ${DIM}$INSTALL_DIR${NC}"
fi

echo

# Run local installer
cd "$INSTALL_DIR"
bash install.sh
