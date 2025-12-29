# TUI Environment - Technical Solution

## Overview

Multi-window TUI environment using **tmux** as the window manager. Each window is a separate full-screen view, switched via F-keys.

## Architecture

```
tmux session "tui-demo-{pid}"
├── Window 1 (F1): Term1 - zsh shell
├── Window 2 (F2): Term2 - second zsh shell
├── Window 3 (F3): Tree + Viewer - Textual app (tree | viewer | file manager)
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
2. Creates windows at indices 1-6, 9
3. Binds F-keys to select windows
4. Configures status bar showing `F#:Name` format
5. Loads saved theme and status position from config
6. Attaches to session

### tree_view.py
Textual app with multiple screens:

**MainScreen** - Tree browser with file viewer:
- Left panel (20-50%): `DirectoryTree` widget
- Right panel: `FileViewer` (scrollable Static with syntax highlighting)
- Binary file detection (PDF, images, etc.)
- Fuzzy file search (Ctrl+P via fzf)
- Grep search (/ via rg + fzf)

**DualPanelScreen** - Dual-panel file manager (Norton Commander style):
- Left/Right panels showing directory contents
- File selection with Space (multi-select)
- Copy files between panels (c)
- Rename files (r) with dialog
- Delete files (d) with confirmation
- Search/filter files (Ctrl+S) with fzf-style dialog
- Selection persistence (explicit selections preserved after operations)

**SearchDialog** - Popup search modal:
- Case-sensitive filtering as you type
- Tab: auto-select if single result, focus list if multiple
- Enter: select highlighted item
- Escape: cancel

### config_panel.py
Theme configuration panel:
- 8 color themes (Catppuccin, Tokyo Night, Gruvbox, Dracula, Nord, etc.)
- Status bar position toggle (top/bottom)
- Live preview and instant apply to tmux

### favorites.py
Folder favorites browser:
- Two-panel layout (All Folders | Favorites)
- Configurable root directories (Admin screen)
- Search/filter with `/`
- Copy path to clipboard (Space)
- Add/remove favorites (Enter/x)

### Status Bar
tmux status bar shows all windows:
```
 F1:Term1  F2:Term2  F3:Tree  F4:Lizard  F5:Glow  F6:Favs  F9:Config  F10:Exit  F12:Keys
                     ^^^^^^^ (current = cyan highlight)
```

## Key Bindings

### Global (tmux)
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
| Shift+Left | Previous window |
| Shift+Right | Next window |

### Tree View (F3) - MainScreen
| Key | Action |
|-----|--------|
| Up/Down | Navigate tree |
| Enter | Open folder / view file |
| Backspace | Go to parent directory |
| o | Open with system (macOS: open) |
| m | File manager (dual-panel mode) |
| TAB | Switch tree <-> viewer |
| w | Toggle wide tree (20% <-> 50%) |
| g | Toggle first/last position |
| Ctrl+P | Fuzzy find files (fzf) |
| / | Grep search (rg + fzf) |
| q | Quit |

### File Manager (m key) - DualPanelScreen
| Key | Action |
|-----|--------|
| Up/Down | Navigate files |
| Left/Right | Switch panels |
| Enter | Enter directory / view file |
| Backspace | Go to parent directory |
| h | Go to home (initial start path) |
| Space | Toggle selection (multi-select) |
| a | Select all / Unselect all (toggle) |
| c | Copy selected to other panel |
| r | Rename highlighted item |
| d | Delete selected (with confirmation) |
| Ctrl+S | Search/filter files (fzf-style dialog) |
| g | Toggle first/last position |
| Escape | Close file manager |

### Search Dialog (Ctrl+S in File Manager)
| Key | Action |
|-----|--------|
| Type | Filter results (case-sensitive) |
| Tab | Auto-select (1 result) or focus list (multiple) |
| Up/Down | Navigate results (when list focused) |
| Enter | Select and close |
| Escape | Cancel |

