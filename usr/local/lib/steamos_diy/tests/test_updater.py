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
        self._download_ready = SimpleNamespace(emit=emitted.append)

    def _set_busy(self, label):
        self.button.setEnabled(False)
        self.button.setText(label)


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
