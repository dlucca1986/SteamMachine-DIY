[![Version](https://img.shields.io/badge/Version-2.1.1-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Session](https://img.shields.io/badge/Logic-Atomic%20State-orange.svg)](#)
[![Framework](https://img.shields.io/badge/Framework-SSoT%20Architecture-blue.svg)](#)

Core components, filesystem layout, and the SteamOS compatibility shim layer.

---

## 🛠️ The Core Logic Components

### 0. Core Engine (`utils.py`)
Centralizes shared functions used across the framework:

* **Atomic I/O**: Implements hardware-safe file writes.

* **Logging**: Provides standardized logging interfaces (`jlog`).

* **Environment Resolution**: Handles SSoT variable parsing and permission enforcement (`fix_ownership`).

---

### 1. SSoT (Single Source of Truth)
Located at `/etc/default/steamos_diy.conf`. It stores system-wide variables including binary paths, user config paths, timing parameters, and log levels. This configuration ensures consistent behavior across all Python components.

### 2. Session Launcher (`session_launch.py`)
Primary execution logic managed by `steamos_diy.service`. It determines the session target (Gaming Mode or Desktop Mode) by evaluating the state file at runtime.

### 3. Session Switcher (`session_select.py`)
Handles explicit mode transitions. Writes the next session target atomically to the state file and signals the running session to terminate.

### 4. DGM Engine (Dynamic Gamescope Mapping)
A module within the launcher that parses `config.yaml`. It dynamically generates the `gamescope` execution command based on defined flags and parameters.

### 5. SDY Discovery Engine (`sdy.py`)
A wrapper that identifies games via `SteamAppId` or executable name and applies per-game YAML overrides from `games.d/`.

### 6. Control Center (`control_center.py`, `editors.py`, `journal.py`)
The PyQt6 dashboard that manages YAML configurations using the `ruamel.yaml` library to preserve user comments and formatting. UI rendering widgets (`YAMLEditor`, `YAMLSyntaxHighlighter`, `LineNumberArea`) are isolated in `editors.py`. Journal parsing and game discovery logic (`get_journal_cmd`, `fetch_gamescope_logs`, `filter_game_journal_lines`, `parse_game_logs`, `parse_export_format`, `extract_game_metadata`) live in `journal.py`, keeping `control_center.py` focused on UI wiring only.

---

## 📂 File System Hierarchy & Logic

| Path | Type | Purpose |
| :--- | :--- | :--- |
| `/etc/default/steamos_diy.conf` | **Master Config** | **SSoT**: System identity (User/UID) and global paths. |
| `~/.config/steamos_diy/` | **User Config** | Directory containing YAML manifests for Gamescope flags and user presets. |
| `/var/lib/steamos_diy/next_session` | **State File** | **Atomic**: Persistence flag determining if the next boot loads Steam or Desktop. |
| `/usr/local/lib/steamos_diy/` | **Logic Core** | Framework core and Python engines. |
| `/etc/systemd/system/steamos_diy.service` | **System Service** | Manages the TTY1 graphical session lifecycle. |
| `/usr/share/libalpm/hooks/gamescope-privs.hook` | **Pacman Hook** | Restores `setcap` privileges to Gamescope after every package update. |

---

## 🔗 Architecture & Compatibility Layer

The framework implements a redirection layer using symbolic links to satisfy Steam's expectations for specific SteamOS paths and to provide CLI access.

* **SteamOS UI Shims**: These links prevent UI errors in Game Mode by redirecting SteamOS-specific system requests to the framework logic. For `steamos-update`, `jupiter-biosupdate`, and `steamos-set-timezone`, the `/usr/bin/` alias is itself a symlink to the polkit helper, forming a two-hop chain: `/usr/bin/<name>` → `/usr/bin/steamos-polkit-helpers/<name>` → `.py`.

| Target (Logic in `/usr/local/lib/steamos_diy/`) | Shim Paths (Steam & System) | Purpose |
| :--- | :--- | :--- |
| `helpers/steamos-update.py` | `/usr/bin/steamos-update`<br>`/usr/bin/steamos-polkit-helpers/steamos-update` | Redirects UI update requests to the DIY engine. |
| `helpers/jupiter-biosupdate.py` | `/usr/bin/jupiter-biosupdate`<br>`/usr/bin/steamos-polkit-helpers/jupiter-biosupdate` | Handles firmware check requests to prevent UI errors. |
| `helpers/set-timezone.py` | `/usr/bin/steamos-set-timezone`<br>`/usr/bin/steamos-polkit-helpers/steamos-set-timezone` | Enables timezone management via the Steam interface. |
| `helpers/jupiter-dock-updater.py` | `/usr/bin/steamos-polkit-helpers/jupiter-dock-updater` | Provides compatibility for official Steam Deck Dock accessories. |
| `helpers/steamos-select-branch.py` | `/usr/bin/steamos-select-branch` | Mocks the update channel selection in the Steam UI. |


* **System Aliases** : Standard CLI entry points for framework management and game execution.

| Target (Logic in `/usr/local/lib/steamos_diy/`) | Shim Paths (Steam & System) | Purpose |
| :--- | :--- | :--- |
| `session_launch.py` | `/usr/bin/steamos-session-launch` | **Entry Point**: Primary command to spawn the graphical session. |
| `session_select.py` | `/usr/bin/steamos-session-select` | Interface for toggling between system modes. |
| `sdy.py` | `/usr/local/bin/sdy` | CLI wrapper for game execution using YAML profiles. |
| `control_center.py` | `/usr/local/bin/sdy-control-center` | CLI entry point for the Dashboard. |
| `backup.py` | `/usr/local/bin/sdy-backup` | CLI command to create a full system backup. |
| `restore.py` | `/usr/local/bin/sdy-restore` | CLI command to restore from a backup archive. |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
