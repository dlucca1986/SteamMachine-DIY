"""Tests for session_launch.py: shlex parsing of user config, and the
crash-detection / recovery-to-Desktop mechanism.

An unbalanced quote in a hand-edited `flags:` entry
once raised ValueError out of run(): the session crashed until systemd's
restart limit failed the unit. The parsing tests pin the
degrade-gracefully behavior.

The crash-recovery tests drive `_monitor_process`/`_run_session` with
real short-lived subprocesses, unmocked: this is what
decides whether a crash lands on Desktop or on a black screen."""

import os
import signal
import subprocess
import threading
import time

import pytest
import session_launch
import utils


def test_build_gamescope_args_survives_malformed_flag(set_ssot):
    set_ssot()
    cfg = {
        "env_vars": {},
        "flags": ["-W 1280", '--nested-width="1280', "-H 800"],
    }

    args = session_launch._build_gamescope_args(cfg)

    assert "-W" in args and "1280" in args
    assert "-H" in args and "800" in args
    # Malformed entry degrades via str.split() instead of raising.
    assert '--nested-width="1280' in args


def test_build_gamescope_args_well_formed_unaffected(set_ssot):
    set_ssot()
    cfg = {"env_vars": {}, "flags": ["-W 1280 -H 800"]}

    args = session_launch._build_gamescope_args(cfg)

    assert args[0].endswith("gamescope")
    assert {"-W", "1280", "-H", "800"} <= set(args)
    assert "--" in args


def test_build_gamescope_args_survives_non_list_flags(set_ssot):
    """Regression: `flags` used `cfg.get("flags") or []`, which only
    substitutes the default for a falsy value. A truthy non-list typo
    (e.g. `flags: true` from a hand-edited config.yaml) made the loop
    raise TypeError uncaught in run() -- before _run_session's try/except
    even starts, crash-looping the systemd unit on every Game Mode boot
    attempt."""
    set_ssot()
    cfg = {"env_vars": {}, "flags": True}

    args = session_launch._build_gamescope_args(cfg)

    assert args[0].endswith("gamescope")


def test_build_gamescope_args_survives_a_bad_env_var_name(set_ssot):
    """Regression: an env_vars key the OS refuses (here one holding "=")
    raised out of _build_gamescope_args, which run() calls before
    _run_session's try/except even starts — same boot crash-loop as the
    non-list flags case above."""
    set_ssot()
    cfg = {"env_vars": {"MANGOHUD=1": 1, "SDY_TEST_OK": "yes"}}

    args = session_launch._build_gamescope_args(cfg)

    assert args[0].endswith("gamescope")
    assert os.environ["SDY_TEST_OK"] == "yes"


def test_game_mode_env_sets_only_what_gamescope_does_not():
    """Regression: GAME_MODE_ENV repeated variables gamescope -e already
    exports (and forced STEAM_MULTIPLE_XWAYLANDS=1 with one Xwayland),
    plus two nothing reads (QT_QPA_PLATFORM_THEME, XCURSOR_SCALE). See the
    comment above GAME_MODE_ENV for where the rest come from."""
    assert set(session_launch.GAME_MODE_ENV) == {
        "SRT_LOG_TO_JOURNAL",
        "VKD3D_SWAPCHAIN_LATENCY_FRAMES",
        "WINEDLLOVERRIDES",
    }


def test_raise_nofile_limit_raises_soft_below_target(monkeypatch):
    monkeypatch.setattr(
        session_launch.resource, "getrlimit", lambda _r: (1024, 524288)
    )
    calls = []
    monkeypatch.setattr(
        session_launch.resource,
        "setrlimit",
        lambda _r, pair: calls.append(pair),
    )

    session_launch._raise_nofile_limit(524288)

    assert calls == [(524288, 524288)]


def test_raise_nofile_limit_noop_when_already_at_target(monkeypatch):
    """A user/distro-set soft limit already at or above target must never
    be lowered."""
    monkeypatch.setattr(
        session_launch.resource, "getrlimit", lambda _r: (524288, 1048576)
    )
    monkeypatch.setattr(
        session_launch.resource,
        "setrlimit",
        lambda *_a: (_ for _ in ()).throw(
            AssertionError("must not be called")
        ),
    )

    session_launch._raise_nofile_limit(524288)


def test_raise_nofile_limit_caps_at_existing_hard_limit(monkeypatch):
    monkeypatch.setattr(
        session_launch.resource, "getrlimit", lambda _r: (1024, 2048)
    )
    calls = []
    monkeypatch.setattr(
        session_launch.resource,
        "setrlimit",
        lambda _r, pair: calls.append(pair),
    )

    session_launch._raise_nofile_limit(524288)

    assert calls == [(2048, 2048)]


