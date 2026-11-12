[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Core components, filesystem layout, and the SteamOS compatibility shim layer.

---

## 🛠️ The Core Logic Components

### 0. Core Engine (`utils.py`)
Centralizes shared functions used across the framework:

* **Atomic I/O**: `write_atomic()` (tmp → `fdatasync` → `rename`).

* **Logging**: `jlog()`, to the systemd journal.

* **SSoT and ownership**: SSoT parsing (`get_ssot_var`) and `fix_ownership()`, which gives files written as root back to the user.

---

### 1. SSoT (Single Source of Truth)
Located at `/etc/default/steamos_diy.conf`. It stores system-wide variables including binary paths, user config paths, timing parameters, and log levels. The Python code reads it through `utils.get_ssot_var()`.

### 2. Session Launcher (`session_launch.py`)
Started by `steamos_diy.service`. It reads the session target (Game Mode or Desktop) from the state file, starts that session and supervises it.

### 3. Session Switcher (`session_select.py`)
Writes the next session target atomically to the state file and asks the running session to quit.

### 4. DGM Engine (Dynamic Gamescope Mapping)
The part of the launcher (`_build_gamescope_args()`) that builds the `gamescope` command line from `config.yaml`'s `flags`.

### 5. SDY Discovery Engine (`sdy.py`)
A wrapper that identifies games via `SteamAppId` or executable name and applies per-game YAML overrides from `games.d/`.

### 6. Control Center (`control_center.py`, `editors.py`, `journal.py`, `updater.py`)
The PyQt6 dashboard that manages YAML configurations using the `ruamel.yaml` library to preserve user comments and formatting. UI rendering widgets (`YAMLEditor`, `YAMLSyntaxHighlighter`, `LineNumberArea`) are isolated in `editors.py`. Journal parsing and game discovery logic (`get_journal_cmd`, `fetch_tagged_entries`, `fetch_gamescope_logs`, `filter_game_journal_lines`, `parse_game_logs`, `parse_export_format`, `extract_game_metadata`) live in `journal.py`. The in-app updater flow (release check, download, installer handoff — `UpdateManager`) lives in `updater.py`.

### 7. Health & Preflight (`health.py`)
A Qt-free backend module — like `journal.py`, testable in isolation — powering the Control Center's diagnostics. `run_preflight()` returns a list of `CheckResult`s that validate the configuration: SSoT presence, binary handlers, SSoT path resolution, YAML syntax, `flags`/`post_start_cmds` types, gamescope flag validity (checked by running the configured flags through gamescope's own argv parser), group membership, C-Core loadability, and session-state writability. `get_service_status()` snapshots `steamos_diy.service` via `systemctl show`. See [Control Center](https://github.com/dlucca1986/SteamMachine-DIY/wiki/SteamMachine-DIY-Control-Center).

### 8. Backup & Restore (`backup.py`, `restore.py`)
CLI utilities (`sdy-backup` / `sdy-restore`) that back up and restore the framework's config, game profiles, and SteamOS compatibility symlinks. Both start from the same `utils.get_backup_mapping()` (restore matches archive entries against it on its own; tests check every entry round-trips), and restore enforces a path allow-list plus traversal and symlink guards. See [Backup & Recovery](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Backup-&-Recovery).

---

## 📂 File System Hierarchy & Logic

| Path | Type | Purpose |
| :--- | :--- | :--- |
| `/etc/default/steamos_diy.conf` | **Master Config** | **SSoT**: config and state paths, binary paths, timing values, log level. |
| `~/.config/steamos_diy/` | **User Config** | `config.yaml` (Gamescope flags, environment), `games.d/` per-game profiles, backups. |
| `/var/lib/steamos_diy/next_session` | **State File** | `steam` or `desktop`: the session the launcher starts next. Written atomically. |
| `/usr/local/lib/steamos_diy/` | **Code** | Python modules, helper shims and `libcore.so`. |
| `/etc/systemd/system/steamos_diy.service` | **System Service** | Runs the session launcher on TTY1. |
| `/usr/share/libalpm/hooks/gamescope-privs.hook` | **Pacman Hook** | Re-applies the file capabilities to Gamescope after each install or upgrade of the `gamescope` package. |

---

## 🔗 Architecture & Compatibility Layer

Symbolic links put the project's scripts at the SteamOS paths Steam calls, and its CLI tools in `/usr/local/bin`.

* **SteamOS UI Shims**: Stand-ins for SteamOS helper commands that Steam's Game Mode can call; each shim logs the call and returns a fixed exit code, changing nothing on the system. For `steamos-update`, `jupiter-biosupdate`, and `steamos-set-timezone`, the `/usr/bin/` alias is itself a symlink to the polkit helper, forming a two-hop chain: `/usr/bin/<name>` → `/usr/bin/steamos-polkit-helpers/<name>` → `.py`.

| Target (Logic in `/usr/local/lib/steamos_diy/`) | Shim Paths (Steam & System) | Purpose |
| :--- | :--- | :--- |
| `helpers/steamos-update.py` | `/usr/bin/steamos-update`<br>`/usr/bin/steamos-polkit-helpers/steamos-update` | Exits `7`, the SteamOS convention for "no update available". |
| `helpers/jupiter-biosupdate.py` | `/usr/bin/jupiter-biosupdate`<br>`/usr/bin/steamos-polkit-helpers/jupiter-biosupdate` | Exits `0` without doing anything. |
| `helpers/set-timezone.py` | `/usr/bin/steamos-set-timezone`<br>`/usr/bin/steamos-polkit-helpers/steamos-set-timezone` | Exits `0` without changing the timezone. |
| `helpers/jupiter-dock-updater.py` | `/usr/bin/steamos-polkit-helpers/jupiter-dock-updater` | Exits `7` ("no update available"). |
| `helpers/steamos-select-branch.py` | `/usr/bin/steamos-select-branch` | Answers the `-c`/`-l` queries with `stable`; a branch switch exits `0` and changes nothing. |


* **System Aliases** : Standard CLI entry points for framework management and game execution.

| Target (Logic in `/usr/local/lib/steamos_diy/`) | Shim Paths (Steam & System) | Purpose |
| :--- | :--- | :--- |
| `session_launch.py` | `/usr/bin/steamos-session-launch` | Alias of the session launcher. |
| `session_select.py` | `/usr/bin/steamos-session-select` | Switches session: `steamos-session-select desktop` / `steam`. |
| `sdy.py` | `/usr/local/bin/sdy` | CLI wrapper for game execution using YAML profiles. |
| `control_center.py` | `/usr/local/bin/sdy-control-center` | CLI entry point for the Dashboard. |
| `backup.py` | `/usr/local/bin/sdy-backup` | CLI command to create a full system backup. |
| `restore.py` | `/usr/local/bin/sdy-restore` | CLI command to restore from a backup archive. |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
