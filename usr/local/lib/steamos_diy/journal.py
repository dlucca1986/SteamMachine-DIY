#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Journal/Log Backend
# VERSION:      2.1.9
# DESCRIPTION:  journalctl invocation and journal/gamescope log parsing.
#               No Qt dependency — testable in isolation.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/journal.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import re

# B404: every subprocess call below passes an argv list and never uses
# shell=True, so no value (even one from the user's config) is parsed by
# a shell.
import subprocess  # nosec B404
from datetime import datetime
from typing import Any

from utils import JOURNALCTL_BIN, SYSTEMD_CALL_TIMEOUT, jlog

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GAME_LOG_TAIL: int = 2000
_MICROSECONDS_PER_SECOND: int = 1_000_000

_GAME_LOG_NOISE = re.compile(r"GpuTopology|steamui|/steamapps/common$|bin/")

# journalctl's default "short" line format (used with --no-hostname) is
# "<timestamp> <syslog-identifier>[<pid>]: <message>" — the pid lets us
# attribute a NAME/ID pair to the process that actually logged it.
_PID_FROM_LINE = re.compile(r"\[(\d+)\]:")

# Allow-list for genuine gamescope log payloads (upstream output format).
# Excludes false positives where "gamescope" appears only as a substring
# inside file paths (e.g. Dolphin/kio copying gamescope.example.yaml) or
# inside steam wrapper noise (steam.sh boot messages).
_GAMESCOPE_PAYLOAD = re.compile(
    r"\[(?:Info|Warn|Error|Gamescope WSI)\]|/usr/bin/gamescope:"
)


# ---------------------------------------------------------------------------
# Journalctl invocation
# ---------------------------------------------------------------------------


def get_journal_cmd(tag: str) -> list[str]:
    """Build journalctl argv for *tag*; ALL expands to all known SDY tags."""
    base_cmd = [
        JOURNALCTL_BIN,
        "--since",
        "12 hours ago",
        "-n",
        "300",
        "--no-hostname",
        "--no-pager",
        "-o",
        "export",
    ]
    tag_args = {
        "ALL": ["-t", "CORE", "-t", "STEAM", "-t", "SYSTEM"],
        "CORE": ["-t", "CORE"],
        "STEAM": ["-t", "STEAM"],
        "SYSTEM": ["-t", "SYSTEM"],
    }
    return base_cmd + tag_args.get(tag, ["-t", tag])


# ---------------------------------------------------------------------------
# Game metadata extraction
# ---------------------------------------------------------------------------


def _normalize_appid(value: str) -> str:
    """Collapse Non-Steam shortcut AppIDs to their 32-bit real form.

    Steam logs Non-Steam AppIDs as 64-bit integers: high 32 bits = real
    AppID (matches $SteamAppId), low 32 bits = internal flag mask.
    Anything wider than 32 bits is shifted down.
    """
    try:
        n = int(value)
    except ValueError:
        return value
    if n.bit_length() > 32:
        return str(n >> 32)
    return value


def extract_game_metadata(line: str) -> tuple[str | None, str | None]:
    """Extract ("NAME", name) or ("ID", appid) from a raw journal export line.

    NAME is derived from chdir entries; ID from gameID/AppID patterns.
    AppIDs wider than 32 bits are normalised via _normalize_appid.
    Returns (None, None) when no metadata is found.
    """
    if 'chdir "' in line:
        match = re.search(r'chdir\s+"([^"]+)"', line)
        if match:
            return "NAME", os.path.basename(match.group(1).rstrip("/"))

    match_id = re.search(r"(?:gameID|AppID\s*=\s*)\s*(\d+)", line)
    if match_id:
        return "ID", _normalize_appid(match_id.group(1))
    return (None, None)


# ---------------------------------------------------------------------------
# Game launch detection
# ---------------------------------------------------------------------------


