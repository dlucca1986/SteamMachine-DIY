[![Version](https://img.shields.io/badge/Version-2.1.1-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: PEP8](https://img.shields.io/badge/Code%20Style-PEP8-brightgreen.svg)](https://www.python.org/dev/peps/pep-0008/)
[![Language: Python](https://img.shields.io/badge/Language-Python-3776AB.svg?logo=python&logoColor=white)](#)
[![Drivers](https://img.shields.io/badge/Drivers-AMD%20%7C%20Intel%20%7C%20NVIDIA-orange.svg)](#)

This page outlines the modular framework for configuring Arch Linux as a dedicated gaming system.

---

### 📍 System Requirements

* **Distribution**: Arch Linux or Arch-based distributions (e.g., EndeavourOS) using `systemd`.
* **Graphics Stack**: Open-source drivers recommended (Mesa). Proprietary NVIDIA also supported.
    * **AMD**: RADV — Recommended
    * **Intel**: ANV
    * **NVIDIA (NVK/Nouveau)**: Mesa open-source Vulkan ICD
    * **NVIDIA (Proprietary)**: `nvidia-utils` deployed automatically if the `nvidia` module is detected
    * **Display Manager**: **None**. The system manages session handovers via a `systemd` service on TTY1.
    * **Desktop Environment**: **KDE Plasma 6.x** (Wayland).

> [!IMPORTANT]
>
> **NVK** is currently in active development; users may experience varying compatibility compared to proprietary drivers.


---

### 🚀 Features

#### 1. Zero-DM & Service-Based Boot
Replaces traditional Display Managers (SDDM/plasmalogin) to eliminate session conflicts and reduce overhead.

* **Direct DRM Access**: The session manager runs as a high-priority service, granting `Gamescope` "DRM Master" status to minimize latency.
* **Visual Transitions**: The integrated `notify` engine manages visual feedback during session swaps, suppressing raw TTY output.

#### 2. Session Management
Session state is persisted to `/var/lib/steamos_diy/next_session` via [atomic writes](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine), ensuring the file is never partially written after a power loss.

* **Crash Recovery**: The launcher monitors sessions via `proc.wait()`. If a session exits before `VALIDATION_TIMEOUT` (default: 5s), the system boots to Desktop to prevent a soft-lock loop.

#### 3. Dynamic Parameter Mapping
Acts as a bridge between user configuration and the compositor:

* **Argument Translation**: The engine parses `config.yaml` and maps variables into command-line arguments for Gamescope (e.g., FSR, HDR, Sharpness).
* **Configuration-driven Tuning**: Allows modification of rendering behavior and display output through text files without altering the Python source code.

#### 4. Game Wrapper
Utility for automated game execution and environment setup:

* **Profile Lookup**: Searches the directory tree for specific `.yaml` configurations based on `SteamAppId` or directory names.
* **Environment Injection**: Applies per-game environment variables and wrappers (e.g., GameMode).
---

### ⚙️ Centralized Configuration

Configuration is split into system-level (`/etc/default/steamos_diy.conf`) and user-level (`~/.config/steamos_diy/config.yaml`), with optional per-game overrides in `games.d/`. See [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture) for the full filesystem hierarchy.

---

### 📦 Essential Core Packages
* 🚀 **Gamescope**: Valve's micro-compositor for Wayland.
* 🎮 **Steam**: Running in `-gamepadui` mode.
* 📊 **MangoHud**: Vulkan/OpenGL performance overlay.
* ⚡ **GameMode**: Feral Interactive’s system optimizer.
* 🖥️ **PyQt6**: Powers the **Control Center** dashboard.

---

### ➕ Optional Packages

* **[Goverlay](https://github.com/benjamimgois/goverlay)**: Graphical interface for MangoHud and vkBasalt.
* **[LACT](https://github.com/ilya-zlobintsev/LACT)**: Control your AMD, Nvidia, or Intel GPU.
* **[Bottles](https://github.com/bottlesdevs/Bottles)**: Run Windows software and games.
* **[ProtonUp-Qt](https://davidotek.github.io/protonup-qt/)**: Manage Proton-GE and Wine-GE versions.
* **[Lutris](https://lutris.net/)**: Central interface for all your game libraries.
* **[Ludusavi](https://github.com/mtkennerly/ludusavi)**: Back up PC game save data.
* **[Protontricks](https://github.com/matoking/protontricks)**: Run Winetricks commands for Steam Play/Proton games.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
