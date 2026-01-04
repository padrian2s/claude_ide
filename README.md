# Claude IDE

Multi-window terminal IDE using tmux with tree viewer, favorites, prompt writer, and more.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/padrian2s/claude_ide/main/remote-install.sh | bash
```

Then run `tui` to launch.

## Layout

| Key | Window |
|-----|--------|
| F1 | Terminal 1 (zsh) |
| F2 | Terminal 2 (zsh) |
| F3 | Tree + Viewer |
| F4 | Lizard TUI |
| F5 | Glow (Markdown) |
| F6 | Favorites |
| F7 | Prompt Writer |
| F8 | Status (session metrics) |
| F9 | Config (themes) |
| F10 | Exit |
| F12 | Toggle key passthrough |
| Ctrl+P | Quick input popup |
| Shift+Left/Right | Navigate windows |

## Tree View (F3)

| Key | Action |
|-----|--------|
| Enter | Open folder / view file |
| Backspace | Go to parent |
| TAB | Switch tree <-> viewer |
| w | Toggle wide tree |
| f | Toggle viewer fullscreen |
| Ctrl+F | Fuzzy find files |
| / | Grep search |
| o | Open with system |
| m | File manager mode |

## File Manager (m in Tree View)

| Key | Action |
|-----|--------|
| Left/Right | Switch panels |
| Space | Toggle selection |
| c | Copy selected |
| r | Rename |
| d | Delete |
| Ctrl+S | Search/filter |

## Prompt Writer (F7)

| Key | Action |
|-----|--------|
| Ctrl+S | Save prompt |
| Ctrl+O | Open saved prompts |
| Ctrl+T | Insert template |
| Ctrl+G | AI enhance prompt |
| Ctrl+R | Send to Terminal |

## Dependencies

Installed automatically:
- tmux
- fzf
- ripgrep
- textual (Python)
