#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Jupiter Dock Updater Shim
# VERSION:      2.1.9
# DESCRIPTION:  Self-sufficient shim for SteamOS Dock firmware updates.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/jupiter-dock-updater.py
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
    # Same exit code as steamos-update.
    run_shim(
        "SYSTEM",
        "[Dock] Jupiter updater intercepted. Status: UP TO DATE (Exit 7)",
        exit_code=7,
    )
