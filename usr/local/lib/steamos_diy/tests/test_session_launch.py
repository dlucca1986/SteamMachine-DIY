"""Tests for session_launch.py: shlex parsing of user config, and the
crash-detection / recovery-to-Desktop mechanism.

Before the fix, an unbalanced quote in a hand-edited `flags:`/
`post_start_cmds:` entry raised ValueError out of run() with nothing
catching it — the whole Game Mode session crashed instead of falling
back to Desktop, and systemd's restart limit eventually took the unit
to `failed`. Those tests pin the degrade-gracefully behavior instead.

The crash-recovery tests below cover `_monitor_process`/
`_terminate_gracefully`/`_run_session` with real short-lived
subprocesses (no mocking of the process lifecycle itself) because this
is the single mechanism that decides whether the machine self-heals to
Desktop after a crash or is left with a black screen — arguably the
most safety-critical behavior in the whole project, and previously
untested."""

import subprocess
import threading
import time

import session_launch


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
    attempt (found via a full-file 9-agent review, 2026-08-31)."""
    set_ssot()
    cfg = {"env_vars": {}, "flags": True}

    args = session_launch._build_gamescope_args(cfg)

    assert args[0].endswith("gamescope")


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
    for the identical class of hand-edited field, instead of silently
    skipping the malformed command outright (code-review finding,
    2026-08-27: the two fields had diverged to different error-handling
    despite this file's own docstring already documenting one shared
    degrade-gracefully contract for both)."""
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
    -- silently dropping every post_start_cmds with no diagnostic (found
    via a full-file 9-agent review, 2026-08-31). Must clamp to 0 instead
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
    """Regression: no try/except at all previously wrapped this daemon
    thread's body -- any unexpected exception (e.g. spawn_native raising)
    vanished silently (stderr is /dev/null when the app is launched
    detached)."""
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
    """Regression: write_atomic() used to be void, so a persist failure
    on the stable path (symlink/FIFO at the tmp path, a failed rename)
    was invisible here (found via a third full-file review pass,
    2026-09-03)."""
    set_ssot()
    monkeypatch.setattr(session_launch, "write_atomic", lambda *a: False)
    logged = []
    monkeypatch.setattr(
        session_launch,
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


# ---------------------------------------------------------------------------
# _terminate_gracefully — SIGTERM, then SIGKILL escalation on timeout
# ---------------------------------------------------------------------------


def test_terminate_gracefully_stops_a_responsive_process(set_ssot):
    set_ssot(TERM_TIMEOUT="2.0")
    with subprocess.Popen(["/bin/sleep", "10"]) as proc:
        session_launch._terminate_gracefully(proc)

        assert proc.returncode is not None


def test_terminate_gracefully_escalates_to_sigkill(set_ssot):
    # Ignores SIGTERM outright, forcing the SIGKILL escalation path.
    # TERM_TIMEOUT shrunk so the test doesn't wait out a real 5s default.
    set_ssot(TERM_TIMEOUT="0.2")
    with subprocess.Popen(
        ["/bin/sh", "-c", "trap '' TERM; sleep 5"]
    ) as proc:
        session_launch._terminate_gracefully(proc)

        assert proc.returncode is not None


def test_terminate_gracefully_returns_even_if_still_alive_after_sigkill(
    set_ssot,
):
    """Regression: a process stuck in uninterruptible I/O (D-state) can
    outlive even SIGKILL. The final proc.wait() must be bounded so this
    function returns instead of blocking forever — systemd's own
    KillMode=mixed + TimeoutStopSec backstop handles the cgroup regardless
    (code-review finding, 2026-08-27)."""
    set_ssot(TERM_TIMEOUT="0.05")
    calls = {"kill": 0}

    class _StuckProc:
        returncode = None

        def terminate(self):
            pass

        def kill(self):
            calls["kill"] += 1

        def wait(self, timeout=None):  # pylint: disable=unused-argument
            raise subprocess.TimeoutExpired(cmd="stuck", timeout=timeout)

    # Must return promptly (not hang) even though wait() never succeeds.
    session_launch._terminate_gracefully(_StuckProc())

    assert calls["kill"] == 1


# ---------------------------------------------------------------------------
# _run_session — end-to-end crash-recovery integration
# ---------------------------------------------------------------------------


def test_run_session_crash_recovers_to_desktop(tmp_path, set_ssot):
    set_ssot(TERM_TIMEOUT="1.0")
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


def test_handle_recovery_logs_when_write_atomic_fails(set_ssot, monkeypatch):
    """Regression: this is the single most important write_atomic() call
    in the file (persists the desktop fallback after a crash) -- a
    silent failure here used to mean the next boot could re-read
    whatever next_session already held, possibly the same target that
    just crashed (found via a third full-file review pass, 2026-09-03)."""
    set_ssot(TERM_TIMEOUT="1.0")
    monkeypatch.setattr(session_launch, "write_atomic", lambda *a: False)
    logged = []
    monkeypatch.setattr(
        session_launch,
        "jlog",
        lambda tag, msg, level="INFO": logged.append((tag, msg, level)),
    )
    with subprocess.Popen(["/bin/true"]) as proc:
        proc.wait()
        session_launch._handle_recovery(proc, "/tmp/does-not-matter")

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
    already switched to desktop (found via the second full-file review
    pass, 2026-09-02)."""
    set_ssot(TERM_TIMEOUT="1.0", POST_START_DELAY="0.05")
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


def test_run_session_stable_process_keeps_target(tmp_path, set_ssot):
    set_ssot(TERM_TIMEOUT="1.0")
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
    degrading like every other malformed-config path in this file
    (found via the second full-file review pass, 2026-09-02)."""

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
