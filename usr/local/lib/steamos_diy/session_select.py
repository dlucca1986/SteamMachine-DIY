#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher
# VERSION:      2.1.9
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and KDE.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_select.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import sys
import time

from utils import (
    DEFAULT_DBUS_BIN,
    DEFAULT_STEAM_BIN,
    NEXT_SESSION_PATH,
    get_ssot_var,
    jlog,
    notify,
    persist_next_session,
    spawn_native,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Keywords that map argv[1] to the desktop target.
_DESKTOP_KEYWORDS: frozenset[str] = frozenset({"plasma", "desktop", "kde"})

# How long to watch the spawned helper for an immediate failure. A helper
# that rejects its arguments or can't reach its target (a renamed
# compositor action, no D-Bus session) exits within milliseconds; one
# that is working either exits 0 or is still running when this expires.
_HELPER_CHECK_SECONDS: float = 1.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_target(arg: str) -> str:
    """Normalise a raw argv string to "desktop" or "steam".

    Case- and whitespace-insensitive. Empty or unknown input means "steam":
    switching to Game Mode is by far the common trigger, and the desktop
    keywords are matched explicitly.
    """
    if not arg:
        return "steam"
    return "desktop" if arg.strip().lower() in _DESKTOP_KEYWORDS else "steam"


def _failed_fast(pid: int) -> bool:
    """True if child *pid* exits non-zero within _HELPER_CHECK_SECONDS.

    Still running, exited 0, or not reapable here: False (not a failure
    we can see). spawn_native() discards stdout/stderr, so without this a
    helper that rejected its arguments (e.g. a compositor update renamed
    its quit action) would look exactly like a success: the switch does
    nothing and nothing is logged.
    """
    deadline = time.monotonic() + _HELPER_CHECK_SECONDS
    while True:
        try:
            done, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return False
        if done:
            return os.waitstatus_to_exitcode(status) != 0
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _dispatch_switch(target: str) -> bool:
    """Spawn the native helper that triggers the session transition.

    Hand-off matrix:
        desktop → ``steam -shutdown``          (Steam exits → desktop)
        steam   → ``qdbus6 org.kde.Shutdown /Shutdown logout`` (→ Game Mode)

    Returns True if the helper was spawned and didn't fail straight away
    (see _failed_fast).
    """
    if target == "desktop":
        steam_bin = get_ssot_var("bin_steam", DEFAULT_STEAM_BIN)
        pid = spawn_native(steam_bin, [steam_bin, "-shutdown"])
    else:
        dbus_bin = get_ssot_var("bin_dbus", DEFAULT_DBUS_BIN)
        pid = spawn_native(
            dbus_bin,
            [dbus_bin, "org.kde.Shutdown", "/Shutdown", "logout"],
        )

    return pid > 0 and not _failed_fast(pid)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def select() -> None:
    """Parse argv and dispatch a session switch request.

    State is persisted to next_session *before* spawning the helper so a
    helper crash still leaves the system in a consistent state for the next
    boot. No-arg invocations are silently ignored.
    """
    if len(sys.argv) < 2:
        return

    target = _resolve_target(sys.argv[1])

    next_session_path = get_ssot_var("next_session", NEXT_SESSION_PATH)
    # DISPATCH_FAILED's "state persisted" message below would be a lie if
    # this didn't actually land — persist_next_session logs the failure
    # separately so the two failure modes (persist vs. dispatch) aren't
    # conflated in the log.
    persist_next_session(next_session_path, target)
    jlog("CORE", f"SWITCH_REQUEST: {target}")
    notify(f"Switching to {target.capitalize()}...")

    if not _dispatch_switch(target):
        jlog(
            "CORE",
            f"DISPATCH_FAILED: target={target} — state persisted, "
            "switch will apply on next session",
            level="WARN",
        )


if __name__ == "__main__":
    select()
