"""Regression tests for session_launch.py's shlex parsing of user config.

Before the fix, an unbalanced quote in a hand-edited `flags:`/
`post_start_cmds:` entry raised ValueError out of run() with nothing
catching it — the whole Game Mode session crashed instead of falling
back to Desktop, and systemd's restart limit eventually took the unit
to `failed`. These tests pin the degrade-gracefully behavior instead."""

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


def test_schedule_post_start_cmds_skips_malformed_runs_rest(monkeypatch):
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

    assert spawned == [["notify-send", "hello"]]
