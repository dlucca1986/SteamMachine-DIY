#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Restore Tool
# VERSION:      2.1.7
# DESCRIPTION:  Full system restoration and dynamic symlink reconstruction.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/restore.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import shlex
import shutil

# B404: importing subprocess isn't the risk — every call site below
# passes a fixed argv list, never shell=True or user-controlled input.
import subprocess  # nosec B404
import sys
import tarfile
from pathlib import Path

from utils import (
    BACKUP_MANIFEST_NAME,
    BACKUP_SCRIPT_NAME,
    SYSTEMCTL_BIN,
    check_root,
    fix_ownership,
    get_backup_mapping,
    get_real_user,
    jlog,
    require_ssot_conf,
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


def _allowed_prefixes(
    home_real: str, mapping: dict[str, str]
) -> tuple[str, ...]:
    """Fixed prefixes plus every mapping destination (SSoT-relocatable
    entries like games_conf_dir/next_session are not necessarily under
    home/etc/usr/var, but backup already wrote there, so restore must be
    allowed to write there too)."""
    # Trailing slash prevents "alice" from matching "alicebob".
    extra = tuple(os.path.realpath(dest) + "/" for dest in mapping.values())
    return _ALLOWED_PREFIXES_FIXED + (home_real + "/",) + extra


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
) -> bool:
    """Write member to target via tmp+rename. False if tmp is a symlink.

    Atomic (target either holds the old content or the fully-written new
    one, never missing/truncated on a crash mid-write), and — like
    backup.py's archive write — os.replace also sidesteps ETXTBSY: it
    swaps the directory entry to a new inode instead of truncating the
    file in place, so replacing a currently-running binary still works.
    """
    if member.isdir():
        os.makedirs(target, exist_ok=True)
        return True

    os.makedirs(os.path.dirname(target), exist_ok=True)

    src = tar.extractfile(member)
    if src is None:
        return True

    tmp = f"{target}.sdy_restore_tmp"
    # _ensure_safe_target only checks target itself — this sibling path
    # is where the write actually lands, so it needs the same guard.
    # O_NOFOLLOW refuses a symlink planted here by another process
    # running as this same user, instead of writing through it as root.
    try:
        fd = os.open(
            tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
    except OSError as err:
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_TMP_SYMLINK: {tmp} - {err}",
            level="WARN",
        )
        return False
    with src, os.fdopen(fd, "wb") as dest:
        shutil.copyfileobj(src, dest)
    os.replace(tmp, target)
    return True


def _extract_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    target: str,
    *,
    home_real: str,
    user: str,
) -> bool:
    """Extract member to target; False if target or its tmp write path
    is a pre-existing symlink."""
    if not _ensure_safe_target(target):
        return False
    if not _write_member(tar, member, target):
        return False
    # Mask to permission bits only: a crafted archive must not be able
    # to plant setuid/setgid files through a root-run restore.
    os.chmod(target, member.mode & 0o777)
    if os.path.realpath(target).startswith(home_real + "/"):
        fix_ownership(target, user)
    return True


# ---------------------------------------------------------------------------
# Internal helpers — archive lifecycle
# ---------------------------------------------------------------------------


# 6 logical inputs (tar, member, mapping, allowed-list, home, user) — all
# independently needed for one archive-entry decision, no natural subset.
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
) -> tuple[int, tarfile.TarInfo | None]:
    """Extract safe members; defer the links entry to _restore_links.

    Returns (restored_count, links_member): the links TarInfo (manifest,
    or legacy restore_links.sh) if present, so the caller can hand it
    straight to _restore_links without a second tar lookup, else None;
    restored_count lets the caller distinguish a real restore from an
    archive where every member was rejected (wrong tool, foreign layout).
    """
    links_member: tarfile.TarInfo | None = None
    restored = 0

    for member in tar.getmembers():
        if member.name in (BACKUP_MANIFEST_NAME, BACKUP_SCRIPT_NAME):
            links_member = member
            continue
        if _process_member(
            tar, member, mapping, allowed, home_real=home_real, user=user
        ):
            restored += 1

    return restored, links_member


# ---------------------------------------------------------------------------
# Internal helpers — symlink reconstruction
# ---------------------------------------------------------------------------


def _iter_link_pairs(name: str, text: str):
    """Yield (link, target) pairs from the links entry, any format.

    New archives embed a data manifest: one "link<TAB>target" row per
    line. Legacy archives embed restore_links.sh instead — only its
    "ln -sf <target> <link>" lines are mined for pairs; the script is
    parsed, never executed.
    """
    if name == BACKUP_MANIFEST_NAME:
        for line in text.splitlines():
            link, sep, target = line.partition("\t")
            if sep and link and target:
                yield link, target
        return
    for line in text.splitlines():
        try:
            # Deliberately skip rather than use shlex_split_or_fallback():
            # a degraded str.split() here could pair the wrong link/target
            # and recreate a bogus symlink, which is worse than skipping
            # one legacy entry outright.
            tokens = shlex.split(line)
        except ValueError:
            continue
        if len(tokens) == 4 and tokens[:2] == ["ln", "-sf"]:
            yield tokens[3], tokens[2]


def _restore_link(link: str, target: str, allowed: tuple[str, ...]) -> None:
    """Recreate one symlink after allow-list validation of both ends."""
    if not (
        _is_path_safe(link, allowed) and _is_path_safe(target, allowed)
    ):
        jlog(
            "SYSTEM",
            f"RESTORE_REJECTED_LINK_PATH: {link} -> {target}",
            level="WARN",
        )
        return
    try:
        os.makedirs(os.path.dirname(link), exist_ok=True)
        if os.path.lexists(link):
            os.unlink(link)
        os.symlink(target, link)
    except OSError as err:
        jlog("SYSTEM", f"RESTORE_LINK_FAIL: {link} - {err}", level="WARN")


def _restore_links(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    allowed: tuple[str, ...],
) -> None:
    """Recreate the symlinks recorded in the archive's links entry."""
    src = tar.extractfile(member)
    if src is None:
        return
    with src:
        text = src.read().decode("utf-8", errors="replace")
    for link, target in _iter_link_pairs(member.name, text):
        _restore_link(link, target, allowed)


def _reload_systemd() -> None:
    try:
        # Fixed argv, no shell, no user input involved.
        subprocess.run(  # nosec B603
            [SYSTEMCTL_BIN, "daemon-reload"],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as err:
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
    require_ssot_conf("RESTORE")

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
    mapping = get_backup_mapping(home_str)
    return (
        user,
        home_real,
        mapping,
        _allowed_prefixes(home_real, mapping),
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
            restored, links_member = _extract_payload(
                tar, mapping, allowed, home_real, user
            )
            jlog("SYSTEM", "RESTORE_PAYLOAD_DONE", level="DEBUG")
            if links_member is not None:
                _restore_links(tar, links_member, allowed)
                jlog("SYSTEM", "RESTORE_LINKS_DONE", level="DEBUG")
        if restored == 0:
            # Every member was rejected — a wrong/foreign archive (or one
            # from an incompatible layout) can pass verify_archive's
            # gzip/tar integrity check yet match nothing in the mapping.
            # Reporting that as success would leave the user thinking a
            # restore actually happened when nothing on disk changed.
            jlog(
                "SYSTEM",
                "RESTORE_EMPTY: no member matched the backup mapping",
                level="ERROR",
            )
            sys.exit(1)
        _reload_systemd()
        jlog("SYSTEM", "RESTORE_SUCCESS: Environment ready.", level="INFO")
    except (tarfile.TarError, OSError) as err:
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
