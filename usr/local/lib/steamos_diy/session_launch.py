#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Launcher
# VERSION:      1.5.5
# DESCRIPTION:  Core Session Manager
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_launch.py
# LICENSE:      MIT
# =============================================================================
"""

import shlex
import signal
import subprocess  # nosec B404
import sys
import time
from typing import Any

from utils import (
    apply_env_map,
    get_ssot_var,
    jlog,
    load_yaml_safe,
    notify,
    read_session_target,
    sd_notify_ready,
    write_atomic,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

DEFAULT_GS_BIN: str = "/usr/bin/gamescope"
DEFAULT_STEAM_BIN: str = "/usr/bin/steam"
DEFAULT_PLASMA_BIN: str = "/usr/bin/startplasma-wayland"
DEFAULT_SESS_PATH: str = "/var/lib/steamos_diy/next_session"

STATUS_MAP: dict[str, str] = {
    "steam": "Starting Game Mode...",
    "desktop": "Starting Desktop Mode...",
    "crash": "Recovery: Starting Desktop...",
}

# Seconds to wait for graceful SIGTERM before sending SIGKILL on recovery.
_TERM_TIMEOUT: int = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_gamescope_args() -> list[str]:
    """Build gamescope+steam argv, applying user_config env_vars and flags."""
    gs_bin = get_ssot_var("bin_gs", DEFAULT_GS_BIN)
    gs_args = [gs_bin, "-e", "-f"]

    user_cfg_path = get_ssot_var("user_config")
    if user_cfg_path:
        cfg = load_yaml_safe(user_cfg_path)
        if isinstance(cfg, dict):
            apply_env_map(cfg.get("env_vars"))
            for flag in cfg.get("flags") or []:
                gs_args.extend(shlex.split(str(flag)))

    steam_bin = get_ssot_var("bin_steam", DEFAULT_STEAM_BIN)
    gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3"])

    jlog("STEAM", f"LAUNCH_ARGS: {' '.join(gs_args)}")
    return gs_args


def _monitor_process(
    proc: subprocess.Popen[Any],
    timeout: float,
    next_sess_path: str,
    target: str,
) -> bool:
    """Wait up to *timeout* for proc to exit; treat survival as stable.

    Returns:
        True if proc survived the window (stable), False on early exit (crash).
    """
    try:
        proc.wait(timeout=timeout)
        return False  # Exited early — treat as crash
    except subprocess.TimeoutExpired:
        jlog("CORE", f"VALIDATED_{target.upper()}_STABLE", level="DEBUG")
        write_atomic(next_sess_path, target)
        notify("Stable", clear_after=True)
        sd_notify_ready()
        return True  # Still running — stable


def _terminate_gracefully(proc: subprocess.Popen[Any]) -> None:
    """SIGTERM → wait → SIGKILL if ignored within _TERM_TIMEOUT."""
    proc.terminate()
    try:
        proc.wait(timeout=_TERM_TIMEOUT)
    except subprocess.TimeoutExpired:
        jlog("CORE", "SIGTERM_TIMEOUT: escalating to SIGKILL", level="WARN")
        proc.kill()
        proc.wait()


def _build_command_for(target: str) -> list[str]:
    """Resolve argv: "steam" → gamescope+Steam, else → Plasma."""
    if target == "steam":
        return _build_gamescope_args()
    return [get_ssot_var("bin_plasma", DEFAULT_PLASMA_BIN)]


def _handle_recovery(proc: subprocess.Popen[Any], next_path: str) -> str:
    """Recover to desktop after crash: persist target, notify user, kill proc.

    Returns:
        Always ``"desktop"`` — drives caller's next-target logic.
    """
    jlog("CORE", "CRASH_DETECTED: RECOVERY", level="ERROR")
    target = "desktop"
    notify(STATUS_MAP["crash"])
    write_atomic(next_path, target)
    _terminate_gracefully(proc)
    return target


def _post_session_message(target: str, ret_code: int) -> str:
    """Compose the final TTY message shown after the session ends."""
    if target == "desktop":
        return f"Switching to {target.capitalize()}..."
    return f"Ended (Code: {ret_code})"


def _run_session(
    cmd: list[str],
    next_path: str,
    target: str,
    v_timeout: float,
    set_proc_ref,
) -> tuple[str, int]:
    """Spawn cmd, validate stability, recover on crash; return (target, code).

    set_proc_ref is injected by run() so its SIGTERM handler can reach the live
    Popen without a nonlocal binding. Called with None on exit to prevent the
    handler from operating on a closed process. On spawn failure, target is
    returned unchanged to preserve the caller's original intent.
    """
    initial_target = target
    ret_code = 0
    try:
        with subprocess.Popen(  # nosec B603
            cmd, stdout=sys.stdout, stderr=sys.stderr
        ) as proc:
            set_proc_ref(proc)
            if not _monitor_process(proc, v_timeout, next_path, target):
                target = _handle_recovery(proc, next_path)
            proc.wait()
            ret_code = proc.returncode
    except FileNotFoundError as err:
        jlog("CORE", f"BINARY_NOT_FOUND: {cmd[0]} - {err}", level="ERROR")
        notify("FATAL: Session binary not found!")
        ret_code = 127
        target = initial_target
    except OSError as err:
        jlog("CORE", f"OS_ERROR: {err}", level="ERROR")
        notify("FATAL: Cannot launch session!")
        ret_code = 1
        target = initial_target
    except subprocess.SubprocessError as err:
        jlog("CORE", f"SUBPROCESS_ERROR: {err}", level="ERROR")
        ret_code = 1
        target = initial_target
    finally:
        set_proc_ref(None)
    return target, ret_code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Session lifecycle entry point: launch, monitor, recover, exit."""
    next_path = get_ssot_var("next_session", DEFAULT_SESS_PATH)
    target = read_session_target(next_path, default="steam")

    notify(STATUS_MAP.get(target, "Initializing..."))

    cmd = _build_command_for(target)

    # Mutable closure cell for the signal handler. Wrapped in a list so
    # the inner function can rebind without needing `nonlocal` (and
    # without flake8 F824 false-positives).
    proc_holder: list[subprocess.Popen[Any] | None] = [None]

    def _handle_term(signum: int, _frame: Any) -> None:
        """Drain the live process and exit cleanly on SIGTERM/SIGINT."""
        jlog("CORE", f"SIG_{signum}: Shutting down...")
        live_proc = proc_holder[0]
        if live_proc is not None:
            _terminate_gracefully(live_proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    v_timeout = float(get_ssot_var("VALIDATION_TIMEOUT", "5.0"))

    target, ret_code = _run_session(
        cmd,
        next_path,
        target,
        v_timeout,
        lambda p: proc_holder.__setitem__(0, p),
    )

    notify(_post_session_message(target, ret_code))
    time.sleep(float(get_ssot_var("NOTIFY_DELAY", "0.4")))


if __name__ == "__main__":
    run()
