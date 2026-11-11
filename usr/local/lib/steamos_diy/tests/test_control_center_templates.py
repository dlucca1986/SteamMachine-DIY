"""Regression tests for control_center.py's editor-loading state machine
(toggle_template, load_global_file, load_game_file).

Split out of test_control_center.py, which is at pylint's
too-many-lines limit.

toggle_template: the target combo must stay disabled during a template
preview. Switching file mid-preview once restored the previous file's
cache over the new one on exit, and Save then wrote it to the wrong
path.

load_global_file/load_game_file/_enter_template_mode: an unreadable
(e.g. non-UTF-8) file must degrade to a status-bar message, not crash
the load."""

from types import SimpleNamespace

import control_center
from test_control_center import _FakeDocument

_SCC = control_center.SDYControlCenter


class _FakeEditor:
    def __init__(self, text=""):
        self._text = text
        self._document = _FakeDocument()

    def toPlainText(self):  # pylint: disable=invalid-name
        return self._text

    def setPlainText(self, text):  # pylint: disable=invalid-name
        self._text = text

    def document(self):
        return self._document


class _FakeCombo:
    def __init__(self, text=""):
        self._text = text
        self.enabled = True
        self.signals_blocked = False

    def currentText(self):  # pylint: disable=invalid-name
        return self._text

    def setEnabled(self, value):  # pylint: disable=invalid-name
        self.enabled = value

    def blockSignals(self, value):  # pylint: disable=invalid-name
        self.signals_blocked = value

    def setCurrentText(self, text):  # pylint: disable=invalid-name
        self._text = text

    def findText(self, _text):  # pylint: disable=invalid-name
        return -1  # unlisted: exercises the setEditText branch

    def setEditText(self, text):  # pylint: disable=invalid-name
        self._text = text


# pylint: disable-next=too-few-public-methods
class _FakeQMessageBox:
    """Fakes the classmethod-style QMessageBox.question(...) call site."""

    StandardButton = SimpleNamespace(Discard=2, Cancel=4)

    def __init__(self, reply):
        self._reply = reply
        self.asked = 0

    def question(self, *_args, **_kwargs):
        self.asked += 1
        return self._reply


def _noop_widget():
    """Sink for setText/setEnabled/rehighlight - only combo/editor state
    matters to these tests."""
    return SimpleNamespace(
        setText=lambda *_: None,
        setEnabled=lambda *_: None,
        rehighlight=lambda: None,
    )


# pylint: disable-next=too-few-public-methods
class _FakeStatusBar:
    def __init__(self):
        self.messages = []

    # pylint: disable-next=invalid-name,unused-argument
    def showMessage(self, msg, timeout=0):
        self.messages.append(msg)


# pylint: disable-next=too-many-instance-attributes,too-few-public-methods
class _FakeWindow:
    """Stand-in for SDYControlCenter's toggle_template + the
    _enter_template_mode/_exit_template_mode/_template_path_for/
    _template_widgets_for/_read_or_toast/load_global_file/load_game_file
    it delegates to (bound straight from the real class - only the
    Qt-widget leaves are faked)."""

    _template_widgets_for = _SCC._template_widgets_for
    _read_or_toast = _SCC._read_or_toast
    _enter_template_mode = _SCC._enter_template_mode
    _exit_template_mode = _SCC._exit_template_mode
    _template_path_for = _SCC._template_path_for
    _scaffold_game_profile = _SCC._scaffold_game_profile
    toggle_template = _SCC.toggle_template
    load_global_file = _SCC.load_global_file
    _reselect_loaded_global_file = _SCC._reselect_loaded_global_file
    _reload_clean_editors = _SCC._reload_clean_editors
    load_game_file = _SCC.load_game_file
    _confirm_discard = _SCC._confirm_discard
    save_game_profile = _SCC.save_game_profile
    _select_game_text = _SCC._select_game_text

    def __init__(self, conf_root):
        self.conf_root = conf_root
        self.games_conf_dir = conf_root / "games.d"
        self._status_bar = _FakeStatusBar()
        self.combo_global_files = _FakeCombo("config.yaml")
        self.global_editor = _FakeEditor("live: global\n")
        self.global_save_btn = _noop_widget()
        self.global_temp_btn = _noop_widget()
        self.global_hl = _noop_widget()
        self.combo_games = _FakeCombo("MyGame")
        self.game_editor = _FakeEditor("live: game\n")
        self.game_save_btn = _noop_widget()
        self.game_temp_btn = _noop_widget()
        self.game_hl = _noop_widget()
        self.view_states = {
            context: {
                "is_template": False,
                "cache": "",
                "dirty": False,
                "loaded": "",
            }
            for context in ("global", "games")
        }

    def statusBar(self):  # pylint: disable=invalid-name
        return self._status_bar


