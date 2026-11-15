#!/usr/bin/env python3
# pylint: disable=invalid-name,duplicate-code
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Branch Selection Shim
# VERSION:      2.1.9
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
    # utils unavailable (module missing, or its C-Core failed to load):
    # still give Steam the exit code it expects.
    sys.exit(0)

# No real OS branches here: Steam's -c (current) and -l (list) queries
# get one fixed answer. Steam runs -c at every Game Mode start (journal).
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
