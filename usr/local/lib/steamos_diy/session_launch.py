#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Launcher
# VERSION:      2.1.9
# DESCRIPTION:  Core Session Manager
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_launch.py
# LICENSE:      MIT
# =============================================================================
"""

import resource
import signal

# B404: every subprocess call below passes an argv list and never uses
# shell=True, so no value (even one from the user's config) is parsed by
# a shell.
import subprocess  # nosec B404
import sys
import time
from collections.abc import Callable
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
    persist_next_session,
    read_session_target,
    sd_notify_ready,
    shlex_split_or_fallback,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

STATUS_MAP: dict[str, str] = {
    "steam": "Starting Game Mode...",
    "desktop": "Starting Desktop Mode...",
}

# Applied before the user's env_vars (which keep the last word): gamescope
# capabilities advertised to Steam so Game Mode shows the matching
# controls, plus hardware-independent session tweaks. Values and purposes
# as in Valve's gamescope-session; checked here: the WSI layer, the SRT
# journal logger and the Plasma Qt theme plugin. Display-dependent ones
# (VRR, HDR) stay out — they belong in the user's config.
GAME_MODE_ENV: dict[str, str] = {
    # Scaling filters (FSR/NIS)
    "STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT": "1",
    "STEAM_GAMESCOPE_NIS_SUPPORTED": "1",
    # Tearing controls — compositor capability, user opts in per game
    "STEAM_GAMESCOPE_HAS_TEARING_SUPPORT": "1",
    "STEAM_GAMESCOPE_TEARING_SUPPORTED": "1",
    # Steam's in-game FPS limiter
    "STEAM_GAMESCOPE_DYNAMIC_FPSLIMITER": "1",
    # Read by gamescope's WSI layer and by SDL
    "vk_xwayland_wait_ready": "false",
    "SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS": "0",
    # steam-runtime-tools' logger writes to the journal (ships with Steam
    # itself, not the distro).
    "SRT_LOG_TO_JOURNAL": "1",
    # Links clicked in Game Mode open in Steam's overlay browser, not a
    # desktop browser that may be missing inside a gamescope session.
    "SRT_URLOPEN_PREFER_STEAM": "1",
    # Proton / vkd3d session defaults (from Valve's gamescope-session)
    "ENABLE_GAMESCOPE_WSI": "1",
    "VKD3D_SWAPCHAIN_LATENCY_FRAMES": "3",
    "WINEDLLOVERRIDES": "dxgi=n",
    # Plasma styling for Qt apps inside gamescope (missing icons otherwise).
    # Needs KDEPlasmaPlatformTheme6.so, which a Plasma install provides.
    "QT_QPA_PLATFORM_THEME": "kde",
    # Cursor size in the embedded X11 session, for the active cursor theme.
    "XCURSOR_SCALE": "256",
}

# Deliberately NOT ported from Valve's gamescope-session: QT_IM_MODULE=steam,
# GTK_IM_MODULE=Steam and XCURSOR_THEME=steam point at a "steam" input
# module/cursor theme that ships only in the SteamOS image (absent here and
# not bundled with the Steam client), so they would have no effect.

# Same value SteamOS's gamescope-session sets: games with heavy shader-cache
# or asset I/O can exhaust systemd's default soft limit of 1024 files.
GAME_MODE_NOFILE_TARGET: int = 524288

# On a stop, seconds the session gets to exit after SIGTERM before SIGKILL.
# Below the unit's TimeoutStopSec=10, so the launcher still exits by itself.
STOP_GRACE_SECONDS: float = 5.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _raise_nofile_limit(target: int = GAME_MODE_NOFILE_TARGET) -> None:
    """Raise this process's open-file soft limit toward *target*, inherited
    by the gamescope/Steam child spawned right after.

    Only raises, never lowers; stays within the hard limit (raising that
    needs privileges); a failure is logged, never fatal — a low limit
    degrades heavy I/O, it doesn't stop the launch.
    """
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        new_soft = min(target, hard)
        if new_soft > soft:
            resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
    except (ValueError, OSError) as err:
        jlog("STEAM", f"NOFILE_LIMIT_RAISE_FAILED: {err}", level="WARN")


def _build_gamescope_args(cfg: dict) -> list[str]:
    """Build gamescope+steam argv: session capabilities, then user config.

    GAME_MODE_ENV is applied first so the user's env_vars retain the last
    word; user flags are appended to the gamescope argv.
    """
    _raise_nofile_limit()
    gs_bin = get_ssot_var("bin_gs", DEFAULT_GS_BIN)
    gs_args = [gs_bin, "-e", "-f"]

    apply_env_map(GAME_MODE_ENV)
    apply_env_map(cfg.get("env_vars"))
    flags = cfg.get("flags")
    for flag in flags if isinstance(flags, list) else []:
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
        persist_next_session(next_path, target)
        notify("Stable", clear_after=True)
        sd_notify_ready()
        return True  # Still running — stable


def _kill_after_grace(proc: subprocess.Popen[Any]) -> None:
    """On a stop, give the session STOP_GRACE_SECONDS, then SIGKILL it.

    Needed because the session runs in the logind session scope, not in
    the unit's cgroup: systemd's own SIGKILL at TimeoutStopSec reaches
    only this launcher, and a session ignoring SIGTERM was left running
    (checked with a transient unit with this unit's PAMName/KillMode).
    """
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        jlog("CORE", "STOP_TIMEOUT: session ignored SIGTERM, killing", "WARN")
        proc.kill()
        proc.wait()


def _build_command_for(target: str, cfg: dict) -> list[str]:
    """Resolve argv: "steam" → gamescope+Steam, else → the desktop
    session (bin_plasma)."""
    if target == "steam":
        return _build_gamescope_args(cfg)
    return [get_ssot_var("bin_plasma", DEFAULT_PLASMA_BIN)]


def _handle_recovery(next_path: str) -> str:
    """Recover to desktop after an early exit: persist target, notify.

    Deliberate fail-safe: any exit within the validation window (a crash,
    or a switch request that raced the launch) forces "desktop", never
    "steam", so a broken config lands where the user can fix it instead
    of looping back into a session that may not even start. The process
    has already exited (that is how the exit was detected), so there is
    nothing to signal.

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
    # The single most important write in this file: if it doesn't land,
    # the next boot re-reads whatever next_session already held (possibly
    # the same target that just crashed) instead of the desktop fallback
    # this whole function exists to guarantee — hence the ERROR-level log
    # persist_next_session emits on failure.
    persist_next_session(next_path, target)
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
    proc_holder: list[subprocess.Popen[Any] | None],
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
        # cmd is an argv list (SSoT binary paths, fixed session literals
        # and the user's gamescope flags), never run through a shell.
        with subprocess.Popen(  # nosec B603
            cmd, stdout=sys.stdout, stderr=sys.stderr
        ) as proc:
            proc_holder[0] = proc
            try:
                if not _monitor_process(proc, v_timeout, next_path, target):
                    target = _handle_recovery(next_path)
                proc.wait()
            except SystemExit:
                # Raised by _make_term_handler. Leaving the `with` block
                # waits on the child with no limit: bound that wait first.
                _kill_after_grace(proc)
                raise
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
    except ValueError as err:
        # Popen raises ValueError, not OSError, for a malformed argv
        # element (e.g. a NUL byte in a hand-edited flag).
        jlog("CORE", f"BAD_LAUNCH_ARGV: {err}", level="ERROR")
        notify("FATAL: Cannot launch session!")
        ret_code = 1
        target = initial_target
    finally:
        proc_holder[0] = None
    return target, ret_code


def _make_term_handler(
    proc_holder: list[subprocess.Popen[Any] | None],
) -> Callable[[int, Any], None]:
    """Build the SIGTERM/SIGINT handler bound to run()'s proc_holder cell.

    The handler only signals the child and exits — it must NOT wait on it.
    It runs on the main thread, which in the stable phase is blocked in
    _run_session's untimed proc.wait() holding Popen's waitpid lock, so a
    wait from the handler could never reap the child. sys.exit() unwinds
    out of that wait; _run_session then waits for the child, killing it
    if it ignores SIGTERM (_kill_after_grace).

    Exit code 0 — explicit stop, do NOT trigger a systemd restart.
    """

    def _handle_term(signum: int, _frame: Any) -> None:
        jlog("CORE", f"SIG_{signum}: Shutting down...")
        live_proc = proc_holder[0]
        if live_proc is not None and live_proc.returncode is None:
            live_proc.terminate()
        sys.exit(0)

    return _handle_term


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

    # Mutable closure cell for the signal handler. Wrapped in a list so
    # the inner function can rebind without needing `nonlocal` (and
    # without flake8 F824 false-positives).
    proc_holder: list[subprocess.Popen[Any] | None] = [None]

    _handle_term = _make_term_handler(proc_holder)
    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)

    v_timeout = get_ssot_num("VALIDATION_TIMEOUT", 5.0)

    target, ret_code = _run_session(
        cmd, next_path, target, v_timeout, proc_holder
    )

    notify(_post_session_message(target, ret_code))
    time.sleep(get_ssot_num("NOTIFY_DELAY", 0.4))

    # The child ended on its own: a session switch, or a crash already
    # routed to "desktop" by _handle_recovery. The new target is on disk;
    # exit non-zero so `Restart=on-failure` restarts the service, which
    # then launches it. A `systemctl stop` exits 0 instead (see
    # _make_term_handler), so it doesn't trigger a restart.
    sys.exit(75)  # EX_TEMPFAIL — semantically "transient, retry"


if __name__ == "__main__":
    run()