def test_toggle_template_disables_and_restores_global_combo(tmp_path):
    (tmp_path / "config.example.yaml").write_text("template: global\n")
    win = _FakeWindow(tmp_path)

    win.toggle_template("global")
    assert win.view_states["global"]["is_template"] is True
    assert win.combo_global_files.enabled is False
    assert win.global_editor.toPlainText() == "template: global\n"

    win.toggle_template("global")
    assert win.view_states["global"]["is_template"] is False
    assert win.combo_global_files.enabled is True
    assert win.global_editor.toPlainText() == "live: global\n"


def test_toggle_template_disables_and_restores_games_combo(tmp_path):
    (tmp_path / "game.example.yaml").write_text("template: game\n")
    win = _FakeWindow(tmp_path)

    win.toggle_template("games")
    assert win.view_states["games"]["is_template"] is True
    assert win.combo_games.enabled is False
    assert win.game_editor.toPlainText() == "template: game\n"

    win.toggle_template("games")
    assert win.view_states["games"]["is_template"] is False
    assert win.combo_games.enabled is True
    assert win.game_editor.toPlainText() == "live: game\n"


# ---------------------------------------------------------------------------
# load_global_file / load_game_file / _enter_template_mode - a read_text()
# failure (non-UTF-8 content, or a TOCTOU delete after the exists() check)
# must degrade to a status-bar message, not an uncaught exception out of a
# Qt slot.
# ---------------------------------------------------------------------------


def test_load_global_file_survives_non_utf8_content(tmp_path):
    (tmp_path / "config.yaml").write_bytes(b"\xff\xfe not valid utf-8\n")
    win = _FakeWindow(tmp_path)

    win.load_global_file()

    assert win.global_editor.toPlainText() == "live: global\n"  # unchanged
    assert win.statusBar().messages


def test_load_game_file_survives_non_utf8_content(tmp_path):
    games_dir = tmp_path / "games.d"
    games_dir.mkdir()
    (games_dir / "MyGame.yaml").write_bytes(b"\xff\xfe not valid utf-8\n")
    win = _FakeWindow(tmp_path)

    win.load_game_file("MyGame")

    assert win.game_editor.toPlainText() == "live: game\n"  # unchanged
    assert win.statusBar().messages


def test_enter_template_mode_survives_non_utf8_content(tmp_path):
    (tmp_path / "config.example.yaml").write_bytes(
        b"\xff\xfe not valid utf-8\n"
    )
    win = _FakeWindow(tmp_path)

    win.toggle_template("global")

    assert win.view_states["global"]["is_template"] is False  # unchanged
    assert win.combo_global_files.enabled is True  # unchanged
    assert win.global_editor.toPlainText() == "live: global\n"  # unchanged
    assert win.statusBar().messages


# ---------------------------------------------------------------------------
# load_global_file / load_game_file - switching the combo to another file
# must not silently drop unsaved edits, just as closing the window doesn't.
# ---------------------------------------------------------------------------


