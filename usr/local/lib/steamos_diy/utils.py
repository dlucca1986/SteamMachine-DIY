#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Shared Library
# VERSION:      2.1.0
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
import subprocess  # nosec B404
import sys
import tarfile
import threading
from pathlib import Path
from typing import Any, overload

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

SSOT_CONF_PATH: str = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
NEXT_SESSION_PATH: str = "/var/lib/steamos_diy/next_session"
CORE_LIB_DIR: str = "/usr/local/lib/steamos_diy"
_SERVICE_PATH: str = "/etc/systemd/system/steamos_diy.service"

# User-side path (relative to home) and embedded restore-script entry name.
# Centralised here so the archive format contract has a single source of
# truth — backup and restore can never disagree about what goes where.
USER_CONFIG_REL: str = ".config/steamos_diy"
BACKUP_SCRIPT_NAME: str = "restore_links.sh"

# In-process cache for SSoT values — avoids repeated disk reads.
_SSOT_CACHE: dict[str, str] = {}

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


@overload
def get_ssot_var(var_name: str, default: str) -> str: ...


@overload
def get_ssot_var(var_name: str, default: None = ...) -> str | None: ...


def _strip_quotes(value: str) -> str:
    """Strip whitespace and matching outer quotes from a key=value RHS."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def get_ssot_var(var_name: str, default: str | None = None) -> str | None:
    """Read a SSoT config value, caching it in-process.

    Also sets os.environ[var_name] so spawned subprocesses inherit it
    without re-reading the config.
    """
    if var_name in _SSOT_CACHE:
        return _SSOT_CACHE[var_name]

    try:
        with open(SSOT_CONF_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, raw = line.partition("=")
                if key.strip() == var_name:
                    value = _strip_quotes(raw)
                    _SSOT_CACHE[var_name] = value
                    os.environ[var_name] = value
                    return value
    except OSError as err:
        jlog("CORE", f"SSOT_READ_ERROR: {var_name} - {err}", level="DEBUG")
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
    """Parse *path* as YAML; return {} on any error."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _yaml_reader.load(fh) or {}
    except (OSError, ValueError) as err:
        jlog("CORE", f"YAML_LOAD_ERROR: {path} - {err}", level="DEBUG")
    except YAMLError as err:
        jlog("CORE", f"YAML_PARSE_ERROR: {path} - {err}", level="DEBUG")
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
