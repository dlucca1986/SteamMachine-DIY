#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher
# VERSION:      1.7.2 (Optimized Native Dispatcher)
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and KDE.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_select.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

from utils import get_ssot_var, jlog, notify, spawn_native, write_atomic

# ---------------------------------------------------------------------------
# Module-level constants — resolved once, never re-read from disk.
# ---------------------------------------------------------------------------

DEFAULT_SESS_PATH: str = "/var/lib/steamos_diy/next_session"
BIN_STEAM_DEFAULT: str = "/usr/bin/steam"
BIN_DBUS_DEFAULT: str = "/usr/bin/qdbus6"

# Keywords that map argv[1] to the desktop target. Frozenset to enforce
# immutability and O(1) membership lookup.
_DESKTOP_KEYWORDS: frozenset[str] = frozenset({"plasma", "desktop", "kde"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_target(arg: str) -> str:
    """Map a raw argv string to a normalised session target.

    Performs case-insensitive matching with whitespace stripped, so values
    coming from systemd unit files, shell aliases or xargs-style triggers
    are tolerated transparently (e.g. "Desktop ", "  KDE\\n").

    Args:
        arg: Raw user-supplied argument from argv.

    Returns:
        Either "desktop" or "steam". Defaults to "steam" for empty or
        unknown values, preserving the original "fail-safe to Game Mode"
        behaviour.
    """
    if not arg:
        return "steam"
    return "desktop" if arg.strip().lower() in _DESKTOP_KEYWORDS else "steam"


def _dispatch_switch(target: str) -> bool:
    """Spawn the native helper that triggers the actual session switch.

    Hand-off matrix:
        - target == "desktop": invoke ``steam -shutdown`` to gracefully
          close the Steam session, allowing the systemd unit to fall
          through to Plasma.
        - target == "steam":   invoke ``qdbus6 org.kde.Shutdown
          /Shutdown logout`` to log out of the current Plasma session,
          allowing systemd to start the Gamescope/Steam unit.

    Args:
        target: Resolved target ("desktop" or "steam").

    Returns:
        True if the helper process was spawned successfully (PID > 0),
        False if spawn_native reported a failure (PID == 0).
    """
    if target == "desktop":
        steam_bin = get_ssot_var("bin_steam", BIN_STEAM_DEFAULT)
        pid = spawn_native(steam_bin, [steam_bin, "-shutdown"])
    else:
        dbus_bin = get_ssot_var("bin_dbus", BIN_DBUS_DEFAULT)
        pid = spawn_native(
            dbus_bin,
            [dbus_bin, "org.kde.Shutdown", "/Shutdown", "logout"],
        )

    return pid > 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def select() -> None:
    """Parse argv and dispatch a session switch request.

    Flow:
        1. Read argv[1] and normalise it via _resolve_target.
        2. Persist the chosen target to the next_session file (atomic).
        3. Log the request and notify the user via TTY.
        4. Spawn the native helper to trigger the actual switch.
        5. Log a warning if the helper could not be spawned — the
           persisted state is still valid, so the next boot will respect
           it, but the immediate switch will not happen.

    Note:
        Silently returns when no argument is provided. The persisted state
        is updated *before* spawning the helper: this is intentional, so
        that if the helper crashes after persisting we still come up in
        the requested target on the next session.
    """
    if len(sys.argv) < 2:
        return

    target = _resolve_target(sys.argv[1])

    next_session_path = get_ssot_var("next_session", DEFAULT_SESS_PATH)
    write_atomic(next_session_path, target)
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
