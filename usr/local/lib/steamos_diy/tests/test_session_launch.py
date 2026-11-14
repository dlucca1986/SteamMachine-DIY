"""Tests for session_launch.py: shlex parsing of user config, and the
crash-detection / recovery-to-Desktop mechanism.

An unbalanced quote in a hand-edited `flags:`/`post_start_cmds:` entry
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


def test_game_mode_env_matches_real_steamos_agnostic_vars():
    """Pins some of the vars ported from Valve's gamescope-session (not a
    comparison with SteamOS itself). QT_IM_MODULE/
    GTK_IM_MODULE/XCURSOR_THEME are deliberately absent: their "steam"
    plugin/theme exists only inside the SteamOS image (see the comment
    above GAME_MODE_ENV)."""
    assert session_launch.GAME_MODE_ENV["QT_QPA_PLATFORM_THEME"] == "kde"
    assert session_launch.GAME_MODE_ENV["XCURSOR_SCALE"] == "256"
    assert session_launch.GAME_MODE_ENV["STEAM_MULTIPLE_XWAYLANDS"] == "1"
    assert session_launch.GAME_MODE_ENV["SRT_LOG_TO_JOURNAL"] == "1"
    assert session_launch.GAME_MODE_ENV["SRT_URLOPEN_PREFER_STEAM"] == "1"
    assert "QT_IM_MODULE" not in session_launch.GAME_MODE_ENV
    assert "GTK_IM_MODULE" not in session_launch.GAME_MODE_ENV
    assert "XCURSOR_THEME" not in session_launch.GAME_MODE_ENV


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


def test_get_post_start_cmds_returns_empty_for_non_list(set_ssot):
    """Same class of bug as the flags test above, for post_start_cmds:
    a truthy non-list value (e.g. `post_start_cmds: 1`) made the list
    comprehension raise TypeError uncaught."""
    set_ssot()

    assert session_launch._get_post_start_cmds({"post_start_cmds": 1}) == []
    assert (
        session_launch._get_post_start_cmds({"post_start_cmds": "notify"})
        == []
    )


def test_schedule_post_start_cmds_survives_malformed_entry(monkeypatch):
    """Matches _build_gamescope_args's degrade-via-str.split() behavior
    for the same kind of hand-edited field, instead of silently skipping
    the malformed command outright."""
    monkeypatch.setattr(session_launch.time, "sleep", lambda *_: None)
    spawned = []
    monkeypatch.setattr(
        session_launch,
        "spawn_native",
        lambda path, args: spawned.append(args),
    )

    session_launch._schedule_post_start_cmds(
        ['echo "unterminated', "notify-send hello"], 0.0, threading.Event()
    )

    # First entry degrades via str.split() and still runs; second is
    # well-formed and unaffected.
    assert spawned == [
        ["echo", '"unterminated'],
        ["notify-send", "hello"],
    ]


def test_schedule_post_start_cmds_clamps_negative_delay(monkeypatch):
    """A negative POST_START_DELAY (a plausible SSoT typo) used to reach
    time.sleep() raw, raising ValueError uncaught in this daemon thread
    -- silently dropping every post_start_cmds. Must clamp to 0 instead
    of skipping the commands."""
    slept = []
    monkeypatch.setattr(session_launch.time, "sleep", slept.append)
    spawned = []
    monkeypatch.setattr(
        session_launch,
        "spawn_native",
        lambda path, args: spawned.append(args),
    )

    session_launch._schedule_post_start_cmds(
        ["notify-send hi"], -1.0, threading.Event()
    )

    assert slept == [0]
    assert spawned == [["notify-send", "hi"]]


def test_schedule_post_start_cmds_survives_unexpected_exception(
    monkeypatch,
):
    """Regression: an unexpected exception in this daemon thread (e.g.
    spawn_native raising) ended it with no project log line at all; it
    must be caught and logged."""
    monkeypatch.setattr(session_launch.time, "sleep", lambda *_: None)

    def raising_spawn(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(session_launch, "spawn_native", raising_spawn)
    logged = []
    monkeypatch.setattr(
        session_launch,
        "jlog",
        lambda tag, msg, level="INFO": logged.append((tag, msg, level)),
    )

    session_launch._schedule_post_start_cmds(
        ["notify-send hi"], 0.0, threading.Event()
    )

    assert ("STEAM", "POST_START_CMDS_FAILED: boom", "ERROR") in logged


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
                [],
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
                [],
            )
    finally:
        timer.cancel()
        watchdog.cancel()
        signal.signal(signal.SIGTERM, previous)

    assert exc.value.code == 0
    assert time.monotonic() - start < 3.0
    assert started[0].returncode == -signal.SIGKILL


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
        [],
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


def test_run_session_skips_post_start_cmds_after_crash(
    tmp_path, set_ssot, monkeypatch
):
    """Regression: the post_start_cmds daemon thread had no link to
    session outcome -- it fired its configured commands even after
    _monitor_process detected an early crash and _handle_recovery had
    already switched to desktop."""
    set_ssot(POST_START_DELAY="0.05")
    spawned = []
    monkeypatch.setattr(
        session_launch,
        "spawn_native",
        lambda path, args: spawned.append(args),
    )
    proc_holder = [None]

    target, _ret_code = session_launch._run_session(
        ["/bin/true"],
        str(tmp_path / "next_session"),
        "steam",
        1.0,
        proc_holder,
        ["notify-send should-not-run"],
    )
    time.sleep(0.2)  # let the daemon thread's POST_START_DELAY elapse

    assert target == "desktop"
    assert not spawned


def test_run_session_stable_process_keeps_target(tmp_path):
    proc_holder = [None]

    target, ret_code = session_launch._run_session(
        ["/bin/sleep", "0.3"],
        str(tmp_path / "next_session"),
        "steam",
        0.1,
        proc_holder,
        [],
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
        [],
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
        [],
    )

    assert target == "steam"
    assert ret_code == 1
