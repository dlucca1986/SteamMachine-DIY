#!/usr/bin/env python3
# pylint: disable=invalid-name
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Branch Selection Shim
# VERSION:      1.2.2
# DESCRIPTION:  Self-sufficient shim for SteamOS branch-switch requests.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/steamos-select-branch.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(0, "/usr/local/lib/steamos_diy")

try:
    from utils import jlog  # noqa: E402
except ImportError:
    # No utils available: simulate success so Steam doesn't stall on the UI.
    sys.exit(0)


# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

_LOG_TAG: str = "SYSTEM"
_DEFAULT_BRANCH: str = "stable"
_EXIT_OK: int = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Log the requested branch and report a simulated successful switch."""
    selected = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_BRANCH
    jlog(_LOG_TAG, f"[Branch] Switch intercepted: {selected}. Status: OK")
    sys.exit(_EXIT_OK)


if __name__ == "__main__":
    main()
