# 🎮 SteamMachine-DIY
**Transform any Arch Linux machine into a powerful, seamless SteamOS Console.**

[![Version](https://img.shields.io/badge/Version-1.0.0-green.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Drivers](https://img.shields.io/badge/Drivers-Full%20Open--Source-orange.svg)](#)

> ### "The most robust, hardware-agnostic, and 100% open-source driver experience for the Arch ecosystem."

---

## 🌟 About the Project

Hi, I'm Daniele, and I’m a hardcore gaming fanatic! 🕹️

This project is a professional **System Overlay** designed to faithfully replicate the SteamOS ecosystem on generic hardware. Version 1.0.0 introduces the **SSOTH (Single Source of Truth)** architecture, ensuring that your system remains clean, fast, and hardware-agnostic (supporting **AMD**, **NVIDIA**, and **Intel**).

Unlike other solutions, this project avoids complex systemd overrides or heavy display managers, focusing on a lean, script-driven handover for maximum performance.

---

## ✨ Key Features

* **🔄 SSOTH Core Architecture**:
  The entire system is governed by a single, professional configuration file: `/etc/default/steamos-diy`. This "Single Source of Truth" manages all system identities and paths dynamically.

* **🧠 Intelligent Session Launcher**:
  A robust loop-based manager that handles the transition between **Gamescope** and **KDE Plasma**. It features **Atomic State Updates** to prevent file corruption even during unexpected shutdowns.

* **🎨 Seamless TTY Feedback**:
  Integrated visual banners (`ssoth_banner`) provide professional feedback directly on the TTY during session switches, hiding console clutter.

* **🚀 SteamOS Compatibility Shims**:
  Includes specialized helpers (`jupiter-biosupdate`, `steamos-update`, `steamos-select-branch`) that "trick" the Steam UI into thinking it's on official hardware, ensuring UI stability and preventing update errors.

* **⚙️ Dynamic Gamescope Mapping**:
  The launcher automatically transforms configuration variables (e.g., `GS_WINE_FULLSCREEN=1`) into Gamescope arguments (`--wine-fullscreen`) on the fly.

* **🎮 Universal Game Wrapper (sdy)**:
  A powerful discovery engine for your games. It intelligently climbs directory levels to find specific `.conf` files, allowing custom wrappers or arguments per-game.

* **⚡ Zero-DM Boot (Lean & Fast)**:
  Eliminate SDDM/GDM overhead. The system boots directly into the session via `agetty` autologin on TTY1, ensuring reliable GPU handover to Gamescope.

* **🛠️ Control Center (sdy companion)**:
  A Python-based utility to manage Gamescope parameters and customize game wrappers through an intuitive interface.

---

## 🛡️ Clean Architecture & Safety

I value your system's integrity. This project follows a "system-safe" philosophy:

* **Filesystem Hierarchy Standard**: Scripts are located in `/usr/local/bin/`, keeping your primary `/usr/bin/` clean while satisfying Steam's requirements through symbolic links.
* **User-Agnostic**: Built using dynamic UID/User detection. No hardcoded usernames or IDs.
* **Wayland-First**: Optimized for direct Wayland execution, giving Gamescope exclusive, conflict-free access to the GPU.
* **Full Reversibility**: Every change is tracked. The included uninstaller can revert your system to its original state at any time.

---

## 🛠️ Prerequisites

* **GPU**: AMD Radeon, Intel Graphics, or NVIDIA (Support via NVK/Mesa open-source drivers).
* **Display Manager**: **None/Disabled** (Direct TTY1 login).
* **Desktop Environment**: KDE Plasma 6.x (Wayland).
* **Core Software**: `steam`, `steam-devices`, `gamescope`, `mangohud`, `gamemode`, `lib32-gamemode`, `python-pyqt6`, `qdbus6`.
* **Mesa Drivers**: `vulkan-radeon` (AMD), `vulkan-intel` (Intel), or `vulkan-nouveau` (NVIDIA NVK).

---

## 📖 Documentation & Wiki

For detailed guides and technical information, please visit our [Project Wiki](https://github.com/dlucca1986/SteamMachine-DIY/wiki).

---

## 🤝 Acknowledgments & Credits

Special thanks to the Linux gaming community:
* **[shahnawazshahin](https://github.com/shahnawazshahin/steam-using-gamescope-guide):** For the primary inspiration.
* **[HikariKnight](https://github.com/HikariKnight/ScopeBuddy):** For the ScopeBuddy tool inspiration.
* **[berturion](https://www.reddit.com/r/archlinux/comments/1p2fmso/comment/nqjvr44/):** For technical insights on desktop switching.
* **The SteamOS & Gamescope Teams:** For building the foundation of handheld gaming on Linux.

---

## 🚀 Quick Installation

The installer is interactive and will automatically configure the SSOTH environment and system permissions.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/dlucca1986/SteamMachine-DIY.git
   ```

2. **Enter the folder**:
   ```
   cd SteamMachine-DIY
   ```
  
3. **Set Permission**:
   ```
   chmod +x install.sh
   ```
4. **Run the Installer**:
    ```
   sudo ./install.sh
   ```    

* 💡 **Note**: The installer is interactive and will automatically verify your AMD/Intel hardware, install missing dependencies, and configure the necessary system permissions.

---

## 🗑️ Uninstallation
If you wish to revert all changes, I’ve included a dedicated uninstaller. 

It will completely remove all scripts, symbolic links, desktop shortcuts, and the sudoers rule:

```bash
chmod +x uninstall.sh
sudo ./uninstall.sh
```
