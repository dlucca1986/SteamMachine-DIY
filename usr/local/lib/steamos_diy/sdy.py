#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Game Discovery Engine (SDY)
# VERSION:      1.1.0 - Python
# DESCRIPTION:  Executes games with per-game overrides and global manifesto.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/bin/sdy.py
# =============================================================================

import os
import sys
import shlex
import subprocess
from pathlib import Path

def log_msg(msg):
    subprocess.run(["logger", "-t", "steamos-diy-sdy", f"[ENGINE] {msg}"], check=False)

def load_kv(path):
    """Carica file chiave=valore o flag singole."""
    conf = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        conf[k.strip()] = v.strip().strip('"').strip("'")
                    else:
                        # Gestione flag senza '=' (es. --rt)
                        conf[line] = True
    return conf

def run():
    # 1. IDENTIFICATION
    if len(sys.argv) < 2:
        print("Usage: sdy <command>")
        sys.exit(1)

    raw_args = sys.argv[1:]
    real_path = Path(raw_args[-1]).resolve()
    exe_name = real_path.stem

    # Carica SSoT Centrale
    ssot = load_kv("/etc/default/steamos_diy.conf")
    
    # Path di configurazione (allineati al Launcher)
    user_manifesto = ssot.get("user_config", "/home/lelo/.config/steamos_diy/config")
    game_conf_dir = Path(ssot.get("user_config")).parent / "games.d"
    game_conf_dir.mkdir(parents=True, exist_ok=True)

    specific_conf = None
    game_id = exe_name

    # 2. DISCOVERY LOOP (Climb up to 3 levels)
    stops = {"common", "steamapps", "GOG Games", "Games", "home", "bin"}
    current_dir = real_path.parent

    for _ in range(3):
        if not current_dir or current_dir.name in stops:
            break
        
        name_check = current_dir.name
        checks = [
            game_conf_dir / f"{exe_name}.conf",
            game_conf_dir / f"{name_check}.conf"
        ]

        for p in checks:
            if p.exists():
                specific_conf = p
                game_id = p.stem
                break
        if specific_conf:
            break

        current_dir = current_dir.parent

    # 3. MERGE CONFIGURATIONS (Global Manifesto + Specific Game)
    # Carichiamo il manifesto globale (per variabili d'ambiente comuni)
    final_env = os.environ.copy()
    global_cfg = load_kv(user_manifesto)
    
    # Iniezione variabili dal manifesto globale
    for k, v in global_cfg.items():
        if isinstance(v, str): # Solo se è una variabile K=V
            final_env[k] = v

    # Carichiamo override specifici del gioco (se esistono)
    wrapper = global_cfg.get("GAME_WRAPPER", "")
    extra_args = global_cfg.get("GAME_EXTRA_ARGS", "")

    if specific_conf:
        game_specific = load_kv(specific_conf)
        wrapper = game_specific.get("GAME_WRAPPER", wrapper)
        extra_args = game_specific.get("GAME_EXTRA_ARGS", extra_args)
        # Iniezione variabili specifiche del gioco
        for k, v in game_specific.items():
            if isinstance(v, str) and k not in ["GAME_WRAPPER", "GAME_EXTRA_ARGS"]:
                final_env[k] = v

    # 4. EXECUTION
    full_cmd = []
    if wrapper:
        full_cmd.extend(shlex.split(wrapper))

    full_cmd.extend(raw_args)

    if extra_args:
        full_cmd.extend(shlex.split(extra_args))

    # Log al Journal
    conf_name = specific_conf.name if specific_conf else "GLOBAL"
    log_msg(f"ID: {game_id} | Conf: {conf_name} | Cmd: {full_cmd[0]}")

    # Esegue e sostituisce il processo attuale
    try:
        os.execve(shlex.which(full_cmd[0]), full_cmd, final_env)
    except Exception as e:
        log_msg(f"ERRORE CRITICO: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run()
