#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Health & Preflight Backend
# VERSION:      2.1.1
# DESCRIPTION:  Pure config-validation and service-status helpers.
#               No Qt dependency — fully testable in isolation.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/health.py
# LICENSE:      MIT
# =============================================================================
"""

import ctypes
import grp
import os
import subprocess  # nosec B404
from pathlib import Path
from typing import NamedTuple

from ruamel.yaml import YAML, YAMLError

from utils import (
    CORE_LIB_DIR,
    NEXT_SESSION_PATH,
    SSOT_CONF_PATH,
    clear_ssot_cache,
    get_ssot_var,
)

# Safe loader — validation only cares that the document parses, not about
# preserving comments/quoting (that is the editor's round-trip concern).
_yaml_probe = YAML(typ="safe")

# Binary handlers declared in the SSoT, with their built-in defaults.
_BINARY_KEYS: tuple[tuple[str, str], ...] = (
    ("bin_gs", "/usr/bin/gamescope"),
    ("bin_steam", "/usr/bin/steam"),
    ("bin_plasma", "/usr/bin/startplasma-wayland"),
    ("bin_dbus", "/usr/bin/qdbus6"),
)

# Groups whose absence breaks the session — tty is mandatory because
# notify() writes status straight to /dev/tty1 via the C-Core.
_CRITICAL_GROUPS: tuple[str, ...] = ("tty", "video", "render", "input")

# Global-config fields the session launcher iterates directly: a string
# instead of a list is walked character-by-character into junk argv, and
# runtime has no guard — the one mistyping worth catching before boot.
_LIST_FIELDS: tuple[str, ...] = ("flags", "post_start_cmds")

_LIBCORE_PATH: str = f"{CORE_LIB_DIR}/libcore.so"
_SERVICE_UNIT: str = "steamos_diy.service"


class CheckResult(NamedTuple):
    """One preflight outcome: name, pass/fail, human-readable detail."""

    name: str
    ok: bool
    detail: str


class ServiceStatus(NamedTuple):
    """Parsed snapshot of steamos_diy.service from `systemctl show`."""

    active: str  # ActiveState: active / inactive / failed
    sub: str  # SubState: running / dead / ...
    restarts: int  # NRestarts (grows on every exit-75 session switch)
    exit_code: int  # ExecMainStatus — last main-process exit code


# ---------------------------------------------------------------------------
# Preflight checks — each returns one or more CheckResult
# ---------------------------------------------------------------------------


def _check_ssot() -> CheckResult:
    """Verify the SSoT config file exists on disk."""
    ok = os.path.isfile(SSOT_CONF_PATH)
    detail = SSOT_CONF_PATH if ok else f"missing: {SSOT_CONF_PATH}"
    return CheckResult("SSoT config", ok, detail)


def _check_yaml(path: str) -> CheckResult:
    """Parse one YAML file, reporting the offending line on failure."""
    name = f"YAML {os.path.basename(path)}"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            _yaml_probe.load(fh)
        return CheckResult(name, True, "valid")
    except (OSError, YAMLError) as err:
        mark = getattr(err, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark else ""
        return CheckResult(name, False, f"{type(err).__name__}{where}")


def _check_yaml_files() -> list[CheckResult]:
    """Validate the global config plus every per-game profile.

    A path declared in the SSoT that does not resolve is reported as a
    failure, not skipped: a typo silently disables config loading, so
    "configured but missing" must surface rather than pass unnoticed.
    """
    results: list[CheckResult] = []

    user_config = get_ssot_var("user_config")
    if not user_config:
        results.append(CheckResult("user_config", False, "not set in SSoT"))
    elif not os.path.isfile(user_config):
        results.append(
            CheckResult("user_config", False, f"not found: {user_config}")
        )
    else:
        results.append(_check_yaml(user_config))

    games_dir = get_ssot_var("games_conf_dir")
    if not games_dir:
        results.append(
            CheckResult("games_conf_dir", False, "not set in SSoT")
        )
    elif not os.path.isdir(games_dir):
        results.append(
            CheckResult("games_conf_dir", False, f"not found: {games_dir}")
        )
    else:
        for entry in sorted(Path(games_dir).glob("*.yaml")):
            results.append(_check_yaml(str(entry)))

    return results


def _check_config_types() -> list[CheckResult]:
    """Flag list-typed global-config fields mistyped as a scalar.

    Presence and syntax are already covered by _check_yaml_files; this only
    inspects the parsed structure. A field that is absent or null is fine
    (runtime treats it as empty), so only a present, non-list value fails.
    """
    user_config = get_ssot_var("user_config")
    if not user_config or not os.path.isfile(user_config):
        return []
    try:
        with open(user_config, "r", encoding="utf-8") as fh:
            data = _yaml_probe.load(fh) or {}
    except (OSError, YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    results: list[CheckResult] = []
    for field in _LIST_FIELDS:
        value = data.get(field)
        if value is None:
            continue
        ok = isinstance(value, list)
        kind = type(value).__name__
        detail = "list" if ok else f"must be a list, got {kind}"
        results.append(CheckResult(f"config {field}", ok, detail))
    return results


def _check_binaries() -> list[CheckResult]:
    """Verify each SSoT binary handler resolves to an executable file."""
    results: list[CheckResult] = []
    for key, default in _BINARY_KEYS:
        path = get_ssot_var(key, default)
        ok = bool(path) and os.access(path, os.X_OK)
        detail = path if ok else f"not executable: {path}"
        results.append(CheckResult(f"Binary {key}", ok, detail))
    return results


def _check_groups() -> CheckResult:
    """Confirm the current user belongs to every session-critical group."""
    try:
        current = {grp.getgrgid(g).gr_name for g in os.getgroups()}
    except (KeyError, OSError):
        current = set()
    missing = [g for g in _CRITICAL_GROUPS if g not in current]
    ok = not missing
    detail = "all present" if ok else f"missing: {', '.join(missing)}"
    return CheckResult("User groups", ok, detail)


def _check_core() -> CheckResult:
    """Confirm the native C-Core shared object is loadable."""
    try:
        ctypes.CDLL(_LIBCORE_PATH)
        return CheckResult("C-Core", True, _LIBCORE_PATH)
    except OSError as err:
        return CheckResult("C-Core", False, str(err))


def _check_state() -> CheckResult:
    """Confirm the session-state directory is present and writable."""
    path = get_ssot_var("next_session", NEXT_SESSION_PATH)
    parent = os.path.dirname(path)
    ok = os.path.isdir(parent) and os.access(parent, os.W_OK)
    detail = path if ok else f"not writable: {parent}"
    return CheckResult("Session state", ok, detail)


def run_preflight() -> list[CheckResult]:
    """Run every preflight check; order roughly tracks failure severity.

    Drops the SSoT cache first so re-running the doctor after editing the
    config reflects the current on-disk state, not stale cached values.
    """
    clear_ssot_cache()
    results = [_check_ssot()]
    results.extend(_check_binaries())
    results.extend(_check_yaml_files())
    results.extend(_check_config_types())
    results.append(_check_groups())
    results.append(_check_core())
    results.append(_check_state())
    return results


# ---------------------------------------------------------------------------
# Service status — `systemctl show` snapshot
# ---------------------------------------------------------------------------


def parse_service_status(raw: str) -> ServiceStatus:
    """Parse `systemctl show` key=value lines into a ServiceStatus.

    Missing or non-numeric fields degrade to safe placeholders so the UI
    never has to guard against malformed or partial systemd output.
    """
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, _, val = line.partition("=")
        if key:
            fields[key] = val

    def _as_int(key: str) -> int:
        try:
            return int(fields.get(key, ""))
        except ValueError:
            return 0

    return ServiceStatus(
        active=fields.get("ActiveState", "unknown"),
        sub=fields.get("SubState", "unknown"),
        restarts=_as_int("NRestarts"),
        exit_code=_as_int("ExecMainStatus"),
    )


def get_service_status() -> ServiceStatus:
    """Snapshot steamos_diy.service via `systemctl show` (no root needed)."""
    try:
        res = subprocess.run(  # nosec B603
            [
                "/usr/bin/systemctl",
                "show",
                _SERVICE_UNIT,
                "--property=ActiveState,SubState,NRestarts,ExecMainStatus",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return parse_service_status(res.stdout)
    except OSError:
        return ServiceStatus("unknown", "unknown", 0, 0)
