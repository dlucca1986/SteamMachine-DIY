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
import subprocess
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
    """Return the full gamescope + steam command-line as a list.

    Constructs gamescope command with base flags and optional user config.
    Loads environment variables and flags from user_config YAML if present.

    Returns:
        List of command arguments ready for subprocess.Popen
    """
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
    """Monitor process stability during validation window.

    Waits up to *timeout* seconds for the process to exit. If process
    remains running through timeout window, marks it as stable and persists.

    Args:
        proc: Subprocess Popen object to monitor
        timeout: Maximum seconds to wait before considering stable
        next_sess_path: Path to next_session persistence file
        target: Current session target (steam/desktop)

    Returns:
        True if process remained stable (survived timeout)
        False if process exited early (crash detected)
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
    """Send SIGTERM and wait; escalate to SIGKILL if needed.

    Gracefully terminates a process with timeout. If process ignores SIGTERM,
    escalates to SIGKILL to ensure cleanup (e.g. during crash recovery).

    Args:
        proc: Subprocess Popen object to terminate

    Note:
        Prevents proc.wait() from blocking indefinitely when gamescope
        or Plasma ignores SIGTERM during crash recovery.
    """
    proc.terminate()
    try:
        proc.wait(timeout=_TERM_TIMEOUT)
    except subprocess.TimeoutExpired:
        jlog("CORE", "SIGTERM_TIMEOUT: escalating to SIGKILL", level="WARN")
        proc.kill()
        proc.wait()


def _build_command_for(target: str) -> list[str]:
    """Return the argv to spawn for *target*.

    Args:
        target: Either ``"steam"`` (gamescope + Steam Big Picture) or
            anything else (treated as desktop, spawning Plasma).

    Returns:
        Argv list ready for ``subprocess.Popen``.
    """
    if target == "steam":
        return _build_gamescope_args()
    return [get_ssot_var("bin_plasma", DEFAULT_PLASMA_BIN)]


def _handle_recovery(proc: subprocess.Popen[Any], next_path: str) -> str:
    """Force-recover to desktop after a crash detected during validation.

    Args:
        proc: The crashed process (already exited).
        next_path: Path to the next_session persistence file.

    Returns:
        New target value ("desktop") for downstream feedback. The
        persisted file is updated and the user is notified before this
        helper returns.
    """
    jlog("CORE", "CRASH_DETECTED: RECOVERY", level="ERROR")
    target = "desktop"
    notify(STATUS_MAP["crash"])
    write_atomic(next_path, target)
    _terminate_gracefully(proc)
    return target


def _post_session_message(
    target: str, original_target: str, ret_code: int
) -> str:
    """Compose the final TTY message shown after the session ends.

    Args:
        target: Final target (may have been switched to "desktop" by
            crash recovery).
        original_target: Target read at startup, used to detect a switch.
        ret_code: Exit code returned by the spawned session.

    Returns:
        Human-readable message string.
    """
    if target != original_target or target == "desktop":
        return f"Switching to {target.capitalize()}..."
    return f"Ended (Code: {ret_code})"


def _run_session(
    cmd: list[str],
    next_path: str,
    target: str,
    v_timeout: float,
    set_proc_ref,
) -> tuple[str, int]:
    """Spawn *cmd*, monitor stability, recover on crash, return outcome.

    Wraps the entire ``subprocess.Popen`` lifecycle including monitoring
    and recovery. The signal handler installed by *run* needs visibility
    on the live ``Popen`` instance, which is why the caller passes a
    *set_proc_ref* setter so the closure can be updated in place.

    Args:
        cmd: Argv list produced by _build_command_for.
        next_path: Path to the next_session persistence file.
        target: Initial target (may be replaced by recovery).
        v_timeout: Seconds in the validation window.
        set_proc_ref: Callable that stores the Popen for the signal
            handler. Called once with the live process and once with
            None on exit, so the handler never operates on a closed
            Popen.

    Returns:
        Tuple ``(final_target, return_code)``. On any spawn failure the
        target is reset to *target* as received (unchanged), preserving
        the original "stick to caller's intent on failure" semantics.
    """
    initial_target = target
    ret_code = 0
    try:
        with subprocess.Popen(
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
    """Main session lifecycle — launch, monitor, recover, exit.

    Orchestrates the complete session lifecycle:
    1. Reads target session (steam/desktop) from persistence file
    2. Launches appropriate session manager (gamescope or Plasma)
    3. Monitors for crashes during validation window
    4. Performs emergency recovery to Desktop on crash
    5. Handles graceful shutdown via signals
    6. Provides user feedback via TTY and logging
    """
    next_path = get_ssot_var("next_session", DEFAULT_SESS_PATH)
    target = read_session_target(next_path, default="steam")
    original_target = target

    notify(STATUS_MAP.get(target, "Initializing..."))

    cmd = _build_command_for(target)

    # Mutable closure cell for the signal handler. Wrapped in a list so
    # the inner function can rebind without needing `nonlocal` (and
    # without flake8 F824 false-positives).
    proc_holder: list[subprocess.Popen[Any] | None] = [None]

    def _handle_term(signum: int, _frame: Any) -> None:
        """Clean shutdown on SIGTERM / SIGINT.

        Args:
            signum: Signal number (SIGTERM=15, SIGINT=2).
            _frame: Stack frame (unused, required by signal.signal).
        """
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

    notify(_post_session_message(target, original_target, ret_code))
    time.sleep(float(get_ssot_var("NOTIFY_DELAY", "0.4")))


if __name__ == "__main__":
    run()
