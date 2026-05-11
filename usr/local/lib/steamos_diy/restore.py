#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Restore Tool
# VERSION:      1.3.0
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
    check_root,
    fix_ownership,
    get_real_user,
    get_ssot_var,
    jlog,
    load_ssot,
    verify_archive,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# System-side destinations
_DEFAULT_NEXT_SESSION: str = "/var/lib/steamos_diy/next_session"
_SSOT_CONF_PATH: str = "/etc/default/steamos_diy.conf"
_SERVICE_PATH: str = "/etc/systemd/system/steamos_diy.service"
_CORE_LIB_PREFIX: str = "/usr/local/lib/steamos_diy"

# User-side relative path
_USER_CONFIG_REL: str = ".config/steamos_diy"

# Restore-script handling — extracted to a private root-only directory
# (mode 0700) instead of /tmp, eliminating the TOCTOU window between
# chmod and execution that existed when the file lived in world-writable
# /tmp.
_RESTORE_SCRIPT_NAME: str = "restore_links.sh"

# Allow-list of filesystem prefixes the restore is permitted to write to.
# Each entry is a *real* (symlink-resolved) absolute path; targets are
# normalised before being checked against this set.
_ALLOWED_PREFIXES_FIXED: tuple[str, ...] = (
    "/etc/",
    "/usr/",
    "/var/",
)

# Special-cased archive entry — handled outside the regular extraction loop
_RESTORE_SCRIPT_ARCNAME: str = "restore_links.sh"


# ---------------------------------------------------------------------------
# Internal helpers — destination mapping
# ---------------------------------------------------------------------------


def _build_mapping(home: str) -> dict[str, str]:
    """Return the mapping {archive_prefix: filesystem_destination}.

    Args:
        home: Real user's home directory (resolved by get_real_user).

    Returns:
        Dict mapping each archive prefix produced by backup.py to the
        absolute destination path on disk.
    """
    return {
        "system/next_session": get_ssot_var(
            "next_session", _DEFAULT_NEXT_SESSION
        ),
        "system/steamos_diy.conf": _SSOT_CONF_PATH,
        "system/service": _SERVICE_PATH,
        "source/steamos_diy": _CORE_LIB_PREFIX,
        "user/config": os.path.join(home, _USER_CONFIG_REL),
    }


def _allowed_prefixes(home: str) -> tuple[str, ...]:
    """Return the full allow-list including the dynamic per-user home.

    The home prefix is appended with a trailing slash so a user named
    e.g. ``alice`` cannot match a directory named ``alicebob``.
    """
    home_prefix = str(Path(home).resolve()) + "/"
    return _ALLOWED_PREFIXES_FIXED + (home_prefix,)


# ---------------------------------------------------------------------------
# Internal helpers — security validation
# ---------------------------------------------------------------------------


def _is_path_safe(target: str, allowed: tuple[str, ...]) -> bool:
    """Return True if *target* resolves into one of the allowed prefixes.

    Uses ``os.path.realpath`` to follow any pre-existing symlinks at the
    parent directory level — this defeats symlink redirection attacks
    where an earlier malicious archive planted a symlink pointing
    outside the legitimate destination.

    Args:
        target: Candidate absolute path to validate.
        allowed: Allow-listed prefixes (each ending with "/").

    Returns:
        True if the resolved target is strictly inside any allow-listed
        prefix, False otherwise.
    """
    real = os.path.realpath(target)
    # Append "/" before comparison so "/etcfoo" cannot match "/etc"
    real_check = real if real.endswith("/") else real + "/"
    return any(real_check.startswith(prefix) for prefix in allowed)


def _match_mapping_prefix(
    member_name: str, mapping: dict[str, str]
) -> str | None:
    """Return the longest mapping key that matches *member_name*, or None.

    Uses path-component matching (exact match or prefix + "/") so that
    a mapping key ``user/config`` does not erroneously match an archive
    entry ``user/config_backup/``. Selects the longest match to avoid
    ambiguity when keys share a common root.
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
    """Resolve an archive member to a safe filesystem destination.

    Path-traversal protection: the joined path is resolved with
    ``os.path.realpath`` so that ``..`` segments are normalised BEFORE
    the allow-list check. This was previously broken because the original
    check used ``abspath``, which collapses ``..`` but the result was
    only matched against ``startswith("/etc")`` — letting an archive
    member like ``system/next_session/../../etc/passwd`` slip through.

    Args:
        member_name: Archive-relative path of the tar member.
        mapping: Prefix-to-destination map produced by _build_mapping.
        allowed: Allow-list of safe filesystem prefixes.

    Returns:
        Validated absolute target path, or None if the member doesn't
        match any mapping prefix or escapes the allow-list.
    """
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
    """Reject hardlink/symlink/device/fifo entries inside the archive.

    A trusted backup contains only regular files and directories under
    the documented prefixes. Anything else is suspicious and could be
    used to overwrite arbitrary files via link redirection.

    Args:
        member: Tar member metadata.

    Returns:
        True for regular files and directories only, False otherwise.
    """
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
    """Refuse to overwrite *target* if it's currently a symlink.

    Without this guard, an attacker who can plant a symlink in a
    legitimate destination directory could redirect the next restore
    write to an arbitrary file. Returns False on refusal so the caller
    skips the extraction without aborting the whole restore.
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
    """Write a member, unlinking existing files to bypass ETXTBSY.

    Args:
        tar: Open tar archive.
        member: Member to extract.
        target: Pre-validated filesystem destination.
    """
    if member.isdir():
        os.makedirs(target, exist_ok=True)
        return

    os.makedirs(os.path.dirname(target), exist_ok=True)

    if os.path.exists(target):
        try:
            os.unlink(target)
        except OSError:
            pass

    src = tar.extractfile(member)
    if src is None:
        return

    with src, open(target, "wb") as dest:
        dest.write(src.read())


