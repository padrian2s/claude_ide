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
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
else
    status "$CROSS" "Unsupported OS: $OSTYPE"
    exit 1
fi

# Detect user's actual shell for RC file
CURRENT_SHELL=$(basename "$SHELL")
case "$CURRENT_SHELL" in
    zsh)
        SHELL_RC="$HOME/.zshrc"
        ;;
    bash)
        SHELL_RC="$HOME/.bashrc"
        # Create .bashrc if it doesn't exist
        if [[ ! -f "$SHELL_RC" ]]; then
            touch "$SHELL_RC"
        fi
        ;;
    fish)
        SHELL_RC="$HOME/.config/fish/config.fish"
        mkdir -p "$(dirname "$SHELL_RC")"
        ;;
    *)
        # Fallback: try to detect from existing RC files
        if [[ -f "$HOME/.zshrc" ]]; then
            SHELL_RC="$HOME/.zshrc"
        elif [[ -f "$HOME/.bashrc" ]]; then
            SHELL_RC="$HOME/.bashrc"
        else
            SHELL_RC="$HOME/.bashrc"
        fi
        ;;
esac

echo -e "  ${DIM}Detected: $OS, shell: $CURRENT_SHELL → $(basename $SHELL_RC)${NC}"
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

# Step 2b: fzf
if command -v fzf &> /dev/null; then
    FZF_VER=$(fzf --version | cut -d' ' -f1)
    status "$CHECK" "fzf ${DIM}($FZF_VER)${NC}"
else
    printf "  ${C}⠋${NC} Installing fzf..."
    if [[ "$OS" == "macos" ]]; then
        brew install fzf > /dev/null 2>&1 &
    else
        (sudo apt-get install -y fzf) > /dev/null 2>&1 &
    fi
    spin $! "Installing fzf"
    status "$CHECK" "fzf installed"
fi

# Step 2c: ripgrep
if command -v rg &> /dev/null; then
    RG_VER=$(rg --version | head -1 | cut -d' ' -f2)
    status "$CHECK" "ripgrep ${DIM}($RG_VER)${NC}"
else
    printf "  ${C}⠋${NC} Installing ripgrep..."
    if [[ "$OS" == "macos" ]]; then
        brew install ripgrep > /dev/null 2>&1 &
    else
        (sudo apt-get install -y ripgrep) > /dev/null 2>&1 &
    fi
    spin $! "Installing ripgrep"
    status "$CHECK" "ripgrep installed"
fi

# Step 3: uv (Python package manager)
if command -v uv &> /dev/null; then
    UV_VER=$(uv --version | cut -d' ' -f2)
    status "$CHECK" "uv ${DIM}($UV_VER)${NC}"
else
    echo -ne "  ${C}◦${NC} Installing uv..."
    if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh >/dev/null 2>&1; then
        # Add uv to PATH for this session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        if command -v uv &> /dev/null; then
            status "$CHECK" "uv installed"
        else
            echo ""
            status "$CROSS" "uv not found in PATH after install"
            exit 1
        fi
    else
        echo ""
        status "$CROSS" "Failed to install uv"
        echo -e "\n  ${Y}Install uv manually: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}\n"
        exit 1
    fi
fi

# Step 4: Python packages via uv
echo -ne "  ${C}◦${NC} Installing Python packages..."
# Use --break-system-packages for PEP 668 compliance on Debian/Ubuntu
UV_OUTPUT=$(uv pip install --system --break-system-packages textual prompt-toolkit 2>&1)
if [ $? -eq 0 ]; then
    status "$CHECK" "textual + prompt-toolkit"
else
    echo ""
    status "$CROSS" "Failed to install packages"
    echo -e "\n  ${DIM}Error: $UV_OUTPUT${NC}\n"
    exit 1
fi

echo

# Step 5: Permissions
echo -e "${BOLD}Setup${NC}"
echo -e "${DIM}─────${NC}"

chmod +x "$SCRIPT_DIR/start.sh"
chmod +x "$SCRIPT_DIR/tui_env.py"
chmod +x "$SCRIPT_DIR/tree_view.py"
chmod +x "$SCRIPT_DIR/config_panel.py"
chmod +x "$SCRIPT_DIR/favorites.py"
chmod +x "$SCRIPT_DIR/lizard_tui.py" 2>/dev/null || true
status "$CHECK" "Scripts marked executable"

# Step 6: Create alias (shell-specific syntax)
if [[ "$CURRENT_SHELL" == "fish" ]]; then
    ALIAS_LINE="alias $APP_NAME '$SCRIPT_DIR/start.sh'"
    ALIAS_PATTERN="alias $APP_NAME "
else
    ALIAS_LINE="alias $APP_NAME='$SCRIPT_DIR/start.sh'"
    ALIAS_PATTERN="alias $APP_NAME="
fi

if grep -q "$ALIAS_PATTERN" "$SHELL_RC" 2>/dev/null; then
    # Update existing alias
    if [[ "$OS" == "macos" ]]; then
        sed -i '' "s|${ALIAS_PATTERN}.*|$ALIAS_LINE|" "$SHELL_RC"
    else
        sed -i "s|${ALIAS_PATTERN}.*|$ALIAS_LINE|" "$SHELL_RC"
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
if [[ "$CURRENT_SHELL" == "fish" ]]; then
    echo -e "  ${ARROW} Run ${C}source $SHELL_RC${NC} or open a new terminal"
else
    echo -e "  ${ARROW} Run ${C}source ~/${SHELL_RC##*/}${NC} or open a new terminal"
fi
echo -e "  ${ARROW} Then type ${C}${APP_NAME}${NC} to launch"
echo
echo -e "  ${BOLD}Keys:${NC}"
echo -e "  ${DIM}F1${NC} Terminal    ${DIM}F2${NC} Terminal 2   ${DIM}F9${NC} Config"
echo -e "  ${DIM}F3${NC} File Tree   ${DIM}F4${NC} Lizard TUI   ${DIM}F10${NC} Exit"
echo -e "  ${DIM}F5${NC} Glow        ${DIM}F6${NC} Favorites    ${DIM}F12${NC} Keys Toggle"
echo
