import os
import sys
import subprocess
import time
from pathlib import Path

# --- Inizializzazione Core ---
MASTER_CONFIG = "/etc/default/steamos-diy"

def load_master_config():
    conf = {}
    if os.path.exists(MASTER_CONFIG):
        with open(MASTER_CONFIG, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")
        return conf
    else:
        print(f"FATAL ERROR: Config not found at {MASTER_CONFIG}")
        sys.exit(1)

def log_info(message, log_file):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] [LAUNCHER] {message}\n")

def get_dynamic_gs_flags(config_path):
    """
    Sostituisce il loop Bash che trasforma GS_WINE_FULLSCREEN=1
    in --wine-fullscreen in modo automatico.
    """
    flags = []
    if not os.path.exists(config_path):
        return flags

    with open(config_path, "r") as f:
        for line in f:
            if line.startswith("GS_") and "=" in line:
                name, val = line.strip().split("=", 1)
                val = val.strip('"').strip("'")

                # Trasformazione: GS_WINE_FULLSCREEN -> --wine-fullscreen
                flag_name = "--" + name[3:].lower().replace("_", "-")

                if val == "1":
                    flags.append(flag_name)
                elif val != "0" and val != "":
                    flags.extend([flag_name, val])
    return flags

def run_session():
    conf = load_master_config()
    log_file = conf.get("LOG_FILE", "/tmp/session.log")
    next_session_file = conf.get("NEXT_SESSION_FILE", "/tmp/next_session")
    config_dir = conf.get("CONFIG_DIR", "/etc/steamos-diy")

    log_info("--- SYSTEM STARTUP (PYTHON CORE) ---", log_file)

    while True:
        # 1. Determina sessione target
        if os.path.exists(next_session_file):
            with open(next_session_file, "r") as f:
                target = f.read().strip()
        else:
            target = "steam"

        log_info(f"Target Session: {target}", log_file)

        if target == "steam":
            # Costruzione dinamica Gamescope
            gs_args = ["gamescope", "-e", "-f"]
            user_flags = get_dynamic_gs_flags(f"{config_dir}/config")
            gs_args.extend(user_flags)
            gs_args.extend(["--", "steam", "-gamepadui", "-steamos3"])

            log_info(f"Executing: {' '.join(gs_args)}", log_file)

            start_time = time.time()
            # Esecuzione e log
            with open(log_file, "a") as out:
                subprocess.run(gs_args, stdout=out, stderr=out)

            duration = time.time() - start_time

            # Crash handling
            next_step = "desktop"
            if duration < 5:
                log_info(f"CRASH DETECTED: {duration:.2f}s", log_file)
                time.sleep(3)

            # Scrittura atomica della prossima sessione
            temp_next = f"{next_session_file}.tmp"
            with open(temp_next, "w") as f: f.write(next_step)
            os.replace(temp_next, next_session_file)

        elif target in ["plasma", "desktop"]:
            log_info("Launching Desktop (Plasma)...", log_file)

            # Preparazione ambiente Plasma
            plasma_cmd = ["/usr/bin/startplasma-wayland"]

            with open(log_file, "a") as out:
                subprocess.run(plasma_cmd, stdout=out, stderr=out)

            # Ritorno atomico a Steam
            temp_next = f"{next_session_file}.tmp"
            with open(temp_next, "w") as f: f.write("steam")
            os.replace(temp_next, next_session_file)

        time.sleep(float(conf.get("CHECK_INTERVAL", 0.5)))

if __name__ == "__main__":
    run_session()
