"""Tests for sdy.py: shlex parsing of per-game overrides, and profile
resolution (AppID > effective-name > stem precedence).

A malformed GAME_WRAPPER/GAME_EXTRA_ARGS in a hand-edited profile must
degrade gracefully instead of crashing the game launch (sdy.py execvpe's
the game; a crash here means the game never starts, with no fallback).

Profile resolution is covered because it's fiddly by design (AppID
header matching must be an exact, anchored match — 2.1.4 fixed a real
bug where searching for AppID "220" also matched a profile declaring
"SDY_ID: 2201290") and a future edit could silently reintroduce that
class of bug without a regression test pinning the exact-match contract."""

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


# ---------------------------------------------------------------------------
# _header_declares_id — exact match, not substring (2.1.4 regression)
# ---------------------------------------------------------------------------


def test_header_declares_id_exact_match(tmp_path):
    profile = tmp_path / "game.yaml"
    profile.write_text('# SDY_ID: 220\nSTEAM_APPID: "220"\nGAME_WRAPPER: ""\n')

    assert sdy._header_declares_id(str(profile), "220")


def test_header_declares_id_rejects_substring_match(tmp_path):
    """The exact 2.1.4 bug: searching '220' must not hit 'SDY_ID: 2201290'."""
    profile = tmp_path / "other_game.yaml"
    profile.write_text("SDY_ID: 2201290\n")

    assert not sdy._header_declares_id(str(profile), "220")


def test_header_declares_id_tolerates_quotes_and_comments(tmp_path):
    profile = tmp_path / "game.yaml"
    profile.write_text('STEAM_APPID: "730"  # Counter-Strike\n')

    assert sdy._header_declares_id(str(profile), "730")


def test_header_declares_id_missing_file(tmp_path):
    assert not sdy._header_declares_id(str(tmp_path / "nope.yaml"), "220")


# ---------------------------------------------------------------------------
# _resolve_effective_name — generic-stem substitution
# ---------------------------------------------------------------------------


def test_resolve_effective_name_substitutes_generic_stem(tmp_path):
    game_dir = tmp_path / "MyGame"
    game_dir.mkdir()
    launcher = game_dir / "start.sh"
    launcher.write_text("#!/bin/sh\n")

    stem, eff_name = sdy._resolve_effective_name([str(launcher)])

    assert stem == "start"
    assert eff_name == "MyGame"


def test_resolve_effective_name_keeps_specific_stem(tmp_path):
    game_dir = tmp_path / "SomeGame"
    game_dir.mkdir()
    binary = game_dir / "SomeGame.x86_64"
    binary.write_text("")

    stem, eff_name = sdy._resolve_effective_name([str(binary)])

    # Path.stem strips only the last suffix (".x86_64"), landing on
    # "SomeGame" — not in _GENERIC_STEMS, so it's kept as eff_name too.
    assert stem == "SomeGame"
    assert eff_name == "SomeGame"


def test_resolve_effective_name_picks_rightmost_existing_path(tmp_path):
    wrapper = tmp_path / "mangohud"
    wrapper.write_text("")
    game_dir = tmp_path / "MyGame"
    game_dir.mkdir()
    launcher = game_dir / "start.sh"
    launcher.write_text("")

    # Wrapper comes first in argv but the game binary (rightmost existing
    # absolute path) is what should drive profile lookup, not the wrapper.
    _, eff_name = sdy._resolve_effective_name([str(wrapper), str(launcher)])

    assert eff_name == "MyGame"


def test_resolve_effective_name_no_existing_path_falls_back_to_first_arg():
    stem, _ = sdy._resolve_effective_name(["relative_binary"])

    assert stem == "relative_binary"


# ---------------------------------------------------------------------------
# _get_profile_path — AppID > effective-name > stem precedence
# ---------------------------------------------------------------------------


def test_get_profile_path_appid_wins_over_name_match(tmp_path):
    (tmp_path / "MyGame.yaml").write_text("GAME_WRAPPER: wrong\n")
    by_id = tmp_path / "profile_by_id.yaml"
    by_id.write_text("SDY_ID: 220\nGAME_WRAPPER: right\n")

    found = sdy._get_profile_path(str(tmp_path), "220", "start", "MyGame")

    assert found == str(by_id)


def test_get_profile_path_falls_back_to_effective_name(tmp_path):
    expected = tmp_path / "MyGame.yaml"
    expected.write_text("GAME_WRAPPER: mangohud\n")

    found = sdy._get_profile_path(str(tmp_path), None, "start", "MyGame")

    assert found == str(expected)


def test_get_profile_path_falls_back_to_stem_last(tmp_path):
    expected = tmp_path / "start.yaml"
    expected.write_text("GAME_WRAPPER: mangohud\n")

    found = sdy._get_profile_path(str(tmp_path), None, "start", "MyGame")

    assert found == str(expected)


def test_get_profile_path_none_when_nothing_matches(tmp_path):
    found = sdy._get_profile_path(str(tmp_path), "220", "start", "MyGame")

    assert found is None
