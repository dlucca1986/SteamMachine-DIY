#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      1.0.0 - Phyton
# DESCRIPTION:  Compatibility shim for SteamOS OTA update infrastructure.
#               Returns Exit Code 7 to simulate an "Up to Date" status.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/helpers/set-timezone.py
# LICENSE:      MIT
# =============================================================================

import sys
import subprocess


def main():
    # 1. Cattura il branch (default 'stable' se non viene passato nulla)
    # sys.argv[0] è il nome dello script, sys.argv[1] è il primo argomento
    selected_branch = sys.argv[1] if len(sys.argv) > 1 else "stable"

    tag = "steamos-diy"

    # 2. Logghiamo i messaggi per il Control Center
    msg1 = f"[BRANCH-SHIM] Intercettata richiesta switch: {selected_branch}"
    msg2 = f"[BRANCH-SHIM] Release channel '{selected_branch}' confermato (Simulato)."

    # Invio al journal
    subprocess.run(["logger", "-t", tag, msg1], check=False)
    subprocess.run(["logger", "-t", tag, msg2], check=False)

    # 3. Exit 0 per Steam
    sys.exit(0)


if __name__ == "__main__":
    main()
