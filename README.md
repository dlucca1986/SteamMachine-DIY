# 🎮 SteamMachine-DIY (Systemd Native Build for AMD and Intel)
**Transform any Arch Linux machine into a powerful, seamless SteamOS Console.**

[![Version](https://img.shields.io/badge/Version-3.1.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> ### "The most robust, hardware-agnostic SteamOS experience for the Arch ecosystem."

---

## 🌟 About the Project

Hi, I'm Daniele, and I’m a hardcore gaming fanatic! 🕹️

This project has evolved into a professional **System Overlay** designed to faithfully replicate the SteamOS ecosystem. Version 3.1.0 marks a major milestone: transitioning from a script-based approach to a robust, **system-native architecture** driven by `systemd`. 

While the project remains hardware-agnostic by design (supporting both **AMD and Intel**), this new version deepens the integration with the Linux OS core for unprecedented stability.

---

## ✨ Key Features (Systemd Edition)

* **🔄 Native Session Switching**:
  Transition between **Gamescope** and **KDE Plasma** using the official UI buttons. No login screens, no passwords—just a clean handover managed by `systemd` unit conflicts.

* **🎨 Custom Boot Experience**:
  Includes a **Custom Boot Splash** integration to provide a seamless visual experience from power-on to shutdown, hiding the console clutter.

* **🧠 Intelligent Hardware Detection**:
  The new launcher automatically detects resolution, refresh rates, and GPU capabilities. It configures itself on the fly, ensuring you reach the UI even on complex multi-monitor setups.

* **⚙️ Centralized Master Config**:
  No more hunting for hidden files. The entire system is now governed by a single, professional configuration file: `/etc/default/steamos-diy`.

* **⚡ Zero-DM Boot (Deterministic & Lean)**:
  Eliminates SDDM/GDM. The system boots directly into the session via `agetty` autologin on TTY1, ensuring a reliable GPU handover and reducing background overhead.

* **🚀 SteamOS Compatibility Shims**:
  Includes specialized helpers (`jupiter-biosupdate`, `steamos-update`) that "trick" the Steam UI into thinking it's on official hardware, preventing update errors.

* **🎮 Universal Game Wrapper (sdy)**:
  A powerful injection tool for your games. Add custom prefixes, or extra arguments globally or on a per-game basis.

* **🛠️ SteamMachine-DIY Control Center (sdy companion)**:
  A Python-based graphical utility designed to manage the system's core settings. It allows users to easily configure **Gamescope** parameters, customize the **Universal Game Wrapper**, monitor real-time system logs, and manage the **Safe Mode** state through an intuitive interface.
  
---

## 🛡️ Clean Architecture & Safety

I value your system's integrity. This project follows a "system-safe" philosophy to ensure your Arch Linux installation remains clean and stable:

* **Filesystem Hierarchy Standard**: Scripts are isolated in `/usr/local/bin/steamos-helpers/`, keeping your primary `/usr/bin/` clean while satisfying Steam's hardcoded path requirements through symbolic links.
* **Transparent Sudoers**: Security is paramount. A minimal, dedicated policy file is added to `/etc/sudoers.d/steamos-diy`. It grants passwordless execution *only* to the specific scripts required for session switching.
* **Systemd-Driven**: Sessions are managed as proper system services (`steamos-gamemode@.service`), ensuring better logging and process recovery.
* **User-Agnostic**: Everything is built using dynamic UID/User detection. No hardcoded usernames.
* **Wayland-First & DM-Less**: Optimized for direct Wayland execution. By bypassing the Display Manager, we ensure **Gamescope** has exclusive, conflict-free access to the GPU.
* **Full Reversibility**: Every system change, link, and configuration entry is tracked. The included uninstaller can revert your system to its original state at any time.

---

## 🛠️ Prerequisites

* **GPU**: AMD Radeon (preferred) or Intel Graphics (Mesa drivers).
* **Display Manager**: **None/Disabled** (Direct TTY1 login).
* **Desktop Environment**: KDE Plasma 6.x.
* **Core Software**: `steam`, `steam-devices`, `gamescope`, `mangohud`, `gamemode`, `lib32-gamemode`, `python-pyqt6`

---

## 📖 Documentation & Wiki:

* **For detailed guides and technical information, please visit our Project Wiki.** https://github.com/dlucca1986/SteamMachine-DIY/wiki

---

## 🤝 Acknowledgments & Credits:

This project wouldn't have been possible without the amazing work and guides from the Linux gaming community. A special thanks to:

* **[shahnawazshahin](https://github.com/shahnawazshahin/steam-using-gamescope-guide):** For writing a wonderful guide that served as a primary inspiration for this project.
* **[HikariKnight](https://github.com/HikariKnight/ScopeBuddy):** For the excellent ScopeBuddy tool which inspired the Universal Game Wrapper.
* **[berturion](https://www.reddit.com/r/archlinux/comments/1p2fmso/comment/nqjvr44/):** For the brilliant technical insights that helped finalize the desktop switching logic.
* **The SteamOS & Gamescope Teams:** For building the foundation of handheld gaming on Linux.
* **Community Guides:** Big thanks to the developers and enthusiasts on **Reddit** (r/SteamDeck, r/LinuxGaming) and the **Arch Wiki** contributors.
* **Open Source Contributors:** To everyone sharing scripts and ideas to make Linux a better place for gamers. 

---

## ❤️ Support the Project

Built with ❤️ by a gaming fan for the Linux Community.  
**If you like this project, please leave a ⭐ Star on GitHub!** It helps other gamers find it.

---

## 🚀 Quick Installation

Follow these steps to transform your system. The installer will guide you through the process, detect your hardware, and handle all dependencies.

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
