"""Tests for utils.py's SSoT numeric-value guard and the self-update path.

get_ssot_num() is what stands between a hand-edited SSoT typo and an
unguarded ValueError aborting the session boot (the exact failure mode
2.1.1 fixed: a malformed VALIDATION_TIMEOUT crashed run() before the
session launched, and systemd's Restart=on-failure looped until the
start-limit tripped — black TTY, no diagnostic). This pins the
degrade-to-default contract every timing parameter in the SSoT relies
on.

The download_release()/check_latest_release() coverage below targets
CLAUDE.md's own highest-priority supply-chain concern: the update path
fetches and unpacks a GitHub release tarball with elevated privileges
downstream (install.sh runs as root), so its HTTPS-only guardrail and
extraction behavior are worth pinning even without full network mocking."""

import io
import tarfile

import utils


def test_get_ssot_num_returns_default_when_key_missing():
    assert utils.get_ssot_num("SOME_MISSING_KEY", 2.5) == 2.5


def test_get_ssot_num_parses_valid_value(set_ssot):
    set_ssot(TERM_TIMEOUT="7.5")
    assert utils.get_ssot_num("TERM_TIMEOUT", 5.0) == 7.5


def test_get_ssot_num_falls_back_on_malformed_value(set_ssot):
    set_ssot(VALIDATION_TIMEOUT="5s")
    assert utils.get_ssot_num("VALIDATION_TIMEOUT", 3.0) == 3.0


def test_get_ssot_num_falls_back_on_empty_value(set_ssot):
    set_ssot(NOTIFY_DELAY="")
    assert utils.get_ssot_num("NOTIFY_DELAY", 0.4) == 0.4


def test_get_ssot_num_falls_back_on_stray_comma(set_ssot):
    """A decimal comma is a realistic hand-edit mistake (locale habit)."""
    set_ssot(POST_START_DELAY="2,0")
    assert utils.get_ssot_num("POST_START_DELAY", 2.0) == 2.0


# ---------------------------------------------------------------------------
# _version_tuple / _release_from_api — pure parsing, no network
# ---------------------------------------------------------------------------


def test_version_tuple_parses_with_or_without_v_prefix():
    assert utils._version_tuple("v2.1.7") == (2, 1, 7)
    assert utils._version_tuple("2.1.7") == (2, 1, 7)


def test_version_tuple_falls_back_on_malformed_value():
    assert utils._version_tuple("not-a-version") == (0,)


def test_release_from_api_rejects_non_dict_payload():
    assert utils._release_from_api(["not", "a", "dict"]) is None


def test_release_from_api_rejects_missing_tag_name():
    assert utils._release_from_api({"body": "notes"}) is None


def test_release_from_api_detects_newer_version():
    info = utils._release_from_api(
        {
            "tag_name": "v99.0.0",
            "body": "notes",
            "tarball_url": "https://example.invalid/tar",
            "html_url": "https://example.invalid/html",
        }
    )
    assert info.version == "99.0.0"
    assert info.is_newer is True


def test_release_from_api_detects_not_newer_version():
    info = utils._release_from_api({"tag_name": f"v{utils.VERSION}"})
    assert info.is_newer is False


def test_release_from_api_defaults_missing_optional_fields_to_empty_str():
    info = utils._release_from_api({"tag_name": "v9.9.9"})
    assert info.notes == ""
    assert info.tarball_url == ""
    assert info.html_url == ""


# ---------------------------------------------------------------------------
# _prune_downloads
# ---------------------------------------------------------------------------


def test_prune_downloads_removes_only_version_named_dirs(tmp_path):
    (tmp_path / "v1.0.0").mkdir()
    (tmp_path / "v1.0.0" / "marker").write_text("x")
    (tmp_path / "not-a-version").mkdir()
    (tmp_path / "readme.txt").write_text("keep me")

    utils._prune_downloads(tmp_path)

    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {"not-a-version", "readme.txt"}


# ---------------------------------------------------------------------------
# download_release — HTTPS-only guardrail and real-tarball extraction
# ---------------------------------------------------------------------------


def _fake_release_info(tarball_url: str) -> utils.ReleaseInfo:
    return utils.ReleaseInfo(
        version="9.9.9",
        is_newer=True,
        notes="",
        tarball_url=tarball_url,
        html_url="",
    )


def _make_release_tarball(export_dir: str, files: dict[str, bytes]) -> bytes:
    """Build a real in-memory .tar.gz shaped like a GitHub source export."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel_path, content in files.items():
            member = tarfile.TarInfo(name=f"{export_dir}/{rel_path}")
            member.size = len(content)
            tar.addfile(member, io.BytesIO(content))
    return buf.getvalue()


def test_download_release_rejects_non_https_url(tmp_path, monkeypatch):
    def _fail_if_called(*_a, **_k):
        raise AssertionError("urlopen must not run for a non-https URL")

    monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)

    info = _fake_release_info("http://example.invalid/tarball")
    assert utils.download_release(info, tmp_path) is None


def test_download_release_extracts_and_locates_install_sh(
    tmp_path, monkeypatch
):
    tarball = _make_release_tarball(
        "dlucca1986-SteamMachine-DIY-abc123",
        {"install.sh": b"#!/bin/bash\necho hi\n"},
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: io.BytesIO(tarball),
    )

    info = _fake_release_info("https://example.invalid/tarball")
    result = utils.download_release(info, tmp_path)

    assert result is not None
    assert result.name == "dlucca1986-SteamMachine-DIY-abc123"
    assert (result / "install.sh").is_file()


def test_download_release_returns_none_when_install_sh_is_missing(
    tmp_path, monkeypatch
):
    tarball = _make_release_tarball("export-dir", {"README.md": b"hi"})
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: io.BytesIO(tarball),
    )

    info = _fake_release_info("https://example.invalid/tarball")
    assert utils.download_release(info, tmp_path) is None


def test_download_release_prunes_stale_versions_first(tmp_path, monkeypatch):
    stale = tmp_path / "v1.0.0"
    stale.mkdir()
    (stale / "marker").write_text("stale")

    tarball = _make_release_tarball(
        "export-dir", {"install.sh": b"#!/bin/bash\n"}
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: io.BytesIO(tarball),
    )

    info = _fake_release_info("https://example.invalid/tarball")
    utils.download_release(info, tmp_path)

    assert not stale.exists()
