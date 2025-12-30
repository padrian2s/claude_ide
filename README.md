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
| F9 | Config |
| F10 | Exit |
| F12 | Toggle key passthrough |

## Dependencies

Installed automatically:
- tmux
- fzf
- ripgrep
- textual (Python)
