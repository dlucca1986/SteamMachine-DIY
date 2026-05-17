#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher
# VERSION:      2.0.0
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and KDE.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_select.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

from utils import (
    NEXT_SESSION_PATH,
    get_ssot_var,
    jlog,
    notify,
    spawn_native,
    write_atomic,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once, never re-read from disk.
# ---------------------------------------------------------------------------

BIN_STEAM_DEFAULT: str = "/usr/bin/steam"
BIN_DBUS_DEFAULT: str = "/usr/bin/qdbus6"

# Keywords that map argv[1] to the desktop target. Frozenset to enforce
# immutability and O(1) membership lookup.
_DESKTOP_KEYWORDS: frozenset[str] = frozenset({"plasma", "desktop", "kde"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_target(arg: str) -> str:
    """Normalise a raw argv string to "desktop" or "steam".

    Strips whitespace and lowercases before matching, tolerating values
    from systemd units, shell aliases, or xargs. Defaults to "steam" on
    empty or unknown input (fail-safe to Game Mode).
    """
    if not arg:
        return "steam"
    return "desktop" if arg.strip().lower() in _DESKTOP_KEYWORDS else "steam"


def _dispatch_switch(target: str) -> bool:
    """Spawn the native helper that triggers the session transition.

    Hand-off matrix:
        desktop → ``steam -shutdown``          (Steam exits → Plasma)
        steam   → ``qdbus6 org.kde.Shutdown /Shutdown logout`` (→ Gamescope)

    Returns True if the helper process was spawned (PID > 0).
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

    State is persisted to next_session *before* spawning the helper so a
    helper crash still leaves the system in a consistent state for the next
    boot. No-arg invocations are silently ignored.
    """
    if len(sys.argv) < 2:
        return

    target = _resolve_target(sys.argv[1])

    next_session_path = get_ssot_var("next_session", NEXT_SESSION_PATH)
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
