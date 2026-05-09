#!/usr/bin/env python3
# pylint: disable=invalid-name
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Jupiter Dock Updater Shim
# VERSION:      1.2.2
# DESCRIPTION:  Self-sufficient shim for SteamOS Dock firmware updates.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/helpers/jupiter-dock-updater.py
# LICENSE:      MIT
# =============================================================================
"""

import sys

# Helpers live in a subdir; expose the project library before any import.
sys.path.insert(0, "/usr/local/lib/steamos_diy")

try:
    from utils import jlog  # noqa: E402
except ImportError:
    # Exit 7 is mandatory even without utils — Steam reads it as
    # "firmware up to date" and skips the real update flow.
    sys.exit(7)


# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

_LOG_TAG: str = "SYSTEM"
_LOG_MESSAGE: str = (
    "[Dock] Jupiter updater intercepted. Status: UP TO DATE (Exit 7)"
)
# RAUC-style convention: 7 means "no update available".
_EXIT_UP_TO_DATE: int = 7


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Log the dock-update interception and report up-to-date status."""
    jlog(_LOG_TAG, _LOG_MESSAGE)
    sys.exit(_EXIT_UP_TO_DATE)


if __name__ == "__main__":
    main()
