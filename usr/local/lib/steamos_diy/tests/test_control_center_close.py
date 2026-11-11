"""Regression tests for control_center.py's closeEvent: a failed save
must keep the window open instead of silently discarding the edit.

Split out of test_control_center.py, which is at pylint's
too-many-lines limit."""

import control_center
from test_control_center import _FakeEditor


class _FakeEvent:
    def __init__(self):
        self.accepted = None

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class _FakeStandardButton:  # pylint: disable=too-few-public-methods
    Save = 1
    Discard = 2
    Cancel = 4


class _FakeQMessageBox:  # pylint: disable=too-few-public-methods
    """Fakes the classmethod-style QMessageBox.question(...) call site."""

    StandardButton = _FakeStandardButton

    def __init__(self, reply):
        self._reply = reply

    def question(self, *_args, **_kwargs):
        return self._reply


class _FakeCloseWindow:
    """Binds the real _dirty_editors/closeEvent so the actual wiring
    between them is exercised, not just each in isolation."""

    _dirty_editors = control_center.SDYControlCenter._dirty_editors
    closeEvent = control_center.SDYControlCenter.closeEvent

    def __init__(self, save_succeeds):
        self.view_states = {
            "global": {"is_template": False},
            "games": {"is_template": False},
        }
        self.global_editor = _FakeEditor()
        self.game_editor = _FakeEditor()
        self.global_editor.document().setModified(True)
        self.game_editor.document().setModified(True)
        self._save_succeeds = save_succeeds
        self.save_calls = 0

    def _save(self, editor):
        self.save_calls += 1
        if self._save_succeeds:
            editor.document().setModified(False)
        # On failure, mirrors _atomic_save's real behavior: it shows its
        # own error dialog and leaves the document modified.

    def save_global_config(self):
        self._save(self.global_editor)

    def save_game_profile(self):
        self._save(self.game_editor)


def test_close_event_accepts_when_nothing_dirty():
    win = _FakeCloseWindow(save_succeeds=True)
    win.global_editor.document().setModified(False)
    win.game_editor.document().setModified(False)
    event = _FakeEvent()

    win.closeEvent(event)

    assert event.accepted is True
    assert win.save_calls == 0


def test_close_event_cancel_ignores_without_saving(monkeypatch):
    monkeypatch.setattr(
        control_center,
        "QMessageBox",
        _FakeQMessageBox(_FakeStandardButton.Cancel),
    )
    win = _FakeCloseWindow(save_succeeds=True)
    event = _FakeEvent()

    win.closeEvent(event)

    assert event.accepted is False
    assert win.save_calls == 0


def test_close_event_save_success_accepts_and_clears_dirty(monkeypatch):
    monkeypatch.setattr(
        control_center,
        "QMessageBox",
        _FakeQMessageBox(_FakeStandardButton.Save),
    )
    win = _FakeCloseWindow(save_succeeds=True)
    event = _FakeEvent()

    win.closeEvent(event)

    assert event.accepted is True
    assert win.save_calls == 2


def test_close_event_save_failure_keeps_window_open(monkeypatch):
    """Regression: _atomic_save reports its own errors and returns nothing,
    so closeEvent must check the document's modified flag after saving. A
    failed save (e.g. a YAML syntax error typed just before closing) was
    treated like Discard instead of keeping the edit for another try."""
    monkeypatch.setattr(
        control_center,
        "QMessageBox",
        _FakeQMessageBox(_FakeStandardButton.Save),
    )
    win = _FakeCloseWindow(save_succeeds=False)
    event = _FakeEvent()

    win.closeEvent(event)

    assert event.accepted is False
    assert win.global_editor.document().isModified() is True
