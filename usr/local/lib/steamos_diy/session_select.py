#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Switcher (Trigger)
# VERSION:      1.0.0 - Pyton
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
    """Invia un messaggio al journal di sistema per il Control Center."""
    subprocess.run(["logger", "-t", "steamos-diy", f"[SELECT] {msg}"], check=False)

def select():
    if len(sys.argv) < 2:
        return

    # 1. Carica SSoT
    conf = {}
    try:
        with open("/etc/default/steamos_diy.conf", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        # Fallback se il file non esiste ancora (es. durante l'installazione)
        conf['next_session'] = "/var/lib/steamos_diy/next_session"
        conf['bin_steam'] = "steam"

    # 2. Validazione Target (Rigida)
    target = sys.argv[1].lower()
    if target not in ["desktop", "steam"]:
        log_msg(f"Target '{target}' non riconosciuto. Solo 'desktop' o 'steam' sono ammessi.")
        return

    log_msg(f"Richiesta cambio sessione verso: {target.upper()}")

    # 3. Scrittura atomica (Evita corruzione se salta la corrente)
    next_session_file = conf['next_session']
    tmp = f"{next_session_file}.tmp"
    with open(tmp, "w") as f:
        f.write(target)
    os.replace(tmp, next_session_file)

    # 4. Shutdown della sessione corrente
    if target == "desktop":
        log_msg("Chiusura Steam in corso...")
        # Usiamo il binario definito nel SSoT (Flessibilità)
        subprocess.run([conf.get('bin_steam', 'steam'), "-shutdown"], 
                       stderr=subprocess.DEVNULL)
    else:
        log_msg("Logout sessione Plasma (KDE) in corso...")
        for cmd in ["qdbus6", "qdbus"]:
            args = ["org.kde.Shutdown", "/Shutdown", "logout"]
            subprocess.run([cmd] + args, stderr=subprocess.DEVNULL)

if __name__ == "__main__":
    select()
