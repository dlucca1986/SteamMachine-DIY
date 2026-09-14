"""Regression tests for control_center.py's Diagnostics-tab log coloring
(_apply_log_style / _highlight_log_markers).

Before this fix, "ERROR:"/"DEBUG:" lived in the same log_styles dict as
the CORE:/STEAM:/SYSTEM: identifier tags, matched in a loop that returned
on the *first* hit — since every real line already contains its
identifier (CORE:/STEAM:/SYSTEM: is always present), that match always
won first and "ERROR:"/"DEBUG:" could never be reached, even though
"ERROR:" genuinely appears as a substring in real jlog message text
(SCAN_ERROR:, OS_ERROR:, etc.). Confirmed live with the real function
before fixing it, not just reasoned about (2026-09-14). Also never
covered the more common _FAIL:/_FAILED: message family at all. Fixed by
making identifier colour and message-content markers independent layers
instead of mutually exclusive."""

from typing import ClassVar

import control_center


# pylint: disable-next=too-few-public-methods
class _FakeLogWindow:
    """Stand-in for SDYControlCenter: only the log-styling attributes and
    methods _apply_log_style touches, bound straight from the real class
    so the actual regex/replace logic runs unmocked."""

    log_styles: ClassVar = {
        "CORE:": ("🔵", "#3498db"),
        "STEAM:": ("🎮", "#2ecc71"),
        "SYSTEM:": ("⚙️", "#f39c12"),
    }
    gs_levels: ClassVar = {
        "[Error]": ("❌", "#ff4444"),
        "[Warn]": ("⚠️", "#ffbb33"),
        "[Info]": ("ℹ️", "#33b5e5"),
    }
    _apply_log_style = control_center.SDYControlCenter._apply_log_style
    _highlight_log_markers = staticmethod(
        control_center.SDYControlCenter._highlight_log_markers
    )
    _style_gamescope_line = (
        control_center.SDYControlCenter._style_gamescope_line
    )


def test_apply_log_style_colours_identifier_and_error_marker_together():
    """The exact regression: a CORE-tagged error message must get BOTH
    the CORE: identifier colour AND the error-marker highlight, not just
    whichever matched first."""
    win = _FakeLogWindow()

    styled = win._apply_log_style(
        "[10:00:00] CORE: SCAN_ERROR: /some/dir - PermissionError"
    )

    assert "#3498db" in styled  # CORE: identifier colour
    assert "#e74c3c" in styled  # error-marker colour
    assert "SCAN_ERROR:" in styled


def test_apply_log_style_colours_failed_family_not_just_error():
    """_FAIL:/_FAILED: (the more common family in this codebase — 18+
    distinct tags) must be highlighted the same as _ERROR:, not missed
    entirely like before this fix."""
    win = _FakeLogWindow()

    styled = win._apply_log_style(
        "[10:00:00] STEAM: NEXT_SESSION_WRITE_FAILED: /var/lib/x"
    )

    assert "#e74c3c" in styled
    assert "NEXT_SESSION_WRITE_FAILED:" in styled


def test_apply_log_style_colours_early_exit_recovery():
    """EARLY_EXIT_RECOVERY: doesn't follow the _ERROR:/_FAIL: naming
    convention, so it's matched as an explicit special case."""
    win = _FakeLogWindow()

    styled = win._apply_log_style(
        "[18:55:20] CORE: EARLY_EXIT_RECOVERY: process exited"
    )

    assert "#e74c3c" in styled
    assert "EARLY_EXIT_RECOVERY:" in styled


def test_apply_log_style_colours_validated_stable_success_markers():
    win = _FakeLogWindow()

    for target in ("STEAM", "DESKTOP"):
        styled = win._apply_log_style(
            f"[18:55:24] CORE: VALIDATED_{target}_STABLE"
        )
        assert "#2ecc71" in styled
        assert f"VALIDATED_{target}_STABLE" in styled


def test_apply_log_style_colours_switch_request_neutral():
    win = _FakeLogWindow()

    styled = win._apply_log_style("[18:55:19] CORE: SWITCH_REQUEST: steam")

    assert "#7f8c8d" in styled
    assert "SWITCH_REQUEST:" in styled


def test_apply_log_style_leaves_unmatched_message_unhighlighted():
    """A message with no error/success/switch marker only gets the
    identifier colour — no spurious highlighting."""
    win = _FakeLogWindow()

    styled = win._apply_log_style(
        "[10:00:00] SYSTEM: BACKUP_SUCCESS: sdy_backup_20260908.tar.gz"
    )

    assert "#f39c12" in styled  # SYSTEM: identifier colour
    assert "#e74c3c" not in styled
    assert "#2ecc71" not in styled


def test_apply_log_style_gamescope_lines_still_route_separately():
    """Regression guard: gamescope's own [Error]/[Warn]/[Info] styling
    must still take the _style_gamescope_line() path, unaffected by the
    new marker layer."""
    win = _FakeLogWindow()

    styled = win._apply_log_style(
        "[gamescope] [Error] drm: drmModeAddFB2WithModifiers failed"
    )

    assert "#ff4444" in styled  # gamescope [Error] colour
    assert "#1abc9c" in styled  # [gamescope] tag colour
