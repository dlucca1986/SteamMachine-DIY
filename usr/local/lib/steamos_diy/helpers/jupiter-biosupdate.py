#!/usr/bin/env python3
# pylint: disable=invalid-name
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Jupiter BIOS Update Shim
# VERSION:      1.2.2
# DESCRIPTION:  Compatibility shim for SteamOS BIOS update infrastructure.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(0, "/usr/local/lib/steamos_diy")

try:
    from utils import jlog  # noqa: E402
except ImportError:
    # No utils available: simulate success so Steam doesn't stall on update UI.
    sys.exit(0)


# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

_LOG_TAG: str = "SYSTEM"
_LOG_MESSAGE: str = (
    "[Bios] Jupiter update intercepted. Reporting: OK (Simulated)"
)
_EXIT_OK: int = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Log the BIOS update interception and report simulated success."""
    jlog(_LOG_TAG, _LOG_MESSAGE)
    sys.exit(_EXIT_OK)


if __name__ == "__main__":
    main()
