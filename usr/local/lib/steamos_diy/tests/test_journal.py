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


def test_parse_export_format_survives_garbled_timestamp_line():
    stdout = "\n".join(
        [
            "__REALTIME_TIMESTAMP=garbage",
            "SYSLOG_IDENTIFIER=CORE",
            "MESSAGE=first entry",
            "__REALTIME_TIMESTAMP=1700000000000000",
            "SYSLOG_IDENTIFIER=STEAM",
            "MESSAGE=second entry",
        ]
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
