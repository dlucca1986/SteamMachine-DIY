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
    # No utils available (missing module, or utils.py's own C-Core load
    # failure raising SystemExit): simulate success so Steam doesn't
    # stall on the UI.
    sys.exit(0)

# There are no real OS branches here: one fixed value answers Steam's
# -c (current branch) and -l (branch list) queries instead of empty stdout,
# which its update-channel UI reads. Steam runs -c at every Game Mode
# start, not only when its settings page is opened.
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
