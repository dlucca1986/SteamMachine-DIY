#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Shared Library
# VERSION:      2.1.9
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

# B404: subprocess is only called with argv lists, never shell=True.
import subprocess  # nosec B404
import sys
import threading
from pathlib import Path
from typing import Any, NamedTuple, overload

from ruamel.yaml import YAML as _YAML
from ruamel.yaml import YAMLError

_yaml_reader = _YAML(typ="safe")


# ---------------------------------------------------------------------------
# C-Core integration — mandatory at import time.
# ---------------------------------------------------------------------------

# Public: health.py's C-Core check reports this same path.
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

# Runtime project version — must match the "# VERSION:" file headers;
# both are updated together at release time.
VERSION: str = "2.1.9"

SSOT_CONF_PATH: str = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
NEXT_SESSION_PATH: str = "/var/lib/steamos_diy/next_session"
CORE_LIB_DIR: str = "/usr/local/lib/steamos_diy"
_SERVICE_PATH: str = "/etc/systemd/system/steamos_diy.service"

# User-side path (relative to home) and embedded archive-entry names.
# Shared by backup.py and restore.py.
USER_CONFIG_REL: str = ".config/steamos_diy"
BACKUP_MANIFEST_NAME: str = "links.txt"

# Basename of the global config file under user_config's directory
# (get_backup_mapping and control_center.py's _resolve_config_paths).
CONFIG_FILE_NAME: str = "config.yaml"

# Where downloaded release tarballs are unpacked, relative to the user
# config dir. Shared with backup.py, which must exclude it from archives.
UPDATES_DIR_NAME: str = "updates"

# Fallbacks when the matching SSoT bin_* key is unset (session_launch,
# session_select, health).
DEFAULT_GS_BIN: str = "/usr/bin/gamescope"
DEFAULT_STEAM_BIN: str = "/usr/bin/steam"
DEFAULT_PLASMA_BIN: str = "/usr/bin/startplasma-wayland"
DEFAULT_DBUS_BIN: str = "/usr/bin/qdbus6"

# Fixed tool paths, not SSoT-backed: systemctl/journalctl/python3 live here
# on Arch; install.sh installs konsole.
SYSTEMCTL_BIN: str = "/usr/bin/systemctl"
JOURNALCTL_BIN: str = "/usr/bin/journalctl"
PYTHON3_BIN: str = "/usr/bin/python3"
KONSOLE_BIN: str = "/usr/bin/konsole"

# Timeout for short systemctl/journalctl calls (journal, restore, Control
# Center). health.py's `systemctl show` keeps its own 5 s, tied to the
# Control Center's 4 s status poll.
SYSTEMD_CALL_TIMEOUT: int = 10

# SSoT cache, filled by one full parse on first access. The loaded flag
# is a mutable cell so clear_ssot_cache can reset it without `global`.
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

# Recursion guard — thread-local so the Control Center's worker threads
# and its main thread each track their own jlog re-entry independently.
# A shared flag would let one thread's log bypass the LOG_LEVEL threshold
# while another holds the guard.
_JLOG_REENTRY = threading.local()


# ---------------------------------------------------------------------------
# Logging & feedback
# ---------------------------------------------------------------------------


def jlog(tag: str, message: str, level: str = "INFO") -> None:
    """Log *message* to the journal via syslog if *level* passes LOG_LEVEL.

    _JLOG_REENTRY stops the recursion when reading LOG_LEVEL logs itself.
    Encoded with backslashreplace: a file name decoded from non-UTF-8 bytes
    carries surrogates, and a strict encode would raise in the caller (e.g.
    stop sdy launching a game over its own log line).
    """
    if getattr(_JLOG_REENTRY, "active", False):
        # Already inside jlog: skip threshold lookup and emit directly
        # at the requested level. This avoids recursion via get_ssot_var.
        _LIB.c_jlog(
            tag.replace(":", "").strip().encode("utf-8"),
            message.encode("utf-8", "backslashreplace"),
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
            message.encode("utf-8", "backslashreplace"),
            _LEVELS_C.get(level.upper(), _DEFAULT_LEVEL_C),
        )
    finally:
        _JLOG_REENTRY.active = False


