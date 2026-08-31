#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Game Discovery Engine (SDY)
# VERSION:      2.1.7
# DESCRIPTION:  Executes games with per-game overrides and global config.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/sdy.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import re
import sys
from pathlib import Path

from utils import (
    apply_env_map,
    default_games_conf_dir,
    get_ssot_var,
    jlog,
    load_yaml_safe,
    shlex_split_or_fallback,
)

# ---------------------------------------------------------------------------
# Module-level constants — resolved once at import, never re-read from disk.
# ---------------------------------------------------------------------------

# Generic executable stems that should be replaced by parent directory name
# when used as profile lookup keys (e.g. /opt/MyGame/start.sh -> "MyGame").
_GENERIC_STEMS: frozenset[str] = frozenset(
    {
        "start",
        "run",
        "launcher",
        "launch",
        "game",
        "main",
    }
)

# Bytes read from the head of each YAML file when scanning for an AppID.
# Headers are always at the top, so reading more would only waste I/O.
_HEADER_READ_BYTES: int = 1024

# ID declaration line in a profile header (value optionally quoted,
# inline comment tolerated). Anchored to end-of-line so an AppID can
# never prefix-match a longer one (searching 220 must not hit
# "SDY_ID: 2201290").
_ID_LINE = re.compile(
    r"(?:STEAM_APPID|SDY_ID):\s*[\"']?(\d+)[\"']?\s*(?:#.*)?$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Internal helpers — profile resolution
# ---------------------------------------------------------------------------


def _header_declares_id(path: str, appid: str) -> bool:
    """Check first _HEADER_READ_BYTES of *path* for an exact-ID header line."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            header = fh.read(_HEADER_READ_BYTES)
    except (OSError, UnicodeDecodeError):
        return False
    return any(m.group(1) == appid for m in _ID_LINE.finditer(header))


def _iter_yaml_files(directory: str):
    """Yield DirEntry for every *.yaml in *directory*; silent on error."""
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith(".yaml"):
                yield entry
    except OSError as err:
        jlog("CORE", f"SCAN_ERROR: {directory} - {err}", level="DEBUG")


def _find_profile_by_id(directory: str, appid: str) -> str | None:
    """Scan YAML headers for STEAM_APPID/SDY_ID match without full parsing.

    Reads only _HEADER_READ_BYTES per file — IDs live at the top by convention,
    full parsing would be pure waste.
    """
    if not appid or not os.path.isdir(directory):
        return None

    for entry in _iter_yaml_files(directory):
        if _header_declares_id(entry.path, appid):
            return entry.path

    return None


def _resolve_effective_name(raw_args: list[str]) -> tuple[str, str]:
    """Derive (stem, effective_name) from the rightmost absolute path in argv.

    When the stem is generic (start, launcher, run…), substitutes the parent
    directory name — /opt/MyGame/start.sh resolves to "MyGame", not "start".
    Rightmost, not first: a wrapper (mangohud, gamemoderun) commonly comes
    first in argv, with the actual game binary later — see the "rightmost"
    regression test. isfile (not just exists) skips a trailing directory
    argument (e.g. --workshop-dir /path/to/workshop) that would otherwise
    be mistaken for the game binary itself.
    """
    target_path = next(
        (
            a
            for a in reversed(raw_args)
            if a.startswith("/") and os.path.isfile(a)
        ),
        os.path.abspath(raw_args[0]),
    )

    p = Path(target_path)
    stem = p.stem
    parent = p.parent.name

    eff_name = parent if stem.lower() in _GENERIC_STEMS else stem
    return stem, eff_name


def _get_profile_path(
    game_conf_dir: str, steam_appid: str | None, stem: str, eff_name: str
) -> str | None:
    """Resolve profile with AppID > effective_name > stem precedence.

    First hit wins:
        1. Header-matched STEAM_APPID/SDY_ID in *game_conf_dir*
        2. <game_conf_dir>/<eff_name>.yaml
        3. <game_conf_dir>/<stem>.yaml
    """
    if steam_appid:
        found = _find_profile_by_id(game_conf_dir, steam_appid)
        if found:
            return found

    for name in (eff_name, stem):
        candidate = os.path.join(game_conf_dir, f"{name}.yaml")
        if os.path.exists(candidate):
            return candidate

    return None


def _safe_split(field: str, value: str) -> list[str]:
    """shlex.split *value*; on an unbalanced quote, fall back to str.split().

    A malformed per-game override must not stop the game from launching —
    same fallback health.py's preflight already uses for gamescope flags.
    """
    tokens, err = shlex_split_or_fallback(value)
    if err is not None:
        jlog("STEAM", f"BAD_{field}: {value!r} - {err}", level="WARN")
    return tokens


def _build_command(raw_args: list[str], profile_data: dict) -> list[str]:
    """Compose wrapper + raw_args + extra_args for execvpe.

    Profile values override env vars — mirrors SSoT layering semantics.
    None means "key absent" (fall back to env); "" means "explicitly empty"
    (disable the wrapper/extra for this profile, do not fall back).
    """
    wrapper_val = profile_data.get("GAME_WRAPPER")
    wrapper = (
        os.getenv("GAME_WRAPPER", "")
        if wrapper_val is None
        else str(wrapper_val)
    )

    extra_val = profile_data.get("GAME_EXTRA_ARGS")
    extra = (
        os.getenv("GAME_EXTRA_ARGS", "")
        if extra_val is None
        else str(extra_val)
    )

    full_cmd: list[str] = (
        _safe_split("GAME_WRAPPER", wrapper) if wrapper else []
    )
    full_cmd.extend(raw_args)
    if extra:
        full_cmd.extend(_safe_split("GAME_EXTRA_ARGS", extra))

    return full_cmd


def _exec_game(full_cmd: list[str], stem: str, steam_id: str | None) -> None:
    """execvpe the game, replacing this process. Never returns on success.

    Exits with 1 on binary-not-found, permission denied, or OS failure.
    """
    try:
        jlog("STEAM", f"GAME_LAUNCH: {stem} (AppID: {steam_id or 'N/A'})")
        # full_cmd comes from the user's own local YAML config (wrapper/
        # extra args), not from network or other-user input — same trust
        # level as a shell alias the user wrote for themselves.
        os.execvpe(full_cmd[0], full_cmd, os.environ)  # nosec B606
    except OSError as err:
        jlog("STEAM", f"EXECUTION_FAILED: {err}", level="ERROR")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Resolve profile and exec the game zero-fork.

    Flow: SSoT → argv → AppID/name lookup → env layering → execvpe.
    Exits with 1 on failure; never returns on success.
    """
    if len(sys.argv) < 2:
        jlog("STEAM", "NO_TARGET: sdy invoked with no argv", level="ERROR")
        sys.exit(1)

    raw_args = sys.argv[1:]

    user_config_path = get_ssot_var("user_config")
    game_conf_dir = get_ssot_var(
        "games_conf_dir", str(default_games_conf_dir())
    )

    stem, eff_name = _resolve_effective_name(raw_args)
    steam_id = os.getenv("SteamAppId")

    found_path = _get_profile_path(game_conf_dir, steam_id, stem, eff_name)
    global_data = load_yaml_safe(user_config_path)
    profile_data = load_yaml_safe(found_path)

    apply_env_map(global_data.get("env_vars"))
    apply_env_map(profile_data.get("env_vars"))

    full_cmd = _build_command(raw_args, profile_data)
    _exec_game(full_cmd, stem, steam_id)  # execvpe — replaces this process


if __name__ == "__main__":
    run()
