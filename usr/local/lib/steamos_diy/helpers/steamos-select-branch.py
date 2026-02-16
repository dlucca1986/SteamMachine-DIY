#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Compatibility shim for SteamOS OTA update infrastructure.
#               Returns Exit Code 0 to simulate a successful branch switch.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/steamos-select-branch.py
# LICENSE:      MIT
# =============================================================================

import sys
import subprocess


def main():
    """
    Simulates a successful update channel (branch) selection.
    """
    # 1. Capture the branch (defaults to 'stable' if no argument is provided)
    selected_branch = sys.argv[1] if len(sys.argv) > 1 else "stable"

    tag = "steamos-diy"

    # 2. Prepare log messages for the System Control Center
    msg1 = f"[BRANCH-SHIM] Intercepted branch switch request: {selected_branch}"
    msg2 = f"[BRANCH-SHIM] Release channel '{selected_branch}' confirmed (Simulated)."

    # Send messages to system journal
    subprocess.run(["logger", "-t", tag, msg1], check=False)
    subprocess.run(["logger", "-t", tag, msg2], check=False)

    # 3. Exit with success (0) for Steam Client compatibility
    sys.exit(0)


if __name__ == "__main__":
    main()
