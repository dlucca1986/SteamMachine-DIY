#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Jupiter BIOS Update Shim
# VERSION:      2.1.7
# DESCRIPTION:  Compatibility shim for SteamOS BIOS update infrastructure.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py
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
except ImportError:
    # No utils available: simulate success so Steam doesn't stall on update UI.
    sys.exit(0)

if __name__ == "__main__":
    run_shim(
        "SYSTEM",
        "[Bios] Jupiter update intercepted. Reporting: OK (Simulated)",
        exit_code=0,
    )
