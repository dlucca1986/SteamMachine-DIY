#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Shared Library
# VERSION:      2.1.6
# DESCRIPTION:  Shared library. Mandatory C-Core integration.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/utils.py
# LICENSE:      MIT
# =============================================================================
"""

import ctypes
import os
import pwd
import shutil
import subprocess  # nosec B404
import sys
import tarfile
import threading
from pathlib import Path
from typing import Any, NamedTuple, overload

from ruamel.yaml import YAML as _YAML, YAMLError

_yaml_reader = _YAML(typ="safe")


# ---------------------------------------------------------------------------
# C-Core integration — mandatory at import time.
# ---------------------------------------------------------------------------

_CORE_LIB_PATH: str = "/usr/local/lib/steamos_diy/libcore.so"

try:
    _LIB: ctypes.CDLL = ctypes.CDLL(_CORE_LIB_PATH)

    _LIB.c_jlog.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _LIB.c_notify.argtypes = [ctypes.c_char_p, ctypes.c_int]
    _LIB.c_write_atomic.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    _LIB.c_sd_notify_ready.argtypes = []

except OSError as err:
    sys.stderr.write(f"FATAL: C-Core missing at {_CORE_LIB_PATH}: {err}\n")
    sys.exit(127)


# ---------------------------------------------------------------------------
# Project-wide path constants — single source of truth for all modules.
# ---------------------------------------------------------------------------

# Runtime project version — kept in sync with the file headers by the
# release bump (a plain-text substitution across the whole tree).
VERSION: str = "2.1.6"

SSOT_CONF_PATH: str = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
NEXT_SESSION_PATH: str = "/var/lib/steamos_diy/next_session"
CORE_LIB_DIR: str = "/usr/local/lib/steamos_diy"
_SERVICE_PATH: str = "/etc/systemd/system/steamos_diy.service"

# User-side path (relative to home) and embedded archive-entry names.
# Centralised here so the archive format contract has a single source of
# truth — backup and restore can never disagree about what goes where.
# BACKUP_SCRIPT_NAME survives only so restore can recognise the legacy
# entry in old archives; new backups embed the data manifest instead.
USER_CONFIG_REL: str = ".config/steamos_diy"
BACKUP_SCRIPT_NAME: str = "restore_links.sh"
BACKUP_MANIFEST_NAME: str = "links.txt"

# Where downloaded release tarballs are unpacked, relative to the user
# config dir. Shared with backup.py, which must exclude it from archives.
UPDATES_DIR_NAME: str = "updates"

# In-process cache for SSoT values, filled by one full parse on first
# access — a missing key then costs a dict miss, not a disk re-read.
# The loaded flag lives in a mutable cell so clear_ssot_cache can reset
# it without a `global` statement (same idiom as run()'s proc_holder).
_SSOT_CACHE: dict[str, str] = {}
_SSOT_LOADED: list[bool] = [False]

# syslog priority levels for c_jlog (RFC 5424 severity).
_LEVELS_C: dict[str, int] = {"DEBUG": 7, "INFO": 6, "WARN": 4, "ERROR": 3}

# Numeric priorities for log-level filtering (lower = less important).
_LEVELS_NUM: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 25,
    "ERROR": 30,
}

# Default thresholds used when a level/value is missing or malformed.
_DEFAULT_LEVEL_NUM: int = 20  # INFO
_DEFAULT_LEVEL_C: int = 6  # INFO

# Recursion guard — thread-local so the post_start_cmds thread and the
# main thread each track their own jlog re-entry independently. A shared
# flag would let one thread's log bypass the LOG_LEVEL threshold while
# another holds the guard.
_JLOG_REENTRY = threading.local()


# ---------------------------------------------------------------------------
# Logging & feedback
# ---------------------------------------------------------------------------


def jlog(tag: str, message: str, level: str = "INFO") -> None:
    """Route a log entry to the kernel journal, gated by SSoT LOG_LEVEL.

    Filters in Python before any C call to skip suppressed levels cheaply.
    _JLOG_REENTRY prevents infinite recursion when get_ssot_var itself
    triggers a log call (e.g. a decode error while reading LOG_LEVEL).
    """
    if getattr(_JLOG_REENTRY, "active", False):
        # Already inside jlog: skip threshold lookup and emit directly
        # at the requested level. This avoids recursion via get_ssot_var.
        _LIB.c_jlog(
            tag.replace(":", "").strip().encode("utf-8"),
            message.encode("utf-8"),
            _LEVELS_C.get(level.upper(), _DEFAULT_LEVEL_C),
        )
        return

    _JLOG_REENTRY.active = True
    try:
        sys_threshold = _LEVELS_NUM.get(
            get_ssot_var("LOG_LEVEL", "INFO").upper(),
            _DEFAULT_LEVEL_NUM,
        )
        msg_level = _LEVELS_NUM.get(level.upper(), _DEFAULT_LEVEL_NUM)

        # Discard messages less important than the system threshold
        if msg_level < sys_threshold:
            return

        _LIB.c_jlog(
            tag.replace(":", "").strip().encode("utf-8"),
            message.encode("utf-8"),
            _LEVELS_C.get(level.upper(), _DEFAULT_LEVEL_C),
        )
    finally:
        _JLOG_REENTRY.active = False


def notify(status: str, clear_after: bool = False) -> None:
    """Write *status* to /dev/tty1 via C-Core, bypassing Python buffering."""
    _LIB.c_notify(status.encode("utf-8"), 1 if clear_after else 0)


def sd_notify_ready() -> None:
    """Send READY=1 to systemd via C-Core."""
    _LIB.c_sd_notify_ready()


# ---------------------------------------------------------------------------
# Config & filesystem
# ---------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    """Strip whitespace and matching outer quotes from a key=value RHS."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _load_ssot_cache() -> None:
    """Parse the whole SSoT file into the cache in a single disk read.

    First occurrence wins on duplicate keys (same as the old per-key
    scan). The loaded flag is set before parsing so a read failure is
    cached too instead of being retried on every later lookup. Resolved
    values are exported to os.environ so spawned subprocesses inherit
    them without re-reading the config.
    """
    _SSOT_LOADED[0] = True
    try:
        with open(SSOT_CONF_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                _SSOT_CACHE.setdefault(key.strip(), _strip_quotes(raw))
    except OSError as err:
        jlog("CORE", f"SSOT_READ_ERROR: {err}", level="DEBUG")
    os.environ.update(_SSOT_CACHE)


@overload
def get_ssot_var(var_name: str, default: str) -> str: ...


@overload
def get_ssot_var(var_name: str, default: None = ...) -> str | None: ...


def get_ssot_var(var_name: str, default: str | None = None) -> str | None:
    """Read a SSoT config value from the in-process cache.

    The first call parses the whole file once (_load_ssot_cache); later
    calls — hit or miss — never touch the disk.
    """
    if not _SSOT_LOADED[0]:
        _load_ssot_cache()
    return _SSOT_CACHE.get(var_name, default)


def clear_ssot_cache() -> None:
    """Drop the in-process SSoT cache so the next read hits disk.

    The session launcher reads config once at boot and benefits from the
    cache, but long-lived tools (the Control Center doctor) must re-validate
    the *current* on-disk config after the user edits it.
    """
    _SSOT_CACHE.clear()
    _SSOT_LOADED[0] = False


def get_ssot_num(var_name: str, default: float) -> float:
    """Read a numeric SSoT value; fall back to *default* if malformed.

    SSoT values are hand-editable, so a typo (e.g. "5s", a stray comma, an
    empty value) must degrade to the default with a warning rather than raise
    an unguarded ValueError that could brick the session boot loop.
    """
    try:
        return float(get_ssot_var(var_name, str(default)))
    except (TypeError, ValueError):
        jlog("CORE", f"BAD_SSOT_NUM: {var_name} - using {default}", "WARN")
        return default


def read_session_target(path: str | Path, default: str = "steam") -> str:
    """Read the first line of *path*; fall back to *default* on failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = _strip_quotes(fh.readline())
            return value or default
    except OSError:
        return default


def load_yaml_safe(path: str | Path | None) -> dict[str, Any]:
    """Parse *path* as a YAML mapping; return {} on error or wrong shape."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = _yaml_reader.load(fh)
    except (OSError, ValueError) as err:
        jlog("CORE", f"YAML_LOAD_ERROR: {path} - {err}", level="DEBUG")
        return {}
    except YAMLError as err:
        jlog("CORE", f"YAML_PARSE_ERROR: {path} - {err}", level="DEBUG")
        return {}
    if isinstance(data, dict):
        return data
    if data is not None:
        # Valid YAML but wrong shape (list/scalar root): callers do
        # cfg.get(...) on the result, so returning it as-is would crash
        # the session at boot. Degrade to {} and warn loudly.
        jlog("CORE", f"YAML_NOT_MAPPING: {path}", level="WARN")
    return {}


def write_atomic(path: str | Path, val: str) -> None:
    """Write *val* to *path* via C-Core (tmp+rename+fdatasync, SSD-durable)."""
    _LIB.c_write_atomic(str(path).encode("utf-8"), str(val).encode("utf-8"))


# ---------------------------------------------------------------------------
# Environment & process management
# ---------------------------------------------------------------------------


def apply_env_map(data_dict: dict[str, Any] | None) -> None:
    """Inject *data_dict* into os.environ; skips None values."""
    if not isinstance(data_dict, dict):
        return
    for key, val in data_dict.items():
        if val is not None:
            os.environ[str(key)] = str(val)


def spawn_native(path: str, args: list[str]) -> int:
    """Fork/exec *path* detached; returns PID or 0 on failure.

    Uses ``start_new_session=True`` (setsid) so the child survives the
    caller and does not inherit the controlling terminal.
    """
    try:
        # pylint: disable=consider-using-with
        # Detached spawn — `with` would force a wait() on context exit,
        # defeating the whole point of fire-and-forget.
        proc = subprocess.Popen(  # nosec B603
            args,
            executable=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return proc.pid
    except (OSError, ValueError) as err:
        jlog("CORE", f"SPAWN_ERROR: {path} - {err}", level="WARN")
        return 0


# ---------------------------------------------------------------------------
# System & user management
# ---------------------------------------------------------------------------


def get_real_user() -> tuple[str, Path]:
    """Resolve real user behind sudo/pkexec; falls back to ("root", /root)."""
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    try:
        u_info = pwd.getpwuid(int(uid)) if uid else pwd.getpwuid(os.getuid())
        return u_info.pw_name, Path(u_info.pw_dir)
    except (ValueError, KeyError, TypeError) as err:
        jlog("CORE", f"USER_LOOKUP_ERROR: {err}", level="DEBUG")
        return "root", Path("/root")


def fix_ownership(target_path: str | Path, user_name: str) -> None:
    """Set ownership of *target_path* to *user_name*; no-op for root/empty."""
    if not user_name or user_name == "root":
        return
    target = Path(target_path)
    try:
        u_info = pwd.getpwnam(user_name)
        if target.is_dir():
            subprocess.run(  # nosec B603
                [
                    "/usr/bin/chown",
                    "-R",
                    f"{user_name}:{user_name}",
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.chown(target, u_info.pw_uid, u_info.pw_gid)
    except (OSError, KeyError, subprocess.CalledProcessError) as err:
        jlog("CORE", f"OWNERSHIP_ERROR: {target_path} - {err}", level="DEBUG")


def check_root() -> None:
    """Exit with code 1 unless UID == 0."""
    if os.getuid() != 0:
        sys.exit(1)


def get_backup_mapping(home: str) -> dict[str, str]:
    """Archive-path → filesystem-path map. Single source of truth for the
    backup format used by both backup.py and restore.py.

    Adding a new entry here propagates to both sides: backup picks it up
    when adding members, restore picks it up when mapping them back.
    Order is preserved (3.7+ dict insertion order).
    """
    return {
        "system/next_session": get_ssot_var("next_session", NEXT_SESSION_PATH),
        "system/steamos_diy.conf": SSOT_CONF_PATH,
        "system/service": _SERVICE_PATH,
        "source/steamos_diy": CORE_LIB_DIR,
        "user/config": os.path.join(home, USER_CONFIG_REL),
    }


def verify_archive(
    path: str | Path, fail_tag: str = "ARCHIVE_VERIFY_FAIL"
) -> bool:
    """Walk all tar members end-to-end to verify gzip integrity."""
    try:
        with tarfile.open(str(path), "r:gz") as tar:
            for _ in tar:
                pass
        return True
    except (tarfile.TarError, OSError, EOFError) as err:
        jlog("SYSTEM", f"{fail_tag}: {err}", level="ERROR")
        return False


def run_shim(tag: str, message: str, exit_code: int = 0) -> None:
    """Log the intercepted SteamOS call and exit with the expected code."""
    jlog(tag, message)
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Update check & download (GitHub Releases) — no Qt, testable standalone.
# ---------------------------------------------------------------------------

_RELEASES_API: str = (
    "https://api.github.com/repos/dlucca1986/SteamMachine-DIY"
    "/releases/latest"
)
_HTTP_TIMEOUT: int = 10


class ReleaseInfo(NamedTuple):
    """Latest-release facts consumed by the Control Center updater."""

    version: str
    is_newer: bool
    notes: str
    tarball_url: str
    html_url: str


def _version_tuple(text: str) -> tuple[int, ...]:
    """Parse "v2.1.6"/"2.1.6" into a comparable tuple; (0,) if malformed."""
    try:
        return tuple(int(p) for p in text.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def _api_str(data: dict[str, Any], key: str) -> str:
    """String field from the API reply; missing/None degrade to ""."""
    val = data.get(key)
    return str(val) if val else ""


def _release_from_api(data: Any) -> ReleaseInfo | None:
    """Map the releases-API JSON to a ReleaseInfo; None if unusable."""
    if not isinstance(data, dict) or not data.get("tag_name"):
        jlog("SYSTEM", "UPDATE_CHECK_FAIL: malformed API reply", "WARN")
        return None
    remote = _api_str(data, "tag_name").lstrip("v")
    return ReleaseInfo(
        version=remote,
        is_newer=_version_tuple(remote) > _version_tuple(VERSION),
        notes=_api_str(data, "body"),
        tarball_url=_api_str(data, "tarball_url"),
        html_url=_api_str(data, "html_url"),
    )


def check_latest_release() -> ReleaseInfo | None:
    """Query GitHub for the latest published release.

    Returns None when the network or the API reply is unusable — the
    caller renders that as "could not check", never as a crash. Fixed
    https URL and a short timeout: a dead network degrades to a quick
    "unknown" instead of hanging the worker thread.
    """
    # Deferred imports: urllib pulls in ~40ms of http machinery. Only
    # the Control Center pays that, never the session-boot or game-
    # launch paths that import utils.
    # pylint: disable=import-outside-toplevel
    import json
    import urllib.request
    from http.client import HTTPException

    req = urllib.request.Request(
        _RELEASES_API,
        headers={
            "User-Agent": "SteamMachine-DIY",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        # B310: fixed https:// URL (_RELEASES_API), no user-controlled scheme.
        with urllib.request.urlopen(  # nosec B310
            req, timeout=_HTTP_TIMEOUT
        ) as resp:
            data = json.load(resp)
    except (OSError, ValueError, HTTPException) as err:
        jlog("SYSTEM", f"UPDATE_CHECK_FAIL: {err}", level="WARN")
        return None
    return _release_from_api(data)


def _prune_downloads(root: Path) -> None:
    """Drop previous release downloads (v<digit>… dirs) under *root*.

    Only version-named directories are touched, so anything the user
    parked in the updates folder by hand survives the cleanup.
    """
    for entry in root.iterdir():
        if (
            entry.is_dir()
            and entry.name.startswith("v")
            and entry.name[1:2].isdigit()
        ):
            shutil.rmtree(entry, ignore_errors=True)


def download_release(info: ReleaseInfo, dest_root: str | Path) -> Path | None:
    """Download and unpack *info*'s source tarball under *dest_root*.

    Layout: <dest_root>/v<version>/<github-export-dir>/… — returns the
    inner export directory (the one holding install.sh), or None on any
    failure. Older downloads are pruned first so the updates folder
    never accumulates stale releases. The "data" extraction filter
    rejects absolute paths, traversal and special members.
    """
    # Deferred imports — see check_latest_release.
    # pylint: disable=import-outside-toplevel
    import urllib.request
    from http.client import HTTPException

    if not info.tarball_url.startswith("https://"):
        jlog("SYSTEM", "UPDATE_DOWNLOAD_FAIL: non-https URL", "ERROR")
        return None
    root = Path(dest_root)
    target = root / f"v{info.version}"
    req = urllib.request.Request(
        info.tarball_url, headers={"User-Agent": "SteamMachine-DIY"}
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
        _prune_downloads(root)
        # B310: scheme constrained to https:// by the guard above.
        with urllib.request.urlopen(  # nosec B310
            req, timeout=_HTTP_TIMEOUT
        ) as resp:
            with tarfile.open(fileobj=resp, mode="r|gz") as tar:
                tar.extractall(target, filter="data")
    except (OSError, ValueError, tarfile.TarError, HTTPException) as err:
        jlog("SYSTEM", f"UPDATE_DOWNLOAD_FAIL: {err}", level="ERROR")
        return None
    for entry in sorted(target.iterdir()):
        if (entry / "install.sh").is_file():
            return entry
    jlog("SYSTEM", "UPDATE_DOWNLOAD_FAIL: install.sh not found", "ERROR")
    return None
