"""Tests for session_select.py: target resolution, dispatch argv, and the
persist-before-spawn ordering in select().

State (next_session) must be written before the helper is spawned, and
must stay written even if the spawn fails — a helper crash must not
strand the system without a target for the next boot."""

import session_select


def test_resolve_target_maps_desktop_keywords():
    assert session_select._resolve_target("plasma") == "desktop"
    assert session_select._resolve_target("desktop") == "desktop"
    assert session_select._resolve_target("kde") == "desktop"


def test_resolve_target_tolerates_whitespace_and_case():
    assert session_select._resolve_target("  KDE\n") == "desktop"


def test_resolve_target_defaults_to_steam_on_empty():
    assert session_select._resolve_target("") == "steam"


def test_resolve_target_defaults_to_steam_on_unknown_value():
    assert session_select._resolve_target("garbage") == "steam"


def test_dispatch_switch_desktop_spawns_steam_shutdown(monkeypatch):
    calls = []
    monkeypatch.setattr(
        session_select,
        "spawn_native",
        lambda path, args: calls.append((path, args)) or 123,
    )

    assert session_select._dispatch_switch("desktop") is True
    (path, args) = calls[0]
    assert path == session_select.DEFAULT_STEAM_BIN
    assert args == [session_select.DEFAULT_STEAM_BIN, "-shutdown"]


def test_dispatch_switch_steam_spawns_qdbus_logout(monkeypatch):
    calls = []
    monkeypatch.setattr(
        session_select,
        "spawn_native",
        lambda path, args: calls.append((path, args)) or 456,
    )

    assert session_select._dispatch_switch("steam") is True
    (path, args) = calls[0]
    assert path == session_select.DEFAULT_DBUS_BIN
    assert args == [
        session_select.DEFAULT_DBUS_BIN,
        "org.kde.Shutdown",
        "/Shutdown",
        "logout",
    ]


def test_dispatch_switch_returns_false_on_spawn_failure(monkeypatch):
    monkeypatch.setattr(
        session_select, "spawn_native", lambda path, args: 0
    )
    assert session_select._dispatch_switch("steam") is False


def test_select_with_no_argv_is_a_noop(monkeypatch):
    monkeypatch.setattr(session_select.sys, "argv", ["session_select.py"])
    writes = []
    monkeypatch.setattr(
        session_select, "write_atomic", lambda *a: writes.append(a)
    )

    session_select.select()

    assert not writes


def test_select_persists_state_even_when_dispatch_fails(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        session_select.sys, "argv", ["session_select.py", "steam"]
    )
    writes = []
    monkeypatch.setattr(
        session_select, "write_atomic", lambda *a: writes.append(a)
    )
    monkeypatch.setattr(
        session_select, "spawn_native", lambda path, args: 0
    )
    next_session_path = str(tmp_path / "next_session")
    monkeypatch.setattr(
        session_select, "get_ssot_var", lambda key, default: (
            next_session_path if key == "next_session" else default
        )
    )

    session_select.select()

    assert writes == [(next_session_path, "steam")]
