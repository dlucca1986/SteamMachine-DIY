"""Regression test for updater.py's download worker exception backstop.

_download's worker previously had no try/except at all -- an uncaught
exception from download_release() (e.g. the empty-tarball
FileNotFoundError pinned in test_utils.py) killed the daemon thread
silently before emitting anything, exactly like the validate_config bug
already fixed in control_center.py: stderr is /dev/null when the app is
launched detached, so nothing is printed and the button stays disabled
forever with no error shown.

No real QApplication/QPushButton is needed: _download only touches
self.button, self._dest_root and self._download_ready, so a plain
stand-in exercises the exact same code path."""

from pathlib import Path
from types import SimpleNamespace

import updater


class _FakeButton:  # pylint: disable=too-few-public-methods
    def __init__(self):
        self.enabled = True
        self.text = ""

    def setEnabled(self, value):  # pylint: disable=invalid-name
        self.enabled = value

    def setText(self, value):  # pylint: disable=invalid-name
        self.text = value


class _FakeManager:  # pylint: disable=too-few-public-methods
    def __init__(self, emitted):
        self.button = _FakeButton()
        self._dest_root = "/unused"
        self._win = SimpleNamespace()
        self._check_ready = SimpleNamespace(emit=emitted.append)
        self._download_ready = SimpleNamespace(emit=emitted.append)

    def _set_busy(self, label):
        self.button.setEnabled(False)
        self.button.setText(label)

    def _set_idle(self):
        self.button.setEnabled(True)
        self.button.setText("idle")


class _FakeMessageBox:  # pylint: disable=too-few-public-methods
    def __init__(self, calls):
        self._calls = calls

    def warning(self, *args):
        self._calls.append(("warning", args))

    def information(self, *args):
        self._calls.append(("information", args))

    def critical(self, *args):
        self._calls.append(("critical", args))


def _sync_thread_factory():
    def _make_thread(*_args, target, **_kwargs):
        return SimpleNamespace(start=target)

    return _make_thread


def test_download_worker_survives_unexpected_exception(monkeypatch):
    monkeypatch.setattr(
        updater.threading, "Thread", _sync_thread_factory()
    )

    def raising_download_release(*_a, **_k):
        raise FileNotFoundError("boom")

    monkeypatch.setattr(
        updater, "download_release", raising_download_release
    )

    emitted = []
    mgr = _FakeManager(emitted)
    info = SimpleNamespace(version="9.9.9")

    updater.UpdateManager._download(mgr, info)

    assert emitted == [None]


def test_download_worker_survives_emit_on_torn_down_window(monkeypatch):
    """Regression: emit() itself sat outside the worker's try/except --
    if the Control Center window is closed while a download is still in
    flight, Qt tears down self._download_ready and .emit() raises
    RuntimeError ("wrapped C/C++ object has been deleted"), uncaught."""
    monkeypatch.setattr(
        updater.threading, "Thread", _sync_thread_factory()
    )
    monkeypatch.setattr(
        updater, "download_release", lambda *_a, **_k: None
    )

    def raising_emit(_result):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    mgr = _FakeManager([])
    mgr._download_ready = SimpleNamespace(emit=raising_emit)
    info = SimpleNamespace(version="9.9.9")

    updater.UpdateManager._download(mgr, info)  # must not raise


def test_check_worker_survives_emit_on_torn_down_window(monkeypatch):
    monkeypatch.setattr(
        updater.threading, "Thread", _sync_thread_factory()
    )
    monkeypatch.setattr(
        updater, "check_latest_release", lambda: None
    )

    def raising_emit(_result):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    mgr = _FakeManager([])
    mgr._check_ready = SimpleNamespace(emit=raising_emit)

    updater.UpdateManager.check(mgr)  # must not raise


def test_on_download_shows_error_when_konsole_fails_to_spawn(monkeypatch):
    """Regression: spawn_native()'s return value (0 on failure, per its
    own documented contract) was discarded -- if Konsole fails to
    launch, the user previously saw "Installing Update..." and then
    nothing, with no indication the update never actually started."""
    calls = []
    monkeypatch.setattr(updater, "QMessageBox", _FakeMessageBox(calls))
    monkeypatch.setattr(
        updater, "verify_file_sha256", lambda *_a, **_k: True
    )
    monkeypatch.setattr(updater, "spawn_native", lambda *_a, **_k: 0)

    mgr = _FakeManager([])
    result = (Path("/tmp/unused"), "0" * 64)

    updater.UpdateManager._on_download(mgr, result)

    assert any(kind == "critical" for kind, _args in calls)


def test_on_download_treats_verify_oserror_as_verification_failed(
    monkeypatch,
):
    """Regression: verify_file_sha256()/_sha256_file() have no try/except
    of their own -- if install_sh is deleted/inaccessible in the TOCTOU
    gap this re-check exists to narrow, open() raises OSError uncaught
    inside a Qt main-thread slot instead of failing closed like the
    surrounding logic intends."""
    calls = []
    monkeypatch.setattr(updater, "QMessageBox", _FakeMessageBox(calls))

    def raising_verify(*_a, **_k):
        raise FileNotFoundError("install.sh vanished")

    monkeypatch.setattr(updater, "verify_file_sha256", raising_verify)
    spawned = []
    monkeypatch.setattr(
        updater, "spawn_native", lambda *a, **_k: spawned.append(a) or 1
    )

    mgr = _FakeManager([])
    result = (Path("/tmp/unused"), "0" * 64)

    updater.UpdateManager._on_download(mgr, result)  # must not raise

    assert not spawned
    assert calls[-1][0] == "critical"