def _dirty_window(tmp_path, monkeypatch, reply):
    (tmp_path / "config.example.yaml").write_text("other: global\n")
    games_dir = tmp_path / "games.d"
    games_dir.mkdir()
    (games_dir / "OtherGame.yaml").write_text("other: game\n")
    box = _FakeQMessageBox(reply)
    monkeypatch.setattr(control_center, "QMessageBox", box)
    win = _FakeWindow(tmp_path)
    win.view_states["global"]["loaded"] = "config.yaml"
    win.view_states["games"]["loaded"] = "MyGame"
    win.global_editor.document().setModified(True)
    win.game_editor.document().setModified(True)
    return win, box


def test_global_switch_cancel_keeps_edits_and_reverts_combo(
    tmp_path, monkeypatch
):
    win, box = _dirty_window(tmp_path, monkeypatch, reply=4)
    win.combo_global_files = _FakeCombo("config.example.yaml")

    win.load_global_file()

    assert box.asked == 1
    assert win.global_editor.toPlainText() == "live: global\n"
    assert win.combo_global_files.currentText() == "config.yaml"
    assert win.combo_global_files.signals_blocked is False


def test_global_switch_discard_loads_new_file(tmp_path, monkeypatch):
    win, _box = _dirty_window(tmp_path, monkeypatch, reply=2)
    win.combo_global_files = _FakeCombo("config.example.yaml")

    win.load_global_file()

    assert win.global_editor.toPlainText() == "other: global\n"
    assert win.view_states["global"]["loaded"] == "config.example.yaml"


def test_game_switch_cancel_keeps_edits_and_reverts_combo(
    tmp_path, monkeypatch
):
    win, box = _dirty_window(tmp_path, monkeypatch, reply=4)
    win.combo_games = _FakeCombo("OtherGame")

    win.load_game_file("OtherGame")

    assert box.asked == 1
    assert win.game_editor.toPlainText() == "live: game\n"
    assert win.combo_games.currentText() == "MyGame"


def test_game_switch_discard_loads_new_file(tmp_path, monkeypatch):
    win, _box = _dirty_window(tmp_path, monkeypatch, reply=2)

    win.load_game_file("OtherGame")

    assert win.game_editor.toPlainText() == "other: game\n"
    assert win.view_states["games"]["loaded"] == "OtherGame"


def test_clean_editor_switches_without_asking(tmp_path, monkeypatch):
    win, box = _dirty_window(tmp_path, monkeypatch, reply=4)
    win.game_editor.document().setModified(False)

    win.load_game_file("OtherGame")

    assert box.asked == 0
    assert win.game_editor.toPlainText() == "other: game\n"


def test_save_game_profile_without_a_name_says_so(tmp_path):
    """Regression: with no game selected or typed, Save returned without
    writing and without a word — the edit just stayed unsaved, and
    closeEvent's Save kept the window open just as silently."""
    win = _FakeWindow(tmp_path)
    win.combo_games = _FakeCombo("   ")

    win.save_game_profile()

    assert win.statusBar().messages
    assert not (tmp_path / "games.d").exists()


def test_template_preview_preserves_the_unsaved_edits_flag(tmp_path):
    """Regression: entering a preview cleared the editor's modified flag
    and leaving it never restored it — the edits came back, but neither
    closeEvent nor a file switch warned about them any more."""
    (tmp_path / "config.example.yaml").write_text("template: global\n")
    win = _FakeWindow(tmp_path)
    win.global_editor.document().setModified(True)

    win.toggle_template("global")
    assert win.global_editor.document().isModified() is False  # preview

    win.toggle_template("global")
    assert win.global_editor.toPlainText() == "live: global\n"
    assert win.global_editor.document().isModified() is True


