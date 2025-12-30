#!/bin/bash
# Claude IDE Installer
# Usage: curl -fsSL https://claude-ide.org/install | bash
set -e

# Colors
R='\033[0;31m'
G='\033[0;32m'
C='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

REPO="https://github.com/padrian2s/claude_ide.git"
INSTALL_DIR="$HOME/.claude-ide"

echo
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}      ${BOLD}Claude IDE Installer${NC}           ${C}│${NC}"
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

# Run local installer from file (not piped) to avoid stdin conflicts
cd "$INSTALL_DIR"
exec bash install.sh </dev/null
