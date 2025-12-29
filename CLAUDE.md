# TUI Environment - Technical Solution

## Overview

Multi-window TUI environment using **tmux** as the window manager. Each window is a separate full-screen view, switched via F-keys.

## Architecture

```
tmux session "tui-demo-{pid}"
├── Window 1 (F1): Term1 - zsh shell
├── Window 2 (F2): Term2 - second zsh shell
├── Window 3 (F3): Tree + Viewer - Textual app (20% tree | 80% viewer)
├── Window 4 (F4): Lizard TUI - Python TUI app
├── Window 5 (F5): Glow - Markdown viewer
├── Window 6 (F6): Favs - Folder favorites browser
├── Window 9 (F9): Config - Theme selector panel
└── F10: Exit - kills session
```

## Why tmux?

Embedding a real PTY terminal inside Python TUI frameworks (Textual, urwid, prompt_toolkit, curses) is extremely difficult because both compete for terminal I/O. Tried approaches that failed:

- **textual-terminal**: `DEFAULT_COLORS` import error in newer Textual versions
- **Custom PTY + pyte**: Terminal not rendering properly, `screen` property conflicts
- **urwid.Terminal**: Event loop freezes
- **prompt_toolkit + ptterm**: Key bindings not working, layout issues
- **curses + PTY**: Terminal displays in narrow band, not full screen

**Solution**: Use tmux which is designed for terminal multiplexing. Each "view" is a tmux window, F-keys switch between them instantly.

## Components

### tui_env.py
Main launcher that:
1. Creates tmux session with base-index 1
2. Creates 4 windows at indices 1-4
3. Binds F1-F4 to select windows
4. Configures status bar showing `F#:Name` format
5. Attaches to session

### tree_view.py
Textual app with split layout:
- Left panel (30%): `DirectoryTree` widget
- Right panel (70%): `FileViewer` (scrollable Static)
- Enter on file loads content in viewer
- TAB switches focus between panels

### Status Bar
tmux status bar at bottom shows all windows:
```
 F1:Term   F2:Tree   F3:Lizard   F4:Term2
           ^^^^^^^^ (current = cyan highlight)
```

## Key Bindings

| Key | Action |
|-----|--------|
| F1 | Terminal 1 |
| F2 | Terminal 2 |
| F3 | Tree + Viewer |
| F4 | Lizard TUI |
| F5 | Glow (Markdown viewer) |
| F6 | Favorites (folder browser) |
| F9 | Config (theme selector) |
| F10 | Exit (kill session) |
| F12 | Toggle key passthrough (for apps using F-keys) |
| Shift+← | Previous window |
| Shift+→ | Next window |

### Tree View (F3)
| Key | Action |
|-----|--------|
| ↑/↓ | Navigate tree |
| Enter | Open folder / view file |
| o | Open with system (macOS: open) |
| m | File manager (dual-panel copy) |
| TAB | Switch tree ↔ viewer |
| w | Toggle wide tree (20% ↔ 50%) |
| Ctrl+P | Fuzzy find files (fzf) |
| / | Grep search (rg + fzf) |
| q | Quit |

### Favorites (F6)
| Key | Action |
|-----|--------|
| ↑/↓ | Navigate folders |
| / | Filter folders (fzf-style) |
| Escape | Cancel filter |
| TAB | Switch left ↔ right panel |
| Enter | Add to ★ (left panel) |
| Space | Copy path to clipboard |
| x | Remove from ★ |
| a | Admin (configure root folders) |
| q | Quit |

## Dependencies

```bash
brew install tmux fzf ripgrep
pip install textual
```

## Usage

```bash
./start.sh
# or
python3 tui_env.py
```

## Adding a New F-Key Window

To add a new window (e.g., F6), edit `tui_env.py`:

### Step 1: Create the window

Add after the last `new-window` block (around line 52):

```python
# Create Window 6 = MyApp
subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:6", "-n", "MyApp"])
```

### Step 2: Launch content in the window

**Option A - Plain shell** (no additional command needed, shell starts automatically)

**Option B - Run a Python script:**
```python
MY_SCRIPT = SCRIPT_DIR / "my_app.py"  # Add at top with other paths
# ...
subprocess.run([
    "tmux", "send-keys", "-t", f"{SESSION}:6",
    f" python3 '{MY_SCRIPT}'", "Enter"
])
```

**Option C - Run an external command:**
```python
subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:6", " htop", "Enter"])
```

Note: The leading space (` python3`, ` htop`) prevents the command from being saved to shell history.

### Step 3: Bind the F-key

Add after the last `bind-key` line (around line 72):

```python
subprocess.run(["tmux", "bind-key", "-n", "F6", "select-window", "-t", f"{SESSION}:6"])
```

### Checklist

- [ ] Window index matches F-key number (F6 → window 6)
- [ ] Window name is short (shows in status bar as `F6:Name`)
- [ ] For Python scripts: add path constant at top, check script exists
- [ ] For external commands: ensure command is installed

### Window Types Reference

| Type | Example | Notes |
|------|---------|-------|
| Shell | Term1, Term2 | Just create window, shell starts automatically |
| Python TUI | Tree, Lizard | Use `send-keys` with `python3 'script.py'` |
| External TUI | Glow | Use `send-keys` with command name |

### tmux Command Patterns

```python
# Create window at specific index with name
subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:N", "-n", "Name"])

# Send keystrokes to window (simulates typing + Enter)
subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:N", "command", "Enter"])

# Bind F-key (without prefix, -n flag)
subprocess.run(["tmux", "bind-key", "-n", "F6", "select-window", "-t", f"{SESSION}:N"])
```

## Files

```
my_env/
├── tui_env.py      # tmux launcher (edit this to add windows)
├── tree_view.py    # Textual tree+viewer app (with fzf/rg search)
├── config_panel.py # Theme configuration panel
├── favorites.py    # Folder favorites browser (~/work, ~/personal)
├── lizard_tui.py   # Lizard TUI app
├── start.sh        # convenience script
├── install.sh      # installer with dependency checks
├── .tui_config.json    # saved config (auto-generated)
├── .tui_favorites.json # saved favorites (auto-generated)
└── CLAUDE.md           # this file
```
