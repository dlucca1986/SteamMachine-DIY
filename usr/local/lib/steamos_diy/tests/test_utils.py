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

import hashlib
import io
import subprocess
import tarfile
from types import SimpleNamespace

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
# read_session_target — a next_session file with invalid UTF-8 bytes (e.g.
# restored from a corrupted backup) must degrade to default rather than
# raise UnicodeDecodeError uncaught into session_launch.py::run(), which
# wraps nothing around this call — an uncaught exception there would crash
# the boot path instead of falling back to "steam".
# ---------------------------------------------------------------------------


def test_read_session_target_falls_back_on_invalid_utf8(tmp_path):
    path = tmp_path / "next_session"
    path.write_bytes(b"\xff\xfe steam")

    assert utils.read_session_target(str(path), default="steam") == "steam"


# ---------------------------------------------------------------------------
# get_backup_mapping — a games_conf_dir relocated via the SSoT must get its
# own mapping entry, or it silently drops out of every backup (control_
# center.py/health.py both already resolve it dynamically the same way).
# ---------------------------------------------------------------------------


def test_get_backup_mapping_omits_games_dir_entry_when_default(tmp_path):
    """The default games_conf_dir already lives under user/config, which
    is backed up recursively — a separate entry would just duplicate it
    in the archive."""
    mapping = utils.get_backup_mapping(str(tmp_path / "home"))

    assert "user/games_conf_dir" not in mapping


def test_get_backup_mapping_adds_games_dir_entry_when_relocated(
    tmp_path, set_ssot
):
    custom = tmp_path / "elsewhere" / "games.d"
    set_ssot(games_conf_dir=str(custom))

    mapping = utils.get_backup_mapping(str(tmp_path / "home"))

    assert mapping["user/games_conf_dir"] == str(custom)


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
    assert info.checksum_url == ""


def test_release_from_api_finds_checksum_asset_url():
    info = utils._release_from_api(
        {
            "tag_name": "v9.9.9",
            "assets": [
                {"name": "irrelevant.txt", "browser_download_url": "x"},
                {
                    "name": "SHA256SUMS",
                    "browser_download_url": "https://example.invalid/sums",
                },
            ],
        }
    )
    assert info.checksum_url == "https://example.invalid/sums"


def test_release_from_api_ignores_malformed_assets_list():
    info = utils._release_from_api(
        {"tag_name": "v9.9.9", "assets": "not-a-list"}
    )
    assert info.checksum_url == ""


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


def test_prune_downloads_skips_the_keep_directory(tmp_path):
    (tmp_path / "v1.0.0").mkdir()
    (tmp_path / "v2.0.0").mkdir()

    utils._prune_downloads(tmp_path, keep=tmp_path / "v2.0.0")

    remaining = {p.name for p in tmp_path.iterdir()}
    assert remaining == {"v2.0.0"}


# ---------------------------------------------------------------------------
# download_release — HTTPS-only guardrail, checksum verification, extraction
# ---------------------------------------------------------------------------

_TARBALL_URL = "https://example.invalid/tarball"
_CHECKSUM_URL = "https://example.invalid/sums"


def _fake_release_info(
    tarball_url: str = _TARBALL_URL, checksum_url: str = _CHECKSUM_URL
) -> utils.ReleaseInfo:
    return utils.ReleaseInfo(
        version="9.9.9",
        is_newer=True,
        notes="",
        tarball_url=tarball_url,
        html_url="",
        checksum_url=checksum_url,
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


def _fake_urlopen(tarball: bytes, checksum_body: bytes):
    """Dispatch by URL: checksum text for _CHECKSUM_URL, tarball otherwise."""

    def _fake(req, timeout):  # pylint: disable=unused-argument
        if req.full_url == _CHECKSUM_URL:
            return io.BytesIO(checksum_body)
        return io.BytesIO(tarball)

    return _fake


def test_download_release_rejects_non_https_url(tmp_path, monkeypatch):
    def _fail_if_called(*_a, **_k):
        raise AssertionError("urlopen must not run for a non-https URL")

    monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)

    info = _fake_release_info(tarball_url="http://example.invalid/tarball")
    assert utils.download_release(info, tmp_path) is None


