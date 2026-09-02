#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Shared Library
# VERSION:      2.1.7
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
import re
import shlex
import shutil

# B404: importing subprocess isn't the risk — every call site below
# passes a fixed argv list, never shell=True or user-controlled input.
import subprocess  # nosec B404
import sys
import tarfile
import threading
from pathlib import Path
from typing import Any, NamedTuple, overload

from ruamel.yaml import YAML as _YAML
from ruamel.yaml import YAMLError

_yaml_reader = _YAML(typ="safe")


# ---------------------------------------------------------------------------
# C-Core integration — mandatory at import time.
# ---------------------------------------------------------------------------

# Public so health.py's C-Core preflight check can report the same path
# it's actually loaded from here, instead of re-deriving its own copy.
CORE_LIB_PATH: str = "/usr/local/lib/steamos_diy/libcore.so"

try:
    _LIB: ctypes.CDLL = ctypes.CDLL(CORE_LIB_PATH)

    _LIB.c_jlog.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _LIB.c_notify.argtypes = [ctypes.c_char_p, ctypes.c_int]
    _LIB.c_write_atomic.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    _LIB.c_write_atomic.restype = ctypes.c_int
    _LIB.c_sd_notify_ready.argtypes = []

except OSError as err:
    sys.stderr.write(f"FATAL: C-Core missing at {CORE_LIB_PATH}: {err}\n")
    sys.exit(127)


# ---------------------------------------------------------------------------
# Project-wide path constants — single source of truth for all modules.
# ---------------------------------------------------------------------------

# Runtime project version — kept in sync with the file headers by the
# release bump (a plain-text substitution across the whole tree).
VERSION: str = "2.1.7"

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

# Basename of the global config file under user_config's directory.
# Shared by get_backup_mapping (below) and control_center.py's
# _resolve_config_paths so the two can't independently drift on what a
# relocated user_config's directory is computed relative to.
CONFIG_FILE_NAME: str = "config.yaml"

# Where downloaded release tarballs are unpacked, relative to the user
# config dir. Shared with backup.py, which must exclude it from archives.
UPDATES_DIR_NAME: str = "updates"

# Session binary fallbacks, used when the matching SSoT bin_* key is
# unset. Single source of truth for session_launch.py, session_select.py
# and health.py's preflight — previously each re-declared its own copy,
# risking drift if a distro ever relocates one of these.
DEFAULT_GS_BIN: str = "/usr/bin/gamescope"
DEFAULT_STEAM_BIN: str = "/usr/bin/steam"
DEFAULT_PLASMA_BIN: str = "/usr/bin/startplasma-wayland"
DEFAULT_DBUS_BIN: str = "/usr/bin/qdbus6"

# systemd tool paths — unlike the DEFAULT_*_BIN group above, these are not
# SSoT-backed: every systemd distro ships them at this fixed path, so
# there's no legitimate per-deployment override. Centralized here purely
# to stop health.py/restore.py/journal.py/control_center.py from each
# re-declaring their own literal.
SYSTEMCTL_BIN: str = "/usr/bin/systemctl"
JOURNALCTL_BIN: str = "/usr/bin/journalctl"
PYTHON3_BIN: str = "/usr/bin/python3"
KONSOLE_BIN: str = "/usr/bin/konsole"

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
    except (OSError, UnicodeDecodeError) as err:
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
    except (OSError, UnicodeDecodeError):
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


GAMES_CONF_SUBDIR: str = "games.d"


def default_games_conf_dir() -> Path:
    """Fallback games_conf_dir when the SSoT key is unset.

    ~/.config/steamos_diy/games.d — the same default the SSoT template
    itself ships (etc/default/steamos_diy.conf). Single source of truth
    for sdy.py and control_center.py so they can't silently disagree on
    where per-game profiles live if the SSoT key is ever missing.
    """
    return Path.home() / USER_CONFIG_REL / GAMES_CONF_SUBDIR


