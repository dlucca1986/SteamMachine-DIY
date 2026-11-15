#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - SteamOS Update Shim
# VERSION:      2.1.9
# DESCRIPTION:  Self-sufficient shim for SteamOS OTA update infrastructure.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/steamos-update.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)

try:
    from utils import run_shim
except (ImportError, SystemExit):
    # utils unavailable (module missing, or its C-Core failed to load):
    # still give Steam the exit code it expects.
    sys.exit(7)

if __name__ == "__main__":
    # SteamOS convention: 7 = no update available.
    run_shim(
        "SYSTEM",
        "[Update] OTA request intercepted. Status: UP TO DATE (Exit 7)",
        exit_code=7,
    )
