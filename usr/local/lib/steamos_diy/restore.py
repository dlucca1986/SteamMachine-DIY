#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Restore Tool
# VERSION:      2.1.2
# DESCRIPTION:  Full system restoration and dynamic symlink reconstruction.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/restore.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
from pathlib import Path

from utils import (
    BACKUP_SCRIPT_NAME,
    SSOT_CONF_PATH,
    check_root,
    fix_ownership,
    get_backup_mapping,
    get_real_user,
    jlog,
    verify_archive,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# Allow-list of filesystem prefixes the restore is permitted to write to.
# Each entry is a *real* (symlink-resolved) absolute path; targets are
# normalised before being checked against this set.
_ALLOWED_PREFIXES_FIXED: tuple[str, ...] = (
    "/etc/",
    "/usr/",
    "/var/",
)


# ---------------------------------------------------------------------------
# Internal helpers — destination mapping
# ---------------------------------------------------------------------------


def _allowed_prefixes(home_real: str) -> tuple[str, ...]:
    # Trailing slash prevents "alice" from matching "alicebob".
    return _ALLOWED_PREFIXES_FIXED + (home_real + "/",)


# ---------------------------------------------------------------------------
# Internal helpers — security validation
# ---------------------------------------------------------------------------


def _is_path_safe(target: str, allowed: tuple[str, ...]) -> bool:
    """Guard against symlink-redirect attacks via realpath allow-list check.

    os.path.realpath follows symlinks already on disk at the parent level,
    so a malicious archive cannot plant a link that re-aims a later write
    outside the allow-list.
    """
    real = os.path.realpath(target)
    # Append "/" so "/etcfoo" cannot match "/etc"
    real_check = real if real.endswith("/") else real + "/"
    return any(real_check.startswith(prefix) for prefix in allowed)


def _match_mapping_prefix(
    member_name: str, mapping: dict[str, str]
) -> str | None:
    """Return the longest path-component prefix of member_name in mapping.

    Path-component matching (exact or prefix + "/") prevents "user/config"
    from matching "user/config_backup/". Longest match wins on shared roots.
    """
    matches = [
        k
        for k in mapping
        if member_name == k or member_name.startswith(k + "/")
    ]
    if not matches:
        return None
    return max(matches, key=len)


def _resolve_target(
    member_name: str, mapping: dict[str, str], allowed: tuple[str, ...]
) -> str | None:
    """Map an archive member to a validated filesystem path.

    Uses os.path.realpath (not abspath) before the allow-list check.
    abspath collapses ".." without following existing symlinks, so
    "system/next_session/../../etc/passwd" would slip through; realpath
    catches it.

    Args:
        member_name: Archive-relative path of the tar member.
        mapping: Prefix-to-destination map from get_backup_mapping.
        allowed: Real-path-resolved allow-list from _allowed_prefixes.

    Returns:
        Validated absolute path, or None if unmapped or outside allow-list.
    """
    # Reject any member whose path contains traversal components before
    # resolution. A crafted archive can exploit realpath's lexical
    # collapsing of "file/.." to escape the allow-list (e.g.
    # "system/steamos_diy.conf/../../shadow" resolves to "/etc/shadow"
    # which legitimately starts with "/etc/").
    if any(part == ".." for part in Path(member_name).parts):
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_TRAVERSAL: {member_name}",
            level="WARN",
        )
        return None

    match = _match_mapping_prefix(member_name, mapping)
    if match is None:
        return None

    dest_root = mapping[match]
    if member_name == match:
        target = dest_root
    else:
        rel = os.path.relpath(member_name, match)
        target = os.path.join(dest_root, rel)

    if not _is_path_safe(target, allowed):
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_PATH: {member_name} -> {target}",
            level="WARN",
        )
        return None

    return target


def _is_member_safe(member: tarfile.TarInfo) -> bool:
    """Reject hardlinks, symlinks, devices, fifos — only files/dirs trusted."""
    if member.islnk() or member.issym():
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_LINK: {member.name}",
            level="WARN",
        )
        return False
    if member.isdev() or member.isfifo():
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_SPECIAL: {member.name}",
            level="WARN",
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Internal helpers — extraction
# ---------------------------------------------------------------------------


def _ensure_safe_target(target: str) -> bool:
    """Refuse to overwrite a pre-existing symlink at target.

    A symlink planted by a previous malicious archive could redirect
    the write to an arbitrary path; bail out rather than follow it.
    """
    if os.path.islink(target):
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_EXISTING_SYMLINK: {target}",
            level="WARN",
        )
        return False
    return True


def _write_member(
    tar: tarfile.TarFile, member: tarfile.TarInfo, target: str
) -> None:
    """Write member to target; unlink first to avoid ETXTBSY."""
    if member.isdir():
        os.makedirs(target, exist_ok=True)
        return

    os.makedirs(os.path.dirname(target), exist_ok=True)

    if os.path.exists(target):
        try:
            os.unlink(target)
        except OSError as err:
            jlog(
                "SYSTEM",
                f"RESTORE_UNLINK_WARN: {target} - {err}",
                level="WARN",
            )

    src = tar.extractfile(member)
    if src is None:
        return

    with src, open(target, "wb") as dest:
        dest.write(src.read())


def _extract_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    target: str,
    *,
    home_real: str,
    user: str,
) -> bool:
    """Extract member to target; False if target is a pre-existing symlink."""
    if not _ensure_safe_target(target):
        return False
    _write_member(tar, member, target)
    os.chmod(target, member.mode)
    if os.path.realpath(target).startswith(home_real + "/"):
        fix_ownership(target, user)
    return True


