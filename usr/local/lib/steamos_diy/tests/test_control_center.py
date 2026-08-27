"""Regression tests for control_center.py's SSoT path resolution, combo
display-name parsing, the pkexec re-entrancy guard, and (CLAUDE.md review
checklist item 14) the subprocess timeout discipline of the two
background workers that talk to journalctl/pkexec.

None need a real QMainWindow/QApplication: _resolve_config_paths and
_extract_game_name_from_display are pure functions, and _run_pkexec /
refresh_detected_games only touch self._pkexec_busy, self.statusBar(),
self.combo_games and their signal's .emit() — a plain stand-in object
exercises the exact same code path without pulling Qt into the suite."""

import subprocess
from types import SimpleNamespace

import control_center
import pytest

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


def test_resolve_config_paths_fallback_follows_games_conf_subdir_constant(
    set_ssot, tmp_path, monkeypatch
):
    """Pins that the games_conf_dir fallback derives from the shared
    utils.GAMES_CONF_SUBDIR constant (also used by
    utils.default_games_conf_dir() for sdy.py) rather than an
    independently hardcoded "games.d" literal — the exact class of
    divergence bug CLAUDE.md's 2026-08-26 audit already found once for
    this same concept."""
    set_ssot()
    monkeypatch.setattr(control_center, "GAMES_CONF_SUBDIR", "custom.d")
    default_root = tmp_path / "default"

    _, games_conf_dir = control_center._resolve_config_paths(default_root)

    assert games_conf_dir == default_root / "custom.d"


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


class _FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):  # pylint: disable=invalid-name
        self.enabled = value


class _FakeWindow:
    """Stand-in for SDYControlCenter: only what _run_pkexec touches."""

    def __init__(self):
        self._pkexec_busy = {}
        self.process_finished = SimpleNamespace(emit=lambda *a: None)
        self._status_bar = _FakeStatusBar()
        self._service_status_busy = False
        self.service_status_ready = SimpleNamespace(emit=lambda *a: None)
        self._lock_key_buttons = {}
        self.pkexec_lock_released = SimpleNamespace(emit=lambda *a: None)

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
    win._pkexec_busy = {"files": True}
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
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
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert started
    assert win._pkexec_busy == {"files": True}
    assert not win._status_bar.messages


def test_run_pkexec_lock_keys_are_independent(monkeypatch):
    """Pins the fix for the too-coarse shared guard: a busy "files" lock
    (Backup/Restore) must not block an unrelated "vacuum" operation, and
    vice versa — they don't share any target file."""
    win = _FakeWindow()
    win._pkexec_busy = {"files": True}
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="vacuum",
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert started
    assert win._pkexec_busy == {"files": True, "vacuum": True}
    assert not win._status_bar.messages


def test_run_pkexec_disables_buttons_for_its_lock_key(monkeypatch):
    """Regression: starting a privileged operation must visually disable
    the button(s) tied to its lock_key — previously the only feedback for
    a double-click was a 3s status-bar toast, unlike updater.py's
    _set_busy pattern (CLAUDE.md checklist item 15; code-review finding,
    2026-08-27)."""
    win = _FakeWindow()
    btn = _FakeButton()
    win._lock_key_buttons = {"files": [btn]}
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert started
    assert btn.enabled is False


def test_run_pkexec_emits_lock_released_on_success(monkeypatch):
    """The worker thread must never touch widgets directly — it emits
    pkexec_lock_released so the main-thread slot can re-enable buttons."""
    win = _FakeWindow()
    released = []
    win.pkexec_lock_released = SimpleNamespace(
        emit=released.append
    )
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    monkeypatch.setattr(
        control_center.subprocess, "run", lambda *a, **k: None
    )

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert released == ["files"]


def test_run_pkexec_does_not_emit_lock_released_on_sticky_timeout(
    monkeypatch,
):
    """A sticky timeout must leave the button disabled — the underlying
    script may still be running, matching _pkexec_busy staying True."""
    win = _FakeWindow()
    released = []
    win.pkexec_lock_released = SimpleNamespace(
        emit=released.append
    )
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="pkexec", timeout=300)

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="e",
        err_msg="m2",
    )

    assert not released


def test_on_pkexec_lock_released_reenables_only_matching_buttons():
    win = _FakeWindow()
    files_btn = _FakeButton()
    files_btn.enabled = False
    vacuum_btn = _FakeButton()
    vacuum_btn.enabled = False
    win._lock_key_buttons = {"files": [files_btn], "vacuum": [vacuum_btn]}

    control_center.SDYControlCenter._on_pkexec_lock_released(win, "files")

    assert files_btn.enabled is True
    assert vacuum_btn.enabled is False


def test_refresh_service_status_skips_tick_while_busy(monkeypatch):
    """Regression: _service_status_busy must block an overlapping poll —
    get_service_status's subprocess timeout (5s) exceeds the QTimer
    interval that calls it (4s), so without this guard a slow systemctl
    call would let ticks pile up instead of just skipping one
    (code-review finding, 2026-08-27)."""
    win = _FakeWindow()
    win._service_status_busy = True
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter._refresh_service_status(win)

    assert not started


def test_refresh_service_status_resets_guard_after_completion(monkeypatch):
    win = _FakeWindow()
    emitted = []
    win.service_status_ready = SimpleNamespace(
        emit=lambda *a: emitted.append(a)
    )
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    monkeypatch.setattr(
        control_center, "get_service_status", lambda: "status"
    )

    control_center.SDYControlCenter._refresh_service_status(win)

    assert emitted == [("status",)]
    assert win._service_status_busy is False


# ---------------------------------------------------------------------------
# subprocess timeout discipline (CLAUDE.md review checklist item 14) —
# _run_pkexec's own worker, and refresh_detected_games's journalctl scan.
# ---------------------------------------------------------------------------


