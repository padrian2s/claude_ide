# Development Conventions

## Window Mapping (tmux)

- F1: Terminal (zsh)
- F2: lstime.py (directory listing TUI with file manager)
- F3: Tree View (tree_view.py)
- F4: Glow (Markdown viewer)
- F5: Workflow
- F6: Prompt Writer
- F7: Git (lazygit)
- F8: Status
- F9: Config
- F10: Exit

## Shortcut Bar Convention

When adding any new keyboard shortcut/action to a TUI component:

1. Add the binding to `BINDINGS` list
2. Create the `action_*` method
3. **ALWAYS add the shortcut to the help bar/footer** (e.g., `h:home`)

Example help bar format:
```python
yield Label("/search  Space:sel  v:view  c:copy  r:ren  d:del  a:all  s:sort  h:home  i:sync  g:jump", id="help-bar")
```

Keep labels short (3-5 chars) to fit more shortcuts. Use abbreviations:
- `sel` for select
- `del` for delete
- `^S` for Ctrl+S