def filter_game_journal_lines(stdout: str, home: str) -> list[str]:
    """Return last _GAME_LOG_TAIL game-launch lines from journalctl output."""
    # Trailing "/" so a chdir into another user's home ("/home/deck2/...")
    # can't false-positive-match this user's home ("/home/deck") — same
    # boundary reasoning as restore.py::_allowed_prefixes.
    chdir_marker = f'chdir "{home}/'
    matched = [
        line
        for line in stdout.splitlines()
        if (chdir_marker in line or "gameID " in line or "AppID = " in line)
        and not _GAME_LOG_NOISE.search(line)
    ]
    return matched[-_GAME_LOG_TAIL:]


def parse_game_logs(res: str) -> dict[str, str]:
    """Extract {name: appid_or_name} pairs from filtered journal text.

    Tracks the last-seen NAME per source pid, so interleaved lines from
    two processes (two games launched close together) can't attribute one
    game's AppID to the other's name. A line without a [pid]: suffix is
    never correlated: its NAME is still recorded (mapped to itself), but a
    pid-less ID line is attributed to no name.

    No minimum length on the ID: it is only matched after a literal
    "gameID"/"AppID = " token, and some real AppIDs have 1-2 digits
    (10 = Counter-Strike, 70 = Half-Life).
    """
    det: dict[str, str] = {}
    cur_by_pid: dict[str, str] = {}
    for line in res.splitlines():
        kind, value = extract_game_metadata(line)
        pid_match = _PID_FROM_LINE.search(line)
        if kind == "NAME" and value:
            det[value] = value
            if pid_match:
                cur_by_pid[pid_match.group(1)] = value
        elif kind == "ID" and value and pid_match:
            cur = cur_by_pid.get(pid_match.group(1))
            if cur:
                det[cur] = value
    return det


# ---------------------------------------------------------------------------
# SDY/Steam export-format journal parsing
# ---------------------------------------------------------------------------


def parse_export_format(
    stdout: str, launches: set[str]
) -> list[tuple[datetime, str]]:
    """Parse ``journalctl -o export`` into (timestamp, line) tuples.

    Args:
        stdout: Raw export-format journalctl output.
        launches: Mutated in place — LAUNCH_ARGS added for dedup.

    Returns:
        (datetime, formatted_line) list in arrival order.
    """
    ents: list[tuple[datetime, str]] = []
    cur: dict[str, Any] = {}
    for line in stdout.splitlines():
        entry = _consume_export_line(line, cur, launches)
        if entry is not None:
            ents.append(entry)
            cur = {}
    return ents


def _consume_export_line(
    line: str,
    cur: dict[str, Any],
    launches: set[str],
) -> tuple[datetime, str] | None:
    """Accumulate one export-format field; return entry on MESSAGE=.

    Args:
        line: Single export-format line.
        cur: Accumulator dict for the current record (mutated in place).
        launches: Mutated — LAUNCH_ARGS strings added as a side effect.

    Returns:
        (datetime, formatted_line) on MESSAGE= terminator, else None.
    """
    if line.startswith("__REALTIME_TIMESTAMP="):
        try:
            cur["ts"] = datetime.fromtimestamp(
                int(line.split("=", 1)[1]) / _MICROSECONDS_PER_SECOND
            ).astimezone()
        except (ValueError, OSError, OverflowError):
            # Malformed/truncated timestamp (corrupted journal): leave "ts"
            # unset — _finalize_export_entry already falls back to
            # datetime.now() for a missing key, same as a dropped field.
            pass
        return None
    if line.startswith("SYSLOG_IDENTIFIER="):
        cur["id"] = line.split("=", 1)[1]
        return None
    if line.startswith("MESSAGE="):
        return _finalize_export_entry(line, cur, launches)
    return None


def _finalize_export_entry(
    line: str, cur: dict[str, Any], launches: set[str]
) -> tuple[datetime, str]:
    msg = line.split("=", 1)[1]
    ident = cur.get("id", "SYSTEM")
    ts = cur.get("ts", datetime.now().astimezone())
    if ident == "STEAM" and "LAUNCH_ARGS" in msg:
        launches.add(msg.split("LAUNCH_ARGS:", 1)[-1].strip())
    return (ts, f"[{ts.strftime('%H:%M:%S')}] {ident}: {msg}")