# ---------------------------------------------------------------------------
# Internal helpers — archive lifecycle
# ---------------------------------------------------------------------------


# pylint: disable=too-many-arguments
def _process_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    mapping: dict[str, str],
    allowed: tuple[str, ...],
    *,
    home_real: str,
    user: str,
) -> bool:
    """Validate and extract one archive member; False on any rejection."""
    if not _is_member_safe(member):
        return False

    target = _resolve_target(member.name, mapping, allowed)
    if not target:
        return False

    if not _extract_member(
        tar, member, target, home_real=home_real, user=user
    ):
        return False

    jlog("SYSTEM", f"RESTORE_EXTRACT: {target}", level="DEBUG")
    return True


def _extract_payload(
    tar: tarfile.TarFile,
    mapping: dict[str, str],
    allowed: tuple[str, ...],
    home_real: str,
    user: str,
) -> tarfile.TarInfo | None:
    """Extract safe members; defer restore_links.sh to a sandbox runner.

    Returns the restore-script TarInfo if present (so the caller can hand
    it straight to _run_restore_script without a second tar lookup),
    else None.
    """
    script_member: tarfile.TarInfo | None = None

    for member in tar.getmembers():
        if member.name == BACKUP_SCRIPT_NAME:
            script_member = member
            continue
        _process_member(
            tar, member, mapping, allowed, home_real=home_real, user=user
        )

    return script_member


def _run_restore_script(tar: tarfile.TarFile, member: tarfile.TarInfo) -> None:
    """Run restore_links.sh from a root-owned 0700 mkdtemp sandbox.

    Writing to /tmp allowed a race between extraction and exec; mkdtemp
    with mode 0700 (owned by root) closes that TOCTOU window.
    """
    # mkdtemp returns a 0700 dir owned by the calling user (root here)
    sandbox = tempfile.mkdtemp(prefix="sdy_restore_")
    script_path = os.path.join(sandbox, BACKUP_SCRIPT_NAME)

    try:
        src = tar.extractfile(member)
        if src is None:
            return
        with src, open(script_path, "wb") as dest:
            dest.write(src.read())
        os.chmod(script_path, 0o700)
        subprocess.run([script_path], check=True)  # nosec B603
    finally:
        try:
            if os.path.exists(script_path):
                os.remove(script_path)
            os.rmdir(sandbox)
        except OSError as err:
            jlog(
                "SYSTEM",
                f"RESTORE_SANDBOX_CLEANUP_FAIL: {err}",
                level="WARN",
            )


def _reload_systemd() -> None:
    try:
        subprocess.run(  # nosec B603
            ["/usr/bin/systemctl", "daemon-reload"],
            check=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, OSError) as err:
        jlog("SYSTEM", f"RESTORE_DAEMON_RELOAD_FAIL: {err}", level="ERROR")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _prepare_restore(
    archive_path: str,
) -> tuple[str, str, dict[str, str], tuple[str, ...]]:
    """Validate preconditions; exit(1) on first failure to keep callers clean.

    Returns:
        (user, home_real, mapping, allowed) ready for _execute_restore.
    """
    check_root()
    if not os.path.isfile(SSOT_CONF_PATH):
        jlog("SYSTEM", "RESTORE_FAILED: SSoT config not found", level="ERROR")
        sys.exit(1)

    if not os.path.exists(archive_path):
        jlog(
            "SYSTEM",
            f"RESTORE_FAILED: Missing {archive_path}",
            level="ERROR",
        )
        sys.exit(1)

    if not verify_archive(archive_path, "RESTORE_VERIFY_FAIL"):
        sys.exit(1)

    user, home = get_real_user()
    # Two forms intentionally: home_str (unresolved) keeps the mapping in
    # lockstep with the paths backup.py wrote; home_real (symlink-resolved)
    # is what the security allow-list must check against. Not redundant.
    home_str = str(home)
    home_real = str(home.resolve())
    return (
        user,
        home_real,
        get_backup_mapping(home_str),
        _allowed_prefixes(home_real),
    )


def _execute_restore(
    archive_path: str,
    user: str,
    home_real: str,
    mapping: dict[str, str],
    allowed: tuple[str, ...],
) -> None:
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            script_member = _extract_payload(
                tar, mapping, allowed, home_real, user
            )
            jlog("SYSTEM", "RESTORE_PAYLOAD_DONE", level="DEBUG")
            if script_member is not None:
                _run_restore_script(tar, script_member)
                jlog("SYSTEM", "RESTORE_LINKS_DONE", level="DEBUG")
        _reload_systemd()
        jlog("SYSTEM", "RESTORE_SUCCESS: Environment ready.", level="INFO")
    except (tarfile.TarError, OSError, subprocess.SubprocessError) as err:
        jlog(
            "SYSTEM",
            f"RESTORE_FATAL: {type(err).__name__}: {err}",
            level="ERROR",
        )
        sys.exit(1)


def run_restore(archive_path: str) -> None:
    """Restore from archive_path.

    Per-member rejections are logged but non-fatal; archive-level errors
    abort with exit code 1.
    """
    user, home_real, mapping, allowed = _prepare_restore(archive_path)
    _execute_restore(archive_path, user, home_real, mapping, allowed)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_restore(sys.argv[1])
    else:
        sys.exit(1)
