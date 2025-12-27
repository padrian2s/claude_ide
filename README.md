# TUI cu Terminal Real + Tree View + Lizard

Terminal real (zsh) cu tree view + nano editor și lizard-tui.

## Rulare

```bash
./start.sh
# sau
python3 tui_demo.py
```

## Layout

- **F1** - Terminal (zsh)
- **F2** - Tree + Viewer (split view)
- **F3** - Lizard TUI

## Keybindings (Tree View - Textual)

| Key | Acțiune |
|-----|---------|
| ↑/↓ | Navigare în tree |
| Enter | Deschide folder sau vizualizează fișier |
| TAB | Switch între tree și viewer |
| q | Quit |

## Dependențe

```bash
brew install tmux
pip install textual
```

## Cum funcționează

Folosește **tmux** cu 3 windows:
- Window 0: Terminal (zsh real)
- Window 1: Textual app (Tree 30% | Viewer 70%)
- Window 2: Lizard TUI
