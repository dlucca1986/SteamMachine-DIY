"""Tests for health.py's preflight checks and service-status snapshot.

_check_groups: one stale gid in os.getgroups() (grp.getgrgid raises
KeyError) once made every critical group read "missing", even with the
user in all of them."""

import subprocess
from types import SimpleNamespace

import health


def test_check_groups_survives_one_stale_gid(monkeypatch):
    gid_names = {100: "tty", 101: "video", 102: "render", 103: "input"}
    stale_gid = 999
    gids = [*gid_names, stale_gid]
    monkeypatch.setattr(health.os, "getgroups", lambda: gids)

    def fake_getgrgid(gid):
        if gid not in gid_names:
            raise KeyError(gid)
        return SimpleNamespace(gr_name=gid_names[gid])

    monkeypatch.setattr(health.grp, "getgrgid", fake_getgrgid)

    result = health._check_groups()

    assert result.ok
    assert result.detail == "all present"


# ---------------------------------------------------------------------------
# get_service_status — a wedged `systemctl show` must time out to the
# "unknown" fallback, not hang the Control Center's status refresh.
# ---------------------------------------------------------------------------


def test_get_service_status_falls_back_on_timeout(monkeypatch):
    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

    monkeypatch.setattr(health.subprocess, "run", fake_run)

    status = health.get_service_status()

    assert status == health.ServiceStatus("unknown", "unknown", 0, 0)


# ---------------------------------------------------------------------------
# _check_yaml / _read_user_config — non-UTF-8 content must degrade to a
# failed CheckResult / _UNREADABLE, not raise UnicodeDecodeError past the
# except clause; uncaught, it ended control_center.py's validate_config
# worker with no dialog and no project log line.
# ---------------------------------------------------------------------------


def test_check_yaml_reports_non_utf8_content_instead_of_raising(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_bytes(b"flags: [\xff\xfe invalid utf-8]")

    result = health._check_yaml(str(bad))

    assert result.ok is False
    assert "UnicodeDecodeError" in result.detail


def test_read_user_config_returns_unreadable_for_non_utf8(
    tmp_path, monkeypatch
):
    bad = tmp_path / "config.yaml"
    bad.write_bytes(b"flags: [\xff\xfe invalid utf-8]")
    monkeypatch.setattr(health, "get_ssot_var", lambda *a, **k: str(bad))

    result = health._read_user_config()

    assert result is health._UNREADABLE


def test_check_yaml_reports_unbuildable_scalar_instead_of_raising(tmp_path):
    """Regression: ruamel raises a plain ValueError, not YAMLError, for an
    unquoted scalar shaped like a date that isn't one — it escaped
    _check_yaml and aborted the whole preflight with a bare "day 30 must
    be in range..." and no file name."""
    bad = tmp_path / "config.yaml"
    bad.write_text("released: 2026-02-30\n")

    result = health._check_yaml(str(bad))

    assert result.ok is False
    assert result.name == "YAML config.yaml"


def test_read_user_config_returns_unreadable_for_unbuildable_scalar(
    tmp_path, monkeypatch
):
    bad = tmp_path / "config.yaml"
    bad.write_text("released: 2026-02-30\n")
    monkeypatch.setattr(health, "get_ssot_var", lambda *a, **k: str(bad))

    assert health._read_user_config() is health._UNREADABLE


def test_check_binaries_rejects_a_directory(tmp_path, monkeypatch):
    """Regression: os.access(path, os.X_OK) alone is true for a
    traversable directory, not just an executable file -- a SSoT binary
    key mistakenly pointed at a directory passed this preflight as "OK"
    even though session_launch.py can't actually exec it."""
    fake_dir = tmp_path / "not-a-binary"
    fake_dir.mkdir()
    monkeypatch.setattr(health, "get_ssot_var", lambda key, default: (
        str(fake_dir) if key == "bin_gs" else default
    ))

    results = health._check_binaries()

    gs_result = next(r for r in results if r.name == "Binary bin_gs")
    assert gs_result.ok is False
    assert "not executable" in gs_result.detail


# ---------------------------------------------------------------------------
# _check_gamescope_flags — validated via gamescope's own argv parser, not
# a --help-derived allowlist (which false-flags real but undocumented
# flags like --fade-out-duration)
# ---------------------------------------------------------------------------


def _fake_run(stdout="", stderr="", returncode=0):
    def run(_argv, **_kwargs):
        return SimpleNamespace(
            stdout=stdout, stderr=stderr, returncode=returncode
        )

    return run


def test_check_gamescope_flags_accepts_undocumented_but_valid_flag(
    monkeypatch,
):
    """Regression: gamescope accepts some flags (e.g. --fade-out-duration)
    it never lists in --help: run through gamescope's own parser, such
    a flag yields normal usage output (no "unrecognized option"), so it
    must not be reported as unrecognised."""
    monkeypatch.setattr(
        health, "get_ssot_var", lambda *a, **k: "/usr/bin/gamescope"
    )
    monkeypatch.setattr(
        health.subprocess,
        "run",
        _fake_run(stdout="usage: gamescope [options...] -- [command...]\n"),
    )

    result = health._check_gamescope_flags(
        {"flags": ["--fade-out-duration 200"]}
    )

    assert result.ok is True
    assert result.detail == "all recognised"


def test_check_gamescope_flags_rejects_a_genuinely_unknown_long_flag(
    monkeypatch,
):
    monkeypatch.setattr(
        health, "get_ssot_var", lambda *a, **k: "/usr/bin/gamescope"
    )
    monkeypatch.setattr(
        health.subprocess,
        "run",
        _fake_run(
            stderr="gamescope: unrecognized option "
            "'--supercazzola-test-recovery'\n"
            "See --help for a list of options.\n",
            returncode=1,
        ),
    )

    result = health._check_gamescope_flags(
        {"flags": ["--supercazzola-test-recovery"]}
    )

    assert result.ok is False
    assert result.detail == "unrecognised: --supercazzola-test-recovery"


def test_check_gamescope_flags_rejects_a_genuinely_unknown_short_flag(
    monkeypatch,
):
    monkeypatch.setattr(
        health, "get_ssot_var", lambda *a, **k: "/usr/bin/gamescope"
    )
    monkeypatch.setattr(
        health.subprocess,
        "run",
        _fake_run(
            stderr="gamescope: invalid option -- 'Z'\n"
            "See --help for a list of options.\n",
            returncode=1,
        ),
    )

    result = health._check_gamescope_flags({"flags": ["-Z"]})

    assert result.ok is False
    assert result.detail == "unrecognised: -Z"


def test_check_gamescope_flags_degrades_when_gamescope_unavailable(
    monkeypatch,
):
    monkeypatch.setattr(
        health, "get_ssot_var", lambda *a, **k: "/usr/bin/gamescope"
    )

    def raising_run(*_a, **_k):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(health.subprocess, "run", raising_run)

    result = health._check_gamescope_flags({"flags": ["-e"]})

    assert result.ok is True
    assert result.detail == "gamescope unavailable"


def test_check_gamescope_flags_skips_when_no_flags_configured():
    result = health._check_gamescope_flags({"flags": []})

    assert result.ok is True
    assert result.detail == "none set"
