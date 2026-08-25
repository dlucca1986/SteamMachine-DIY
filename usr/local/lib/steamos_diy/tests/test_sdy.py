"""Regression tests for sdy.py's shlex parsing of per-game overrides.

A malformed GAME_WRAPPER/GAME_EXTRA_ARGS in a hand-edited profile must
degrade gracefully instead of crashing the game launch (sdy.py execvpe's
the game; a crash here means the game never starts, with no fallback)."""

import sdy


def test_safe_split_well_formed_command():
    assert sdy._safe_split("GAME_WRAPPER", "mangohud gamemoderun") == [
        "mangohud",
        "gamemoderun",
    ]


def test_safe_split_falls_back_on_unbalanced_quote():
    result = sdy._safe_split("GAME_WRAPPER", 'mangohud "unterminated')
    assert result == ["mangohud", '"unterminated']


def test_build_command_survives_malformed_wrapper():
    profile = {"GAME_WRAPPER": 'mangohud "broken', "GAME_EXTRA_ARGS": None}

    full_cmd = sdy._build_command(["/opt/Game/start.sh"], profile)

    assert full_cmd[-1] == "/opt/Game/start.sh"
    assert "mangohud" in full_cmd


def test_build_command_survives_malformed_extra_args():
    profile = {"GAME_WRAPPER": None, "GAME_EXTRA_ARGS": '-foo "bar'}

    full_cmd = sdy._build_command(["/opt/Game/start.sh"], profile)

    assert full_cmd[0] == "/opt/Game/start.sh"
    assert '"bar' in full_cmd


def test_build_command_well_formed_unaffected():
    profile = {"GAME_WRAPPER": "mangohud", "GAME_EXTRA_ARGS": "-foo bar"}

    full_cmd = sdy._build_command(["/opt/Game/start.sh", "arg1"], profile)

    assert full_cmd == [
        "mangohud",
        "/opt/Game/start.sh",
        "arg1",
        "-foo",
        "bar",
    ]
