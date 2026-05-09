#!/usr/bin/env python3
# pylint: disable=invalid-name
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Set Timezone Shim
# VERSION:      1.2.2
# DESCRIPTION:  Self-sufficient shim for SteamOS timezone requests.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/set-timezone.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(0, "/usr/local/lib/steamos_diy")

try:
    from utils import jlog  # noqa: E402
except ImportError:
    # No utils available: simulate success so Steam doesn't stall on this call.
    sys.exit(0)


# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

_LOG_TAG: str = "SYSTEM"
_LOG_MESSAGE: str = (
    "[Time] Set Time request intercepted. Reporting: OK (Simulated)"
)
_EXIT_OK: int = 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Log the timezone-set interception and report simulated success."""
    jlog(_LOG_TAG, _LOG_MESSAGE)
    sys.exit(_EXIT_OK)


if __name__ == "__main__":
    main()
