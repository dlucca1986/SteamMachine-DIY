#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Backup Tool
# VERSION:      1.0.0 - Python
# DESCRIPTION:  Chirurgical backup with dynamic symlink recovery script.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# PATH:         /usr/local/lib/steamos_diy/backup_tool.py
# =============================================================================

import os
import sys
import tarfile
import subprocess
from datetime import datetime
from pathlib import Path

def get_ssot():
    """Carica il SSoT coerente con gli altri script di sistema."""
    conf = {
        'next_session': '/var/lib/steamos_diy/next_session', # Uniformato underscore
        'user_config': '/home/lelo/.config/steamos_diy/config'
    }
    path = "/etc/default/steamos_diy.conf"
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")
    return conf

def generate_links_recap():
    """Trova dinamicamente i link simbolici che puntano alla sorgente."""
    target_prefix = "/usr/local/lib/steamos_diy"
    recap_commands = [
        "#!/bin/bash\n",
        "# Script di ripristino automatico link simbolici\n",
        "echo 'Ripristino link simbolici in corso...'\n"
    ]

    try:
        # Cerca tutti i link in /usr che puntano alla nostra cartella lib
        cmd = ["find", "/usr", "-type", "l", "-lname", f"{target_prefix}*"]
        links = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).splitlines()

        for link_path in links:
            target = os.readlink(link_path)
            parent_dir = os.path.dirname(link_path)
            recap_commands.append(f"mkdir -p {parent_dir}\n")
            recap_commands.append(f"ln -sf {target} {link_path}\n")

    except subprocess.CalledProcessError:
        recap_commands.append("# Nessun link simbolico trovato durante il discovery.\n")

    return "".join(recap_commands)

def run_backup():
    """Esegue il backup includendo il recap per i link."""
    ssot = get_ssot()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Configurazione percorsi
    user_config_path = Path(ssot.get('user_config')).parent
    backup_root = user_config_path / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    archive_name = backup_root / f"sdy_backup_{timestamp}.tar.gz"
    recap_file = backup_root / "restore_links.sh"

    # 1. Genera lo script di ripristino
    links_script = generate_links_recap()
    with open(recap_file, "w") as f:
        f.write(links_script)

    # 2. Sorgenti (In linea con il nuovo SSoT)
    sources = [
        (ssot.get('next_session'), "system/next_session"),
        ("/etc/default/steamos_diy.conf", "system/steamos_diy.conf"),
        ("/usr/local/lib/steamos_diy", "source/steamos_diy"),
        (str(user_config_path), "user/config_steamos"),
        (str(recap_file), "restore_links.sh")
    ]

    print(f"📦 Creazione backup: {archive_name.name}...")

    try:
        with tarfile.open(archive_name, "w:gz") as tar:
            for src_path, arc_name in sources:
                if src_path and Path(src_path).exists():
                    # Filtro per evitare ricorsione infinita se la cartella backup è "dentro"
                    def tar_filter(tarinfo):
                        if "backups" in tarinfo.name:
                            return None
                        return tarinfo

                    tar.add(src_path, arcname=arc_name, filter=tar_filter)
                    print(f"  + {src_path} -> OK")

        # Rimuoviamo lo script temporaneo dopo averlo impacchettato
        if recap_file.exists():
            recap_file.unlink()

        print("\n✅ Backup completato!")
        print(f"📍 File: {archive_name}")

    except Exception as e:
        print(f"\n❌ ERRORE: {e}")
        if archive_name.exists():
            archive_name.unlink()
        sys.exit(1)

if __name__ == "__main__":
    run_backup()
