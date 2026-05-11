#!/usr/bin/env python3
"""
# =============================================================================
# PROJECT:      SteamMachine-DIY - Game Discovery Engine (SDY)
# VERSION:      1.3.4 (Wrapper and Native Discovery)
# DESCRIPTION:  Executes games with per-game overrides and global manifesto.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/sdy.py
# LICENSE:      MIT
# =============================================================================
"""

import os
import shlex
import shutil
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
    """Return True if the first _HEADER_READ_BYTES of *path* contain any term.

    Args:
        path: File to inspect.
        search_terms: Terms to look for as substrings in the header.

    Returns:
        True if the file is readable and at least one term appears in
        its head; False on read errors or no match.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            header = fh.read(_HEADER_READ_BYTES)
    except OSError:
        return False
    return any(term in header for term in search_terms)


def _iter_yaml_files(directory: str):
    """Yield ``os.DirEntry`` for every *.yaml file in *directory*.

    Yields nothing on scandir failures (logged at DEBUG level).
    """
    try:
        for entry in os.scandir(directory):
            if entry.is_file() and entry.name.endswith(".yaml"):
                yield entry
    except OSError as err:
        jlog("CORE", f"SCAN_ERROR: {directory} - {err}", level="DEBUG")


def _find_profile_by_id(directory: str, appid: str) -> str | None:
    """Scan YAML headers in *directory* for a STEAM_APPID or SDY_ID match.

    Reads only the first _HEADER_READ_BYTES of each file to avoid full YAML
    parsing — profile headers are always at the top of the file by convention.

    Args:
        directory: Absolute path to the directory containing *.yaml profiles.
        appid: Steam AppID or SDY_ID to look for, as a string.

    Returns:
        Absolute path of the first matching profile file, or None if no
        match is found or the directory cannot be read.
    """
    if not appid or not os.path.isdir(directory):
        return None

    search_terms = (f"STEAM_APPID: {appid}", f"SDY_ID: {appid}")

    for entry in _iter_yaml_files(directory):
        if _file_header_matches(entry.path, search_terms):
            return entry.path

    return None


def _resolve_effective_name(raw_args: list[str]) -> tuple[str, str]:
    """Derive (stem, effective_name) from the target executable in *raw_args*.

    Walks *raw_args* from the end looking for the first argument that is an
    existing absolute path (e.g. the actual game binary, not a wrapper flag).
    Falls back to the first argument resolved as absolute when no match is
    found.

    If the executable stem is in _GENERIC_STEMS (e.g. "start", "launcher")
    the parent directory name is used as effective_name instead — this is
    much more useful for profile lookup than a generic word.

    Args:
        raw_args: Original argv received by sdy (without sys.argv[0]).

    Returns:
        A (stem, effective_name) tuple of strings. Both are non-empty.
    """
    target_path = next(
        (
            a
            for a in reversed(raw_args)
            if a.startswith("/") and os.path.exists(a)
        ),
        os.path.abspath(raw_args[0]),
    )

    stem = Path(target_path).stem
    parent = Path(target_path).parent.name

    eff_name = parent if stem.lower() in _GENERIC_STEMS else stem
    return stem, eff_name


def _get_profile_path(
    game_conf_dir: str, steam_appid: str | None, stem: str, eff_name: str
) -> str | None:
    """Hierarchical profile lookup: AppID first, then by-name fallbacks.

    Resolution order (first hit wins):
        1. YAML file whose header declares STEAM_APPID/SDY_ID == *steam_appid*
        2. <game_conf_dir>/<eff_name>.yaml
        3. <game_conf_dir>/<stem>.yaml

    Args:
        game_conf_dir: Directory containing per-game *.yaml profiles.
        steam_appid: Steam AppID set by Steam in the env, or None for non-Steam
            launches.
        stem: Raw executable stem (e.g. "start" from "start.sh").
        eff_name: Effective name after _resolve_effective_name normalisation.

    Returns:
        Absolute path to the matching profile file, or None when no profile
        is found at any tier.
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


def _resolve_games_dir() -> str:
    """Return the directory containing per-game YAML profiles.

    Reads games_conf_dir directly from the SSoT config. Falls back to
    _FALLBACK_GAMES_DIR when the SSoT key is absent.

    Returns:
        Absolute path to the games.d directory. Existence is NOT checked
        here — the caller is responsible for graceful handling of missing
        directories (this is by design: profile resolution is best-effort
        and a missing directory simply means "no profile found").
    """
    conf_dir = get_ssot_var("games_conf_dir")
    if conf_dir:
        return conf_dir
    return _FALLBACK_GAMES_DIR