def test_raise_nofile_limit_survives_setrlimit_failure(monkeypatch):
    monkeypatch.setattr(
        session_launch.resource, "getrlimit", lambda _r: (1024, 524288)
    )

    def _boom(*_a):
        raise OSError("nope")

    monkeypatch.setattr(session_launch.resource, "setrlimit", _boom)

    session_launch._raise_nofile_limit(524288)  # must not raise


# ---------------------------------------------------------------------------
# _monitor_process — crash vs. stable detection (real subprocesses)
# ---------------------------------------------------------------------------


def test_monitor_process_detects_early_exit_as_crash(tmp_path, set_ssot):
    set_ssot()
    with subprocess.Popen(["/bin/true"]) as proc:
        stable = session_launch._monitor_process(
            proc, 1.0, str(tmp_path / "next_session"), "steam"
        )

    assert stable is False


def test_monitor_process_detects_survival_as_stable(tmp_path, set_ssot):
    set_ssot()
    with subprocess.Popen(["/bin/sleep", "2"]) as proc:
        stable = session_launch._monitor_process(
            proc, 0.15, str(tmp_path / "next_session"), "steam"
        )
        assert stable is True
        assert proc.poll() is None  # still running — survived the window
        proc.kill()


def test_monitor_process_logs_when_write_atomic_fails(
    tmp_path, set_ssot, monkeypatch
):
    """Regression: a failed persist on the stable path (refused tmp path,
    failed rename) must be logged, not invisible. Patched at the utils
    level, where the write-or-log logic lives
    (utils.persist_next_session)."""
    set_ssot()
    monkeypatch.setattr(utils, "write_atomic", lambda *a: False)
    logged = []
    monkeypatch.setattr(
        utils,
        "jlog",
        lambda tag, msg, level="INFO": logged.append((tag, msg, level)),
    )
    with subprocess.Popen(["/bin/sleep", "2"]) as proc:
        session_launch._monitor_process(
            proc, 0.15, str(tmp_path / "next_session"), "steam"
        )
        proc.kill()

    assert any(
        "NEXT_SESSION_WRITE_FAILED" in msg and level == "ERROR"
        for _tag, msg, level in logged
    )


def test_term_handler_stops_stable_session_promptly(tmp_path):
    """Regression: the SIGTERM handler used to call a helper whose
    proc.wait() can never reap the child while the interrupted main
    thread is itself blocked in _run_session's untimed stable-phase
    proc.wait() (Popen's waitpid lock is held) — every stop ran out both
    5s wait windows and logged false SIGTERM/SIGKILL timeout lines.
    Runs on pytest's main thread because Python only delivers signals
    there, exactly like the real launcher."""
    proc_holder = [None]
    previous = signal.signal(
        signal.SIGTERM, session_launch._make_term_handler(proc_holder)
    )
    # Fires well after the 0.1s validation window, i.e. in the stable phase.
    timer = threading.Timer(0.6, os.kill, (os.getpid(), signal.SIGTERM))
    start = time.monotonic()
    try:
        timer.start()
        with pytest.raises(SystemExit) as exc:
            session_launch._run_session(
                ["/bin/sleep", "30"],
                str(tmp_path / "next_session"),
                "steam",
                0.1,
                proc_holder,
            )
    finally:
        timer.cancel()
        signal.signal(signal.SIGTERM, previous)

    assert exc.value.code == 0
    # Old code: two full wait windows. Fixed: child reaped right away.
    assert time.monotonic() - start < 2.0
    assert proc_holder[0] is None


def test_term_handler_kills_a_session_that_ignores_sigterm(
    tmp_path, monkeypatch
):
    """Regression: on a stop, leaving _run_session's `with Popen` block
    waited on the child with no limit, so a session ignoring SIGTERM kept
    the launcher hung until systemd's TimeoutStopSec, and then survived it
    (it lives in the logind session scope, not the unit's cgroup). Found
    with a transient unit using this unit's PAMName/KillMode. The child
    must now be killed after STOP_GRACE_SECONDS. A watchdog kills it after
    5s so the old code fails instead of hanging the suite."""
    monkeypatch.setattr(session_launch, "STOP_GRACE_SECONDS", 0.3)
    started = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):
        # Closed by _run_session's own `with` block.
        # pylint: disable-next=consider-using-with
        proc = real_popen(*args, **kwargs)
        started.append(proc)
        return proc

    monkeypatch.setattr(session_launch.subprocess, "Popen", recording_popen)
    proc_holder = [None]
    previous = signal.signal(
        signal.SIGTERM, session_launch._make_term_handler(proc_holder)
    )
    timer = threading.Timer(0.6, os.kill, (os.getpid(), signal.SIGTERM))
    watchdog = threading.Timer(
        5.0, lambda: started and started[0].kill()
    )
    start = time.monotonic()
    try:
        timer.start()
        watchdog.start()
        with pytest.raises(SystemExit) as exc:
            session_launch._run_session(
                ["/bin/sh", "-c", "trap '' TERM; exec sleep 30"],
                str(tmp_path / "next_session"),
                "steam",
                0.1,
                proc_holder,
            )
    finally:
        timer.cancel()
        watchdog.cancel()
        signal.signal(signal.SIGTERM, previous)

    assert exc.value.code == 0
    assert time.monotonic() - start < 3.0
    assert started[0].returncode == -signal.SIGKILL


