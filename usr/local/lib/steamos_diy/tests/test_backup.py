"""Tests for backup.py: pure exclusion/pruning/manifest logic, plus one
end-to-end run_backup() smoke test tying the pieces together."""

import os
import tarfile

import backup
import pytest
import utils

# ---------------------------------------------------------------------------
# _path_is_excluded — component match, not substring match
# ---------------------------------------------------------------------------


def test_path_is_excluded_matches_directory_component():
    assert backup._path_is_excluded("user/config/backups/old.tar.gz")
    assert backup._path_is_excluded("source/steamos_diy/__pycache__/x.pyc")


def test_path_is_excluded_does_not_match_substring():
    assert not backup._path_is_excluded("user/config/backups_2024.yaml")
    assert not backup._path_is_excluded("user/config/my_backups.yaml")


# ---------------------------------------------------------------------------
# _generate_links_manifest
# ---------------------------------------------------------------------------


def test_generate_links_manifest_includes_qualifying_symlinks(
    tmp_path, monkeypatch
):
    search_dir = tmp_path / "usr_bin"
    search_dir.mkdir()

    target_dir = tmp_path / "steamos-polkit-helpers"
    target_dir.mkdir()
    real_target = target_dir / "helper-bin"
    real_target.write_text("x")
    link = search_dir / "helper-shim"
    link.symlink_to(real_target)

    other_target = tmp_path / "elsewhere"
    other_target.mkdir()
    (other_target / "bin").write_text("y")
    other_link = search_dir / "other-shim"
    other_link.symlink_to(other_target / "bin")

    monkeypatch.setattr(backup, "_SYMLINK_SEARCH_PATHS", (str(search_dir),))

    manifest = backup._generate_links_manifest().decode("utf-8")

    assert f"{link}\t{os.path.realpath(link)}" in manifest
    assert "other-shim" not in manifest


def test_generate_links_manifest_skips_paths_with_tab_or_newline(
    tmp_path, monkeypatch
):
    search_dir = tmp_path / "usr_bin"
    search_dir.mkdir()
    link = search_dir / "bad-shim"
    os.symlink(
        str(tmp_path / "steamos-polkit-helpers" / "weird\ttarget"), str(link)
    )

    monkeypatch.setattr(backup, "_SYMLINK_SEARCH_PATHS", (str(search_dir),))

    assert backup._generate_links_manifest() == b""


