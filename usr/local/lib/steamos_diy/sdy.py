#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Game Discovery Engine (SDY)
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Executes games with per-game overrides and global manifesto.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/sdy.py
# LICENSE:      MIT
# =============================================================================

import os
import shlex
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


def log_msg(msg, tag="PROF"):
    """Print 'TAG: message' - PROF tag is used for Game Profile events."""
    print(f"{tag}: {msg}", flush=True)


def load_yaml_safe(path):
    """Resilient and safe YAML loader."""
    if yaml and path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return yaml.safe_load(file) or {}
        except (yaml.YAMLError, OSError) as e:
            log_msg(f"Error parsing YAML at {path}: {e}", "ERROR")
    return {}


def load_ssot():
    """Inject SSoT configuration into os.environ for child processes."""
    conf_path = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
    if not os.path.exists(conf_path):
        return

    try:
        with open(conf_path, "r", encoding="utf-8") as file:
            for line in file:
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
    except OSError as e:
        log_msg(f"Failed to load SSoT: {e}", "WARN")


def find_profile_by_id(directory, appid):
    """Scan YAML files content to find a matching STEAM_APPID."""
    if not appid or not directory.exists():
        return None

    for p in directory.glob("*.yaml"):
        try:
            content = p.read_text(encoding="utf-8")
            if (
                f"STEAM_APPID: {appid}" in content
                or f"SDY_ID: {appid}" in content
            ):
                return p
        except OSError:
            continue
    return None


def get_target_info(raw_args):
    """Determine the target executable path and an effective name."""
    target_path = None
    for arg in reversed(raw_args):
        if arg.startswith("/"):
            path_obj = Path(arg)
            if path_obj.exists():
                target_path = path_obj
                break

    if not target_path:
        target_path = Path(raw_args[0]).absolute()

    generic = {"start", "run", "launcher", "launch", "game"}
    eff_name = (
        target_path.parent.name
        if target_path.stem.lower() in generic
        else target_path.stem
    )
    return target_path, eff_name


def get_profile_path(game_conf_dir, steam_appid, target_path, eff_name):
    """Logic to find the best matching profile YAML."""
    if steam_appid:
        found = find_profile_by_id(game_conf_dir, steam_appid)
        if found:
            log_msg(f"Profile via AppID [{steam_appid}] -> {found.name}")
            return found

    stops = {"common", "steamapps", "GOG Games", "Games", "home", "bin"}
    curr_dir = target_path.parent
    for _ in range(3):
        if not curr_dir or curr_dir.name in stops:
            break
        checks = [
            game_conf_dir / f"{eff_name}.yaml",
            game_conf_dir / f"{target_path.stem}.yaml",
            game_conf_dir / f"{curr_dir.name}.yaml",
            game_conf_dir / f"{steam_appid}.yaml" if steam_appid else None,
        ]
        for path in filter(None, checks):
            if path.exists():
                return path
        curr_dir = curr_dir.parent
    return None


def build_cmd(profile_data, merged, raw_args):
    """Construct the final command list."""
    wrapper = profile_data.get("GAME_WRAPPER") or merged.get(
        "GAME_WRAPPER", ""
    )
    extra = profile_data.get("GAME_EXTRA_ARGS") or merged.get(
        "GAME_EXTRA_ARGS", ""
    )

    full_cmd = shlex.split(str(wrapper)) if wrapper else []
    full_cmd.extend(raw_args)
    if extra:
        full_cmd.extend(shlex.split(str(extra)))
    return full_cmd


def run():
    """Main execution flow."""
    if len(sys.argv) < 2:
        sys.exit(0)

    raw_args = sys.argv[1:]
    load_ssot()

    u_cfg = os.getenv(
        "user_config", os.path.expanduser("~/.config/steamos_diy/config.yaml")
    )
    game_conf_dir = Path(u_cfg).parent / "games.d"

    t_path, eff_name = get_target_info(raw_args)
    found_path = get_profile_path(
        game_conf_dir, os.getenv("SteamAppId"), t_path, eff_name
    )

    global_data = load_yaml_safe(u_cfg)
    profile_data = load_yaml_safe(found_path) if found_path else {}

    if found_path and not os.getenv("SteamAppId"):
        log_msg(f"Profile Loaded by Name: {found_path.name}")

    # Merge env_vars: Profiles override Global settings
    merged = global_data.get("env_vars", {}).copy()
    p_envs = profile_data.get("env_vars") or {}
    merged.update(p_envs)

    for k, v in merged.items():
        if v is not None:
            os.environ[str(k)] = str(v)

    full_cmd = build_cmd(profile_data, merged, raw_args)

    try:
        executable = shutil.which(full_cmd[0])
        if not executable:
            raise FileNotFoundError(f"Command not found: {full_cmd[0]}")
        log_msg(f"EXEC: {' '.join(full_cmd[:3])}...")
        os.execvpe(executable, full_cmd, os.environ)
    except (OSError, FileNotFoundError) as e:
        log_msg(f"FATAL ERROR: {e}", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    run()
