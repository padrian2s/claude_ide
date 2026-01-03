# Session: Release-Based Auto-Upgrade Implementation

**Date**: 2026-01-02

## Summary
Implemented release-based auto-upgrade system for Claude IDE, replacing the previous main-branch tracking approach.

## Changes Made

### upgrader.py - Complete Rewrite
- **Before**: Tracked main branch with `git pull`
- **After**: Only updates from tagged releases (git tags)

Key new functions:
- `get_current_version()` - Detects current version from git tags
- `get_latest_release()` - Fetches latest release from GitHub API with git tags fallback
- `get_latest_tag()` - Fallback when GitHub API unavailable (SSL issues, network errors)
- `parse_version()` - Semantic version comparison
- `get_changed_files_between_tags()` - Diff files between releases
- `perform_upgrade(target_tag, skip_files)` - Checkout specific tag instead of pull

### Release Created
- **Tag**: `v0.1.0`
- **Commit**: `f7fcf1e`
- **Status**: Pushed to origin

## Technical Details

### Version Detection
```python
# Exact tag match first, then most recent tag
git describe --tags --exact-match HEAD
git describe --tags --abbrev=0
```

### GitHub API with Fallback
- Primary: GitHub releases API (`/repos/{owner}/{repo}/releases/latest`)
- Fallback: Git tags sorted by version (`git tag --sort=-v:refname`)
- Uses `certifi` for SSL if available, falls back to git tags on SSL errors

### Upgrade Flow
1. Check current version (from git tags)
2. Fetch latest release (GitHub API → git tags fallback)
3. Compare versions semantically
4. Preserve AI-modified files during checkout
5. Checkout target tag

## Environment Notes
- `gh` CLI installed via `brew install gh`
- Re-authenticated with `gh auth login` - now has `repo` scope

## Completed
- **GitHub Release created**: https://github.com/padrian2s/claude_ide/releases/tag/v0.1.0
- Upgrader successfully detects v0.1.0 via GitHub API
- Full release-based upgrade system operational

## Files Modified
- `upgrader.py` - 161 insertions, 40 deletions
