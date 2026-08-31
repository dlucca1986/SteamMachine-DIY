"""Tests for restore.py: atomic member writes and target-resolution safety."""

import io
import subprocess
import tarfile
from pathlib import Path

import pytest
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


def test_write_member_refuses_symlinked_tmp_path(tmp_path):
    """A symlink planted at the tmp write path (not the target itself)
    must not be followed — regression for the TOCTOU where only the
    final target was checked, never the sibling path actually opened
    for writing."""
    target = tmp_path / "config.yaml"
    victim = tmp_path / "victim"
    victim.write_text("do not touch")
    tmp = tmp_path / "config.yaml.sdy_restore_tmp"
    tmp.symlink_to(victim)

    with _tar_with_member("member", b"attacker content") as tar:
        ok = restore._write_member(tar, tar.getmember("member"), str(target))

    assert ok is False
    assert victim.read_text() == "do not touch"
    assert not target.exists()
    assert tmp.is_symlink()


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


def test_every_backup_mapping_key_resolves_via_restore(monkeypatch):
    # The autouse _isolate_ssot_cache fixture points SSOT_CONF_PATH at a
    # nonexistent tmp path (outside /etc/, /usr/, /var/) so no test
    # touches the real conf file — but this test's whole point is to
    # verify the *real* production path actually lands in restore's
    # allow-list, so it must use the real value here. home must be the
    # real $HOME too: the real conf's SSoT-read values (e.g.
    # games_conf_dir) are absolute paths install.sh patched against this
    # actual home, not a fabricated tmp one — on a machine with no real
    # conf installed (CI), every SSoT-read key just falls back to its
    # home-relative default instead, so this stays hermetic either way.
    monkeypatch.setattr(
        utils, "SSOT_CONF_PATH", "/etc/default/steamos_diy.conf"
    )
    home = str(Path.home())
    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real, mapping)

    assert mapping, "get_backup_mapping returned nothing to verify"
    for archive_key, expected_fs_path in mapping.items():
        resolved = restore._resolve_target(archive_key, mapping, allowed)
        assert resolved == expected_fs_path, (
            f"backup key {archive_key!r} -> {expected_fs_path!r} did not "
            f"round-trip through restore._resolve_target (got {resolved!r})"
        )


def test_every_backup_mapping_key_nested_member_resolves(monkeypatch):
    """Same guarantee one level down — a file *inside* each mapped root
    (not just the root itself) must also resolve and land in the
    allow-list, exactly what a real archive member looks like."""
    monkeypatch.setattr(
        utils, "SSOT_CONF_PATH", "/etc/default/steamos_diy.conf"
    )
    home = str(Path.home())
    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real, mapping)

    for archive_key, expected_fs_path in mapping.items():
        member_name = f"{archive_key}/some_file.txt"
        resolved = restore._resolve_target(member_name, mapping, allowed)
        assert resolved == f"{expected_fs_path}/some_file.txt", (
            f"nested member under {archive_key!r} did not resolve safely"
        )


def test_relocated_games_conf_dir_round_trips_through_restore(
    tmp_path, set_ssot
):
    """A games_conf_dir relocated (but still under home) must get its own
    mapping entry (utils.get_backup_mapping) *and* that entry must
    actually resolve through restore — the two generic round-trip tests
    above don't exercise this branch on a machine whose real installed
    conf's games_conf_dir happens to equal the default."""
    home = str(tmp_path / "home" / "tester")
    custom = str(Path(home) / "elsewhere" / "games.d")
    set_ssot(games_conf_dir=custom)

    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real, mapping)

    assert mapping["user/games_conf_dir"] == custom
    resolved = restore._resolve_target(
        "user/games_conf_dir", mapping, allowed
    )
    assert resolved == custom


def test_games_conf_dir_relocated_outside_home_round_trips(
    tmp_path, set_ssot
):
    """Regression: games_conf_dir relocated *outside* home/etc/usr/var
    (e.g. external/SD-card storage) used to be silently rejected by
    restore even though backup archived it fine, because the allow-list
    was built from home_real alone and never consulted the mapping's
    own (SSoT-relocatable) destination paths."""
    home = str(tmp_path / "home" / "tester")
    external = str(tmp_path / "external_storage" / "sdy_profiles")
    set_ssot(games_conf_dir=external)

    mapping = utils.get_backup_mapping(home)
    home_real = str(Path(home).resolve())
    allowed = restore._allowed_prefixes(home_real, mapping)

    assert mapping["user/games_conf_dir"] == external
    resolved = restore._resolve_target(
        "user/games_conf_dir", mapping, allowed
    )
    assert resolved == external


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


# ---------------------------------------------------------------------------
# _extract_payload / _execute_restore — a wrong/foreign archive can pass
# verify_archive's gzip/tar integrity check yet match nothing in the
# mapping. Restoring zero members must not be reported as success.
# ---------------------------------------------------------------------------


def test_extract_payload_counts_a_matched_member(tmp_path):
    mapping = {"user/config": str(tmp_path / "config")}
    allowed = restore._allowed_prefixes(str(tmp_path), mapping)

    with _tar_with_member("user/config/file.txt", b"hello") as tar:
        restored, links = restore._extract_payload(
            tar, mapping, allowed, str(tmp_path), "tester"
        )

    assert restored == 1
    assert links is None


def test_extract_payload_counts_zero_for_foreign_archive(tmp_path):
    mapping = {"user/config": str(tmp_path / "config")}
    allowed = restore._allowed_prefixes(str(tmp_path), mapping)

    with _tar_with_member("totally/unrelated/path.txt", b"hello") as tar:
        restored, _links = restore._extract_payload(
            tar, mapping, allowed, str(tmp_path), "tester"
        )

    assert restored == 0


def test_execute_restore_aborts_when_nothing_matched(tmp_path, monkeypatch):
    """Regression: previously always logged RESTORE_SUCCESS and returned
    normally regardless of how many members actually matched, so a
    foreign/wrong archive silently "succeeded" while changing nothing."""
    archive = tmp_path / "foreign.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo(name="totally/unrelated/path.txt")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"hello"))

    mapping = {"user/config": str(tmp_path / "config")}
    allowed = restore._allowed_prefixes(str(tmp_path), mapping)
    monkeypatch.setattr(restore, "_reload_systemd", lambda: None)

    with pytest.raises(SystemExit):
        restore._execute_restore(
            str(archive), "tester", str(tmp_path), mapping, allowed
        )