def _sync_thread_factory():
    """Like _fake_thread_factory, but actually runs the worker inline —
    needed to observe what the try/except inside it does."""

    def _make_thread(*_args, target, **_kwargs):
        return SimpleNamespace(start=target)

    return _make_thread


def test_run_pkexec_reports_timeout_distinctly(monkeypatch):
    """A timed-out pkexec may have left a privileged grandchild running,
    so _pkexec_busy must stay set (only a restart clears it) rather than
    being reset — see the TimeoutExpired branch's own comment."""
    win = _FakeWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    emitted = []
    win.process_finished = SimpleNamespace(
        emit=lambda *a: emitted.append(a)
    )

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="pkexec", timeout=300)

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="ERR",
        err_msg="generic failure",
    )

    assert len(emitted) == 1
    title, msg, is_error = emitted[0]
    assert title == "ERR"
    assert "timed out" in msg.lower()
    assert is_error is True
    assert win._pkexec_busy == {"files": True}


def test_run_pkexec_non_sticky_timeout_resets_guard(monkeypatch):
    """Regression: sticky_on_timeout=False (journal vacuum) must reset the
    guard on a timeout instead of leaving it permanently stuck — a timeout
    there is far more likely to be a slow polkit prompt than a wedged
    operation, and vacuum runs are idempotent (code-review finding,
    2026-08-27)."""
    win = _FakeWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    emitted = []
    win.process_finished = SimpleNamespace(
        emit=lambda *a: emitted.append(a)
    )

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="pkexec", timeout=300)

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="vacuum",
        ok_title="t",
        ok_msg="m",
        err_title="ERR",
        err_msg="generic failure",
        sticky_on_timeout=False,
    )

    assert len(emitted) == 1
    title, msg, is_error = emitted[0]
    assert title == "ERR"
    assert "timed out" in msg.lower()
    assert is_error is True
    assert win._pkexec_busy == {"vacuum": False}


def test_run_pkexec_still_reports_called_process_error_generically(
    monkeypatch,
):
    """Guards the pre-existing branch: adding the TimeoutExpired handler
    above it must not swallow a plain CalledProcessError differently."""
    win = _FakeWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    emitted = []
    win.process_finished = SimpleNamespace(
        emit=lambda *a: emitted.append(a)
    )

    def fake_run(*_a, **_k):
        raise subprocess.CalledProcessError(1, "pkexec")

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter._run_pkexec(
        win,
        ["/bin/true"],
        lock_key="files",
        ok_title="t",
        ok_msg="m",
        err_title="ERR",
        err_msg="generic failure",
    )

    assert emitted == [("ERR", "generic failure", True)]


def test_run_pkexec_resets_guard_on_an_unforeseen_exception(monkeypatch):
    """Regression: the guard must reset on ANY outcome other than a
    timeout, not just the three explicitly-caught exception types —
    a `finally` guarantees this even for an exception this code doesn't
    know to expect (e.g. a cross-thread Qt signal emit failing)."""
    win = _FakeWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )

    def fake_run(*_a, **_k):
        return None

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)
    win.process_finished = SimpleNamespace(
        emit=lambda *a: (_ for _ in ()).throw(RuntimeError("wrapped C/C++"))
    )

    with pytest.raises(RuntimeError):
        control_center.SDYControlCenter._run_pkexec(
            win,
            ["/bin/true"],
            lock_key="files",
            ok_title="t",
            ok_msg="m",
            err_title="ERR",
            err_msg="generic failure",
        )

    assert win._pkexec_busy == {"files": False}


class _FakeCombo:  # pylint: disable=too-few-public-methods
    def setPlaceholderText(self, text):  # pylint: disable=invalid-name
        pass


class _FakeGamesWindow:  # pylint: disable=too-few-public-methods
    """Stand-in for SDYControlCenter: only what refresh_detected_games
    touches."""

    def __init__(self):
        self.combo_games = _FakeCombo()
        self.games_detected = SimpleNamespace(emit=lambda *a: None)
        self._scan_games_busy = False


def test_refresh_detected_games_passes_a_timeout(monkeypatch):
    """The except clause in refresh_detected_games already caught
    SubprocessError before the CLAUDE.md item-14 fix — timeout= itself
    is the only thing that actually changed, so this pins that directly
    rather than exercising the (already-covered) recovery path."""
    win = _FakeGamesWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return control_center.subprocess.CompletedProcess(
            cmd, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter.refresh_detected_games(win)

    assert captured.get("timeout") is not None


def test_refresh_detected_games_skips_scan_while_busy(monkeypatch):
    """Regression: a second click while a scan is in flight must not
    start a new one — the previous, unguarded version let two scans
    overlap, and whichever journalctl call finished last would silently
    overwrite the other's (possibly fresher) result (CLAUDE.md checklist
    item 17; code-review finding, 2026-08-27)."""
    win = _FakeGamesWindow()
    win._scan_games_busy = True
    started = []
    monkeypatch.setattr(
        control_center.threading, "Thread", _fake_thread_factory(started)
    )

    control_center.SDYControlCenter.refresh_detected_games(win)

    assert not started


def test_refresh_detected_games_resets_guard_after_completion(monkeypatch):
    win = _FakeGamesWindow()
    monkeypatch.setattr(
        control_center.threading, "Thread", _sync_thread_factory()
    )

    def fake_run(cmd, **_kwargs):
        return control_center.subprocess.CompletedProcess(
            cmd, 0, stdout="", stderr=""
        )

    monkeypatch.setattr(control_center.subprocess, "run", fake_run)

    control_center.SDYControlCenter.refresh_detected_games(win)

    assert win._scan_games_busy is False
