"""Regression tests for control_center.py's game-scan subsystem
(refresh_detected_games's journalctl invocation, _update_game_combo_ui's
editable-combo handling).

Split out of test_control_center.py (which was already at the pylint
too-many-lines ceiling) rather than trimming other tests to make room —
reuses that file's own _FakeGamesWindow/_sync_thread_factory instead of
duplicating them (pylint's duplicate-code check flags a copy)."""

import control_center
from test_control_center import _FakeGamesWindow, _sync_thread_factory


def test_refresh_detected_games_caps_journalctl_line_count(monkeypatch):
    """Regression: the journalctl call had no -n line cap, unlike
    journal.py's own bounded get_journal_cmd() pattern (-n 300) — every
    "Scan History" click pulled the WHOLE 24h system journal, mostly
    discarded by the Python-side filter (found via the second full-file
    review pass, 2026-09-02)."""
    win = _FakeGamesWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    captured = {}

    # duplicate-code: this fake_run/monkeypatch shape mirrors the other
    # refresh_detected_games tests in test_control_center.py — not an
    # independent reimplementation worth a shared helper for 8 lines.
    # pylint: disable=duplicate-code
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured.update(kwargs)
        return control_center.subprocess.CompletedProcess(
            cmd, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)
    # pylint: enable=duplicate-code

    control_center.SDYControlCenter.refresh_detected_games(win)

    cmd = captured["cmd"]
    assert "-n" in cmd
    assert cmd[cmd.index("-n") + 1].isdigit()


# ---------------------------------------------------------------------------
# _update_game_combo_ui — must not wipe an in-progress typed entry
# ---------------------------------------------------------------------------


class _FakeEditableCombo:
    def __init__(self, text=""):
        self._text = text
        self.items = []

    def currentText(self):  # pylint: disable=invalid-name
        return self._text

    def clear(self):
        self.items = []
        self._text = ""

    def addItems(self, items):  # pylint: disable=invalid-name
        # Real QComboBox auto-selects index 0 when items land on a
        # freshly-cleared (no current selection) combo — for an editable
        # combo that also updates the line-edit text.
        self.items = list(items)
        if items:
            self._text = items[0]

    # pylint: disable-next=invalid-name,unused-argument
    def setPlaceholderText(self, text):
        pass

    def setEditText(self, text):  # pylint: disable=invalid-name
        self._text = text


# pylint: disable-next=too-few-public-methods
class _FakeComboWindow:
    """Stand-in for SDYControlCenter: only what _update_game_combo_ui (and
    the _merge_on_disk_profiles/_format_combo_items it delegates to, bound
    straight from the real class) touches."""

    _merge_on_disk_profiles = (
        control_center.SDYControlCenter._merge_on_disk_profiles
    )
    _format_combo_items = staticmethod(
        control_center.SDYControlCenter._format_combo_items
    )
    _update_game_combo_ui = (
        control_center.SDYControlCenter._update_game_combo_ui
    )

    def __init__(self, games_conf_dir, typed_text=""):
        self.games_conf_dir = games_conf_dir
        self.combo_games = _FakeEditableCombo(typed_text)


def test_update_game_combo_ui_preserves_in_progress_typed_entry(tmp_path):
    """Regression: a "Scan History" click finishing while the user is
    still typing a manually-added game's name into the editable combo
    wiped that text — QComboBox.clear() resets the line-edit text along
    with the item list, and a subsequent Save silently no-ops on the
    now-empty currentText() (found via the second full-file review pass,
    2026-09-02)."""
    win = _FakeComboWindow(tmp_path / "games.d", typed_text="MyCustomGame")

    win._update_game_combo_ui({"OtherGame": "OtherGame"})

    assert win.combo_games.currentText() == "MyCustomGame"


def test_update_game_combo_ui_leaves_a_real_selection_untouched(tmp_path):
    win = _FakeComboWindow(tmp_path / "games.d", typed_text="OtherGame")

    win._update_game_combo_ui({"OtherGame": "OtherGame"})

    assert win.combo_games.currentText() == "OtherGame"
    assert win.combo_games.items == ["OtherGame"]
