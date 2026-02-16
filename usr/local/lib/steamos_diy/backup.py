#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Backup Tool
# VERSION:      1.1.0 - Python
# DESCRIPTION:  Surgical backup with dynamic symlink recovery and user configs.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/backup_tool.py
# LICENSE:      MIT
# =============================================================================

import os
import sys
import tarfile
import subprocess
from datetime import datetime
from pathlib import Path


def get_ssot():
    """Loads SSoT configuration consistently with other system scripts."""
    conf = {
        'next_session': '/var/lib/steamos_diy/next_session',
        'user': os.environ.get('USER') or os.environ.get('SUDO_USER')
    }
    path = "/etc/default/steamos_diy.conf"
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    conf[k.strip()] = v.strip().strip('"').strip("'")

    # Ensure we have a valid home path
    if 'user' in conf and not conf.get('user_home'):
        conf['user_home'] = str(Path(f"/home/{conf['user']}"))

    return conf


def generate_links_recap():
    """Dynamically finds symlinks pointing to the project source."""
    target_prefix = "/usr/local/lib/steamos_diy"
    recap_commands = [
        "#!/bin/bash\n",
        "# Automatic symlink recovery script\n",
        "echo 'Restoring symbolic links...'\n"
    ]

    try:
        # Find all links in /usr pointing to our lib folder
        cmd = ["find", "/usr", "-type", "l", "-lname", f"{target_prefix}*"]
        links = subprocess.check_output(cmd, text=True,
                                        stderr=subprocess.DEVNULL).splitlines()

        for link_path in links:
            target = os.readlink(link_path)
            parent_dir = os.path.dirname(link_path)
            recap_commands.append(f"mkdir -p {parent_dir}\n")
            recap_commands.append(f"ln -sf {target} {link_path}\n")

    except subprocess.CalledProcessError:
        recap_commands.append("# No symbolic links found during discovery.\n")

    return "".join(recap_commands)


def run_backup():
    """Executes the backup including recovery script and user profiles."""
    ssot = get_ssot()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Path configuration
    user_home = Path(ssot.get('user_home', '/root'))
    user_config_path = Path(ssot.get('user_config',
                            user_home / ".config/steamos_diy/config")).parent
    
    backup_root = user_config_path / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    archive_name = backup_root / f"sdy_backup_{timestamp}.tar.gz"
    recap_file = backup_root / "restore_links.sh"

    # 1. Generate restoration script
    links_script = generate_links_recap()
    with open(recap_file, "w") as f:
        f.write(links_script)

    # 2. Backup Sources
    bash_profile = user_home / ".bash_profile"
    sources = [
        (ssot.get('next_session'), "system/next_session"),
        ("/etc/default/steamos_diy.conf", "system/steamos_diy.conf"),
        ("/usr/local/lib/steamos_diy", "source/steamos_diy"),
        (str(user_config_path), "user/config_steamos"),
        (str(bash_profile), "user/bash_profile"),
        (str(recap_file), "restore_links.sh")
    ]

    print(f"📦 Creating backup: {archive_name.name}...")

    try:
        with tarfile.open(archive_name, "w:gz") as tar:
            for src_path, arc_name in sources:
                if src_path and Path(src_path).exists():
                    # Filter to avoid recursive backup inclusion
                    def tar_filter(tarinfo):
                        if "backups" in tarinfo.name:
                            return None
                        return tarinfo

                    tar.add(src_path, arcname=arc_name, filter=tar_filter)
                    print(f"  + {src_path} -> OK")

        # Remove temporary script after packing
        if recap_file.exists():
            recap_file.unlink()

        print("\n✅ Backup completed successfully!")
        print(f"📍 Location: {archive_name}")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        if archive_name.exists():
            archive_name.unlink()
        sys.exit(1)


if __name__ == "__main__":
    run_backup()
