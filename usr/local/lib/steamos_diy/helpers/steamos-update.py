#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Compatibility shim for SteamOS OTA update infrastructure.
#               Returns Exit Code 7 to simulate an "Up to Date" status.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/steamos-update.py
# LICENSE:      MIT
# =============================================================================
"""

# pylint: disable=invalid-name, duplicate-code

import subprocess
import sys


def log_to_journal(tag, message):
    """Force message injection into systemd-journal."""
    full_msg = f"{tag}: {message}"
    try:
        subprocess.run(
            ["systemd-cat", "-t", tag],
            input=full_msg.encode("utf-8"),
            check=False,
        )
    except FileNotFoundError:
        print(full_msg, flush=True)


def main():
    """Intercept OTA requests and report Up-to-Date status."""
    tag = "BRANCH-SHIM"
    msg1 = "Steam OTA update request intercepted."
    msg2 = "Reporting status: UP TO DATE (Forced Exit 7)."

    log_to_journal(tag, msg1)
    log_to_journal(tag, msg2)
    sys.exit(7)


if __name__ == "__main__":
    main()
