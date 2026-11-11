"""Regression tests for control_center.py's _atomic_save: a YAML root that
isn't a mapping must be refused (load_yaml_safe() turns it into {} on
the next load), and write_atomic()'s bool result must be checked.

Split out of test_control_center.py, which is at pylint's
too-many-lines limit."""

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
    next load, silently dropping the whole profile."""
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
    """Regression: a refused or failed C-Core write (tmp path refused,
    short write, failed rename) must show a Save Error and keep the
    document modified, so closeEvent still warns — not "Configuration
    saved!"."""
    calls, written, editor = _atomic_save_harness(
        monkeypatch, tmp_path, "flags:\n  - -W 1280\n", write_succeeds=False
    )

    assert written
    assert calls and calls[0][0] == "critical"
    assert editor.document().modified is None


def test_atomic_save_survives_unbuildable_scalar(monkeypatch, tmp_path):
    """Regression: ruamel raises a plain ValueError, not YAMLError, for an
    unquoted impossible date. Uncaught in this Qt slot, PyQt6 aborted the
    whole Control Center (exit 134 on the real window) with the unsaved
    edit in it; it must be reported like any other syntax error."""
    calls, written, editor = _atomic_save_harness(
        monkeypatch, tmp_path, "released: 2026-02-30\n"
    )

    assert not written
    assert calls and calls[0][0] == "critical"
    assert editor.document().modified is None