def test_generate_links_manifest_empty_when_nothing_qualifies(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(backup, "_SYMLINK_SEARCH_PATHS", (str(tmp_path),))
    assert backup._generate_links_manifest() == b""


# ---------------------------------------------------------------------------
# _prune_old_archives
# ---------------------------------------------------------------------------


def test_prune_old_archives_keeps_newest_n(tmp_path, set_ssot):
    set_ssot(BACKUP_KEEP="2")
    names = [
        "sdy_backup_20260101_000000.tar.gz",
        "sdy_backup_20260102_000000.tar.gz",
        "sdy_backup_20260103_000000.tar.gz",
    ]
    for name in names:
        (tmp_path / name).write_text("x")

    backup._prune_old_archives(tmp_path)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == names[-2:]


def test_prune_old_archives_disabled_when_keep_not_positive(
    tmp_path, set_ssot
):
    set_ssot(BACKUP_KEEP="0")
    (tmp_path / "sdy_backup_20260101_000000.tar.gz").write_text("x")
    (tmp_path / "sdy_backup_20260102_000000.tar.gz").write_text("x")

    backup._prune_old_archives(tmp_path)

    assert len(list(tmp_path.iterdir())) == 2


def test_prune_old_archives_ignores_in_flight_tmp_files(tmp_path, set_ssot):
    set_ssot(BACKUP_KEEP="1")
    (tmp_path / "sdy_backup_20260101_000000.tar.gz").write_text("old")
    (tmp_path / "sdy_backup_20260102_000000.tar.gz").write_text("new")
    (tmp_path / "sdy_backup_20260103_000000.tar.gz.tmp").write_text("wip")

    backup._prune_old_archives(tmp_path)

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [
        "sdy_backup_20260102_000000.tar.gz",
        "sdy_backup_20260103_000000.tar.gz.tmp",
    ]


# ---------------------------------------------------------------------------
# run_backup() — end to end against a fully faked environment
# ---------------------------------------------------------------------------


def test_run_backup_end_to_end(tmp_path, monkeypatch):
    home = tmp_path / "home" / "tester"
    user_config_dir = home / ".config" / "steamos_diy"
    user_config_dir.mkdir(parents=True)
    (user_config_dir / "config.yaml").write_text("flags: []\n")
    # A pre-existing backups dir must never be walked into.
    (user_config_dir / "backups").mkdir()
    (user_config_dir / "backups" / "old_archive.tar.gz").write_text("stale")

    ssot_conf = tmp_path / "steamos_diy.conf"
    ssot_conf.write_text("LOG_LEVEL=ERROR\n")

    core_lib_dir = tmp_path / "core_lib"
    core_lib_dir.mkdir()
    (core_lib_dir / "backup.py").write_text("# fake\n")

    next_session = tmp_path / "next_session"
    next_session.write_text("steam\n")

    service_file = tmp_path / "steamos_diy.service"
    service_file.write_text("[Unit]\n")

    monkeypatch.setattr(utils, "SSOT_CONF_PATH", str(ssot_conf))
    monkeypatch.setattr(utils, "NEXT_SESSION_PATH", str(next_session))
    monkeypatch.setattr(utils, "CORE_LIB_DIR", str(core_lib_dir))
    monkeypatch.setattr(utils, "_SERVICE_PATH", str(service_file))
    monkeypatch.setattr(backup, "check_root", lambda: None)
    monkeypatch.setattr(backup, "get_real_user", lambda: ("tester", home))
    monkeypatch.setattr(backup, "fix_ownership", lambda *a, **k: None)
    monkeypatch.setattr(backup, "_SYMLINK_SEARCH_PATHS", ())

    backup.run_backup()

    archives = list(
        (user_config_dir / "backups").glob("sdy_backup_*.tar.gz")
    )
    assert len(archives) == 1

    with tarfile.open(archives[0], "r:gz") as tar:
        names = tar.getnames()

    assert "user/config/config.yaml" in names
    assert not any(n.startswith("user/config/backups") for n in names)
    assert "source/steamos_diy/backup.py" in names
    assert backup.BACKUP_MANIFEST_NAME in names


def test_run_backup_refuses_symlinked_tmp_path(tmp_path, monkeypatch):
    """A symlink pre-planted at the predictable tmp archive path must not
    be followed — regression for the TOCTOU where tarfile.open() (via the
    builtin open()) would write archive content through it as root."""
    home = tmp_path / "home" / "tester"
    user_config_dir = home / ".config" / "steamos_diy"
    user_config_dir.mkdir(parents=True)
    (user_config_dir / "config.yaml").write_text("flags: []\n")
    backups_dir = user_config_dir / "backups"
    backups_dir.mkdir()

    victim = tmp_path / "victim"
    victim.write_text("do not touch")
    final_path = backups_dir / "sdy_backup_FIXED.tar.gz"
    tmp_path_archive = backups_dir / "sdy_backup_FIXED.tar.gz.tmp"
    tmp_path_archive.symlink_to(victim)

    ssot_conf = tmp_path / "steamos_diy.conf"
    ssot_conf.write_text("LOG_LEVEL=ERROR\n")
    core_lib_dir = tmp_path / "core_lib"
    core_lib_dir.mkdir()
    next_session = tmp_path / "next_session"
    next_session.write_text("steam\n")
    service_file = tmp_path / "steamos_diy.service"
    service_file.write_text("[Unit]\n")

    monkeypatch.setattr(utils, "SSOT_CONF_PATH", str(ssot_conf))
    monkeypatch.setattr(utils, "NEXT_SESSION_PATH", str(next_session))
    monkeypatch.setattr(utils, "CORE_LIB_DIR", str(core_lib_dir))
    monkeypatch.setattr(utils, "_SERVICE_PATH", str(service_file))
    monkeypatch.setattr(backup, "check_root", lambda: None)
    monkeypatch.setattr(backup, "get_real_user", lambda: ("tester", home))
    monkeypatch.setattr(backup, "fix_ownership", lambda *a, **k: None)
    monkeypatch.setattr(backup, "_SYMLINK_SEARCH_PATHS", ())
    monkeypatch.setattr(
        backup,
        "_archive_paths",
        lambda backup_dir: (final_path, tmp_path_archive),
    )

    with pytest.raises(SystemExit):
        backup.run_backup()

    assert victim.read_text() == "do not touch"
    assert not final_path.exists()
