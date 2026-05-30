[![Version](https://img.shields.io/badge/Version-2.1.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
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
4. The system will create a compressed `.tar.gz` archive in `~/.config/steamos_diy/backups/` named `sdy_backup_YYYYMMDD_HHMMSS.tar.gz`. The archive is written atomically: the tool writes to a `.tmp` file first, verifies integrity end-to-end with `verify_archive()`, then renames it to the final path — the previous archive is never touched on failure.

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

The utility targets specific paths to maintain a minimal backup footprint. The mapping is defined in `utils.get_backup_mapping(home)` as the single source of truth — both `backup.py` (writing the archive) and `restore.py` (reading it back) consume the same dict, so the archive layout can never drift between the two sides.

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
> During backup, `restore_links.sh` is generated and embedded in the archive. During restore, it is extracted into a private root-only temp directory (`mkdtemp`, mode `0700`, owned by root) and executed from there. This eliminates the TOCTOU window that would exist if the script were written to a world-writable location before being executed.

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

## 🛡️ Restore Security
The restore tool implements multiple layers of validation before writing anything to disk:
* **Path allow-list**: Writes are only permitted to `/etc/`, `/usr/`, `/var/`, and the user's home directory. Any archive member resolving outside these paths is rejected and logged.
* **Path traversal protection**: Archive members containing `..` components are rejected before resolution, preventing crafted archives from escaping the allow-list.
* **Archive content filter**: Hardlinks, symlinks, device nodes, and FIFOs inside the archive are rejected — only regular files and directories are extracted.
* **Pre-existing symlink guard**: If a symlink already exists at the target path on disk, the write is refused to prevent redirect attacks from a previously planted link.

## ⚠️ Important Notes
* **Service Reload**: The restoration process reloads the `systemd` daemon automatically to ensure the session launcher is ready immediately.
* **Ownership**: The restore tool is aware of your `SUDO_USER` and will ensure that files in your home directory are not locked as "root" after extraction.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
