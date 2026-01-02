#!/usr/bin/env python3
"""Auto-upgrade module for Claude IDE.

Handles git updates while preserving AI-customized files.
"""

import subprocess
from pathlib import Path

# Constants
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / "backups"

# Files that can be AI-modified (from ai_customizer.py SCREEN_CONFIGS)
AI_MODIFIABLE_FILES = [
    "tree_view.py",
    "lizard_tui.py",
    "favorites.py",
    "prompt_writer.py",
    "config_panel.py",
]


def get_ai_modified_files() -> list[str]:
    """Get list of files that have been modified by AI customization.

    A file is considered AI-modified if it has backups in the backup directory.

    Returns:
        List of filenames that have been AI-modified
    """
    if not BACKUP_DIR.exists():
        return []

    modified = []
    for script in AI_MODIFIABLE_FILES:
        script_stem = Path(script).stem
        pattern = f"{script_stem}_*.py.bak"
        if list(BACKUP_DIR.glob(pattern)):
            modified.append(script)

    return modified


def check_for_updates() -> tuple[bool, str]:
    """Check if there are updates available from remote.

    Returns:
        Tuple of (has_updates, message)
    """
    # Fetch from remote
    result = subprocess.run(
        ["git", "fetch"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, f"Git fetch failed: {result.stderr}"

    # Check if we're behind
    result = subprocess.run(
        ["git", "status", "-uno"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )

    if "Your branch is behind" in result.stdout:
        # Count commits behind
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD..@{upstream}"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )
        count = result.stdout.strip()
        return True, f"{count} commit(s) behind"

    return False, "Already up to date"


def get_changed_files_from_remote() -> list[str]:
    """Get list of files that would be changed by pulling.

    Returns:
        List of file paths that differ from remote
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD..@{upstream}"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes in the working directory."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def perform_upgrade(skip_files: list[str] | None = None) -> tuple[bool, str]:
    """Perform git pull, preserving specified files.

    Uses git stash to handle uncommitted changes, then restores AI-modified files.

    Args:
        skip_files: List of files to preserve (not overwrite)

    Returns:
        Tuple of (success, message)
    """
    skip_files = skip_files or []
    stashed_contents = {}

    # Save contents of AI-modified files we want to preserve
    for filename in skip_files:
        filepath = SCRIPT_DIR / filename
        if filepath.exists():
            stashed_contents[filename] = filepath.read_text()

    # Check for uncommitted changes and stash them
    had_stash = False
    if has_uncommitted_changes():
        result = subprocess.run(
            ["git", "stash", "push", "-m", "auto-upgrade-stash"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and "No local changes" not in result.stdout:
            had_stash = True

    # Perform the pull
    result = subprocess.run(
        ["git", "pull"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    pull_success = result.returncode == 0
    pull_msg = result.stdout if pull_success else result.stderr

    # Pop stash if we had one
    if had_stash:
        subprocess.run(
            ["git", "stash", "pop"],
            cwd=SCRIPT_DIR,
            capture_output=True,
            text=True,
        )

    # Always restore AI-modified files (overwrite whatever git did)
    for filename, content in stashed_contents.items():
        filepath = SCRIPT_DIR / filename
        filepath.write_text(content)

    if not pull_success:
        if stashed_contents:
            return False, f"Git pull failed, but {len(stashed_contents)} AI-modified file(s) preserved"
        return False, f"Git pull failed: {pull_msg}"

    if stashed_contents:
        return True, f"Updated, preserved {len(stashed_contents)} AI-modified file(s)"
    return True, "Updated successfully"


def auto_upgrade(silent: bool = False) -> bool:
    """Check for updates and apply them, preserving AI-modified files.

    Args:
        silent: If True, don't print messages

    Returns:
        True if upgrade was performed or no updates available
    """
    # Check if we're in a git repo
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=SCRIPT_DIR,
        capture_output=True,
    )
    if result.returncode != 0:
        if not silent:
            print("Not a git repository, skipping upgrade check")
        return True

    # Check for updates
    has_updates, msg = check_for_updates()

    if not has_updates:
        if not silent:
            print(f"Upgrade check: {msg}")
        return True

    if not silent:
        print(f"Updates available: {msg}")

    # Get AI-modified files
    ai_modified = get_ai_modified_files()

    # Get files that would change
    changed_files = get_changed_files_from_remote()

    # Find overlap - files that are both AI-modified AND would be updated
    files_to_preserve = [f for f in ai_modified if f in changed_files]

    if files_to_preserve and not silent:
        print(f"Preserving AI-customized files: {', '.join(files_to_preserve)}")

    # Perform upgrade
    success, msg = perform_upgrade(files_to_preserve)

    if not silent:
        print(f"Upgrade: {msg}")

    return success


if __name__ == "__main__":
    # Test run
    auto_upgrade(silent=False)
