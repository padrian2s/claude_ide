#!/usr/bin/env python3
"""Auto-upgrade module for Claude IDE.

Handles release-based updates while preserving AI-customized files.
Only updates from tagged releases, not from main/master branch.
"""

import json
import re
import subprocess
import urllib.request
from pathlib import Path

# Constants
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR / "backups"
GITHUB_REPO = "padrian2s/claude_ide"  # owner/repo format

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


def get_current_version() -> str | None:
    """Get the current version from git tags.

    Returns:
        Current version tag (e.g., 'v0.1.0') or None if not on a tag
    """
    # First check if we're exactly on a tag
    result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match", "HEAD"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    # If not on exact tag, get the most recent tag
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    return None


def get_latest_release() -> tuple[str | None, str]:
    """Get the latest release tag from GitHub or git tags.

    Tries GitHub API first, falls back to git tags if that fails.

    Returns:
        Tuple of (tag_name, message) - tag_name is None on error
    """
    # Try GitHub API first
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    try:
        import ssl
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=10, context=context) as response:
            data = json.loads(response.read().decode())
            return data.get("tag_name"), "OK"
    except ImportError:
        # certifi not available, fall back to git tags
        return get_latest_tag()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # No releases yet, try tags instead
            return get_latest_tag()
        # Fall back to git tags on API errors
        return get_latest_tag()
    except (urllib.error.URLError, json.JSONDecodeError, ssl.SSLError):
        # Network/SSL errors, fall back to git tags
        return get_latest_tag()


def get_latest_tag() -> tuple[str | None, str]:
    """Get the latest tag from git (fallback if no GitHub releases).

    Returns:
        Tuple of (tag_name, message)
    """
    # Fetch tags from remote
    subprocess.run(
        ["git", "fetch", "--tags"],
        cwd=SCRIPT_DIR,
        capture_output=True,
    )

    result = subprocess.run(
        ["git", "tag", "--sort=-v:refname"],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None, "No tags found"

    tags = result.stdout.strip().split("\n")
    # Filter for version tags (v*.*.*)
    version_tags = [t for t in tags if re.match(r"^v?\d+\.\d+", t)]
    if version_tags:
        return version_tags[0], "OK"
    return tags[0] if tags else None, "OK"


def parse_version(version: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple.

    Args:
        version: Version string like 'v0.1.0' or '1.2.3'

    Returns:
        Tuple of integers for comparison
    """
    # Remove 'v' prefix if present
    v = version.lstrip("v")
    # Extract numbers
    parts = re.findall(r"\d+", v)
    return tuple(int(p) for p in parts) if parts else (0,)


def check_for_updates() -> tuple[bool, str, str | None]:
    """Check if there are new releases available.

    Returns:
        Tuple of (has_updates, message, latest_version)
    """
    current = get_current_version()
    latest, err_msg = get_latest_release()

    if latest is None:
        return False, err_msg, None

    if current is None:
        # No current version tag, any release is an update
        return True, f"New release available: {latest}", latest

    # Compare versions
    current_tuple = parse_version(current)
    latest_tuple = parse_version(latest)

    if latest_tuple > current_tuple:
        return True, f"Update available: {current} → {latest}", latest

    return False, f"Already on latest release ({current})", None


def get_changed_files_between_tags(from_tag: str, to_tag: str) -> list[str]:
    """Get list of files that changed between two tags.

    Returns:
        List of file paths that differ
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", from_tag, to_tag],
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


def perform_upgrade(target_tag: str, skip_files: list[str] | None = None) -> tuple[bool, str]:
    """Checkout a specific release tag, preserving specified files.

    Uses git stash to handle uncommitted changes, then restores AI-modified files.

    Args:
        target_tag: The tag/release to checkout
        skip_files: List of files to preserve (not overwrite)

    Returns:
        Tuple of (success, message)
    """
    skip_files = skip_files or []
    stashed_contents = {}

    # Fetch latest tags
    subprocess.run(
        ["git", "fetch", "--tags"],
        cwd=SCRIPT_DIR,
        capture_output=True,
    )

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

    # Checkout the target tag
    result = subprocess.run(
        ["git", "checkout", target_tag],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
    )
    checkout_success = result.returncode == 0
    checkout_msg = result.stdout if checkout_success else result.stderr

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

    if not checkout_success:
        if stashed_contents:
            return False, f"Checkout failed, but {len(stashed_contents)} AI-modified file(s) preserved"
        return False, f"Checkout failed: {checkout_msg}"

    if stashed_contents:
        return True, f"Updated to {target_tag}, preserved {len(stashed_contents)} AI-modified file(s)"
    return True, f"Updated to {target_tag}"


def auto_upgrade(silent: bool = False) -> bool:
    """Check for new releases and apply them, preserving AI-modified files.

    Only updates from tagged releases, not from main/master branch.

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
    has_updates, msg, latest_version = check_for_updates()

    if not has_updates:
        if not silent:
            print(f"Upgrade check: {msg}")
        return True

    if not silent:
        print(f"Updates available: {msg}")

    if latest_version is None:
        return True

    # Get AI-modified files
    ai_modified = get_ai_modified_files()

    # Get current version for comparison
    current_version = get_current_version()

    # Get files that would change
    if current_version:
        changed_files = get_changed_files_between_tags(current_version, latest_version)
    else:
        changed_files = []

    # Find overlap - files that are both AI-modified AND would be updated
    files_to_preserve = [f for f in ai_modified if f in changed_files]

    if files_to_preserve and not silent:
        print(f"Preserving AI-customized files: {', '.join(files_to_preserve)}")

    # Perform upgrade
    success, msg = perform_upgrade(latest_version, files_to_preserve)

    if not silent:
        print(f"Upgrade: {msg}")

    return success


if __name__ == "__main__":
    # Test run
    print("Current version:", get_current_version())
    print("Checking for updates...")
    auto_upgrade(silent=False)