def fetch_tagged_entries(
    tag: str, launches: set[str]
) -> list[tuple[datetime, str]]:
    """Run journalctl for *tag* and parse into (timestamp, line) entries.

    Shared by the Diagnostics view and the support-report export. Raises
    subprocess.SubprocessError (includes TimeoutExpired)/OSError — error
    handling is the caller's concern. errors="replace" keeps decoding
    itself from ever raising: a MESSAGE field with an embedded newline
    flips journalctl's export format to binary-safe encoding, which is
    not guaranteed valid UTF-8.
    """
    # argv list, no shell: the tag reaches journalctl as a single "-t"
    # value (always one of the Diagnostics tab's four fixed choices).
    res = subprocess.run(  # nosec B603
        get_journal_cmd(tag),
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
        timeout=SYSTEMD_CALL_TIMEOUT,
    )
    return parse_export_format(res.stdout, launches)


# ---------------------------------------------------------------------------
# Gamescope log parsing
# ---------------------------------------------------------------------------


def fetch_gamescope_logs(launches: set[str]) -> list[tuple[datetime, str]]:
    """Pull gamescope journal lines, skipping echoes of known *launches*.

    Args:
        launches: LAUNCH_ARGS already emitted — prevents duplicate display.

    Returns:
        (datetime, formatted_line) list ready for merge-sort.
    """
    stdout = _run_journalctl_iso()
    if not stdout:
        return []

    ents = []
    for line in stdout.splitlines():
        if not _GAMESCOPE_PAYLOAD.search(line):
            continue
        entry = _parse_gamescope_line(line, launches)
        if entry is not None:
            ents.append(entry)
    return ents


def _run_journalctl_iso() -> str:
    """Pull last hour of gamescope-bearing identifiers.

    `python3` is the service's stdout/stderr stream, which gamescope
    inherits from session_launch.py, so gamescope's own output is logged
    under it. `steam` is Steam's own logger, which carries the
    "[Gamescope WSI]" lines of the Vulkan apps Steam starts. Narrowing to
    these two keeps Dolphin/plasmashell noise out.
    """
    try:
        # Fixed argv, no shell — the identifiers below are hardcoded.
        res = subprocess.run(  # nosec B603
            [
                JOURNALCTL_BIN,
                "-t",
                "steam",
                "-t",
                "python3",
                "--since",
                "1 hour ago",
                "-o",
                "short-iso",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=SYSTEMD_CALL_TIMEOUT,
        )
        return res.stdout or ""
    except (OSError, subprocess.SubprocessError) as err:
        # Degrades to "" (gamescope lines are an extra), but logged so a
        # real journalctl failure isn't mistaken for "no gamescope
        # activity in the last hour".
        jlog("SYSTEM", f"GAMESCOPE_LOG_FETCH_FAIL: {err}", level="WARN")
        return ""


def _parse_gamescope_line(
    line: str, launches: set[str]
) -> tuple[datetime, str] | None:
    """Parse one gamescope line; return None if duplicate or malformed."""
    parsed = _split_gamescope_line(line)
    if parsed is None:
        return None
    ts, msg = parsed
    if _is_duplicate_launch(msg, launches):
        return None
    d_msg = msg if "[gamescope]" in msg else f"[gamescope] {msg}"
    return (ts, f"[{ts.strftime('%H:%M:%S')}] {d_msg}")


def _split_gamescope_line(line: str) -> tuple[datetime, str] | None:
    try:
        ps = line.split(" ", 2)
        if len(ps) < 3:
            return None
        # Timezone-aware, matching _finalize_export_entry's .astimezone()
        # entries — load_logs() sorts both lists together (tag ALL/STEAM),
        # and mixing aware/naive datetimes raises TypeError there.
        ts = datetime.fromisoformat(ps[0])
        msg = (
            ps[2].split(": ", 1)[1].strip() if ": " in ps[2] else ps[2].strip()
        )
        return ts, msg
    except (IndexError, ValueError):
        return None


def _is_duplicate_launch(msg: str, launches: set[str]) -> bool:
    if "LAUNCH_ARGS" not in msg:
        return False
    arg = msg.split("LAUNCH_ARGS:", 1)[-1].strip()
    return arg in launches