def _apply_metadata(
    target: str, member: tarfile.TarInfo, home_real: str, user: str
) -> None:
    """Set mode and ownership on *target* after extraction."""
    os.chmod(target, member.mode)
    if os.path.realpath(target).startswith(home_real + "/"):
        fix_ownership(target, user)


def _extract_member(
    tar: tarfile.TarFile,
    member: tarfile.TarInfo,
    target: str,
    *,
    home_real: str,
    user: str,
) -> bool:
    """Extract *member* to *target*, applying mode and ownership.

    Args:
        tar: Open tar archive.
        member: Member to extract.
        target: Pre-validated filesystem destination.
        home_real: Resolved real path of the user's home (for chown
            decision — substring match was unsafe in the original).
        user: Real username for ownership.

    Returns:
        True on success, False if the destination was a symlink and
        the write was refused for safety.
    """
    if not _ensure_safe_target(target):
        return False
    _write_member(tar, member, target)
    _apply_metadata(target, member, home_real, user)
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
    """Validate, resolve and extract a single archive member.

    Args:
        tar: Open tar archive.
        member: Member to process.
        mapping: Prefix-to-destination map.
        allowed: Allow-list of safe filesystem prefixes.
        home_real: Resolved real path of the user's home.
        user: Real username for ownership.

    Returns:
        True if the member was extracted, False if it was rejected for
        any reason (unsafe link, no mapping, path escape, symlink at
        destination).
    """
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
) -> str | None:
    """Extract every safe member, return path of restore_links.sh if any.

    The restore script is special-cased — it's extracted to a private
    root-only temp directory (created by the caller) instead of being
    written into one of the standard prefixes. This eliminates the
    TOCTOU window that existed when it was written to /tmp and then
    chmod+exec'd.

    Args:
        tar: Open tar archive.
        mapping: Prefix-to-destination map.
        allowed: Allow-list of safe filesystem prefixes.
        home_real: Resolved real path of the user's home.
        user: Real username for ownership.

    Returns:
        Filesystem path to the extracted restore_links.sh, or None if
        the archive doesn't contain one.
    """
    script_path: str | None = None

    for member in tar.getmembers():
        if member.name == _RESTORE_SCRIPT_ARCNAME:
            # Deferred to the post-extraction sandbox runner.
            script_path = _RESTORE_SCRIPT_ARCNAME
            continue
        _process_member(
            tar, member, mapping, allowed, home_real=home_real, user=user
        )

    return script_path


def _run_restore_script(tar: tarfile.TarFile) -> None:
    """Extract restore_links.sh to a private root-only dir and run it.

    The script is extracted into a fresh ``mkdtemp`` directory created
    with mode 0700, owned by root. This is immune to the TOCTOU
    pre-image attack possible when the script was written to /tmp.

    Args:
        tar: Open tar archive containing restore_links.sh.
    """
    try:
        member = tar.getmember(_RESTORE_SCRIPT_ARCNAME)
    except KeyError:
        return

    # mkdtemp returns a 0700 dir owned by the calling user (root here)
    sandbox = tempfile.mkdtemp(prefix="sdy_restore_")
    script_path = os.path.join(sandbox, _RESTORE_SCRIPT_NAME)

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
    """Tell systemd to re-read unit files; surface failures explicitly."""
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


def run_restore(archive_path: str) -> None:
    """Restore the system from *archive_path*.

    Flow:
        1. Verify root privileges and load the SSoT config.
        2. Resolve the real user behind sudo/pkexec.
        3. Pre-flight: confirm the archive exists and is readable.
        4. Verify integrity by walking the archive end-to-end before
           writing anything to disk.
        5. Extract every safe member to its mapped destination, with
           path-traversal and symlink protection at every step.
        6. Run the embedded restore_links.sh in a private 0700 sandbox.
        7. Reload systemd so service unit changes take effect.

    Exits with status 1 on any pre-flight or extraction failure. The
    restore is best-effort once started: per-member rejections are
    logged but do not abort the whole operation, while archive-level
    failures (corruption, missing file) abort cleanly.

    Args:
        archive_path: Filesystem path to a *.tar.gz produced by backup.py.
    """
    check_root()
    if not load_ssot():
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
    home_str = str(home)
    home_real = str(Path(home).resolve())
    mapping = _build_mapping(home_str)
    allowed = _allowed_prefixes(home_str)

    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            has_script = _extract_payload(
                tar, mapping, allowed, home_real, user
            )
            jlog("SYSTEM", "RESTORE_PAYLOAD_DONE", level="DEBUG")
            if has_script:
                _run_restore_script(tar)
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


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_restore(sys.argv[1])
    else:
        sys.exit(1)
