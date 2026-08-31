"""Regression test for health.py's _check_groups group-resolution guard.

Before the fix, one stale/deleted gid in os.getgroups() (grp.getgrgid
raises KeyError for it) aborted the whole set-comprehension, so every
critical group came back "missing" even when the user actually belonged
to all of them — a misleading "everything is broken" preflight result
caused by one unrelated stale entry."""

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
# get_service_status — subprocess timeout discipline (CLAUDE.md review
# checklist item 14): a wedged `systemctl show` must degrade to the
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
# except clause. An uncaught exception here previously killed
# control_center.py's validate_config worker thread silently (nothing
# printed, no dialog, no log — the app is launched detached with stderr
# to /dev/null), the same failure mode as the journal.py aware/naive
# datetime bug.
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
