"""Regression tests for control_center.py's SSoT path resolution, combo
display-name parsing, and the pkexec re-entrancy guard.

None need a real QMainWindow/QApplication: _resolve_config_paths and
_extract_game_name_from_display are pure functions, and _run_pkexec only
touches self._pkexec_busy, self.statusBar() and self.process_finished —
a plain stand-in object exercises the exact same code path without
pulling Qt into the suite."""

from types import SimpleNamespace

import control_center

# ---------------------------------------------------------------------------
# _resolve_config_paths
# ---------------------------------------------------------------------------


def test_resolve_config_paths_honours_ssot_override(set_ssot, tmp_path):
    set_ssot(
        user_config=str(tmp_path / "custom" / "cfg.yaml"),
        games_conf_dir=str(tmp_path / "custom" / "games.d"),
    )

    conf_root, games_conf_dir = control_center._resolve_config_paths(
        tmp_path / "default"
    )

    assert conf_root == tmp_path / "custom"
    assert games_conf_dir == tmp_path / "custom" / "games.d"


def test_resolve_config_paths_falls_back_when_unset(set_ssot, tmp_path):
    set_ssot()
    default_root = tmp_path / "default"

    conf_root, games_conf_dir = control_center._resolve_config_paths(
        default_root
    )

    assert conf_root == default_root
    assert games_conf_dir == default_root / "games.d"


# ---------------------------------------------------------------------------
# _extract_game_name_from_display
# ---------------------------------------------------------------------------


def test_extract_game_name_strips_trailing_appid_suffix():
    assert (
        control_center._extract_game_name_from_display("Half-Life 2 (220)")
        == "Half-Life 2"
    )


def test_extract_game_name_keeps_parens_that_are_not_the_appid_suffix():
    raw = "Portal (Test Build) (730)"
    assert (
        control_center._extract_game_name_from_display(raw)
        == "Portal (Test Build)"
    )


def test_extract_game_name_returns_bare_name_unchanged():
    assert (
        control_center._extract_game_name_from_display("MyGame")
        == "MyGame"
    )


# ---------------------------------------------------------------------------
# _run_pkexec re-entrancy guard
# ---------------------------------------------------------------------------


# pylint: disable=invalid-name,too-few-public-methods,unused-argument
# camelCase names below must match Qt's own QStatusBar/QMainWindow API —
# _run_pkexec calls self.statusBar().showMessage(...) on the real window.
class _FakeStatusBar:
    def __init__(self):
        self.messages = []

    def showMessage(self, msg, timeout=0):
        self.messages.append(msg)


class _FakeWindow:
    """Stand-in for SDYControlCenter: only what _run_pkexec touches."""

    def __init__(self):
        self._pkexec_busy = False
        self.process_finished = SimpleNamespace(emit=lambda *a: None)
        self._status_bar = _FakeStatusBar()

    def statusBar(self):
        return self._status_bar
# pylint: enable=invalid-name,too-few-public-methods,unused-argument


def _fake_thread_factory(started):
    def _make_thread(*args, **kwargs):
        started.append((args, kwargs))
        return SimpleNamespace(start=lambda: None)

    return _make_thread


def test_run_pkexec_blocks_while_already_busy(monkeypatch):
    win = _FakeWindow()
    win._pkexec_busy = True
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert not started
    assert win._status_bar.messages


def test_run_pkexec_starts_when_idle(monkeypatch):
    win = _FakeWindow()
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert started
    assert win._pkexec_busy is True
    assert not win._status_bar.messages