def _build_command(raw_args: list[str], profile_data: dict) -> list[str]:
    """Compose the final command line: wrapper + raw_args + extra_args.

    Reads GAME_WRAPPER and GAME_EXTRA_ARGS from the profile first, then from
    the environment. Profile values take precedence — this matches the SSoT
    layering used in the rest of the project.

    Args:
        raw_args: Original argv received from Steam (binary + steam args).
        profile_data: Parsed YAML profile (may be empty dict).

    Returns:
        Final argv list ready for os.execvpe.
    """
    wrapper = profile_data.get("GAME_WRAPPER") or os.getenv("GAME_WRAPPER", "")
    extra = profile_data.get("GAME_EXTRA_ARGS") or os.getenv(
        "GAME_EXTRA_ARGS", ""
    )

    full_cmd: list[str] = shlex.split(str(wrapper)) if wrapper else []
    full_cmd.extend(raw_args)
    if extra:
        full_cmd.extend(shlex.split(str(extra)))

    return full_cmd


def _load_profiles(
    user_config_path: str | None, found_path: str | None
) -> tuple[dict, dict]:
    """Load global manifesto and per-game profile.

    Args:
        user_config_path: SSoT user_config path or None.
        found_path: Resolved per-game profile path or None.

    Returns:
        Tuple ``(global_data, profile_data)``. Either may be an empty
        dict when the corresponding source is missing.
    """
    global_data = load_yaml_safe(user_config_path) if user_config_path else {}
    profile_data = load_yaml_safe(found_path) if found_path else {}
    return global_data, profile_data


def _exec_game(full_cmd: list[str], stem: str, steam_id: str | None) -> None:
    """Replace the current process with the resolved game command.

    Logs the launch and never returns on success — ``os.execvpe`` swaps
    the running process image with *full_cmd*. On failure (binary not
    found, permission denied, etc.) logs the error and exits with 1.

    Args:
        full_cmd: Full argv list for the game (wrapper + game + extra).
        stem: Executable stem, used in the launch log.
        steam_id: Steam AppID for the launch log; "N/A" when missing.
    """
    try:
        executable = shutil.which(full_cmd[0])
        if not executable:
            raise FileNotFoundError(f"Binary not found: {full_cmd[0]}")
        jlog("STEAM", f"GAME_LAUNCH: {stem} (AppID: {steam_id or 'N/A'})")
        os.execvpe(executable, full_cmd, os.environ)  # nosec B606
    except (OSError, FileNotFoundError, PermissionError) as err:
        jlog("STEAM", f"EXECUTION_FAILED: {err}", level="ERROR")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    """Resolve profile, apply environment and exec the game (zero-fork).

    Discovery flow:
        1. Resolve the games.d directory from the SSoT.
        2. Derive stem / effective name from raw argv.
        3. Look up a profile by AppID -> effective name -> stem.
        4. Apply environment in SSoT order: global manifesto, then profile.
        5. Build the final command (wrapper + game + extra args).
        6. os.execvpe the result so the game replaces this Python process,
           leaving Steam parented directly to the game (zero-fork).

    Exits with status 1 on launch failure; never returns on success because
    the process image is replaced by the game.
    """
    if len(sys.argv) < 2:
        return

    raw_args = sys.argv[1:]

    # 1. Resolve paths via SSoT
    user_config_path = get_ssot_var("user_config")
    game_conf_dir = _resolve_games_dir()

    # 2. Derive lookup keys from argv
    stem, eff_name = _resolve_effective_name(raw_args)
    steam_id = os.getenv("SteamAppId")

    # 3. Load profile and global manifesto
    found_path = _get_profile_path(game_conf_dir, steam_id, stem, eff_name)
    global_data, profile_data = _load_profiles(user_config_path, found_path)

    # 4. Apply environment (SSoT order: global -> profile)
    apply_env_map(global_data.get("env_vars"))
    apply_env_map(profile_data.get("env_vars"))

    # 5. Build final command
    full_cmd = _build_command(raw_args, profile_data)

    # 6. Zero-fork hand-off — Python is replaced by the game process
    _exec_game(full_cmd, stem, steam_id)


if __name__ == "__main__":
    run()
