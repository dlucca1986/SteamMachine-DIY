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
        # No auto-selection, matching the real app: refresh_detected_games
        # sets the combo's placeholder before every scan, and with a
        # placeholder set a real QComboBox leaves the index at -1 (text
        # "") after addItems on a cleared combo. Without one it would
        # auto-select index 0 instead — the behavior this fake used to
        # model, which made the 2026-09-27 fix describe the wrong failure
        # (verified on the real window, 2026-11-09).
        self.items = list(items)

    # pylint: disable-next=invalid-name,unused-argument
    def setPlaceholderText(self, text):
        pass

    def setEditText(self, text):  # pylint: disable=invalid-name
        self._text = text

    def setCurrentIndex(self, index):  # pylint: disable=invalid-name
        self._text = self.items[index]

    def findText(self, text):  # pylint: disable=invalid-name
        return self.items.index(text) if text in self.items else -1


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
    _select_game_text = control_center.SDYControlCenter._select_game_text

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


def test_update_game_combo_ui_keeps_a_non_first_selection(tmp_path):
    """Regression: only a typed entry NOT in the new item list was
    restored, so an already-listed selection was lost on every Scan
    History — the combo ended up with no selection and empty text while
    the editor still held the game's profile, and the next Save (which
    targets currentText()) silently did nothing (fixed 2026-09-27).
    Originally described as "overwrote the first game's file": true only
    for a QComboBox without a placeholder, which auto-selects index 0 —
    re-verified on the real window 2026-11-09, where the scan's
    placeholder keeps the index at -1."""
    gdir = tmp_path / "games.d"
    win = _FakeComboWindow(gdir, typed_text="Beta (20)")

    win._update_game_combo_ui({"Alpha": "10", "Beta": "20"})

    assert win.combo_games.items[0] != "Beta (20)"  # precondition
    assert win.combo_games.currentText() == "Beta (20)"
