#!/usr/bin/env python3
# =============================================================================
# PROJECT:      SteamMachine-DIY - Restore Tool
# VERSION:      1.1.0 - Python
# DESCRIPTION:  Full system restoration and dynamic symlink reconstruction.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/restore.py
# LICENSE:      MIT
# =============================================================================

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

# pylint: disable=invalid-name, broad-exception-caught


def check_root():
    """Ensures the script is running with root privileges."""
    if os.geteuid() != 0:
        print("❌ ERROR: This script must be run with sudo.")
        sys.exit(1)


def get_ssot():
    """Loads SSoT configuration for consistent restoration paths."""
    conf = {"next_session": "/var/lib/steamos_diy/next_session"}
    user = os.environ.get("SUDO_USER")
    if not user or user == "root":
        try:
            cmd = "loginctl user-status | head -n 1 | awk '{print $1}'"
            user = subprocess.check_output(cmd, shell=True, text=True).strip()
        except Exception:
            user = os.environ.get("USER")
    conf["user"] = user
    if user and user != "root":
        conf["user_home"] = f"/home/{user}"
    else:
        conf["user_home"] = "/root"
    return conf


def fix_ownership(path, user):
    """Adjusts file ownership to the real user after root extraction."""
    if not user or user == "root":
        return
    try:
        shutil.chown(path, user, user)
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for f in files:
                    shutil.chown(os.path.join(root, f), user, user)
    except Exception as e:
        print(f"⚠️  Warning: Could not fix ownership for {path}: {e}")


def run_restore(archive_path):
    """Performs the restoration from a compressed tarball."""
    check_root()
    ssot = get_ssot()
    archive = Path(archive_path)

    if not archive.exists():
        print(f"❌ ERROR: Archive not found: {archive_path}")
        return

    print(f"📂 Restoring from: {archive.name}...")
    user_home = Path(ssot.get("user_home", "/root"))
    config_base = user_home / ".config/steamos_diy"

    # Mapping base names to destination paths
    mapping = {
        "system/next_session": ssot.get("next_session"),
        "system/steamos_diy.conf": "/etc/default/steamos_diy.conf",
        "system/service": "/etc/systemd/system/steamos_diy.service",
        "source/steamos_diy": "/usr/local/lib/steamos_diy",
        "user/config_steamos": str(config_base),
        "restore_links.sh": "/tmp/restore_links.sh",
    }

    try:
        with tarfile.open(archive, "r:gz") as tar:
            for m in tar.getmembers():
                # Check if member belongs to mapped paths
                m_key = next(
                    (k for k in mapping if m.name.startswith(k)), None
                )

                if m_key:
                    dest_base = mapping[m_key]
                    rel = os.path.relpath(m.name, m_key)
                    target = (
                        Path(dest_base) / rel
                        if rel != "."
                        else Path(dest_base)
                    )

                    target.parent.mkdir(parents=True, exist_ok=True)

                    if m.isfile():
                        with tar.extractfile(m) as s, open(target, "wb") as t:
                            shutil.copyfileobj(s, t)
                    elif m.isdir():
                        target.mkdir(parents=True, exist_ok=True)

                    os.chmod(target, m.mode)
                    if "user/" in m_key or str(user_home) in str(target):
                        fix_ownership(target, ssot["user"])
                    print(f"  + Restored: {target}")

        recap_script = Path("/tmp/restore_links.sh")
        if recap_script.exists():
            print("🔗 Reconstructing symbolic links...")
            os.chmod(recap_script, 0o755)
            subprocess.run([str(recap_script)], check=True)
            recap_script.unlink()

        subprocess.run(["systemctl", "daemon-reload"], check=False)
        print("\n✅ Restoration completed successfully!")

    except Exception as e:
        print(f"\n❌ ERROR DURING RESTORATION: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: sudo python3 restore.py /path/to/backup.tar.gz")
    else:
        run_restore(sys.argv[1])
