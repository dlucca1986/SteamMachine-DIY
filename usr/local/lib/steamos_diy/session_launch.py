#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Launcher
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Core Session Manager with Dynamic Gamescope Mapping.
#               Handles seamless transitions between Steam and Desktop.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_launch.py
# LICENSE:      MIT
# =============================================================================

import os
import time
import subprocess

def log_msg(msg):
    subprocess.run(["logger", "-t", "steamos-diy", f"[LAUNCHER] {msg}"], check=False)

def run():
    # 1. Carica SSoT (Configurazione di Sistema)
    conf = {}
    with open("/etc/default/steamos_diy.conf", "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip().strip('"').strip("'")

    # 2. Configura l'ambiente Globale (XDG/KDE)
    for k, v in conf.items():
        if k.startswith(("XDG_", "KDE_")):
            os.environ[k] = v

    while True:
        # 3. Leggi il target della sessione
        try:
            with open(conf['next_session'], "r") as f:
                target = f.read().strip()
        except:
            target = "steam"

        # 4. Esecuzione e Switch
        if target == "steam":
            log_msg("Avvio STEAM (Game Mode) con Manifesto...")
            
            gs_params = []
            if os.path.exists(conf['user_config']):
                with open(conf['user_config'], "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        
                        if "=" in line:
                            # Iniezione Variabili d'Ambiente (es. ENABLE_GAMESCOPE_WSI=1)
                            key, val = line.split("=", 1)
                            os.environ[key.strip()] = val.strip().strip('"').strip("'")
                        else:
                            # Flag Gamescope (es. --rt o -W 1920)
                            gs_params.extend(line.split())
            
            # Parametri di sicurezza minimi
            if "-e" not in gs_params: gs_params.append("-e")
            if "-f" not in gs_params: gs_params.append("-f")
            
            cmd = [conf['bin_gs']] + gs_params + ["--", conf['bin_steam'], "-gamepadui", "-steamos3"]
            subprocess.run(cmd)
            next_val = "desktop"
        else:
            log_msg("Avvio DESKTOP (Plasma)...")
            subprocess.run([conf['bin_plasma']])
            next_val = "steam"

        # 5. Scrittura atomica per il prossimo stato
        tmp = f"{conf['next_session']}.tmp"
        with open(tmp, "w") as f:
            f.write(next_val)
        os.replace(tmp, conf['next_session'])
        
        time.sleep(0.5)

if __name__ == "__main__":
    run()
