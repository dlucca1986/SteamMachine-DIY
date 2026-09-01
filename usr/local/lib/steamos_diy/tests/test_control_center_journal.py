"""Regression test for control_center.py's refresh_detected_games journalctl
invocation.

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
