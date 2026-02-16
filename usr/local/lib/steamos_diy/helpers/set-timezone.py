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

import os
import sys
import subprocess
from datetime import datetime


def get_log_file():
    """Determina il file di log dal SSoT o usa un fallback."""
    ssot_path = "/etc/default/steamos-diy.conf"
    if os.path.exists(ssot_path):
        with open(ssot_path, "r") as f:
            for line in f:
                if "LOG_FILE=" in line:
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "/tmp/steamos-diy-fallback.log"


def main():
    # 1. Recupera la timezone (default UTC)
    target_zone = sys.argv[1] if len(sys.argv) > 1 else "UTC"
    log_file = get_log_file()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 2. Messaggi
    msg1 = f"Intercepting Steam Client timezone request: {target_zone}"
    msg2 = ("Timezone request acknowledged. System settings remain unchanged "
            "to preserve host OS integrity.")

    # 3. Log verso il Journal (per il Control Center)
    tag = "steamos-diy"
    subprocess.run(["logger", "-t", tag, f"[TIME-SHIM] {msg1}"], check=False)
    subprocess.run(["logger", "-t", tag, f"[TIME-SHIM] {msg2}"], check=False)

    # 4. Log verso il file fisico (come da script originale)
    try:
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] [TIME-SHIM] {msg1}\n")
            f.write(f"[{timestamp}] [TIME-SHIM] {msg2}\n")
    except OSError:
        pass

    # 5. Exit 0 per Steam
    sys.exit(0)


if __name__ == "__main__":
    main()
