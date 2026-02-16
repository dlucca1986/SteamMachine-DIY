#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher (Trigger)
# VERSION:      1.0.0 - Phyton
# DESCRIPTION:  Dispatcher to trigger session switches between Steam and Desktop.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos-diy/session_select.py
# LICENSE:      MIT
# =============================================================================

import os
import sys
import subprocess


def log_msg(msg):
    """Invia un messaggio al journal di sistema per il Control Center."""
    subprocess.run(["logger", "-t", "steamos-diy", f"[SELECT] {msg}"],
                   check=False)


def select():
    if len(sys.argv) < 2:
        return

    # Carica SSoT per i path
    conf = {}
    with open("/etc/default/steamos_diy.conf", "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                val = v.strip().strip('"').strip("'")
                conf[k.strip()] = val
                os.environ[k.strip()] = val

    target = sys.argv[1].lower()
    if target == "plasma":
        target = "desktop"

    log_msg(f"Richiesta cambio sessione verso: {target.upper()}")

    # Scrittura atomica del target
    next_session_file = conf['next_session']
    tmp = f"{next_session_file}.tmp"
    with open(tmp, "w") as f:
        f.write(target)
    os.replace(tmp, next_session_file)

    # Shutdown basato sul target
    if target == "desktop":
        log_msg("Chiusura Steam in corso...")
        subprocess.run(["steam", "-shutdown"], stderr=subprocess.DEVNULL)
    else:
        log_msg("Logout sessione Plasma (KDE) in corso...")
        for cmd in ["qdbus6", "qdbus"]:
            # Spezziamo il comando per non superare i 79 caratteri (E501)
            args = ["org.kde.Shutdown", "/Shutdown", "logout"]
            subprocess.run([cmd] + args, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    select()
