#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      1.0.0 - Phyton
# DESCRIPTION:  Compatibility shim for SteamOS OTA update infrastructure.
#               Returns Exit Code 7 to simulate an "Up to Date" status.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/helpers/steamos-update.py
# LICENSE:      MIT
# =============================================================================

import sys
import subprocess


def main():
    # 1. Configurazione Tag e Messaggi
    tag = "steamos-diy"
    msg1 = "[UPDATE-SHIM] Intercettata richiesta OTA da Steam."
    msg2 = "[UPDATE-SHIM] Reporting status: UP TO DATE (Forced Exit 7)."

    # 2. Logging verso il Journal (Control Center)
    # Usiamo subprocess per parlare con logger come faceva lo script bash
    subprocess.run(["logger", "-t", tag, msg1], check=False)
    subprocess.run(["logger", "-t", tag, msg2], check=False)

    # 3. Exit Code 7 (Il "segreto" per dire a Steam che non ci sono update)
    sys.exit(7)

if __name__ == "__main__":
    main()
  