def test_download_release_rejects_missing_checksum_url(tmp_path, monkeypatch):
    def _fail_if_called(*_a, **_k):
        raise AssertionError(
            "urlopen must not run when no checksum asset is published"
        )

    monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)

    info = _fake_release_info(checksum_url="")
    assert utils.download_release(info, tmp_path) is None


def test_download_release_rejects_checksum_mismatch(tmp_path, monkeypatch):
    tarball = _make_release_tarball(
        "export-dir", {"install.sh": b"#!/bin/bash\n"}
    )
    wrong_digest = "0" * 64
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, wrong_digest.encode("ascii")),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None
    assert not (tmp_path / "v9.9.9").exists()


def test_download_release_checksum_mismatch_preserves_stale_cache(
    tmp_path, monkeypatch
):
    """Regression: pruning must happen only after checksum verification —
    a corrupted/mismatched download must not cost the last known-good
    previously-cached release (code-review finding, 2026-08-27)."""
    stale = tmp_path / "v1.0.0"
    stale.mkdir()
    (stale / "marker").write_text("stale")

    tarball = _make_release_tarball(
        "export-dir", {"install.sh": b"#!/bin/bash\n"}
    )
    wrong_digest = "0" * 64
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, wrong_digest.encode("ascii")),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None
    assert stale.exists()
    assert (stale / "marker").read_text() == "stale"


def test_download_release_rejects_malformed_checksum_asset(
    tmp_path, monkeypatch
):
    tarball = _make_release_tarball(
        "export-dir", {"install.sh": b"#!/bin/bash\n"}
    )
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, b"not-a-hex-digest"),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None
    assert not (tmp_path / "v9.9.9").exists()


def test_download_release_extracts_and_locates_install_sh(
    tmp_path, monkeypatch
):
    tarball = _make_release_tarball(
        "dlucca1986-SteamMachine-DIY-abc123",
        {"install.sh": b"#!/bin/bash\necho hi\n"},
    )
    digest = hashlib.sha256(tarball).hexdigest()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, digest.encode("ascii")),
    )

    info = _fake_release_info()
    result = utils.download_release(info, tmp_path)

    assert result is not None
    assert result.dir.name == "dlucca1986-SteamMachine-DIY-abc123"
    assert (result.dir / "install.sh").is_file()
    assert result.install_sh_sha256 == hashlib.sha256(
        b"#!/bin/bash\necho hi\n"
    ).hexdigest()


def test_download_release_returns_none_when_install_sh_is_missing(
    tmp_path, monkeypatch
):
    tarball = _make_release_tarball("export-dir", {"README.md": b"hi"})
    digest = hashlib.sha256(tarball).hexdigest()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, digest.encode("ascii")),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None


def test_download_release_returns_none_for_empty_tarball(
    tmp_path, monkeypatch
):
    """Regression: a checksum-verified tarball with zero members never
    makes tarfile.extractall() create the destination directory, so
    target.iterdir() used to raise FileNotFoundError uncaught -- the
    'None on any failure' contract the docstring promises must hold even
    for this structurally-empty-but-valid case."""
    tarball = _make_release_tarball("export-dir", {})
    digest = hashlib.sha256(tarball).hexdigest()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, digest.encode("ascii")),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None


def test_download_release_missing_install_sh_preserves_stale_cache(
    tmp_path, monkeypatch
):
    """Regression: pruning must happen only after install.sh is confirmed
    present, not merely after checksum verification — a checksum-valid
    but malformed release must not cost the last known-good previously
    cached release either (code-review finding, 2026-08-27)."""
    stale = tmp_path / "v1.0.0"
    stale.mkdir()
    (stale / "marker").write_text("stale")

    tarball = _make_release_tarball("export-dir", {"README.md": b"hi"})
    digest = hashlib.sha256(tarball).hexdigest()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, digest.encode("ascii")),
    )

    info = _fake_release_info()
    assert utils.download_release(info, tmp_path) is None
    assert stale.exists()
    assert (stale / "marker").read_text() == "stale"


