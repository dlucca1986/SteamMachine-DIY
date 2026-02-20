#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher
# VERSION:      1.0.0
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and KDE.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_select.py
# LICENSE:      MIT
# =============================================================================

import os
import subprocess
import sys
from pathlib import Path


def qlog(tag, msg):
    """Print 'TAG: message' - Format for Systemd and Control Center."""
    print(f"{tag}: {msg}", flush=True)


def load_ssot():
    """Rapidly load Single Source of Truth (SSoT) into os.environ."""
    conf_path = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
    try:
        content = Path(conf_path).read_text(encoding="utf-8")
        for line in content.splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")
        return True
    except OSError:
        return False


def select():
    """Validate target session and trigger the switch process."""
    if len(sys.argv) < 2:
        return

    if not load_ssot():
        qlog("SELECT", "ERROR: Could not load SSOT")
        return

    # Target Normalization
    raw_target = sys.argv[1].lower()
    target = "desktop" if raw_target == "plasma" else raw_target

    if target not in ["desktop", "steam"]:
        qlog("SELECT", f"ERROR: Invalid target '{raw_target}'")
        return

    # --- ATOMIC & SSD SAFE WRITE ---
    next_session_path = os.getenv(
        "next_session", "/var/lib/steamos_diy/next_session"
    )
    p = Path(next_session_path)

    # SSD Protection: Read-before-write
    if p.exists():
        try:
            if p.read_text(encoding="utf-8").strip() == target:
                qlog("SELECT", f"NO_CHANGE: target already {target}")
            else:
                tmp = p.with_suffix(".tmp")
                tmp.write_text(target, encoding="utf-8")
                tmp.replace(p)
                qlog("SELECT", f"SWITCH_REQUEST: target={target}")
        except OSError as e:
            qlog("SELECT", f"FATAL_WRITE_ERROR: {e}")
            return
    else:
        # Fallback if file doesn't exist
        try:
            p.write_text(target, encoding="utf-8")
        except OSError:
            pass

    # Current Session Shutdown Logic
    if target == "desktop":
        qlog("SELECT", "TRIGGERING_STEAM_SHUTDOWN")
        steam_bin = os.getenv("bin_steam", "steam")
        # pylint: disable=consider-using-with
        subprocess.Popen([steam_bin, "-shutdown"], stderr=subprocess.DEVNULL)
    else:
        qlog("SELECT", "TRIGGERING_PLASMA_LOGOUT")
        # KDE 6 uses qdbus6 for session management
        logout_cmd = ["qdbus6", "org.kde.Shutdown", "/Shutdown", "logout"]
        # pylint: disable=consider-using-with
        subprocess.Popen(logout_cmd, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    select()