def shlex_split_or_fallback(value: str) -> tuple[list[str], ValueError | None]:
    """shlex.split *value*; on an unbalanced quote, also return str.split().

    Shared by every hand-edited shell-like field (game flags, wrapper,
    extra args, gamescope preflight) so a malformed entry degrades instead
    of crashing the session. The second return value is the caught error,
    or None on a clean parse — callers that want to warn about the
    fallback log it themselves, since the tag/field name differs per call
    site.
    """
    try:
        return shlex.split(value), None
    except ValueError as err:
        return value.split(), err


def write_atomic(path: str | Path, val: str) -> bool:
    """Write *val* to *path* via C-Core (tmp+rename+fdatasync, SSD-durable).

    Returns True on success, False on any failure (symlink/FIFO refused at
    tmp_path, a short write, or a failed rename) — already logged via
    syslog on the C side, but callers that need to react (not just have a
    trace to grep for later) can now check the result instead of assuming
    the write landed.
    """
    return bool(
        _LIB.c_write_atomic(
            str(path).encode("utf-8"), str(val).encode("utf-8")
        )
    )


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
            # user_name is the machine's real login user (resolved via
            # pwd above), never attacker-controlled input; fixed argv.
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
                timeout=30,
            )
        else:
            os.chown(target, u_info.pw_uid, u_info.pw_gid)
    except (OSError, KeyError, subprocess.SubprocessError) as err:
        # WARN, not DEBUG: a failed/timed-out chown leaves target_path
        # owned by root after a backup/restore ran as the privileged
        # user, which the user needs to notice and fix manually.
        jlog("CORE", f"OWNERSHIP_ERROR: {target_path} - {err}", level="WARN")


def check_root() -> None:
    """Exit with code 1 unless UID == 0."""
    if os.getuid() != 0:
        sys.exit(1)


def require_ssot_conf(tag: str) -> None:
    """Exit with code 1, logging f"{tag}_FAILED", if the SSoT conf is missing.

    Shared precondition for backup.py and restore.py, which both need the
    SSoT readable before doing anything privileged.
    """
    if not os.path.isfile(SSOT_CONF_PATH):
        jlog("SYSTEM", f"{tag}_FAILED: SSoT config not found", level="ERROR")
        sys.exit(1)