def test_download_release_prunes_stale_versions_first(tmp_path, monkeypatch):
    stale = tmp_path / "v1.0.0"
    stale.mkdir()
    (stale / "marker").write_text("stale")

    tarball = _make_release_tarball(
        "export-dir", {"install.sh": b"#!/bin/bash\n"}
    )
    digest = hashlib.sha256(tarball).hexdigest()
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen(tarball, digest.encode("ascii")),
    )

    info = _fake_release_info()
    utils.download_release(info, tmp_path)

    assert not stale.exists()


# ---------------------------------------------------------------------------
# verify_file_sha256 — TOCTOU re-check between download and pkexec exec
# (updater.py::_on_download re-verifies install.sh with this right before
# handing it to pkexec, since a blocking dialog sits between the
# checksum-verified download and actual privileged execution).
# ---------------------------------------------------------------------------


def test_verify_file_sha256_accepts_untampered_file(tmp_path):
    target = tmp_path / "install.sh"
    target.write_bytes(b"#!/bin/bash\necho hi\n")
    digest = hashlib.sha256(b"#!/bin/bash\necho hi\n").hexdigest()

    assert utils.verify_file_sha256(target, digest) is True


def test_verify_file_sha256_rejects_tampered_file(tmp_path):
    """Regression: a file swapped after the original hash was taken must
    fail verification, not silently pass — this is what closes the
    TOCTOU window between download-time checksum and pkexec execution."""
    target = tmp_path / "install.sh"
    target.write_bytes(b"#!/bin/bash\necho hi\n")
    original_digest = hashlib.sha256(b"#!/bin/bash\necho hi\n").hexdigest()

    target.write_bytes(b"#!/bin/bash\nrm -rf /\n")  # tampered after hashing

    assert utils.verify_file_sha256(target, original_digest) is False


def test_verify_file_sha256_rejects_missing_file(tmp_path):
    missing = tmp_path / "install.sh"
    assert utils.verify_file_sha256(missing, "a" * 64) is False


# ---------------------------------------------------------------------------
# _fetch_expected_sha256 — pure parsing/network guard, isolated from extraction
# ---------------------------------------------------------------------------


def test_fetch_expected_sha256_rejects_non_https_url(monkeypatch):
    def _fail_if_called(*_a, **_k):
        raise AssertionError("urlopen must not run for a non-https URL")

    monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)
    assert (
        utils._fetch_expected_sha256("http://example.invalid/sums") is None
    )


def test_fetch_expected_sha256_parses_valid_digest(monkeypatch):
    digest = "a" * 64
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: io.BytesIO(digest.encode("ascii")),
    )
    assert utils._fetch_expected_sha256(_CHECKSUM_URL) == digest


def test_fetch_expected_sha256_rejects_short_digest(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout: io.BytesIO(b"deadbeef"),
    )
    assert utils._fetch_expected_sha256(_CHECKSUM_URL) is None


# ---------------------------------------------------------------------------
# default_games_conf_dir
# ---------------------------------------------------------------------------


def test_default_games_conf_dir_under_user_config_home(monkeypatch, tmp_path):
    """Pins the shared fallback sdy.py and control_center.py must agree on.

    sdy.py used to hardcode an unrelated, never-created "/etc/steamos_diy/
    games.d" as its own fallback — a dead path that would silently
    diverge from where control_center.py actually saves per-game
    profiles if the SSoT's games_conf_dir key were ever unset.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    assert utils.default_games_conf_dir() == tmp_path / (
        ".config/steamos_diy/games.d"
    )


# ---------------------------------------------------------------------------
# fix_ownership — subprocess timeout discipline (CLAUDE.md review checklist
# item 14): a wedged `chown -R` must be logged and swallowed, not left to
# hang backup/restore indefinitely.
# ---------------------------------------------------------------------------


def test_fix_ownership_swallows_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(
        utils.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000),
    )

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="chown", timeout=30)

    monkeypatch.setattr(utils.subprocess, "run", fake_run)

    utils.fix_ownership(tmp_path, "someuser")  # must not raise
