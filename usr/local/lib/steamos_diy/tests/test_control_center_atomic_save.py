"""Regression tests for control_center.py's _atomic_save: a saved profile
whose YAML root isn't a mapping used to report success while
load_yaml_safe() (utils.py) silently degrades that exact shape to {} on
the next load, dropping the whole profile; and write_atomic()'s bool
return (added when c_write_atomic stopped being void) must actually be
checked, not just called.

Split out of test_control_center.py (which was already at the pylint
too-many-lines ceiling) rather than trimming other tests to make room."""

from types import SimpleNamespace

import control_center
from test_control_center import _FakeEditor, _FakeMessageBox


def _atomic_save_harness(monkeypatch, tmp_path, content, write_succeeds=True):
    calls = []
    monkeypatch.setattr(
        control_center, "QMessageBox", _FakeMessageBox(calls)
    )
    written = []

    def fake_write_atomic(p, c):
        written.append((p, c))
        return write_succeeds

    monkeypatch.setattr(control_center, "write_atomic", fake_write_atomic)
    editor = _FakeEditor()
    win = SimpleNamespace(_highlight_yaml_error=lambda *a: None)

    control_center.SDYControlCenter._atomic_save(
        win, str(tmp_path / "profile.yaml"), content, editor
    )
    return calls, written, editor


def test_atomic_save_rejects_non_mapping_root(monkeypatch, tmp_path):
    """Regression: _atomic_save only called yaml_parser.load(content) to
    validate syntax, discarding the result -- a syntactically valid but
    non-mapping root (e.g. a bare list) reported "Configuration saved!"
    even though load_yaml_safe() degrades that exact shape to {} on the
    next load, silently dropping the whole profile (found via a
    full-file 9-agent review, 2026-08-31)."""
    calls, written, editor = _atomic_save_harness(
        monkeypatch, tmp_path, "- one\n- two\n"
    )

    assert not written
    assert calls and calls[0][0] == "critical"
    assert editor.document().modified is None


def test_atomic_save_accepts_mapping_root(monkeypatch, tmp_path):
    calls, written, editor = _atomic_save_harness(
        monkeypatch, tmp_path, "flags:\n  - -W 1280\n"
    )

    assert written
    assert calls and calls[0][0] == "information"
    assert editor.document().modified is False


def test_atomic_save_accepts_empty_content(monkeypatch, tmp_path):
    """An empty/comments-only document parses to None, not a dict -- must
    still save (matches beautify_yaml's own None-is-fine handling right
    above _atomic_save), not be rejected as "not a mapping"."""
    calls, written, _editor = _atomic_save_harness(
        monkeypatch, tmp_path, "# just a comment\n"
    )

    assert written
    assert calls and calls[0][0] == "information"


def test_atomic_save_reports_write_atomic_failure(monkeypatch, tmp_path):
    """Regression: write_atomic() used to be void (no return value at
    all), so _atomic_save always showed "Configuration saved!" and
    cleared the modified flag even when the C-Core write was refused or
    failed (symlink/FIFO at the tmp path, a short write, a failed
    rename). Now checks the bool return and reports a Save Error without
    clearing modified, so closeEvent's unsaved-changes guard still
    catches it too (found via a third full-file review pass, 2026-09-03)."""
    calls, written, editor = _atomic_save_harness(
        monkeypatch, tmp_path, "flags:\n  - -W 1280\n", write_succeeds=False
    )

    assert written
    assert calls and calls[0][0] == "critical"
    assert editor.document().modified is None
