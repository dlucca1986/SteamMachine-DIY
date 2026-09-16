#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Branch Selection Shim
# VERSION:      2.1.8
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
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
)

try:
    from utils import jlog, run_shim
except (ImportError, SystemExit):
    # No utils available (missing module, or utils.py's own C-Core load
    # failure raising SystemExit): simulate success so Steam doesn't
    # stall on the UI.
    sys.exit(0)

# This project has no real branches to report — a single fixed value is
# enough to answer Steam's -c (current branch)/-l (branch list) queries
# coherently instead of leaving stdout empty, which is what Steam's own
# (inapplicable-here) update-channel UI reads from. Confirmed live
# 2026-09-16: Steam calls -c on every normal game launch, not just when
# a settings page is opened, so this is exercised far more than it looks.
_FAKE_BRANCH = "stable"

if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "stable"
    if selected in ("-c", "-l"):
        jlog(
            "SYSTEM",
            f"[Branch] Query intercepted: {selected}. Reporting: "
            f"{_FAKE_BRANCH}",
        )
        print(_FAKE_BRANCH)
        sys.exit(0)
    run_shim(
        "SYSTEM",
        f"[Branch] Switch intercepted: {selected}. Status: OK",
        exit_code=0,
    )
