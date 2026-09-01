"""Regression tests for control_center.py's toggle_template state machine.

Split out of test_control_center.py (which was already at the pylint
too-many-lines ceiling) rather than trimming other tests to make room.

The target combo (combo_global_files/combo_games) must stay disabled for
the duration of a template preview. Regression: switching the target file
mid-preview fired load_global_file/load_game_file (wired to the combo's
own change signal) while is_template/cache still tracked the PREVIOUS
file; exiting template mode then restored that stale cache over the
newly-selected file, and a subsequent Save wrote it to the wrong path
(found via the second full-file review pass, 2026-09-02)."""

from types import SimpleNamespace

import control_center

_SCC = control_center.SDYControlCenter


class _FakeDocument:  # pylint: disable=too-few-public-methods
    def __init__(self):
        self.modified = None

    def setModified(self, value):  # pylint: disable=invalid-name
        self.modified = value


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

    def currentText(self):  # pylint: disable=invalid-name
        return self._text

    def setEnabled(self, value):  # pylint: disable=invalid-name
        self.enabled = value


def _noop_widget():
    """Sink for setText/setEnabled/rehighlight - only combo/editor state
    matters to these tests."""
    return SimpleNamespace(
        setText=lambda *_: None,
        setEnabled=lambda *_: None,
        rehighlight=lambda: None,
    )


# pylint: disable-next=too-many-instance-attributes,too-few-public-methods
class _FakeWindow:
    """Stand-in for SDYControlCenter's toggle_template + the
    _enter_template_mode/_exit_template_mode/_template_path_for/
    _template_widgets_for it delegates to (bound straight from the real
    class - only the Qt-widget leaves are faked)."""

    _template_widgets_for = _SCC._template_widgets_for
    _enter_template_mode = _SCC._enter_template_mode
    _exit_template_mode = _SCC._exit_template_mode
    _template_path_for = _SCC._template_path_for
    toggle_template = _SCC.toggle_template

    def __init__(self, conf_root):
        self.conf_root = conf_root
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
            "global": {"is_template": False, "cache": ""},
            "games": {"is_template": False, "cache": ""},
        }


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
