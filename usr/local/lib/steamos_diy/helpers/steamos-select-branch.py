#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Branch Selection Shim
# VERSION:      1.2.3
# DESCRIPTION:  Self-sufficient shim for SteamOS branch-switch requests.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/steamos-select-branch.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from utils import run_shim
except ImportError:
    # No utils available: simulate success so Steam doesn't stall on the UI.
    sys.exit(0)

if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "stable"
    run_shim(
        "SYSTEM",
        f"[Branch] Switch intercepted: {selected}. Status: OK",
        exit_code=0,
    )
