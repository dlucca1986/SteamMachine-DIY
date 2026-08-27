#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Launcher
# VERSION:      2.1.7
# DESCRIPTION:  Core Session Manager
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_launch.py
# LICENSE:      MIT
# =============================================================================
"""

import signal

# B404: importing subprocess isn't the risk — every call site below
# passes a fixed argv list, never shell=True or user-controlled input.
import subprocess  # nosec B404
import sys
import threading
import time
from typing import Any

from utils import (
    DEFAULT_GS_BIN,
    DEFAULT_PLASMA_BIN,
    DEFAULT_STEAM_BIN,
    NEXT_SESSION_PATH,
    apply_env_map,
    get_ssot_num,
    get_ssot_var,
    jlog,
    load_yaml_safe,
    notify,
    read_session_target,
    sd_notify_ready,
    shlex_split_or_fallback,
    spawn_native,
    write_atomic,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

STATUS_MAP: dict[str, str] = {
    "steam": "Starting Game Mode...",
    "desktop": "Starting Desktop Mode...",
}

# Applied before the user's env_vars (which keep the last word). All
# compositor- or Mesa-level and panel-independent: gamescope capabilities
# advertised to Steam so Game Mode exposes the matching controls, plus
# universal latency/session tweaks. Display-dependent capabilities (VRR,
# HDR) deliberately stay out — they belong in the user's config, where the
# hardware is actually known.
GAME_MODE_ENV: dict[str, str] = {
    # Scaling filters (FSR/NIS) — vendor-agnostic shaders
    "STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT": "1",
    "STEAM_GAMESCOPE_NIS_SUPPORTED": "1",
    # Tearing controls — compositor capability, user opts in per game
    "STEAM_GAMESCOPE_HAS_TEARING_SUPPORT": "1",
    "STEAM_GAMESCOPE_TEARING_SUPPORTED": "1",
    # In-Steam dynamic FPS limiter (Mesa fifo-based integration)
    "STEAM_GAMESCOPE_DYNAMIC_FPSLIMITER": "1",
    # Latency + embedded-session correctness
    "vk_xwayland_wait_ready": "false",
    "SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS": "0",
    # Proton / vkd3d session defaults (from Valve's gamescope-session)
    "ENABLE_GAMESCOPE_WSI": "1",
    "VKD3D_SWAPCHAIN_LATENCY_FRAMES": "3",
    "WINEDLLOVERRIDES": "dxgi=n",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_gamescope_args(cfg: dict) -> list[str]:
    """Build gamescope+steam argv: session capabilities, then user config.

    GAME_MODE_ENV is applied first so the user's env_vars retain the last
    word; user flags are appended to the gamescope argv.
    """
    gs_bin = get_ssot_var("bin_gs", DEFAULT_GS_BIN)
    gs_args = [gs_bin, "-e", "-f"]

    apply_env_map(GAME_MODE_ENV)
    apply_env_map(cfg.get("env_vars"))
    for flag in cfg.get("flags") or []:
        tokens, err = shlex_split_or_fallback(str(flag))
        if err is not None:
            # Unbalanced quote in a hand-edited flag: don't crash the whole
            # session over one bad entry — same fallback health.py's
            # preflight already uses for this exact field.
            jlog("STEAM", f"BAD_FLAG_ENTRY: {flag!r} - {err}", level="WARN")
        gs_args.extend(tokens)

    steam_bin = get_ssot_var("bin_steam", DEFAULT_STEAM_BIN)
    gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3", "-steamdeck"])

    jlog("STEAM", f"LAUNCH_ARGS: {' '.join(gs_args)}")
    return gs_args


def _get_post_start_cmds(cfg: dict) -> list[str]:
    """Return post_start_cmds from user config; [] if absent or invalid."""
    cmds = cfg.get("post_start_cmds") or []
    return [str(c) for c in cmds if c]


def _schedule_post_start_cmds(cmds: list[str], delay: float) -> None:
    """Sleep *delay* seconds, then fire each cmd via spawn_native.

    Uses shlex_split_or_fallback like every other hand-edited shell-like
    field in this codebase (flags, GAME_WRAPPER, GAME_EXTRA_ARGS) — an
    unbalanced quote degrades to a naive str.split() and still runs,
    rather than silently skipping the command entirely.
    """
    time.sleep(delay)
    for cmd_str in cmds:
        parts, err = shlex_split_or_fallback(cmd_str)
        if err is not None:
            jlog(
                "STEAM",
                f"BAD_POST_START_CMD: {cmd_str!r} - {err}",
                level="WARN",
            )
        if parts:
            spawn_native(parts[0], parts)
            jlog("STEAM", f"POST_START_CMD: {cmd_str}")


def _monitor_process(
    proc: subprocess.Popen[Any],
    timeout: float,
    next_path: str,
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
        write_atomic(next_path, target)
        notify("Stable", clear_after=True)
        sd_notify_ready()
        return True  # Still running — stable


def _terminate_gracefully(proc: subprocess.Popen[Any]) -> None:
    """SIGTERM → wait → SIGKILL if ignored within TERM_TIMEOUT."""
    if proc.returncode is None:
        proc.terminate()
    try:
        proc.wait(timeout=get_ssot_num("TERM_TIMEOUT", 5.0))
    except subprocess.TimeoutExpired:
        jlog("CORE", "SIGTERM_TIMEOUT: escalating to SIGKILL", level="WARN")
        proc.kill()
        proc.wait()


def _build_command_for(target: str, cfg: dict) -> list[str]:
    """Resolve argv: "steam" → gamescope+Steam, else → Plasma."""
    if target == "steam":
        return _build_gamescope_args(cfg)
    return [get_ssot_var("bin_plasma", DEFAULT_PLASMA_BIN)]


def _handle_recovery(proc: subprocess.Popen[Any], next_path: str) -> str:
    """Recover to desktop after an early exit: persist target, notify, kill.

    Deliberate fail-safe: any process exit within the validation window
    (a real crash, or a switch request that raced it — see
    _monitor_process) forces "desktop", never "steam", so a broken config
    always lands where the user can fix it via the Control Center rather
    than looping back into a session that might not even be launchable.

    Returns:
        Always ``"desktop"`` — drives caller's next-target logic.
    """
    jlog(
        "CORE",
        "EARLY_EXIT_RECOVERY: process exited during the validation "
        "window (crash, or a switch request raced it) - forcing desktop",
        level="ERROR",
    )
    target = "desktop"
    notify("Recovery: Starting Desktop...")
    write_atomic(next_path, target)
    _terminate_gracefully(proc)
    return target


def _post_session_message(target: str, ret_code: int) -> str:
    """Compose the final TTY message shown after the session ends."""
    if target == "desktop":
        return f"Switching to {target.capitalize()}..."
    return f"Ended (Code: {ret_code})"


# 6 logical inputs (cmd, next_path, target, timeout, proc_holder,
# post_start_cmds) — all independently needed by the caller, no subset.
# pylint: disable=too-many-arguments,too-many-positional-arguments
def _run_session(
    cmd: list[str],
    next_path: str,
    target: str,
    v_timeout: float,
    proc_holder: list[subprocess.Popen[Any] | None],
    post_start_cmds: list[str],
) -> tuple[str, int]:
    """Spawn cmd, validate stability, recover on crash; return (target, code).

    proc_holder is the run()'s mutable cell shared with the SIGTERM handler.
    It is set to the live Popen during the session and reset to None on exit
    so the handler never operates on a closed process. On spawn failure,
    target is returned unchanged to preserve the caller's original intent.
    """
    initial_target = target
    ret_code = 0
    try:
        # cmd is built from SSoT-configured binary paths plus fixed
        # session literals (_build_command_for) — never shell=True or
        # externally-controlled input.
        with subprocess.Popen(  # nosec B603
            cmd, stdout=sys.stdout, stderr=sys.stderr
        ) as proc:
            proc_holder[0] = proc
            if post_start_cmds:
                delay = get_ssot_num("POST_START_DELAY", 2.0)
                threading.Thread(
                    target=_schedule_post_start_cmds,
                    args=(post_start_cmds, delay),
                    daemon=True,
                ).start()
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
        proc_holder[0] = None
    return target, ret_code


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Session lifecycle entry point: launch, monitor, recover, exit."""
    next_path = get_ssot_var("next_session", NEXT_SESSION_PATH)
    target = read_session_target(next_path, default="steam")

    notify(STATUS_MAP.get(target, "Initializing..."))

    cfg = load_yaml_safe(get_ssot_var("user_config"))
    cmd = _build_command_for(target, cfg)
    post_start_cmds = _get_post_start_cmds(cfg) if target == "steam" else []

    # Mutable closure cell for the signal handler. Wrapped in a list so
    # the inner function can rebind without needing `nonlocal` (and
    # without flake8 F824 false-positives).
    proc_holder: list[subprocess.Popen[Any] | None] = [None]

    def _handle_term(signum: int, _frame: Any) -> None:
        """Drain the live process and exit cleanly on SIGTERM/SIGINT.

        Exit code 0 — explicit stop, do NOT trigger a systemd restart.
        """
        jlog("CORE", f"SIG_{signum}: Shutting down...")
        live_proc = proc_holder[0]
        if live_proc is not None:
            _terminate_gracefully(live_proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    v_timeout = get_ssot_num("VALIDATION_TIMEOUT", 5.0)

    target, ret_code = _run_session(
        cmd, next_path, target, v_timeout, proc_holder, post_start_cmds
    )

    notify(_post_session_message(target, ret_code))
    time.sleep(get_ssot_num("NOTIFY_DELAY", 0.4))

    # The child finished naturally — either a session switch (user clicked
    # "Switch to Desktop" / "Switch to Steam") or a crash that already
    # routed `next_session` to "desktop" via _handle_recovery. Either way
    # the new target is now persisted on disk and the only thing missing
    # is the launcher reloading it. Exit non-zero so the service unit's
    # `Restart=on-failure` policy reboots us; the next run reads the new
    # `next_session` value and launches the right target. Without this,
    # `systemctl stop` (clean SIGTERM → exit 0) stays clean while session
    # switches still trigger the restart cycle.
    sys.exit(75)  # EX_TEMPFAIL — semantically "transient, retry"


if __name__ == "__main__":
    run()
