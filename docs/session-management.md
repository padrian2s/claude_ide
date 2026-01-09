# Session Management: Troubleshooting and Design

## Problem: "Can't find session" Error

### Symptom
```
Can't find session: claude-ide-38469
```
This error appears when pressing F-keys or using tmux shortcuts after a session has been killed.

### Root Cause

tmux key bindings created with `bind-key -n` are **global**, not session-specific. When `tui_env.py` creates bindings like:

```python
subprocess.run(["tmux", "bind-key", "-n", "F1", "select-window", "-t", f"{SESSION}:1"])
```

The binding persists in tmux's global key table even after the session `claude-ide-{pid}` is killed. Subsequent F-key presses attempt to reference the dead session.

### Contributing Factors

1. **Hardcoded session names in bindings**: Each binding contains the literal session name (e.g., `claude-ide-38469:1`)

2. **Incomplete cleanup**: Original `cleanup()` only killed the session without unbinding keys

3. **Multiple concurrent sessions**: Running multiple IDE instances creates binding conflicts where the last-launched session's bindings win, but cleanup of any session leaves stale bindings

4. **Orphaned sessions**: Sessions that weren't properly terminated (crash, force-quit terminal) leave bindings pointing to dead sessions

---

## Fix Applied

### 1. Enhanced Cleanup Function

Location: `tui_env.py:403-428`

```python
def cleanup():
    # Check if session still exists before cleanup
    result = subprocess.run(
        ["tmux", "has-session", "-t", SESSION],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL
    )
    if result.returncode != 0:
        # Session already dead, just unbind keys
        for key in [...]:
            subprocess.run(["tmux", "unbind-key", "-n", key], ...)
        return

    # Unbind all keys before killing session
    for key in [...]:
        subprocess.run(["tmux", "unbind-key", "-n", key], ...)

    subprocess.run(["tmux", "unbind-key", "-T", "root", "MouseUp1Status"], ...)
    subprocess.run(["tmux", "kill-session", "-t", SESSION], ...)
```

### 2. Comprehensive Startup Unbind

Location: `tui_env.py:268-274`

Clears all possible stale bindings before creating new ones:
- F1-F10, F12
- S-F1 through S-F9 (Shift+F keys)
- C-t, C-h, C-x, C-p, C-w
- S-Left, S-Right
- MouseUp1Status

---

## Edge Cases NOT Covered

### 1. Crash During Cleanup

**Scenario**: Python process killed with SIGKILL (kill -9) or system crash during cleanup.

**Result**: Cleanup never runs, stale bindings remain.

**Workaround**: Next IDE launch clears stale bindings on startup.

### 2. Concurrent Session Interference

**Scenario**: Two IDE sessions running simultaneously. User exits one session.

**Result**: Cleanup unbinds keys for ALL sessions (bindings are global). The remaining session loses its F-key functionality until user presses a key that triggers rebinding (like F12 toggle).

**Potential Fix**: Use session-specific key tables (`bind-key -T mytable`) instead of global bindings, but this requires prefix key which defeats the purpose.

### 3. External tmux Manipulation

**Scenario**: User manually kills session via `tmux kill-session` from another terminal.

**Result**: Python process doesn't receive signal, cleanup doesn't run, stale bindings remain.

**Workaround**: Next IDE launch clears stale bindings on startup.

### 4. tmux Server Restart

**Scenario**: tmux server is killed/restarted (`tmux kill-server`).

**Result**: All sessions and bindings are cleared. No issue, but user loses all work.

### 5. Binding Collision with User's tmux.conf

**Scenario**: User has F-key bindings in their `~/.tmux.conf`.

**Result**: IDE bindings override user bindings during session. Cleanup removes bindings entirely (doesn't restore user's original bindings).

**Potential Fix**: Save existing bindings on startup, restore on cleanup. Complex to implement correctly.

### 6. Very Long Session Names

**Scenario**: If SESSION name exceeds tmux's internal limits.

**Result**: Undefined behavior. Current PID-based naming is safe (PIDs are bounded).

---

## Manual Recovery

If you encounter stale bindings, run:

```bash
# List sessions to find orphans
tmux list-sessions | grep claude-ide

# Kill orphaned sessions
tmux kill-session -t claude-ide-XXXXX

# Clear all F-key bindings manually
for key in F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F12; do
  tmux unbind-key -n $key
done

# Clear shift+F bindings
for i in 1 2 3 4 5 6 7 8 9; do
  tmux unbind-key -n S-F$i
done

# Clear other bindings
tmux unbind-key -n C-t
tmux unbind-key -n C-h
tmux unbind-key -n C-x
tmux unbind-key -n C-p
tmux unbind-key -T root MouseUp1Status
```

---

## Design Considerations for Future

### Alternative: Session-Scoped Bindings via Hooks

Instead of global bindings, use `client-session-changed` hook to dynamically rebind keys when switching to a claude-ide session:

```bash
tmux set-hook -g client-session-changed 'if-shell "tmux display -p \"#{session_name}\" | grep -q claude-ide" "source ~/.tmux-claude-ide.conf" ""'
```

**Pros**: No global binding pollution
**Cons**: Slight delay when switching sessions, complexity

### Alternative: Prefix-Based Bindings

Use a prefix key (like `C-a`) before F-keys:

```bash
tmux bind-key -T prefix F1 select-window -t ...
```

**Pros**: No global binding conflicts
**Cons**: Extra keypress required, not as seamless

### Alternative: Environment Variable Check

Add session existence check to each binding:

```bash
tmux bind-key -n F1 if-shell "tmux has-session -t claude-ide-38469" "select-window -t claude-ide-38469:1" ""
```

**Pros**: Graceful failure
**Cons**: Adds latency to every keypress, still leaves orphan bindings
