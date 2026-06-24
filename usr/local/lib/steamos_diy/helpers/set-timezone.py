#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Set Timezone Shim
# VERSION:      2.1.3
# DESCRIPTION:  Self-sufficient shim for SteamOS timezone requests.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/set-timezone.py
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
    # No utils available: simulate success so Steam doesn't stall on this call.
    sys.exit(0)

if __name__ == "__main__":
    run_shim(
        "SYSTEM",
        "[Time] Set Time request intercepted. Reporting: OK (Simulated)",
        exit_code=0,
    )