def get_backup_mapping(
    home: str, *, for_restore: bool = False
) -> dict[str, str]:
    """Archive-path → filesystem-path map. Single source of truth for the
    backup format used by both backup.py and restore.py.

    Adding a new entry here propagates to both sides: backup picks it up
    when adding members, restore picks it up when mapping them back.
    Order is preserved (3.7+ dict insertion order).

    for_restore always includes the "user/games_conf_dir" entry - see
    that entry's own comment below for why restore can't use the same
    "only if it needs one" optimization backup does.
    """
    # user_config is SSoT-relocatable to a different *directory* (the
    # basename always stays CONFIG_FILE_NAME - see CLAUDE.md's confirmed-
    # intentional note on control_center.py's Global Options tab). Without
    # resolving it the same way control_center.py's _resolve_config_paths
    # does, a relocated config would silently back up the wrong (default)
    # directory instead of the live one.
    default_conf_dir = os.path.join(home, USER_CONFIG_REL)
    conf_dir = os.path.dirname(
        get_ssot_var(
            "user_config",
            os.path.join(default_conf_dir, CONFIG_FILE_NAME),
        )
    )
    if not conf_dir:
        # A hand-edited user_config with no directory component (e.g. a
        # bare "config.yaml") makes os.path.dirname() return "".
        # os.path.realpath("") resolves to the process's CURRENT WORKING
        # DIRECTORY, not a config path — restore.py's _allowed_prefixes
        # would otherwise add that unmodified to its allow-list of
        # privileged (root, under pkexec) write destinations. Degrade to
        # the same default used when user_config is unset entirely,
        # matching get_ssot_num's own degrade-safely contract, instead of
        # silently widening the restore write surface to an unpredictable
        # cwd.
        conf_dir = default_conf_dir
    mapping = {
        "system/next_session": get_ssot_var("next_session", NEXT_SESSION_PATH),
        "system/steamos_diy.conf": SSOT_CONF_PATH,
        "system/service": _SERVICE_PATH,
        "source/steamos_diy": CORE_LIB_DIR,
        "user/config": conf_dir,
    }
    # A games_conf_dir is backed up recursively for free only when it's
    # actually nested under the (possibly relocated) user/config entry
    # above - otherwise, whether relocated itself or just left at its own
    # default while user_config moved elsewhere, it needs its own entry or
    # it silently drops out of every backup, and restore has no key to put
    # it back even if it had been captured.
    default_games_dir = os.path.join(
        home, USER_CONFIG_REL, GAMES_CONF_SUBDIR
    )
    games_dir = get_ssot_var("games_conf_dir", default_games_dir)
    games_real = os.path.realpath(games_dir) + os.sep
    conf_real = os.path.realpath(conf_dir) + os.sep
    nested = games_real.startswith(conf_real)
    # On restore, the archive's member names were fixed by whatever this
    # same nesting check evaluated to AT BACKUP TIME on a possibly
    # different system state (e.g. a from-scratch reinstall after a
    # system failure, restoring onto a fresh default SSoT from an
    # archive made while games_conf_dir was relocated to an SD card) -
    # this process has no way to know that before opening the tar, so
    # the entry is included unconditionally here; it only ever matches
    # archive members that actually exist under that prefix, so it's a
    # harmless no-op for an archive where nesting still holds.
    if for_restore or not nested:
        mapping["user/games_conf_dir"] = games_dir
    return mapping


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

# Release asset name every release must carry from 2.1.8 on: one line,
# the tarball_url source tarball's hex SHA-256 digest. See download_release().
_CHECKSUM_ASSET_NAME: str = "SHA256SUMS"


class ReleaseInfo(NamedTuple):
    """Latest-release facts consumed by the Control Center updater."""

    version: str
    is_newer: bool
    notes: str
    tarball_url: str
    html_url: str
    checksum_url: str


class ExtractedRelease(NamedTuple):
    """download_release()'s success result: extracted dir + install.sh hash.

    install_sh_sha256 lets the caller re-verify install.sh's integrity
    immediately before executing it via pkexec, narrowing the TOCTOU
    window between this checksum-verified extraction and actual root
    execution — the extracted directory lives under the user's own home,
    writable by that same user.
    """

    dir: Path
    install_sh_sha256: str


def _https_open(url: str, *, extra_headers: dict[str, str] | None = None):
    """Open *url* over HTTPS with the shared SteamMachine-DIY User-Agent.

    Centralizes the Request/urlopen/timeout plumbing common to every
    GitHub-release network call below (check_latest_release,
    _fetch_expected_sha256, _download_verified_tarball); each caller
    keeps its own error handling since what counts as recoverable, and
    what to log, differs per caller (JSON parsing vs. raw digest text
    vs. streamed binary). Every call site passes a URL already confirmed
    https:// (either _RELEASES_API itself or a caller-side guard), so the
    scheme is never attacker-controlled.
    """
    # Deferred import: urllib pulls in ~40ms of http machinery, paid only
    # by the Control Center's update-check path, never session-boot.
    # pylint: disable=import-outside-toplevel
    import urllib.request

    headers = {"User-Agent": "SteamMachine-DIY"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    # B310: every caller has already confirmed url is https:// (see this
    # function's docstring), so the scheme is never attacker-controlled.
    return urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)  # nosec B310


def _require_https(url: str, fail_tag: str) -> bool:
    """Log and return False if *url* isn't https://; True otherwise.

    Shared by every caller that must reject a non-https URL before it
    ever reaches _https_open(), which trusts its caller to have already
    done this check.
    """
    if url.startswith("https://"):
        return True
    jlog("SYSTEM", f"{fail_tag}: non-https URL", "ERROR")
    return False


