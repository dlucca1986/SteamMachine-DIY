[![Version](https://img.shields.io/badge/Version-1.3.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Logic](https://img.shields.io/badge/Logic-Selective%20State%20Capture-blue.svg)](#)
[![Integrity](https://img.shields.io/badge/Integrity-Atomic%20Restoration-orange.svg)](#)


Technical overview of the Backup & Recovery utility. This tool manages the snapshot and restoration of configuration files, game profiles, and system links.

---

## 🛠️ Integrated Tools

The restoration suite consists of three main components working in harmony:
1. **`backup.py`**: Handles archiving of configuration files and system services.
2. **`restore.py`**: Handles extraction, symbolic link reconstruction, and permission management.
3. **Control Center**: The graphical interface to manage these tasks easily.

---

## 🖥️ Using the Control Center
The easiest way to manage your data is through the **Maintenance** tab in the Control Center.

### Creating a Backup
1. Navigate to the **Maintenance** tab.
2. Click on **📦 Create Full System Backup**.
3. A `pkexec` prompt will ask for your password to access system files.
4. The system will create a compressed `.tar.gz` archive in `~/.config/steamos_diy/backups/` named `sdy_backup_YYYYMMDD_HHMMSS.tar.gz`.

### Restoring the System
1. Click on **🔄 Restore from Archive**.
2. Select the `.tar.gz` file you previously created.
3. The tool will automatically:
   - Restore the SSoT (`/etc/default/steamos_diy.conf`), the systemd service, and the session state file (`next_session`).
   - Restore all core Python scripts (`/usr/local/lib/steamos_diy/`).
   - Restore user config and game profiles (`~/.config/steamos_diy/`).
   - Reconstruct symbolic links via the embedded `restore_links.sh`.
   - **Fix Permissions**: Re-assigns ownership to your user for home directory files even when run as root.

---

## 🔍 Mapping Logic

The utility targets specific paths to maintain a minimal backup footprint:

| Source Path | Description |
|:---|:---|
| `/var/lib/steamos_diy/next_session` | Session state (steam / desktop) |
| `/etc/default/steamos_diy.conf` | The Single Source of Truth (SSoT) |
| `/etc/systemd/system/steamos_diy.service` | System service definition |
| `/usr/local/lib/steamos_diy/` | The core Python scripts and C-Core |
| `~/.config/steamos_diy/` | Global YAML and `games.d/` profiles |


> [!IMPORTANT]
> **Link Reconstruction**
>
> During backup, `restore_links.sh` is generated and embedded in the archive. During restore, it is extracted into a private root-only temp directory (mode `0700`, not `/tmp`) and executed from there. This eliminates the TOCTOU window that would exist if the script were written to a world-writable location before being executed.

---

## ⌨️ Command Line Usage (Advanced)
If the UI is unavailable, you can run the tools manually from the terminal:

**To Backup:**
```bash
sudo python3 /usr/local/lib/steamos_diy/backup.py
```

**To Restore:**
```bash
sudo python3 /usr/local/lib/steamos_diy/restore.py /path/to/your/backup.tar.gz
```

---

## ⚠️ Important Notes
* **Atomic Safety**: The restoration process reloads the `systemd` daemon automatically to ensure the session launcher is ready immediately.
* **Ownership**: The restore tool is aware of your `SUDO_USER` and will ensure that files in your home directory are not locked as "root" after extraction.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
