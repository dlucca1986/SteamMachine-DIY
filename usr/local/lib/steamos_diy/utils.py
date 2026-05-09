#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Shared Library
# VERSION:      1.7.9
# DESCRIPTION:  Shared library. Mandatory C-Core integration.
# PHILOSOPHY:   KISS & Comprehensive.
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/utils.py
# LICENSE:      MIT
# =============================================================================
"""

import ctypes
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# C-Core integration — mandatory at import time.
# ---------------------------------------------------------------------------

_CORE_LIB_PATH: str = "/usr/local/lib/steamos_diy/libcore.so"

try:
    _LIB: ctypes.CDLL = ctypes.CDLL(_CORE_LIB_PATH)

    _LIB.c_jlog.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    _LIB.c_notify.argtypes = [ctypes.c_char_p, ctypes.c_int]
    _LIB.c_write_atomic.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    _LIB.c_get_conf_val.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    _LIB.c_get_conf_val.restype = ctypes.c_int
    _LIB.c_read_file_simple.argtypes = [
        ctypes.c_char_p,
        ctypes.c_char_p,
        ctypes.c_int,
    ]
    _LIB.c_read_file_simple.restype = ctypes.c_int
    _LIB.c_spawn_detached.argtypes = [
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_char_p),
    ]
    _LIB.c_spawn_detached.restype = ctypes.c_int
    _LIB.c_monitor_process.argtypes = [ctypes.c_int, ctypes.c_int]
    _LIB.c_monitor_process.restype = ctypes.c_int
    _LIB.c_sd_notify_ready.argtypes = []

except OSError as err:
    sys.stderr.write(f"FATAL: C-Core missing at {_CORE_LIB_PATH}: {err}\n")
    sys.exit(127)


# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# SSoT config path — read once, never changes at runtime.
_SSOT_CONF: str = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")

# In-process cache for SSoT values — avoids repeated C-Core disk reads.
_SSOT_CACHE: dict[str, str] = {}

# C-Core buffer sizes (must match the contract on the C side).
_SSOT_BUF_SIZE: int = 512
_SESSION_BUF_SIZE: int = 64

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

# Re-entry guard for jlog — prevents infinite recursion when the SSoT
# lookup performed by jlog itself fails and would recursively invoke
# jlog. Wrapped in a single-element list so the inner code can flip
# the flag without resorting to the `global` statement (which trips
# pylint W0603 and is generally a code smell).
_JLOG_REENTRY: list[bool] = [False]


# ---------------------------------------------------------------------------
# Logging & feedback
# ---------------------------------------------------------------------------


def jlog(tag: str, message: str, level: str = "INFO") -> None:
    """Send a structured log entry to the kernel journal via C-Core.

    Respects the LOG_LEVEL set in the SSoT config — messages below the
    configured threshold are silently discarded before any C call.

    Args:
        tag: Log tag/module identifier (colons stripped).
        message: Log message content.
        level: Log level (DEBUG, INFO, WARN, ERROR). Defaults to "INFO".

    Note:
        Filtering is done in Python before C-Core invocation to avoid
        unnecessary system calls for suppressed log levels. A re-entry
        guard prevents infinite recursion if the SSoT lookup itself
        triggers a log call (e.g. on a decode error reading LOG_LEVEL).
    """
    if _JLOG_REENTRY[0]:
        # Already inside jlog: skip threshold lookup and emit directly
        # at the requested level. This avoids recursion via get_ssot_var.
        _LIB.c_jlog(
            tag.replace(":", "").strip().encode("utf-8"),
            message.encode("utf-8"),
            _LEVELS_C.get(level.upper(), _DEFAULT_LEVEL_C),
        )
        return

    _JLOG_REENTRY[0] = True
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
        _JLOG_REENTRY[0] = False


def notify(status: str, clear_after: bool = False) -> None:
    """Write a status message to /dev/tty1 via C-Core (zero Python overhead).

    Provides instant TTY feedback with optional screen clear. Bypasses
    Python buffering for immediate visibility during boot.

    Args:
        status: Status message to display.
        clear_after: Clear screen if True. Defaults to False.
    """
    _LIB.c_notify(status.encode("utf-8"), 1 if clear_after else 0)


def sd_notify_ready() -> None:
    """Signal systemd that the service is fully operational (READY=1).

    Called after successful process validation to indicate service readiness.
    """
    _LIB.c_sd_notify_ready()


# ---------------------------------------------------------------------------
# Config & filesystem
# ---------------------------------------------------------------------------


def load_ssot() -> bool:
    """Return True if the SSoT config file exists and is readable.

    Returns:
        True if the SSOT_CONF path points to an existing regular file.
    """
    return os.path.isfile(_SSOT_CONF)


def get_ssot_var(var_name: str, default: str | None = None) -> str | None:
    """Return a SSoT config value, using an in-process cache.

    On cache miss, delegates to the C-Core for a direct disk read and
    populates both the cache and os.environ for downstream consumers.

    Args:
        var_name: Configuration variable name.
        default: Default value if the variable is not found. Defaults to None.

    Returns:
        Configuration value as string, or *default* if the variable is
        missing or cannot be decoded.

    Note:
        Cache is module-level and persists for the lifetime of the process.
        The variable is also set in os.environ for subprocess access.
    """
    if var_name in _SSOT_CACHE:
        return _SSOT_CACHE[var_name]

    res_buf = ctypes.create_string_buffer(_SSOT_BUF_SIZE)
    if _LIB.c_get_conf_val(
        _SSOT_CONF.encode("utf-8"),
        var_name.encode("utf-8"),
        res_buf,
        _SSOT_BUF_SIZE,
    ):
        try:
            value = res_buf.value.decode("utf-8")
            _SSOT_CACHE[var_name] = value
            os.environ[var_name] = value
            return value
        except UnicodeDecodeError as err:
            jlog(
                "CORE", f"SSOT_DECODE_ERROR: {var_name} - {err}", level="WARN"
            )
            return default
    return default


def read_session_target(path: str | Path, default: str = "steam") -> str:
    """Read the session target file via C-Core and return its content.

    Falls back to *default* if the file is missing or unreadable.

    Args:
        path: Path to the session target file.
        default: Fallback if file is unreadable. Defaults to "steam".

    Returns:
        Session target as string ("steam", "desktop", etc.).
    """
    res_buf = ctypes.create_string_buffer(_SESSION_BUF_SIZE)
    if _LIB.c_read_file_simple(
        str(path).encode("utf-8"), res_buf, _SESSION_BUF_SIZE
    ):
        try:
            return res_buf.value.decode("utf-8").strip()
        except UnicodeDecodeError as err:
            jlog("CORE", f"SESSION_DECODE_ERROR: {err}", level="WARN")
            return default
    return default


def _read_yaml_file(path: str | Path) -> dict[str, Any]:
    """Open *path* and parse its YAML content into a dict.

    Args:
        path: Filesystem path of the YAML file (must exist).

    Returns:
        Parsed YAML content as dict, or empty dict if the document is
        empty / null at top level.

    Raises:
        OSError, ValueError, yaml.YAMLError: propagated to the caller for
            unified handling.
    """
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _yaml_skippable(path: str | Path) -> bool:
    """Return True if the YAML load should be skipped without error.

    Skip conditions: PyYAML missing, empty/None path, or path not on disk.
    """
    if yaml is None:
        return True
    if not path:
        return True
    return not os.path.exists(path)


def load_yaml_safe(path: str | Path) -> dict[str, Any]:
    """Parse a YAML file and return its contents as a dict.

    Returns an empty dict on any error (missing file, parse error, missing
    PyYAML module). Never raises exceptions.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML content as dict, or an empty dict on any error.

    Note:
        This function is bulletproof against the absence of the PyYAML
        module — both the early guard and the except clause handle it.
    """
    if _yaml_skippable(path):
        return {}

    try:
        return _read_yaml_file(path)
    except (OSError, ValueError) as err:
        jlog("CORE", f"YAML_LOAD_ERROR: {path} - {err}", level="DEBUG")
    except yaml.YAMLError as err:  # type: ignore[attr-defined]
        jlog("CORE", f"YAML_PARSE_ERROR: {path} - {err}", level="DEBUG")
    return {}


def write_atomic(path: str | Path, val: str) -> None:
    """Write *val* to *path* atomically with fdatasync via C-Core.

    Uses the atomic write pattern (temp file + rename) with filesystem
    sync to ensure durability on SSD.

    Args:
        path: Target file path.
        val: Content to write (will be stripped).
    """
    _LIB.c_write_atomic(
        str(path).encode("utf-8"), str(val).strip().encode("utf-8")
    )


# ---------------------------------------------------------------------------
# Environment & process management
# ---------------------------------------------------------------------------


def apply_env_map(data_dict: dict[str, Any] | None) -> None:
    """Inject all key/value pairs in *data_dict* into os.environ.

    Non-dict arguments and None values are silently ignored.

    Args:
        data_dict: Dictionary of environment variables to inject.
    """
    if not isinstance(data_dict, dict):
        return
    for key, val in data_dict.items():
        if val is not None:
            os.environ[str(key)] = str(val)


def spawn_native(path: str, args: list[str]) -> int:
    """Launch a detached process via C fork/exec (zero Python overhead).

    Uses native C fork/exec for maximum efficiency. The process runs
    detached from the parent session.

    Args:
        path: Full path to the executable.
        args: Full argv passed to execv, including argv[0] (the program name).

    Returns:
        Child process PID on success, 0 on failure (including encoding
        errors on path/args).
    """
    try:
        encoded_path = path.encode("utf-8")
        arg_v = (ctypes.c_char_p * (len(args) + 1))()
        for i, arg in enumerate(args):
            arg_v[i] = ctypes.c_char_p(arg.encode("utf-8"))
        arg_v[len(args)] = None
    except (UnicodeEncodeError, AttributeError) as err:
        jlog("CORE", f"SPAWN_ENCODE_ERROR: {err}", level="WARN")
        return 0

    return _LIB.c_spawn_detached(encoded_path, arg_v)


def spawn_process(cmd: list[str]) -> subprocess.Popen[bytes] | None:
    """Launch *cmd* via Python subprocess in a new session.

    Compatibility wrapper for callers that cannot use spawn_native.
    Silently returns None on any failure.

    Args:
        cmd: Command and arguments as a list.

    Returns:
        Popen object on success, None on failure (OSError).
    """
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as err:
        jlog("CORE", f"SPAWN_ERROR: {err}", level="DEBUG")
        return None


def monitor_pid(pid: int, timeout: int = 5) -> bool:
    """Return True if *pid* is still running after *timeout* seconds.

    Delegates to the C-Core for efficient process monitoring without
    repeated system calls from Python.

    Args:
        pid: Process ID to monitor.
        timeout: Maximum seconds to wait. Defaults to 5.

    Returns:
        True if the process is still running after *timeout*, False if
        it exited within the window.
    """
    return _LIB.c_monitor_process(int(pid), int(timeout)) == 1


# ---------------------------------------------------------------------------
# System & user management
# ---------------------------------------------------------------------------


def get_real_user() -> tuple[str, Path]:
    """Return (username, home_path) of the real user behind sudo/pkexec.

    Falls back to the current effective user if no escalation is detected.
    On any lookup failure, returns ("root", Path("/root")).

    Returns:
        Tuple of (username, home_path) — string and Path object.
    """
    uid = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    try:
        u_info = pwd.getpwuid(int(uid)) if uid else pwd.getpwuid(os.getuid())
        return u_info.pw_name, Path(u_info.pw_dir)
    except (ValueError, KeyError, TypeError) as err:
        jlog("CORE", f"USER_LOOKUP_ERROR: {err}", level="DEBUG")
        return "root", Path("/root")


def _chown_recursive(target: Path, user_name: str) -> None:
    """Run native ``chown -R user:user target`` with all output silenced.

    Args:
        target: Directory to chown recursively.
        user_name: Target username (also used as group name).
    """
    try:
        subprocess.run(
            ["chown", "-R", f"{user_name}:{user_name}", str(target)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as err:
        jlog("CORE", f"CHOWN_R_ERROR: {err}", level="DEBUG")


def fix_ownership(target_path: str | Path, user_name: str) -> None:
    """Recursively set ownership of *target_path* to *user_name*.

    No-op for root or empty user name. Silently ignores permission errors.
    For directories, uses native ``chown -R`` (more efficient than a
    Python recursion). For single files, uses os.chown directly.

    Args:
        target_path: File or directory to chown.
        user_name: Target username.
    """
    if not user_name or user_name == "root":
        return

    target = Path(target_path)
    try:
        u_info = pwd.getpwnam(user_name)
        if target.is_dir():
            _chown_recursive(target, user_name)
        else:
            os.chown(target, u_info.pw_uid, u_info.pw_gid)
    except (OSError, KeyError) as err:
        jlog("CORE", f"OWNERSHIP_ERROR: {target_path} - {err}", level="DEBUG")


def check_root() -> None:
    """Exit with code 1 if the process is not running as root.

    Raises:
        SystemExit: With code 1 if UID != 0.
    """
    if os.getuid() != 0:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Journal & metadata (Control Center / UI consumers)
# ---------------------------------------------------------------------------


def get_journal_cmd(tag: str) -> list[str]:
    """Return the journalctl command list for the requested *tag* filter.

    Constructs a complete journalctl command with standard filters.
    Supports aggregated tags (ALL) and individual tags (CORE, STEAM,
    SYSTEM, etc.).

    Args:
        tag: Journal tag filter (ALL, CORE, STEAM, SYSTEM, or custom).

    Returns:
        List of command arguments ready for subprocess.run/Popen.
    """
    base_cmd = [
        "journalctl",
        "--since",
        "12 hours ago",
        "-n",
        "300",
        "--no-hostname",
        "--no-pager",
        "-o",
        "export",
    ]
    tag_args = {
        "ALL": ["-t", "CORE", "-t", "STEAM", "-t", "SYSTEM", "-t", "DEBUG"],
        "CORE": ["-t", "CORE"],
        "STEAM": ["-t", "STEAM"],
        "SYSTEM": ["-t", "SYSTEM"],
    }
    return base_cmd + tag_args.get(tag, ["-t", tag])


def _normalize_appid(value: str) -> str:
    """Normalize an AppID extracted from journal logs to its 32-bit form.

    Steam logs Non-Steam shortcut AppIDs as 64-bit values where the
    high 32 bits are the *real* AppID (matching ``$SteamAppId``) and
    the low 32 bits are an internal flag mask. The shorter 32-bit
    form is what every other tool (Protontricks, the Steam URL bar,
    compatdata folders) uses, so we collapse anything wider than
    32 bits to its high half before returning.

    Args:
        value: Raw decimal AppID string captured by the regex.

    Returns:
        A decimal AppID string fitting in 32 bits, or *value* unchanged
        when it already fits or is not a parseable integer.
    """
    try:
        n = int(value)
    except ValueError:
        return value
    if n.bit_length() > 32:
        return str(n >> 32)
    return value


def extract_game_metadata(line: str) -> tuple[str | None, str | None]:
    """Extract a game name or AppID from a raw journal log line.

    Searches for chdir patterns (game directory changes) or AppID/gameID
    patterns in the log line. Returns the first match found (NAME preferred).
    AppIDs that exceed 32 bits (Non-Steam shortcut representations) are
    normalised to their 32-bit "real" form via _normalize_appid.

    Args:
        line: Raw journal export line.

    Returns:
        Tuple of (kind, value) where *kind* is "NAME", "ID", or None
        when no metadata is found. *value* is the extracted string.
    """
    if 'chdir "' in line:
        match = re.search(r'chdir\s+"([^"]+)"', line)
        if match:
            return "NAME", os.path.basename(match.group(1).rstrip("/"))

    match_id = re.search(r"(?:gameID|AppID\s*=\s*)\s*(\d+)", line)
    if match_id:
        return "ID", _normalize_appid(match_id.group(1))
    return (None, None)
