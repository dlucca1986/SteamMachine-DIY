#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Game Discovery Engine (SDY)
# VERSION:      2.0.0
# DESCRIPTION:  Executes games with per-game overrides and global manifesto.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/sdy.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import shlex
import sys
from pathlib import Path

from utils import apply_env_map, get_ssot_var, jlog, load_yaml_safe

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

# Fallback directory for per-game profile files (used when user_config is
# unavailable in the SSoT).
_FALLBACK_GAMES_DIR: str = "/etc/steamos_diy/games.d"

# Bytes read from the head of each YAML file when scanning for an AppID.
# Headers are always at the top, so reading more would only waste I/O.
_HEADER_READ_BYTES: int = 1024


# ---------------------------------------------------------------------------
# Internal helpers — profile resolution
# ---------------------------------------------------------------------------


def _file_header_matches(path: str, search_terms: tuple[str, ...]) -> bool:
    """Check first _HEADER_READ_BYTES of *path* for any of *search_terms*."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            header = fh.read(_HEADER_READ_BYTES)
    except OSError:
        return False
    return any(term in header for term in search_terms)


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

    search_terms = (f"STEAM_APPID: {appid}", f"SDY_ID: {appid}")

    for entry in _iter_yaml_files(directory):
        if _file_header_matches(entry.path, search_terms):
            return entry.path

    return None


def _resolve_effective_name(raw_args: list[str]) -> tuple[str, str]:
    """Derive (stem, effective_name) from the rightmost absolute path in argv.

    When the stem is generic (start, launcher, run…), substitutes the parent
    directory name — /opt/MyGame/start.sh resolves to "MyGame", not "start".
    """
    target_path = next(
        (
            a
            for a in reversed(raw_args)
            if a.startswith("/") and os.path.exists(a)
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

    full_cmd: list[str] = shlex.split(str(wrapper)) if wrapper else []
    full_cmd.extend(raw_args)
    if extra:
        full_cmd.extend(shlex.split(str(extra)))

    return full_cmd


def _exec_game(full_cmd: list[str], stem: str, steam_id: str | None) -> None:
    """execvpe the game, replacing this process. Never returns on success.

    Exits with 1 on binary-not-found, permission denied, or OS failure.
    """
    try:
        jlog("STEAM", f"GAME_LAUNCH: {stem} (AppID: {steam_id or 'N/A'})")
        os.execvpe(full_cmd[0], full_cmd, os.environ)  # nosec B606
    except (OSError, FileNotFoundError, PermissionError) as err:
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
        return

    raw_args = sys.argv[1:]

    # 1. Resolve paths via SSoT
    user_config_path = get_ssot_var("user_config")
    game_conf_dir = get_ssot_var("games_conf_dir", _FALLBACK_GAMES_DIR)

    # 2. Derive lookup keys from argv
    stem, eff_name = _resolve_effective_name(raw_args)
    steam_id = os.getenv("SteamAppId")

    # 3. Load profile and global manifesto
    found_path = _get_profile_path(game_conf_dir, steam_id, stem, eff_name)
    global_data = load_yaml_safe(user_config_path)
    profile_data = load_yaml_safe(found_path)

    # 4. Apply environment (SSoT order: global -> profile)
    apply_env_map(global_data.get("env_vars"))
    apply_env_map(profile_data.get("env_vars"))

    # 5. Build final command
    full_cmd = _build_command(raw_args, profile_data)

    # 6. Zero-fork hand-off — Python is replaced by the game process
    _exec_game(full_cmd, stem, steam_id)


if __name__ == "__main__":
    run()
