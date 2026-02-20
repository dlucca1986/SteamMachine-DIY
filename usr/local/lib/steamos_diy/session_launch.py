#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Session Launcher
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Core Session Manager with Dynamic Gamescope Mapping.
#               Handles seamless transitions between Steam and Desktop.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/session_launch.py
# LICENSE:      MIT
# =============================================================================

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

import yaml  # Import standard per conformità Pylint


def qlog(tag, msg):
    """Print 'TAG: message' - Format for Systemd and Control Center."""
    print(f"{tag}: {msg}", flush=True)


def write_atomic(path, val):
    """
    Atomic write with SSD protection.
    Only writes if the new value differs from the current on-disk content.
    """
    p = Path(path)
    new_val = str(val).strip()

    # --- SSD PROTECTION: Read-before-write ---
    if p.exists():
        try:
            if p.read_text(encoding="utf-8").strip() == new_val:
                # No change detected, skipping write to save SSD cycles
                return
        except OSError:
            pass

    # --- ATOMIC WRITE: Standard procedure ---
    tmp = p.with_suffix(".tmp")
    try:
        tmp.write_text(new_val, encoding="utf-8")
        tmp.replace(p)
    except OSError as e:
        qlog("ENGINE", f"WRITE_ERROR: {e}")


def load_ssot():
    """Inject SSoT directly into os.environ (Instant load)."""
    conf_path = os.getenv("SSOT_CONF", "/etc/default/steamos_diy.conf")
    try:
        content = Path(conf_path).read_text(encoding="utf-8")
        for line in content.splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")
        return True
    except OSError:
        return False


def get_gamescope_args():
    """Build gamescope arguments from YAML config."""
    gs_args = [os.getenv("bin_gs", "gamescope"), "-e", "-f"]
    user_cfg = os.getenv("user_config")

    if user_cfg and Path(user_cfg).exists():
        try:
            with open(user_cfg, "r", encoding="utf-8") as file:
                cfg = yaml.safe_load(file)
                if cfg:
                    # 1. Environment Variable Injection
                    for key, val in (cfg.get("env_vars") or {}).items():
                        os.environ[str(key)] = str(val)

                    # 2. Flag Injection
                    for flag in cfg.get("flags") or []:
                        if flag:
                            gs_args.extend(shlex.split(str(flag)))
        except (yaml.YAMLError, OSError) as e:
            qlog("ENGINE", f"CONFIG_LOAD_ERROR: {e}")

    # Final command construction
    gs_args.extend(
        ["--", os.getenv("bin_steam", "steam"), "-gamepadui", "-steamos3"]
    )
    return gs_args


def run():
    """Execute the target session with safety monitoring."""
    if not load_ssot():
        qlog("ENGINE", "CRITICAL: SSOT load failed")
        return

    qlog("LAUNCH", "BOOT_OK")
    next_sess = os.getenv("next_session", "/var/lib/steamos_diy/next_session")

    try:
        target = Path(next_sess).read_text(encoding="utf-8").strip()
    except OSError:
        target = "steam"

    if target == "steam":
        cmd = get_gamescope_args()
        sub_tag = "GAMESCOPE"
        qlog("GAMESCOPE", f"ARGS: {' '.join(cmd)}")
    else:
        cmd = [os.getenv("bin_plasma", "startplasma-wayland")]
        sub_tag = "LAUNCH"

    qlog(sub_tag, f"START_{target}")
    start_time = time.time()

    # Direct execution - pylint: disable=consider-using-with
    proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)

    # --- (5s Persistence Check) ---
    time.sleep(5)

    if proc.poll() is None:
        qlog("ENGINE", f"VALIDATED_{target}_PERSISTENT")
        write_atomic(next_sess, target)
    else:
        qlog("ENGINE", "CRASH_DETECTED: RECOVERY_TO_DESKTOP")
        write_atomic(next_sess, "desktop")

    proc.wait()
    duration = int(time.time() - start_time)
    qlog("LAUNCH", f"SESSION_END_AFTER_{duration}S")


if __name__ == "__main__":
    run()