def test_run_names_the_next_session_not_the_one_that_ended(
    tmp_path, set_ssot, monkeypatch
):
    """Regression: after a Desktop -> Game Mode switch the launcher wrote
    "Switching to Desktop..." on TTY1 (it named the session that had just
    ended; seen on the TV of lelo-gaming). The message must name what
    next_session holds when the session ends."""
    next_session = tmp_path / "next_session"
    next_session.write_text("desktop")
    set_ssot(next_session=str(next_session))
    shown = []
    monkeypatch.setattr(session_launch, "notify", shown.append)
    monkeypatch.setattr(session_launch.signal, "signal", lambda *_a: None)
    monkeypatch.setattr(session_launch.time, "sleep", lambda _s: None)

    def switch_to_steam(*_a):
        next_session.write_text("steam")  # what session_select writes
        return "desktop", 0

    monkeypatch.setattr(session_launch, "_run_session", switch_to_steam)

    with pytest.raises(SystemExit) as exc:
        session_launch.run()

    assert exc.value.code == 75
    assert shown[-1] == "Switching to Game Mode..."


# ---------------------------------------------------------------------------
# _run_session — end-to-end crash-recovery integration
# ---------------------------------------------------------------------------


def test_run_session_crash_recovers_to_desktop(tmp_path):
    proc_holder = [None]

    target, ret_code = session_launch._run_session(
        ["/bin/true"],
        str(tmp_path / "next_session"),
        "steam",
        1.0,
        proc_holder,
    )

    assert target == "desktop"
    assert ret_code == 0
    assert proc_holder[0] is None  # cleared in the finally block


def test_handle_recovery_logs_when_write_atomic_fails(monkeypatch):
    """Regression: this write persists the Desktop fallback after a crash;
    if it fails silently, the next boot re-reads whatever next_session
    held, possibly the target that just crashed. Must be logged. Patched
    at the utils level (utils.persist_next_session)."""
    monkeypatch.setattr(utils, "write_atomic", lambda *a: False)
    logged = []
    monkeypatch.setattr(
        utils,
        "jlog",
        lambda tag, msg, level="INFO": logged.append((tag, msg, level)),
    )
    session_launch._handle_recovery("/tmp/does-not-matter")

    assert any(
        "NEXT_SESSION_WRITE_FAILED" in msg and level == "ERROR"
        for _tag, msg, level in logged
    )


def test_run_session_stable_process_keeps_target(tmp_path):
    proc_holder = [None]

    target, ret_code = session_launch._run_session(
        ["/bin/sleep", "0.3"],
        str(tmp_path / "next_session"),
        "steam",
        0.1,
        proc_holder,
    )

    assert target == "steam"
    assert ret_code == 0


def test_run_session_missing_binary_keeps_initial_target(tmp_path):
    proc_holder = [None]

    target, ret_code = session_launch._run_session(
        ["/nonexistent/binary_xyz"],
        str(tmp_path / "next_session"),
        "steam",
        1.0,
        proc_holder,
    )

    assert target == "steam"
    assert ret_code == 127


def test_run_session_survives_embedded_null_byte_in_argv(
    tmp_path, monkeypatch
):
    """Regression: subprocess.Popen raises ValueError, not OSError, for a
    malformed argv element (e.g. an embedded null byte from a
    hand-edited flags/env_vars entry) -- uncaught by the previous
    except OSError, crashing the whole session launcher instead of
    degrading like every other malformed-config path in this file."""

    def raising_popen(*_a, **_k):
        raise ValueError("embedded null byte")

    monkeypatch.setattr(session_launch.subprocess, "Popen", raising_popen)
    proc_holder = [None]

    target, ret_code = session_launch._run_session(
        ["game", "a\x00b"],
        str(tmp_path / "next_session"),
        "steam",
        1.0,
        proc_holder,
    )

    assert target == "steam"
    assert ret_code == 1