### Favorites (F6)
| Key | Action |
|-----|--------|
| Up/Down | Navigate folders |
| / | Filter folders (fzf-style) |
| Escape | Cancel filter |
| TAB | Switch left <-> right panel |
| Enter | Add to favorites (left panel) |
| Space | Copy path to clipboard |
| x | Remove from favorites |
| a | Admin (configure root folders) |
| r | Refresh |
| q | Quit |

### Config (F9)
| Key | Action |
|-----|--------|
| Up/Down | Navigate themes |
| Enter | Apply theme |
| p | Toggle status bar position (top/bottom) |
| q/Escape | Quit |

## File Operations Details

### Copy (c)
- Uses highlighted item if nothing selected with Space
- Shows progress dialog with percentage
- Preserves explicit selections (Space) after operation
- Refreshes both panels on completion

### Rename (r)
- Opens dialog with current filename pre-filled
- Wide dialog (80% screen) for long filenames
- Refreshes panel on completion

### Delete (d)
- Confirmation dialog (y/n)
- Uses highlighted item if nothing selected
- Supports directories (recursive delete)
- Preserves explicit selections after operation

### Selection Behavior
- Space toggles individual file selection
- 'a' toggles select all / unselect all
- Operations on highlighted item don't clear Space selections
- Operations on Space selections clear them after completion

## Dependencies

```bash
brew install tmux fzf ripgrep glow
pip install textual
```

## Usage

```bash
./start.sh
# or
python3 tui_env.py
```

## Adding a New F-Key Window

To add a new window (e.g., F7), edit `tui_env.py`:

### Step 1: Create the window

Add after the last `new-window` block:

```python
# Create Window 7 = MyApp
subprocess.run(["tmux", "new-window", "-t", f"{SESSION}:7", "-n", "MyApp"])
```

### Step 2: Launch content in the window

**Option A - Plain shell** (no additional command needed)

**Option B - Run a Python script:**
```python
MY_SCRIPT = SCRIPT_DIR / "my_app.py"  # Add at top with other paths
subprocess.run([
    "tmux", "send-keys", "-t", f"{SESSION}:7",
    f" python3 '{MY_SCRIPT}'", "Enter"
])
```

**Option C - Run an external command:**
```python
subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:7", " htop", "Enter"])
```

Note: The leading space (` python3`, ` htop`) prevents the command from being saved to shell history.

### Step 3: Bind the F-key

Add after the last `bind-key` line:

```python
subprocess.run(["tmux", "bind-key", "-n", "F7", "select-window", "-t", f"{SESSION}:7"])
```

### Step 4: Update F12 toggle command

Add the new F-key to both the bind and unbind sections in the `toggle_cmd` string.

## Files

```
my_env/
├── tui_env.py          # tmux launcher (edit this to add windows)
├── tree_view.py        # Tree+viewer+file manager app
├── config_panel.py     # Theme configuration panel
├── favorites.py        # Folder favorites browser
├── lizard_tui.py       # Lizard TUI app
├── start.sh            # convenience script
├── install.sh          # installer with dependency checks
├── .tui_config.json    # saved theme/position config (auto-generated)
├── .tui_favorites.json # saved favorites (auto-generated)
└── CLAUDE.md           # this file
```

## Technical Notes

### Binary File Detection
Files with these extensions show "Cannot display binary file" message:
- Images: .png, .jpg, .jpeg, .gif, .bmp, .ico, .webp, .svg
- Documents: .pdf
- Archives: .zip, .tar, .gz, .rar, .7z
- Media: .mp3, .mp4, .wav, .avi, .mov, .mkv
- Binaries: .exe, .dll, .so, .dylib, .bin
- Data: .pyc, .pyo, .class, .o, .obj

### Threading
File copy operations run in background thread with `threading.Thread`.
UI updates use `self.app.call_from_thread()` to safely update from background thread.

### Session Isolation
Each `tui_env.py` instance creates unique tmux session with PID suffix.
Cleanup via `atexit` and signal handlers (SIGHUP, SIGTERM).
