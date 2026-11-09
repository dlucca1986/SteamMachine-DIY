"""Smoke test: drive the REAL Control Center window, offscreen.

Every other control_center test binds single methods onto minimal fakes
(no QApplication), which is fast and precise but structurally blind to
what only shows up when the whole window actually runs: a Qt API that
changed under a PyQt upgrade, a slot raising on real widget state, a
background worker dying. On 2026-11-09 an ad-hoc offscreen run of the
real window was the only thing that caught the invisible game-selector
hints (and the wrong 2.1.9 description of the Scan History bug), after
many static reads had missed them — this keeps that run in the suite.

Real: QApplication (offscreen platform), SDYControlCenter, its event
loop, every tab, a full Scan History round-trip through its worker
thread and the games_detected signal. Hermetic: HOME points at a temp
dir seeded with the skel config.yaml, the SSoT is already isolated by
conftest, and subprocess.run returns an empty result instead of calling
systemctl/journalctl, so the run is identical on this machine and CI.

Fails on: any exception escaping a Qt slot (sys.excepthook — PyQt6
would otherwise abort the process on one) or a worker thread
(threading.excepthook), and any dialog opening.
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# PyQt6's compiled C-extension bindings aren't visible to pylint's static
# import resolution (same suppression as control_center.py's imports).
# pylint: disable-next=no-name-in-module
from PyQt6.QtWidgets import QApplication, QMessageBox

_SKEL_CONFIG = (
    Path(__file__).resolve().parents[5]
    / "etc/skel/.config/steamos_diy/config.yaml"
)
_WAIT_SECONDS = 5.0


@pytest.fixture(scope="module")
def qapp():
    # Read when the QApplication is created, not at import — so it's set
    # here, and only if the caller didn't already choose a platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def captured(monkeypatch, tmp_path):
    """Isolate the environment and collect every failure signal."""
    home = tmp_path / "home"
    conf_dir = home / ".config/steamos_diy"
    (conf_dir / "games.d").mkdir(parents=True)
    shutil.copy(_SKEL_CONFIG, conf_dir / "config.yaml")
    # One saved profile: the scan's combo update must surface it, which
    # proves the worker -> games_detected -> slot round trip really ran.
    (conf_dir / "games.d/Alpha.yaml").write_text("env_vars:\n")
    monkeypatch.setenv("HOME", str(home))

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, *a, **kw: subprocess.CompletedProcess(args, 0, "", ""),
    )

    problems: list[str] = []
    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda typ, val, _tb: problems.append(f"slot: {typ.__name__}: {val}"),
    )
    monkeypatch.setattr(
        threading,
        "excepthook",
        lambda a: problems.append(
            f"thread: {a.exc_type.__name__}: {a.exc_value}"
        ),
    )
    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(
            QMessageBox,
            name,
            staticmethod(
                lambda *a, _n=name, **_k: problems.append(
                    f"dialog {_n}: {a[1:3]}"
                )
                or QMessageBox.StandardButton.Cancel
            ),
        )
    return problems


def _pump_until(app, done):
    """Run the event loop until done() holds (or fail after a timeout)."""
    deadline = time.monotonic() + _WAIT_SECONDS
    while time.monotonic() < deadline:
        app.processEvents()
        if done():
            return
        time.sleep(0.01)
    pytest.fail("timed out waiting for the Control Center's workers")


def _workers_idle(win):
    return not (
        win._service_status_busy
        or win._scan_games_busy
        or win._logs_busy
    )


# pylint: disable-next=redefined-outer-name
def test_control_center_runs_every_tab_and_a_scan(qapp, captured):
    # Imported here, not at module level: conftest's ctypes patch and the
    # autouse SSoT isolation must be in place before utils is loaded.
    import control_center  # pylint: disable=import-outside-toplevel

    win = control_center.SDYControlCenter()
    try:
        _pump_until(qapp, lambda: _workers_idle(win))

        for index in range(win.tabs.count()):
            win.tabs.setCurrentIndex(index)
            _pump_until(qapp, lambda: _workers_idle(win))

        win.refresh_detected_games()
        _pump_until(qapp, lambda: _workers_idle(win))

        assert win.global_editor.toPlainText()  # seeded config.yaml loaded
        assert not win.global_editor.document().isModified()
        assert win.combo_games.count() == 1  # scan round trip happened
        assert win.combo_games.currentText() == ""  # nothing auto-picked
    finally:
        win._service_timer.stop()
        win.close()

    assert captured == []
