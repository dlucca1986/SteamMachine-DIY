#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher (Trigger)
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and Desktop.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_select.py
# LICENSE:      MIT
# =============================================================================

import os
import sys
import subprocess


def log_msg(msg):
    """Sends a message to the system journal for the Control Center."""
    subprocess.run(["logger", "-t", "steamos-diy", f"[SELECT] {msg}"],
                   check=False)


def select():
    if len(sys.argv) < 2:
        return

    # 1. Load SSoT (Single Source of Truth)
    conf = {}
    try:
        with open("/etc/default/steamos_diy.conf", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        # Fallback if config doesn't exist yet (e.g., during installation)
        conf['next_session'] = "/var/lib/steamos_diy/next_session"
        conf['bin_steam'] = "steam"

    # 2. Target Validation (Strict)
    target = sys.argv[1].lower()
    if target not in ["desktop", "steam"]:
        log_msg(f"Target '{target}' not recognized. Only 'desktop' or 'steam'.")
        return

    log_msg(f"Session switch requested towards: {target.upper()}")

    # 3. Atomic Write (Prevents corruption on power loss)
    next_session_file = conf['next_session']
    tmp = f"{next_session_file}.tmp"
    with open(tmp, "w") as f:
        f.write(target)
    os.replace(tmp, next_session_file)

    # 4. Current Session Shutdown
    if target == "desktop":
        log_msg("Closing Steam...")
        # Use binary defined in SSoT for flexibility
        steam_bin = conf.get('bin_steam', 'steam')
        subprocess.run([steam_bin, "-shutdown"], stderr=subprocess.DEVNULL)
    else:
        log_msg("KDE Plasma logout in progress...")
        for cmd in ["qdbus6", "qdbus"]:
            args = ["org.kde.Shutdown", "/Shutdown", "logout"]
            subprocess.run([cmd] + args, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    select()
