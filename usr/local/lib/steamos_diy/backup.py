#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Backup Tool
# VERSION:      2.1.6
# DESCRIPTION:  Surgical backup with deep symlink recovery for SteamOS shims.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/backup.py
# LICENSE:      MIT
# =============================================================================
"""

import io
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path

from utils import (
    BACKUP_MANIFEST_NAME,
    CORE_LIB_DIR,
    SSOT_CONF_PATH,
    UPDATES_DIR_NAME,
    USER_CONFIG_REL,
    check_root,
    fix_ownership,
    get_backup_mapping,
    get_real_user,
    get_ssot_num,
    jlog,
    verify_archive,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# Folders scanned for symlinks pointing into the core library
_SYMLINK_SEARCH_PATHS: tuple[str, ...] = (
    "/usr/bin",
    "/usr/local/bin",
    "/usr/bin/steamos-polkit-helpers",
)

# Markers in symlink targets that qualify them for inclusion in the recap
_SYMLINK_TARGET_MARKERS: tuple[str, ...] = (
    CORE_LIB_DIR,
    "steamos-polkit-helpers",
)

# Path components excluded from the archive — matched by component, not
# substring, so "my_backups.yaml" is safe while a dir named "backups" is not.
# UPDATES_DIR_NAME keeps downloaded release tarballs out of the archives.
_EXCLUDE_COMPONENTS: frozenset[str] = frozenset(
    {
        ".cache",
        "__pycache__",
        "backups",
        UPDATES_DIR_NAME,
    }
)

# Subdirectory under USER_CONFIG_REL where archives are stored.
_USER_BACKUPS_REL: str = f"{USER_CONFIG_REL}/backups"

# Archive naming
_ARCHIVE_PREFIX: str = "sdy_backup_"
_ARCHIVE_SUFFIX: str = ".tar.gz"
_ARCHIVE_TMP_SUFFIX: str = ".tar.gz.tmp"
_ARCHIVE_TS_FORMAT: str = "%Y%m%d_%H%M%S"

# Mode for the embedded links-manifest tar entry (plain data, not code)
_MANIFEST_MODE: int = 0o644

# Archives kept after pruning when BACKUP_KEEP is missing from the SSoT
_BACKUP_KEEP_DEFAULT: int = 5


# ---------------------------------------------------------------------------
# Internal helpers — symlink scan
# ---------------------------------------------------------------------------


def _resolve_symlink(entry) -> str | None:
    if not entry.is_symlink():
        return None
    try:
        target = os.path.realpath(entry.path)
    except OSError:
        return None
    return (
        target if any(m in target for m in _SYMLINK_TARGET_MARKERS) else None
    )


def _collect_symlinks(search_path: str) -> list[tuple[str, str]]:
    """Non-recursive scandir; returns [] on missing/unreadable dir."""
    if not os.path.isdir(search_path):
        return []
    try:
        entries = list(os.scandir(search_path))
    except OSError:
        return []

    found: list[tuple[str, str]] = []
    for entry in entries:
        target = _resolve_symlink(entry)
        if target is not None:
            found.append((entry.path, target))
    return found


def _generate_links_manifest() -> bytes:
    """Build the links manifest as UTF-8 bytes: one "link<TAB>target" row.

    Plain data instead of an executable script: restore recreates the
    links itself and validates each pair against its allow-list, so the
    archive never carries code. A path holding a tab or newline cannot
    be represented in the row format — skipped with a warning.
    """
    rows: list[str] = []
    for s_path in _SYMLINK_SEARCH_PATHS:
        for link_path, target in _collect_symlinks(s_path):
            if any(c in link_path + target for c in "\t\n"):
                jlog(
                    "SYSTEM",
                    f"BACKUP_LINK_SKIPPED: {link_path!r}",
                    level="WARN",
                )
                continue
            rows.append(f"{link_path}\t{target}")
    return ("\n".join(rows) + "\n").encode("utf-8") if rows else b""


# ---------------------------------------------------------------------------
# Internal helpers — archive content
# ---------------------------------------------------------------------------


def _path_is_excluded(name: str) -> bool:
    """Match by path component, not substring — 'backups_2024.yaml' is safe."""
    return any(part in _EXCLUDE_COMPONENTS for part in name.split("/"))


def _tar_filter(tarinfo):
    """tarfile filter: drop entries whose path components are excluded."""
    if _path_is_excluded(tarinfo.name):
        return None
    return tarinfo


def _add_links_manifest(tar: tarfile.TarFile) -> None:
    """Append the links-manifest entry to *tar*."""
    data = _generate_links_manifest()
    info = tarfile.TarInfo(name=BACKUP_MANIFEST_NAME)
    info.size = len(data)
    info.mode = _MANIFEST_MODE
    tar.addfile(info, io.BytesIO(data))


def _add_payload(tar: tarfile.TarFile, home: str) -> None:
    """Add system + user sources to *tar*, skipping missing paths."""
    for arc, src in get_backup_mapping(home).items():
        if os.path.exists(src):
            tar.add(src, arcname=arc, filter=_tar_filter)
            jlog("SYSTEM", f"BACKUP_ADD: {src}", level="DEBUG")


# ---------------------------------------------------------------------------
# Internal helpers — archive lifecycle
# ---------------------------------------------------------------------------


def _ensure_backup_dir(home: str, user: str) -> Path:
    """Chown only on first creation — not on every run.

    Avoids recursive chown over potentially gigabytes of historical archives.
    """
    backup_dir = Path(home) / _USER_BACKUPS_REL
    pre_existing = backup_dir.is_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    if not pre_existing:
        fix_ownership(backup_dir, user)
    return backup_dir


def _archive_paths(backup_dir: Path) -> tuple[Path, Path]:
    """Return (final_path, tmp_path) for the new archive.

    tmp lives in the same directory so os.replace is atomic (same fs).
    """
    timestamp = datetime.now().strftime(_ARCHIVE_TS_FORMAT)
    final = backup_dir / f"{_ARCHIVE_PREFIX}{timestamp}{_ARCHIVE_SUFFIX}"
    tmp = backup_dir / f"{_ARCHIVE_PREFIX}{timestamp}{_ARCHIVE_TMP_SUFFIX}"
    return final, tmp


def _cleanup_tmp(tmp: Path) -> None:
    """Best-effort removal of a partial *.tmp archive after a failure."""
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError as err:
        jlog("SYSTEM", f"BACKUP_TMP_CLEANUP_FAIL: {err}", level="WARN")


def _prune_old_archives(backup_dir: Path) -> None:
    """Keep the newest BACKUP_KEEP archives; delete the older ones.

    BACKUP_KEEP <= 0 disables pruning entirely (keep everything). The
    timestamped naming makes lexicographic order chronological, and the
    glob cannot match in-flight *.tmp files.
    """
    keep = int(get_ssot_num("BACKUP_KEEP", _BACKUP_KEEP_DEFAULT))
    if keep <= 0:
        return
    archives = sorted(
        backup_dir.glob(f"{_ARCHIVE_PREFIX}*{_ARCHIVE_SUFFIX}")
    )
    for old in archives[:-keep]:
        try:
            old.unlink()
            jlog("SYSTEM", f"BACKUP_PRUNED: {old.name}", level="INFO")
        except OSError as err:
            jlog(
                "SYSTEM",
                f"BACKUP_PRUNE_FAIL: {old.name} - {err}",
                level="WARN",
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_backup() -> None:
    """Execute a complete surgical backup.

    Writes to a *.tmp path, verifies end-to-end, then atomically renames
    to *.tar.gz. The previous archive is never touched on failure.
    """
    check_root()
    if not os.path.isfile(SSOT_CONF_PATH):
        jlog("SYSTEM", "BACKUP_FAILED: SSoT config not found", level="ERROR")
        sys.exit(1)

    user, home = get_real_user()
    home_str = str(home)

    backup_dir = _ensure_backup_dir(home_str, user)
    final_path, tmp_path = _archive_paths(backup_dir)

    jlog("SYSTEM", f"BACKUP_START: {final_path.name}", level="INFO")

    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
            _add_payload(tar, home_str)
            _add_links_manifest(tar)
    except (OSError, tarfile.TarError) as err:
        jlog("SYSTEM", f"BACKUP_FAILED: {err}", level="ERROR")
        _cleanup_tmp(tmp_path)
        sys.exit(1)

    if not verify_archive(tmp_path, "BACKUP_VERIFY_FAIL"):
        _cleanup_tmp(tmp_path)
        sys.exit(1)

    try:
        os.replace(tmp_path, final_path)
    except OSError as err:
        jlog("SYSTEM", f"BACKUP_RENAME_FAIL: {err}", level="ERROR")
        _cleanup_tmp(tmp_path)
        sys.exit(1)

    fix_ownership(final_path, user)
    jlog("SYSTEM", f"BACKUP_SUCCESS: {final_path.name}", level="INFO")
    _prune_old_archives(backup_dir)


if __name__ == "__main__":
    run_backup()
