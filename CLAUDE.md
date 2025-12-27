# TUI Environment - Technical Solution

## Overview

Multi-window TUI environment using **tmux** as the window manager. Each window is a separate full-screen view, switched via F-keys.

## Architecture

```
tmux session "tui-demo"
├── Window 1 (F1): Terminal - zsh shell
├── Window 2 (F2): Tree + Viewer - Textual app (30% tree | 70% viewer)
├── Window 3 (F3): Lizard TUI - Python TUI app
└── Window 4 (F4): Terminal 2 - second zsh shell
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

### tui_demo.py
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
| F2 | Tree + Viewer |
| F3 | Lizard TUI |
| F4 | Terminal 2 |
| Ctrl+B d | Detach tmux |

### Tree View (F2)
| Key | Action |
|-----|--------|
| ↑/↓ | Navigate tree |
| Enter | Open folder / view file |
| TAB | Switch tree ↔ viewer |
| q | Quit |

## Dependencies

```bash
brew install tmux
pip install textual
```

## Usage

```bash
./start.sh
# or
python3 tui_demo.py
```

## Files

```
my_env/
├── tui_demo.py    # tmux launcher
├── tree_view.py   # Textual tree+viewer app
├── start.sh       # convenience script
└── CLAUDE.md      # this file
```
