# Development Conventions

## Shortcut Bar Convention

When adding any new keyboard shortcut/action to a TUI component:

1. Add the binding to `BINDINGS` list
2. Create the `action_*` method
3. **ALWAYS add the shortcut to the help bar/footer** (e.g., `h:home`)

Example help bar format:
```python
yield Label("^S:search  Space:sel  c:copy  r:rename  d:del  a:all  s:sort  h:home  g:jump  q:close", id="help-bar")
```

Keep labels short (3-5 chars) to fit more shortcuts. Use abbreviations:
- `sel` for select
- `del` for delete
- `^S` for Ctrl+S