def _version_tuple(text: str) -> tuple[int, ...]:
    """Parse "v2.1.7"/"2.1.7" into a comparable tuple; (0,) if malformed."""
    try:
        return tuple(int(p) for p in text.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def _api_str(data: dict[str, Any], key: str) -> str:
    """String field from the API reply; missing/None degrade to ""."""
    val = data.get(key)
    return str(val) if val else ""


def _find_checksum_url(data: dict[str, Any]) -> str:
    """browser_download_url of the release's SHA256SUMS asset, or ""."""
    assets = data.get("assets")
    if not isinstance(assets, list):
        return ""
    for asset in assets:
        if (
            isinstance(asset, dict)
            and asset.get("name") == _CHECKSUM_ASSET_NAME
        ):
            return _api_str(asset, "browser_download_url")
    return ""


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
        checksum_url=_find_checksum_url(data),
    )


def check_latest_release() -> ReleaseInfo | None:
    """Query GitHub for the latest published release.

    Returns None when the network or the API reply is unusable — the
    caller renders that as "could not check", never as a crash. Fixed
    https URL and a short timeout: a dead network degrades to a quick
    "unknown" instead of hanging the worker thread.
    """
    # Deferred import — see _https_open.
    # pylint: disable=import-outside-toplevel
    import json
    from http.client import HTTPException

    try:
        with _https_open(
            _RELEASES_API,
            extra_headers={"Accept": "application/vnd.github+json"},
        ) as resp:
            data = json.load(resp)
    except (OSError, ValueError, HTTPException) as err:
        jlog("SYSTEM", f"UPDATE_CHECK_FAIL: {err}", level="WARN")
        return None
    return _release_from_api(data)


def _prune_downloads(root: Path, keep: Path | None = None) -> None:
    """Drop previous release downloads (v<digit>… dirs) under *root*.

    Only version-named directories are touched, so anything the user
    parked in the updates folder by hand survives the cleanup. *keep*,
    if given, is skipped — used to protect a just-verified new download
    from being pruned as if it were a stale previous one.
    """
    for entry in root.iterdir():
        if (
            entry.is_dir()
            and entry.name.startswith("v")
            and entry.name[1:2].isdigit()
            and entry != keep
        ):
            shutil.rmtree(entry, ignore_errors=True)


def _fetch_expected_sha256(url: str) -> str | None:
    """Fetch and parse a SHA256SUMS asset: one 64-char hex digest.

    None on any network/format failure — download_release() treats that
    identically to a missing checksum asset (abort, never extract
    unverified content).
    """
    # Deferred import — see _https_open.
    # pylint: disable=import-outside-toplevel
    from http.client import HTTPException

    if not _require_https(url, "UPDATE_CHECKSUM_FAIL"):
        return None
    try:
        with _https_open(url) as resp:
            text = resp.read(256).decode("ascii")
    except (OSError, HTTPException, UnicodeDecodeError) as err:
        jlog("SYSTEM", f"UPDATE_CHECKSUM_FAIL: {err}", level="ERROR")
        return None
    parts = text.split()
    digest = parts[0].lower() if parts else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        jlog("SYSTEM", f"UPDATE_CHECKSUM_FAIL: bad digest {text!r}", "ERROR")
        return None
    return digest


