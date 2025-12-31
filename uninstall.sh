#!/bin/bash
# Claude IDE Uninstaller
set -e

# Colors
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

INSTALL_DIR="$HOME/.claude-ide"
APP_NAME="tui"

echo
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}      ${BOLD}Claude IDE Uninstaller${NC}         ${C}│${NC}"
echo -e "${C}╰─────────────────────────────────────╯${NC}"
echo

# Confirm
echo -e "  ${Y}This will remove:${NC}"
echo -e "  ${DIM}- $INSTALL_DIR${NC}"
echo -e "  ${DIM}- '$APP_NAME' alias from shell config${NC}"
echo
read -p "  Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "  ${DIM}Cancelled${NC}"
    exit 0
fi

echo

# Detect shell RC file
CURRENT_SHELL=$(basename "$SHELL")
case "$CURRENT_SHELL" in
    zsh)  SHELL_RC="$HOME/.zshrc" ;;
    bash) SHELL_RC="$HOME/.bashrc" ;;
    fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
    *)    SHELL_RC="$HOME/.bashrc" ;;
esac

# Remove alias from shell config
if [ -f "$SHELL_RC" ]; then
    if grep -q "alias $APP_NAME=" "$SHELL_RC" 2>/dev/null || grep -q "alias $APP_NAME " "$SHELL_RC" 2>/dev/null; then
        # Remove the alias line and the comment above it
        if [[ "$(uname)" == "Darwin" ]]; then
            sed -i '' "/# Claude IDE/d" "$SHELL_RC"
            sed -i '' "/# TUI Environment/d" "$SHELL_RC"
            sed -i '' "/alias $APP_NAME=/d" "$SHELL_RC"
            sed -i '' "/alias $APP_NAME /d" "$SHELL_RC"
        else
            sed -i "/# Claude IDE/d" "$SHELL_RC"
            sed -i "/# TUI Environment/d" "$SHELL_RC"
            sed -i "/alias $APP_NAME=/d" "$SHELL_RC"
            sed -i "/alias $APP_NAME /d" "$SHELL_RC"
        fi
        echo -e "  ${G}✓${NC} Removed alias from ${DIM}$(basename $SHELL_RC)${NC}"
    else
        echo -e "  ${DIM}○${NC} No alias found in $(basename $SHELL_RC)"
    fi
fi

# Remove install directory
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo -e "  ${G}✓${NC} Removed ${DIM}$INSTALL_DIR${NC}"
else
    echo -e "  ${DIM}○${NC} Directory not found: $INSTALL_DIR"
fi

# Also clean up old .tui-env if it exists
if [ -d "$HOME/.tui-env" ]; then
    rm -rf "$HOME/.tui-env"
    echo -e "  ${G}✓${NC} Removed old ${DIM}~/.tui-env${NC}"
fi

echo
echo -e "${C}╭─────────────────────────────────────╮${NC}"
echo -e "${C}│${NC}  ${G}${BOLD}Uninstall complete!${NC}               ${C}│${NC}"
echo -e "${C}╰─────────────────────────────────────╯${NC}"
echo
echo -e "  ${DIM}Run 'source ~/${SHELL_RC##*/}' or open a new terminal${NC}"
echo
