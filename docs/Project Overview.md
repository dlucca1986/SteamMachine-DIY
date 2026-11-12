[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

System requirements, main features, and the packages involved.

---

### 📍 System Requirements

* **Distribution**: Arch Linux or Arch-based distributions (e.g., EndeavourOS) using `systemd`.
* **Graphics Stack**:
    * **AMD**: RADV
    * **Intel**: ANV
    * **NVIDIA (NVK)**: open Vulkan driver `vulkan-nouveau`, deployed when no proprietary driver is installed
    * **NVIDIA (Proprietary)**: with `nvidia-open`/`nvidia-open-dkms` installed (detected through their `nvidia-utils` dependency), `lib32-nvidia-utils` is added
    * Tested on Intel and AMD hardware. The NVIDIA package selection is tested in a clean Arch container (detection, dependency resolution, installation); gamescope itself has not been run on an NVIDIA card by the project.
* **Display Manager**: **None**. The system manages session handovers via a `systemd` service on TTY1.
* **Desktop Environment**: **KDE Plasma 6.x** (Wayland).


---

### 🚀 Features

#### 1. Zero-DM & Service-Based Boot
No display manager (SDDM/plasmalogin are disabled): a systemd service starts the session on TTY1.

* **Gamescope capabilities**: `install.sh` grants the `gamescope` binary `cap_sys_admin`/`cap_sys_nice`/`cap_ipc_lock` via `setcap`. `cap_sys_nice` is what gamescope checks for realtime scheduling and higher-priority threads (without it, it logs `No CAP_SYS_NICE, falling back to regular-priority compute and threads`).
* **Transition messages**: during a session switch, `notify()` clears TTY1 and prints a one-line status (e.g. `Switching to Desktop...`).

#### 2. Session Management
Session state is persisted to `/var/lib/steamos_diy/next_session` via [atomic writes](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine), so the file is replaced whole, never partially written.

* **Crash Recovery**: If a session exits before `VALIDATION_TIMEOUT` (default: 5s), the next session started is Desktop, so a broken Game Mode can't trap you in a restart loop.

#### 3. Dynamic Parameter Mapping
The launcher reads `config.yaml` and passes its `flags` list to Gamescope as command-line arguments (resolution, upscaling filter, sharpness…) and its `env_vars` to the session environment.

#### 4. Game Wrapper
`sdy %command%` as a game's launch option:

* **Profile Lookup**: Looks in `games.d/` for the profile declaring the game's `SteamAppId`, then for one named after the executable (or its folder, for generic names like `start`).
* **Environment Injection**: Applies per-game environment variables, a wrapper command (e.g. `gamemoderun`) and extra arguments.
---

### ⚙️ Centralized Configuration

Configuration is split into system-level (`/etc/default/steamos_diy.conf`) and user-level (`~/.config/steamos_diy/config.yaml`), with optional per-game overrides in `games.d/`. See [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture) for the full filesystem hierarchy.

---

### 📦 Essential Core Packages
* 🚀 **Gamescope**: Valve's micro-compositor for Wayland.
* 🎮 **Steam**: Running in Game Mode (`-gamepadui -steamos3 -steamdeck`).
* 📊 **MangoHud**: Vulkan/OpenGL performance overlay.
* ⚡ **GameMode**: Feral Interactive’s system optimizer.
* 🖥️ **PyQt6**: Powers the **Control Center** dashboard.

---

### ➕ Optional Packages

Recommended companion tools (GPU control, launchers, MangoHud GUIs, save-game backup) are collected in [Useful Links & Resources](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Useful-Links-&-Resources).

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
