"""Regression tests for journal.py's export-format parsing safety.

Before the fix, a malformed __REALTIME_TIMESTAMP= (corrupted journal, or
a MESSAGE field that flips journalctl into binary-safe encoding) raised
an uncaught ValueError/UnicodeDecodeError that neither control_center.py
except clause covers — the Diagnostics tab got stuck on "Loading
logs..." forever. These tests pin the graceful-degrade behavior."""

import subprocess
from datetime import datetime

import journal


def test_consume_export_line_malformed_timestamp_does_not_raise():
    cur = {}
    result = journal._consume_export_line(
        "__REALTIME_TIMESTAMP=not-a-number", cur, set()
    )
    assert result is None
    assert "ts" not in cur


def test_finalize_export_entry_falls_back_to_now_on_missing_ts():
    cur = {"id": "SYSTEM"}
    ts, line = journal._finalize_export_entry("MESSAGE=hello", cur, set())
    assert isinstance(ts, datetime)
    assert "hello" in line


# ---------------------------------------------------------------------------
# parse_game_logs — per-pid attribution
#
# Before the fix, a single global "current name" was reassigned on every
# NAME line regardless of which process logged it, so an ID line from one
# process could get attributed to a different, more-recently-seen game.
# ---------------------------------------------------------------------------


def test_parse_game_logs_attributes_appid_to_its_own_process():
    lines = 'chdir "/home/user/.steam/steamapps/common/GameA"\ngameID 220'
    assert journal.parse_game_logs(lines) == {"GameA": "220"}


def test_parse_game_logs_does_not_cross_attribute_interleaved_processes():
    lines = (
        "Aug 26 09:41:07 steam[1001]: "
        'chdir "/home/user/.steam/steamapps/common/GameA"\n'
        "Aug 26 09:41:07 steam[1002]: "
        'chdir "/home/user/.steam/steamapps/common/GameB"\n'
        "Aug 26 09:41:08 steam[1002]: gameID 730\n"
        "Aug 26 09:41:08 steam[1001]: gameID 220"
    )

    detected = journal.parse_game_logs(lines)

    assert detected["GameA"] == "220"
    assert detected["GameB"] == "730"


def test_parse_export_format_survives_garbled_timestamp_line():
    stdout = (
        "__REALTIME_TIMESTAMP=garbage\n"
        "SYSLOG_IDENTIFIER=CORE\n"
        "MESSAGE=first entry\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "SYSLOG_IDENTIFIER=STEAM\n"
        "MESSAGE=second entry"
    )

    entries = journal.parse_export_format(stdout, set())

    assert len(entries) == 2
    assert "first entry" in entries[0][1]
    assert "second entry" in entries[1][1]


def test_fetch_tagged_entries_decodes_with_replace(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(journal.subprocess, "run", fake_run)

    journal.fetch_tagged_entries("ALL", set())

    assert captured.get("errors") == "replace"


# ---------------------------------------------------------------------------
# subprocess timeout discipline (CLAUDE.md review checklist item 14) —
# every journalctl call must bound how long it can block, since this runs
# on a handheld that can wedge or lose power mid-operation.
# ---------------------------------------------------------------------------


def test_fetch_tagged_entries_passes_a_timeout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(journal.subprocess, "run", fake_run)

    journal.fetch_tagged_entries("ALL", set())

    assert captured.get("timeout") is not None


def test_fetch_tagged_entries_propagates_timeout_to_caller(monkeypatch):
    """No local try/except here by design (see docstring: "error handling
    is the caller's concern") — a hung journalctl must still surface as
    TimeoutExpired, not hang the whole process."""

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="journalctl", timeout=10)

    monkeypatch.setattr(journal.subprocess, "run", fake_run)

    try:
        journal.fetch_tagged_entries("ALL", set())
        assert False, "expected TimeoutExpired to propagate"
    except subprocess.TimeoutExpired:
        pass


def test_run_journalctl_iso_returns_empty_on_timeout(monkeypatch):
    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="journalctl", timeout=10)

    monkeypatch.setattr(journal.subprocess, "run", fake_run)

    assert journal._run_journalctl_iso() == ""


# ---------------------------------------------------------------------------
# Gamescope/export timestamp mixing (control_center.py's load_logs sorts
# fetch_tagged_entries + fetch_gamescope_logs together for tag ALL/STEAM).
#
# Before the fix, _split_gamescope_line stripped tzinfo from its parsed
# timestamp while _finalize_export_entry's timestamps stayed timezone-aware
# (via .astimezone()). Mixing aware/naive datetimes in the same sort() call
# raises TypeError, uncaught by load_logs's except clause — the Diagnostics
# tab got stuck on "Loading logs..." forever whenever a real gamescope
# session ran alongside any CORE/STEAM/SYSTEM activity (the default ALL tag
# hits this on every normal session).
# ---------------------------------------------------------------------------


def test_split_gamescope_line_returns_timezone_aware_timestamp():
    ts, _ = journal._split_gamescope_line(
        "2026-08-27T21:40:00+02:00 host python3[5496]: "
        "[gamescope] [Info]  console: gamescope version 3.16.25"
    )
    assert ts.tzinfo is not None


def test_gamescope_and_export_entries_sort_together_without_raising():
    export_stdout = (
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "SYSLOG_IDENTIFIER=STEAM\n"
        "MESSAGE=LAUNCH_ARGS: /usr/bin/gamescope --foo"
    )
    export_entries = journal.parse_export_format(export_stdout, set())
    gamescope_entries = [
        journal._parse_gamescope_line(
            "2026-08-27T21:40:00+02:00 host python3[5496]: "
            "[gamescope] [Info]  console: gamescope version 3.16.25",
            set(),
        )
    ]
    merged = export_entries + gamescope_entries
    merged.sort(key=lambda x: x[0])  # must not raise TypeError
    assert len(merged) == 2
