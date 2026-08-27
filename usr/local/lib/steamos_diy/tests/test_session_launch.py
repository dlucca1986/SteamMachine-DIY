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
        ['echo "unterminated', "notify-send hello"], 0.0
    )

    # First entry degrades via str.split() and still runs; second is
    # well-formed and unaffected.
    assert spawned == [
        ["echo", '"unterminated'],
        ["notify-send", "hello"],
    ]


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
