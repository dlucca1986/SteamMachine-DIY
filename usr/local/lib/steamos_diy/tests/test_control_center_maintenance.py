"""Regression tests for control_center.py's Maintenance-tab actions
(edit_ssot_privileged, export_support_log).

Split out of test_control_center.py (which was already at the pylint
too-many-lines ceiling) rather than trimming other tests to make room."""

from pathlib import Path
from types import SimpleNamespace

import control_center
from test_control_center import _sync_thread_factory


class _FakeMessageBox:  # pylint: disable=too-few-public-methods
    def __init__(self, calls):
        self._calls = calls

    def critical(self, *args):
        self._calls.append(("critical", args))


# pylint: disable-next=too-few-public-methods
class _FakeMaintenanceWindow:
    """Binds the real _launch_or_warn/edit_ssot_privileged so the actual
    wiring between them is exercised, not just each in isolation."""

    _launch_or_warn = control_center.SDYControlCenter._launch_or_warn
    edit_ssot_privileged = (
        control_center.SDYControlCenter.edit_ssot_privileged
    )


# ---------------------------------------------------------------------------
# edit_ssot_privileged — routed through _launch_or_warn/spawn_native like
# every other Maintenance-tab button, instead of its own bare Popen (which
# didn't detach via start_new_session=True the way spawn_native does)
# ---------------------------------------------------------------------------


def test_edit_ssot_privileged_uses_spawn_native(monkeypatch):
    """Regression: edit_ssot_privileged called subprocess.Popen directly,
    unlike the other 3 Maintenance-tab buttons (Switch to Steam/Konsole/
    Browse Config) which all route through spawn_native's
    start_new_session=True detachment. Kate/KWrite stayed attached to
    Control Center's own process group instead (found via the second
    full-file review pass, 2026-09-02)."""
    calls = []
    monkeypatch.setattr(control_center.os.path, "exists", lambda _p: False)
    monkeypatch.setattr(
        control_center, "spawn_native", lambda *a: calls.append(a) or 1234
    )
    win = SimpleNamespace(_launch_or_warn=control_center.spawn_native)

    control_center.SDYControlCenter.edit_ssot_privileged(win)

    assert calls == [
        ("/usr/bin/kwrite", ["/usr/bin/kwrite", control_center.SSOT_CONF_PATH])
    ]


def test_edit_ssot_privileged_reports_spawn_failure(monkeypatch):
    calls = []
    monkeypatch.setattr(control_center.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(control_center, "spawn_native", lambda *a: 0)
    monkeypatch.setattr(
        control_center, "QMessageBox", _FakeMessageBox(calls)
    )
    win = _FakeMaintenanceWindow()

    win.edit_ssot_privileged()

    assert calls and calls[0][0] == "critical"


# ---------------------------------------------------------------------------
# export_support_log — re-entrancy guard (two fast clicks on the SAME
# destination could otherwise race two workers writing to that file)
# ---------------------------------------------------------------------------


def test_export_support_log_skips_while_already_busy():
    """Regression: export_support_log had no re-entrancy guard at all,
    unlike refresh_detected_games/load_logs's established _busy pattern
    (found via the second full-file review pass, 2026-09-02)."""
    win = SimpleNamespace(_export_busy=True)

    # Must return before ever touching QFileDialog/threading — no
    # AttributeError on either (neither is set on this bare fake) means
    # the guard returned early as intended.
    control_center.SDYControlCenter.export_support_log(win)


def test_export_support_log_resets_guard_after_completion(
    monkeypatch, tmp_path
):
    dest = str(tmp_path / "support.log")
    monkeypatch.setattr(
        control_center.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (dest, ""),
    )
    monkeypatch.setattr(
        control_center, "_build_support_report", lambda: "report"
    )
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    win = SimpleNamespace(
        _export_busy=False,
        process_finished=SimpleNamespace(emit=lambda *a: None),
    )

    control_center.SDYControlCenter.export_support_log(win)

    assert win._export_busy is False
    assert Path(dest).read_text(encoding="utf-8") == "report"
