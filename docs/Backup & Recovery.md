[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


Technical overview of the Backup & Recovery utility. This tool manages the snapshot and restoration of configuration files, game profiles, and system links.

---

## 🛠️ Integrated Tools

Three components:
1. **`backup.py`**: Handles archiving of configuration files and system services.
2. **`restore.py`**: Handles extraction, symbolic link reconstruction, and permission management.
3. **Control Center**: The graphical interface to manage these tasks easily.

---

## 🖥️ Using the Control Center
The easiest way is the **Maintenance** tab in the Control Center. Backup and Restore can't run at the same time (their buttons are disabled while one runs). If either times out (5 minutes), the buttons stay disabled until you restart the Control Center — see [Troubleshooting](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Troubleshooting) for why.

### Creating a Backup
1. Navigate to the **Maintenance** tab.
2. Click on **📦 Create Full System Backup**.
3. A `pkexec` prompt will ask for your password to access system files.
4. The system will create a compressed `.tar.gz` archive in `~/.config/steamos_diy/backups/` named `sdy_backup_YYYYMMDD_HHMMSS.tar.gz`. The archive is written atomically: the tool writes to a `.tmp` file first, verifies integrity end-to-end with `verify_archive()`, then renames it to the final path — the previous archive is never touched on failure.
5. **Rotation**: after every successful backup, archives beyond the `BACKUP_KEEP` count (SSoT key, default `5`) are pruned oldest-first, so the folder never grows unbounded. Set `BACKUP_KEEP` to `0` (or any negative value) to keep everything. Each removal is logged as `BACKUP_PRUNED`.

### Restoring the System
1. Click on **🔄 Restore from Archive**.
2. Select the `.tar.gz` file you previously created.
3. The tool will automatically:
   - Restore the SSoT (`/etc/default/steamos_diy.conf`), the systemd service, and the session state file (`next_session`).
   - Restore all core Python scripts (`/usr/local/lib/steamos_diy/`).
   - Restore user config and game profiles (`~/.config/steamos_diy/`).
   - Reconstruct symbolic links from the embedded `links.txt` manifest.
   - **Fix Permissions**: Re-assigns ownership to your user for home directory files even when run as root.

---

## 🔍 Mapping Logic

The utility targets specific paths to keep backups small. The mapping is defined once in `utils.get_backup_mapping(home)`: `backup.py` reads from it, and `restore.py` matches archive entries against it with its own logic (the tests round-trip every entry through both).

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
> During backup, the SteamOS-shim symlinks found on the system are recorded in a plain-data manifest (`links.txt`, one `link<TAB>target` row per line) embedded in the archive. During restore, each pair is validated against the same path allow-list used for file extraction and recreated atomically (a temporary symlink is created next to the target, then swapped into place with `os.replace`) — the archive never carries executable code. Archives from pre-manifest releases embed `restore_links.sh` instead: restore recognises it and mines its `ln -sf` lines for the same pairs, but the script itself is **never executed**.

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
* **Path allow-list**: Writes are only permitted to `/etc/`, `/usr/`, `/var/`, the user's home directory, and the folders the mapping points to (e.g. a `games_conf_dir` moved elsewhere via the SSoT). Any archive member resolving outside these paths is rejected and logged.
* **Path traversal protection**: Archive members containing `..` components are rejected before resolution, preventing crafted archives from escaping the allow-list.
* **Archive content filter**: Hardlinks, symlinks, device nodes, and FIFOs inside the archive are rejected — only regular files and directories are extracted.
* **Pre-existing symlink guard**: If a symlink already exists at the target path on disk, the write is refused to prevent redirect attacks from a previously planted link.
* **Permission mask**: File modes from the archive are applied masked to `0o777` — a crafted archive cannot plant setuid/setgid binaries through a root-run restore.
* **Link manifest validation**: Every `link → target` pair from the manifest (or mined from a legacy script) must resolve inside the allow-list on **both** ends, or it is rejected and logged. No shell is ever involved in link reconstruction.
* **Atomic extraction**: Each file is written to a temporary sibling and `os.replace()`d into place — a crash or power loss mid-restore can never leave a target missing or truncated. Replacing the directory entry instead of truncating the file also avoids `ETXTBSY` on a currently-running binary.

> [!WARNING]
> **What these checks do not cover — treat a backup archive like a root password**
>
> The layers above reject archives that are damaged, malformed, or come from another tool. They cannot tell a genuine backup from one that was deliberately modified: an archive legitimately contains the project's own code (`/usr/local/lib/steamos_diy`), the systemd unit and the symlink manifest, and a restore puts all of that back with root privileges. Archives are stored in `~/.config/steamos_diy/backups/`, a folder your own user (and any program running as you) can write to.
>
> This is an accepted limit of the design, not something the restore tool tries to defend against: only restore archives you created yourself or fully trust, and keep copies you care about somewhere other programs can't modify them.

## ⚠️ Important Notes
* **Service Reload**: The restoration process reloads the `systemd` daemon automatically to ensure the session launcher is ready immediately.
* **Ownership**: The restore tool resolves the real user behind `sudo`/`pkexec`, so restored files in your home directory are owned by you, not root.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
