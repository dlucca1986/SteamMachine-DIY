"""Tests for restore.py: atomic member writes and target-resolution safety."""

import io
import tarfile

import restore


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