def _download_verified_tarball(url: str, expected_sha256: str) -> Any:
    """Download *url* into a temp file, verifying its SHA-256 en route.

    Returns the temp file, seeked to 0, on a match. On any network error
    or a mismatch, logs, closes the temp file, and returns None — the
    caller (download_release) never receives an unverified file object.
    """
    # Deferred imports — see _https_open.
    # pylint: disable=import-outside-toplevel
    import hashlib
    import tempfile
    from http.client import HTTPException

    # SIM115: handle is returned open — download_release() closes it via
    # its own `with tmp, ...` block once extraction finishes.
    tmp = tempfile.TemporaryFile()  # noqa: SIM115
    try:
        digest = hashlib.sha256()
        # Scheme constrained to https:// by download_release's own guard.
        with _https_open(url) as resp:
            for chunk in iter(lambda: resp.read(65536), b""):
                tmp.write(chunk)
                digest.update(chunk)
    except (OSError, HTTPException) as err:
        jlog("SYSTEM", f"UPDATE_DOWNLOAD_FAIL: {err}", level="ERROR")
        tmp.close()
        return None
    if digest.hexdigest() != expected_sha256:
        jlog("SYSTEM", "UPDATE_DOWNLOAD_FAIL: checksum mismatch", "ERROR")
        tmp.close()
        return None
    tmp.seek(0)
    return tmp


def _sha256_file(path: Path) -> str:
    """SHA-256 hex digest of *path*'s contents."""
    # Deferred import — see _https_open.
    # pylint: disable=import-outside-toplevel
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_sha256(path: Path, expected_sha256: str) -> bool:
    """True if *path* exists and its SHA-256 matches *expected_sha256*.

    Used to re-verify a previously-hashed file (e.g. install.sh, right
    before a pkexec execution) so a tamper window between an earlier
    verification and actual privileged use is caught rather than trusted
    blindly.
    """
    if not path.is_file():
        return False
    return _sha256_file(path) == expected_sha256


def download_release(
    info: ReleaseInfo, dest_root: str | Path
) -> ExtractedRelease | None:
    """Download, checksum-verify, and unpack *info*'s source tarball.

    Layout: <dest_root>/v<version>/<github-export-dir>/… — returns an
    ExtractedRelease (the inner export directory holding install.sh, plus
    install.sh's own SHA-256), or None on any failure. Requires
    info.checksum_url (the release's SHA256SUMS asset, published
    alongside every release from 2.1.8 on) and rejects the download
    outright if it's missing or doesn't match — install.sh inside the
    tarball runs with elevated privileges, so nothing gets extracted
    unverified. Older downloads are pruned only after the new tarball is
    checksum-verified, fully extracted, AND confirmed to contain
    install.sh — so a corrupted/mismatched download, a failed extraction,
    or a malformed release tarball never costs the last known-good cached
    release; the updates folder still never accumulates stale releases in
    the success case. The "data" extraction filter rejects absolute
    paths, traversal and special members. The returned install.sh hash is
    for the caller to re-check via verify_file_sha256() immediately
    before a pkexec execution (see updater.py) — the tarball checksum
    alone only covers the moment of extraction, not whatever else might
    touch the (user-writable) destination directory afterward.
    """
    if not _require_https(info.tarball_url, "UPDATE_DOWNLOAD_FAIL"):
        return None

    # _fetch_expected_sha256 already logs the specific reason (non-https,
    # network error, or malformed digest) before returning None here —
    # no second, generic log line needed for the same event.
    expected = _fetch_expected_sha256(info.checksum_url)
    if expected is None:
        return None

    root = Path(dest_root)
    target = root / f"v{info.version}"
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = _download_verified_tarball(info.tarball_url, expected)
        if tmp is None:
            return None
        with tmp, tarfile.open(fileobj=tmp, mode="r:gz") as tar:
            tar.extractall(target, filter="data")
        for entry in sorted(target.iterdir()):
            installer = entry / "install.sh"
            if installer.is_file():
                _prune_downloads(root, keep=target)
                return ExtractedRelease(entry, _sha256_file(installer))
    except (OSError, ValueError, tarfile.TarError) as err:
        jlog("SYSTEM", f"UPDATE_DOWNLOAD_FAIL: {err}", level="ERROR")
        return None
    jlog("SYSTEM", "UPDATE_DOWNLOAD_FAIL: install.sh not found", "ERROR")
    return None