def notify(status: str, clear: bool = False) -> None:
    """Write *status* to /dev/tty1 via C-Core; clear=True only clears the
    screen (status is then ignored)."""
    _LIB.c_notify(status.encode("utf-8"), 1 if clear else 0)


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
    """Parse the whole SSoT into the cache in one read; first key wins.

    The loaded flag is set first, so a failed read isn't retried. Values are
    also exported to os.environ for child processes.
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
    # Not os.environ.update(): one entry the OS refuses (a line starting
    # with "=", a NUL byte) would raise out of every get_ssot_var() caller,
    # session_launch.py's boot path included. apply_env_map skips it.
    apply_env_map(_SSOT_CACHE)


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
    except ValueError:
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
    # WARN, not DEBUG: the whole file is dropped, and at the default
    # LOG_LEVEL=INFO a DEBUG line would leave no trace.
    except (OSError, ValueError) as err:
        jlog("CORE", f"YAML_LOAD_ERROR: {path} - {err}", level="WARN")
        return {}
    except YAMLError as err:
        jlog("CORE", f"YAML_PARSE_ERROR: {path} - {err}", level="WARN")
        return {}
    if isinstance(data, dict):
        return data
    if data is not None:
        # Valid YAML but not a mapping: callers do cfg.get(...), so
        # returning it would crash the session at boot.
        jlog("CORE", f"YAML_NOT_MAPPING: {path}", level="WARN")
    return {}


GAMES_CONF_SUBDIR: str = "games.d"


def default_games_conf_dir() -> Path:
    """~/.config/steamos_diy/games.d: sdy.py's fallback when the SSoT has
    no games_conf_dir (the template's own default)."""
    return Path.home() / USER_CONFIG_REL / GAMES_CONF_SUBDIR


def shlex_split_or_fallback(value: str) -> tuple[list[str], ValueError | None]:
    """shlex.split *value*; on an unbalanced quote return str.split() and
    the error (None on a clean parse). Callers log it with their own tag."""
    try:
        return shlex.split(value), None
    except ValueError as err:
        return value.split(), err


def write_atomic(path: str | Path, val: str) -> bool:
    """Write *val* to *path* via C-Core: tmp file, fdatasync, rename.

    Returns False on any failure (symlink or FIFO at the tmp path, a short
    write, a failed rename); the C side has already logged the reason.
    """
    return bool(
        _LIB.c_write_atomic(os.fsencode(path), str(val).encode("utf-8"))
    )


def persist_next_session(path: str | Path, target: str) -> bool:
    """write_atomic() for next_session, logging NEXT_SESSION_WRITE_FAILED
    on failure; why a failed write matters is noted at each call site."""
    if write_atomic(path, target):
        return True
    jlog("CORE", f"NEXT_SESSION_WRITE_FAILED: {path}", level="ERROR")
    return False


# ---------------------------------------------------------------------------
# Environment & process management
# ---------------------------------------------------------------------------


def apply_env_map(data_dict: dict[str, Any] | None) -> None:
    """Set each *data_dict* entry in os.environ, skipping None values.

    An entry the OS refuses (empty name, "=" in the name, a NUL byte) is
    skipped with a warning: one bad line of hand-edited config must not
    stop a session start or a game launch.
    """
    if not isinstance(data_dict, dict):
        return
    for key, val in data_dict.items():
        if val is None:
            continue
        try:
            os.environ[str(key)] = str(val)
        except (ValueError, OSError) as err:
            jlog("CORE", f"BAD_ENV_ENTRY: {key!r} - {err}", level="WARN")


def spawn_native(path: str, args: list[str]) -> int:
    """Fork/exec *path* detached; returns PID or 0 on failure.

    ``start_new_session=True`` (setsid) detaches the child from the
    caller's terminal and process group, so signals aimed at those (a
    closing terminal, a Ctrl+C) don't reach it.
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


def safe_emit(signal, *args) -> None:
    """Emit *signal* from a worker thread, ignoring a torn-down window.

    Closing the window while a worker is still running deletes the Qt
    object, and emit() then raises RuntimeError; there is nothing left to
    update, so it's swallowed. Duck-typed (only .emit()), so no Qt import.
    """
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# System & user management
# ---------------------------------------------------------------------------


def get_real_user() -> tuple[str, Path]:
    """Real user behind pkexec/sudo, else the current user;
    ("root", /root) if the lookup fails."""
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    try:
        u_info = pwd.getpwuid(int(uid)) if uid else pwd.getpwuid(os.getuid())
        return u_info.pw_name, Path(u_info.pw_dir)
    except (ValueError, KeyError) as err:
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
        # WARN, not DEBUG: target_path stays owned by root, which the
        # user has to notice and fix.
        jlog("CORE", f"OWNERSHIP_ERROR: {target_path} - {err}", level="WARN")


def check_root() -> None:
    """Exit with code 1 unless UID == 0."""
    if os.getuid() != 0:
        sys.exit(1)


def require_ssot_conf(tag: str) -> None:
    """Exit with code 1, logging f"{tag}_FAILED", if the SSoT file is
    missing (backup.py and restore.py's shared precondition)."""
    if not os.path.isfile(SSOT_CONF_PATH):
        jlog("SYSTEM", f"{tag}_FAILED: SSoT config not found", level="ERROR")
        sys.exit(1)


def get_backup_mapping(
    home: str, *, for_restore: bool = False
) -> dict[str, str]:
    """Archive path -> filesystem path, used by backup and restore alike.

    for_restore always includes "user/games_conf_dir" (see below).
    """
    # user_config can move to another directory (the file name stays
    # CONFIG_FILE_NAME): back up the directory it is really in.
    default_conf_dir = os.path.join(home, USER_CONFIG_REL)
    conf_dir = os.path.dirname(
        get_ssot_var(
            "user_config",
            os.path.join(default_conf_dir, CONFIG_FILE_NAME),
        )
    )
    if not conf_dir:
        # A bare "config.yaml" (no directory) gives dirname() == "", which
        # realpath() turns into the current working directory — restore.py
        # would then allow root writes there. Fall back to the default.
        conf_dir = default_conf_dir
    mapping = {
        "system/next_session": get_ssot_var("next_session", NEXT_SESSION_PATH),
        "system/steamos_diy.conf": SSOT_CONF_PATH,
        "system/service": _SERVICE_PATH,
        "source/steamos_diy": CORE_LIB_DIR,
        "user/config": conf_dir,
    }
    # games_conf_dir needs its own entry unless it is inside the user/config
    # directory above, or it drops out of every backup.
    default_games_dir = os.path.join(
        home, USER_CONFIG_REL, GAMES_CONF_SUBDIR
    )
    games_dir = get_ssot_var("games_conf_dir", default_games_dir)
    games_real = os.path.realpath(games_dir) + os.sep
    conf_real = os.path.realpath(conf_dir) + os.sep
    nested = games_real.startswith(conf_real)
    # Restore always includes it: the archive was made under the nesting
    # of backup time (e.g. games_conf_dir on an SD card, restored onto a
    # fresh default SSoT). It only matches members that exist.
    if for_restore or not nested:
        mapping["user/games_conf_dir"] = games_dir
    return mapping


def verify_archive(
    path: str | Path, fail_tag: str = "ARCHIVE_VERIFY_FAIL"
) -> bool:
    """Verify a .tar.gz end-to-end: tar structure AND gzip checksum."""
    # Deferred imports (~15 ms): only backup, restore and the updater need
    # them, not session_launch on every boot/switch.
    # pylint: disable=import-outside-toplevel
    import gzip
    import tarfile
    import zlib

    try:
        with gzip.open(path, "rb") as gz, tarfile.open(
            fileobj=gz, mode="r:"
        ) as tar:
            for _ in tar:
                pass
            # tarfile stops at the end-of-archive marker, before the gzip
            # trailer: read to EOF so gzip checks the CRC32.
            while gz.read(65536):
                pass
        return True
    # zlib.error: raised (rarely) straight from the decompressor on a
    # damaged stream; it is neither an OSError nor a TarError.
    except (tarfile.TarError, OSError, EOFError, zlib.error) as err:
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
    """download_release()'s result: extracted dir + install.sh's SHA-256,
    which updater.py re-checks right before pkexec (the dir stays
    user-writable)."""

    dir: Path
    install_sh_sha256: str


def _https_open(url: str, *, extra_headers: dict[str, str] | None = None):
    """Open *url* over HTTPS with the shared SteamMachine-DIY User-Agent.

    Shared by the three GitHub-release network calls below; each keeps its
    own error handling. Every caller passes a URL already confirmed to be
    https:// (_RELEASES_API itself, or checked via _require_https).
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
    """Query GitHub for the latest release; None if the network or the
    reply is unusable (fixed https URL, _HTTP_TIMEOUT)."""
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
    """Delete previous release downloads (v<digit>… dirs) under *root*,
    except *keep*; anything else in the folder is left alone."""
    # Deferred import — see verify_archive.
    # pylint: disable=import-outside-toplevel
    import shutil

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
    """True if *path* is a file whose SHA-256 is *expected_sha256*."""
    if not path.is_file():
        return False
    return _sha256_file(path) == expected_sha256


def download_release(
    info: ReleaseInfo, dest_root: str | Path
) -> ExtractedRelease | None:
    """Download, checksum-verify and unpack *info*'s source tarball.

    Returns ExtractedRelease(<dest_root>/v<version>/<export dir>, install.sh
    hash) or None. Fail-closed: no SHA256SUMS asset, or a mismatch, means
    nothing is extracted. The "data" filter rejects absolute paths,
    traversal and special files. Older downloads are pruned only on success.
    """
    # Deferred import — see verify_archive.
    # pylint: disable=import-outside-toplevel
    import tarfile

    if not _require_https(info.tarball_url, "UPDATE_DOWNLOAD_FAIL"):
        return None

    # _fetch_expected_sha256 has already logged why.
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
