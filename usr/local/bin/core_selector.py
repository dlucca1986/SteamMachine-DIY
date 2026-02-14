#!/usr/bin/env python3
import os
import sys
import subprocess
import time

# --- 1. CORE INITIALIZATION ---
MASTER_CONFIG = "/etc/default/steamos-diy"

def load_master_config():
    conf = {}
    if os.path.exists(MASTER_CONFIG):
        with open(MASTER_CONFIG, "r") as f:
            for line in f:
                # Carica solo righe con "=" che non sono commenti
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")
        return conf
    else:
        print(f"FATAL ERROR: Master config not found at {MASTER_CONFIG}")
        sys.exit(1)

def log_action(message, log_file):
    # Genera timestamp preciso al millisecondo
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    # In Python è meglio gestire l'apertura file con 'with'
    try:
        with open(log_file, "a") as f:
            f.write(f"[{timestamp}] [TRIGGER-PY] {message}\n")
    except Exception as e:
        print(f"Logging error: {e}")

def safe_write_session(target, session_file):
    """
    Scrittura atomica: scrive in un file .tmp e poi lo rinomina.
    Questo evita file corrotti se il PC si spegne durante la scrittura.
    """
    temp_file = f"{session_file}.tmp"
    try:
        with open(temp_file, "w") as f:
            f.write(target)
        # os.replace è l'equivalente atomico di 'mv' nel filesystem
        os.replace(temp_file, session_file)
        return True
    except Exception as e:
        print(f"Atomic write failed: {e}")
        return False

# --- 2. MAIN LOGIC ---
def main():
    conf = load_master_config()
    log_file = conf.get("LOG_FILE", "/tmp/session.log")
    next_session_file = conf.get("NEXT_SESSION_FILE", "/tmp/next_session")

    # Verifica se è stato passato un argomento
    if len(sys.argv) < 2:
        print(f"Usage: {os.path.basename(sys.argv[0])} {{steam|desktop}}")
        sys.exit(1)

    choice = sys.argv[1].lower()

    if choice in ["plasma", "desktop"]:
        log_action("Switch to DESKTOP requested.", log_file)

        # Scrittura atomica
        safe_write_session("desktop", next_session_file)

        # Chiusura pulita di Steam
        log_action("Shutting down Steam...", log_file)
        subprocess.run(["steam", "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    elif choice == "steam":
        log_action("Switch to STEAM requested.", log_file)

        # Scrittura atomica
        safe_write_session("steam", next_session_file)

        # Logout pulito da Plasma 6 via D-Bus
        log_action("Initiating Plasma 6 Logout via D-Bus...", log_file)
        try:
            subprocess.run(["qdbus6", "org.kde.Shutdown", "/Shutdown", "logout"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log_action("ERROR: qdbus6 not found. Is Plasma running?", log_file)

        time.sleep(0.5)
        os.system('clear')

    else:
        print(f"Unknown option: {choice}")
        sys.exit(1)

if __name__ == "__main__":
    main()
