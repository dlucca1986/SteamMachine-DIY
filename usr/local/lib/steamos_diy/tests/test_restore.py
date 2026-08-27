"""Tests for restore.py: atomic member writes and target-resolution safety."""

import io
import subprocess
import tarfile
from pathlib import Path

import restore
import utils


def _tar_with_member(name: str, data: bytes) -> tarfile.TarFile:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return tarfile.open(fileobj=buf, mode="r")


# ---------------------------------------------------------------------------
# _write_member — atomic tmp+rename replace
# ---------------------------------------------------------------------------


def test_write_member_goes_through_tmp_and_rename(tmp_path, monkeypatch):
    """Pins the mechanism, not just the end state: the pre-fix code wrote
    via unlink()+open(...).write() and never called os.replace() at all,
    so a regression back to that would slip past an end-state-only check."""
    target = tmp_path / "config.yaml"
    target.write_text("old content")
    calls = []
    real_replace = restore.os.replace

    def spy_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(restore.os, "replace", spy_replace)

    with _tar_with_member("member", b"new content") as tar:
        restore._write_member(tar, tar.getmember("member"), str(target))

    assert calls == [(f"{target}.sdy_restore_tmp", str(target))]
    assert target.read_bytes() == b"new content"
    assert not (tmp_path / "config.yaml.sdy_restore_tmp").exists()


def test_write_member_creates_missing_parent_dirs(tmp_path):
    target = tmp_path / "nested" / "dir" / "file.yaml"

    with _tar_with_member("m", b"hello") as tar:
        restore._write_member(tar, tar.getmember("m"), str(target))

    assert target.read_bytes() == b"hello"


def test_write_member_directory_entry(tmp_path):
    target = tmp_path / "somedir"
    info = tarfile.TarInfo(name="d")
    info.type = tarfile.DIRTYPE

    restore._write_member(None, info, str(target))

    assert target.is_dir()


# ---------------------------------------------------------------------------
# _resolve_target — traversal/allow-list safety (pure, no I/O beyond realpath)
# ---------------------------------------------------------------------------


def test_resolve_target_rejects_dotdot_traversal():
    mapping = {"system/steamos_diy.conf": "/etc/default/steamos_diy.conf"}
    result = restore._resolve_target(
        "system/steamos_diy.conf/../../etc/passwd", mapping, ("/etc/",)
    )
    assert result is None


def test_resolve_target_maps_nested_member(tmp_path):
    mapping = {"user/config": str(tmp_path / "config")}
    allowed = (str(tmp_path) + "/",)

    result = restore._resolve_target(
        "user/config/games.d/foo.yaml", mapping, allowed
    )

    assert result == str(tmp_path / "config" / "games.d" / "foo.yaml")


def test_resolve_target_rejects_outside_allowlist():
    mapping = {"user/config": "/root/.config/steamos_diy"}
    result = restore._resolve_target(
        "user/config/x", mapping, ("/home/someoneelse/",)
    )
    assert result is None


# ---------------------------------------------------------------------------
# backup/restore symmetry — get_backup_mapping() is generated once and
# consumed independently by backup.py (tar.add) and restore.py's own
# prefix-matching (_resolve_target). CLAUDE.md calls this out explicitly:
# a key that backs up cleanly but restore can't resolve is a silent
# data-loss bug, not a cosmetic mismatch — so every real mapping key must
# round-trip through restore's actual resolution+allow-list logic.
# ---------------------------------------------------------------------------


def test_every_backup_mapping_key_resolves_via_restore(tmp_path, monkeypatch):
    # The autouse _isolate_ssot_cache fixture points SSOT_CONF_PATH at a
    # nonexistent tmp path (outside /etc/, /usr/, /var/) so no test
    # touches the real conf file — but this test's whole point is to
    # verify the *real* production path actually lands in restore's
    # allow-list, so it must use the real value here.
    monkeypatch.setattr(
        utils, "SSOT_CONF_PATH", "/etc/default/steamos_diy.conf"
    )
    home = str(tmp_path / "home" / "tester")
    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real)

    assert mapping, "get_backup_mapping returned nothing to verify"
    for archive_key, expected_fs_path in mapping.items():
        resolved = restore._resolve_target(archive_key, mapping, allowed)
        assert resolved == expected_fs_path, (
            f"backup key {archive_key!r} -> {expected_fs_path!r} did not "
            f"round-trip through restore._resolve_target (got {resolved!r})"
        )


def test_every_backup_mapping_key_nested_member_resolves(
    tmp_path, monkeypatch
):
    """Same guarantee one level down — a file *inside* each mapped root
    (not just the root itself) must also resolve and land in the
    allow-list, exactly what a real archive member looks like."""
    monkeypatch.setattr(
        utils, "SSOT_CONF_PATH", "/etc/default/steamos_diy.conf"
    )
    home = str(tmp_path / "home" / "tester")
    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real)

    for archive_key, expected_fs_path in mapping.items():
        member_name = f"{archive_key}/some_file.txt"
        resolved = restore._resolve_target(member_name, mapping, allowed)
        assert resolved == f"{expected_fs_path}/some_file.txt", (
            f"nested member under {archive_key!r} did not resolve safely"
        )


# ---------------------------------------------------------------------------
# _reload_systemd — subprocess timeout discipline (CLAUDE.md review
# checklist item 14): a wedged `systemctl daemon-reload` must be logged
# and swallowed, not left to hang the restore flow indefinitely.
# ---------------------------------------------------------------------------


def test_reload_systemd_swallows_timeout(monkeypatch):
    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=10)

    monkeypatch.setattr(restore.subprocess, "run", fake_run)

    restore._reload_systemd()  # must not raise