def test_template_preview_keeps_a_clean_editor_clean(tmp_path):
    (tmp_path / "config.example.yaml").write_text("template: global\n")
    win = _FakeWindow(tmp_path)
    win.global_editor.document().setModified(False)

    win.toggle_template("global")
    win.toggle_template("global")

    assert win.global_editor.document().isModified() is False


# ---------------------------------------------------------------------------
# A load that doesn't happen must not leave the combo on the new entry
# with the previous file's text still in the editor: Save writes the
# editor to whatever the combo names (on the real window, one game's
# profile was written into another's file).
# ---------------------------------------------------------------------------


def test_global_load_failure_puts_the_combo_back(tmp_path):
    (tmp_path / "gamescope.example.yaml").write_bytes(b"\xff\xfe bad")
    win = _FakeWindow(tmp_path)
    win.view_states["global"]["loaded"] = "config.yaml"
    win.combo_global_files = _FakeCombo("gamescope.example.yaml")

    win.load_global_file()

    assert win.combo_global_files.currentText() == "config.yaml"
    assert win.global_editor.toPlainText() == "live: global\n"
    assert win.combo_global_files.signals_blocked is False


def test_global_missing_file_starts_empty(tmp_path):
    win = _FakeWindow(tmp_path)
    win.view_states["global"]["loaded"] = "config.yaml"
    win.combo_global_files = _FakeCombo("gamescope.example.yaml")

    win.load_global_file()

    assert win.global_editor.toPlainText() == ""
    assert win.view_states["global"]["loaded"] == "gamescope.example.yaml"


def test_game_load_failure_puts_the_combo_back(tmp_path):
    games_dir = tmp_path / "games.d"
    games_dir.mkdir()
    (games_dir / "Broken.yaml").write_bytes(b"\xff\xfe bad")
    win = _FakeWindow(tmp_path)
    win.view_states["games"]["loaded"] = "MyGame"
    win.combo_games = _FakeCombo("Broken")

    win.load_game_file("Broken")

    assert win.combo_games.currentText() == "MyGame"
    assert win.game_editor.toPlainText() == "live: game\n"


# ---------------------------------------------------------------------------
# _reload_clean_editors — after a restore the editors must show what is
# now on disk, or the next Save writes the pre-restore text back over the
# restored file.
# ---------------------------------------------------------------------------


def _window_with_files_changed_on_disk(tmp_path):
    (tmp_path / "config.yaml").write_text("restored: global\n")
    games_dir = tmp_path / "games.d"
    games_dir.mkdir()
    (games_dir / "MyGame.yaml").write_text("restored: game\n")
    win = _FakeWindow(tmp_path)
    win.view_states["global"]["loaded"] = "config.yaml"
    win.view_states["games"]["loaded"] = "MyGame"
    win.global_editor.document().setModified(False)
    win.game_editor.document().setModified(False)
    return win


def test_reload_clean_editors_picks_up_restored_files(tmp_path):
    win = _window_with_files_changed_on_disk(tmp_path)

    win._reload_clean_editors()

    assert win.global_editor.toPlainText() == "restored: global\n"
    assert win.game_editor.toPlainText() == "restored: game\n"


def test_reload_clean_editors_never_touches_unsaved_edits(
    tmp_path, monkeypatch
):
    box = _FakeQMessageBox(reply=2)  # would answer "Discard" if asked
    monkeypatch.setattr(control_center, "QMessageBox", box)
    win = _window_with_files_changed_on_disk(tmp_path)
    win.global_editor.document().setModified(True)
    win.game_editor.document().setModified(True)

    win._reload_clean_editors()

    assert box.asked == 0
    assert win.global_editor.toPlainText() == "live: global\n"
    assert win.game_editor.toPlainText() == "live: game\n"


def test_reload_clean_editors_leaves_a_template_preview_alone(tmp_path):
    win = _window_with_files_changed_on_disk(tmp_path)
    win.view_states["global"]["is_template"] = True

    win._reload_clean_editors()

    assert win.global_editor.toPlainText() == "live: global\n"
