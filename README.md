# 🎮 SteamMachine-DIY
**Transform any Arch Linux machine into a powerful, seamless SteamOS Console.**

[![Version](https://img.shields.io/badge/Version-3.1.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> ### "The most robust, hardware-agnostic SteamOS experience for the Arch ecosystem."

---

## 🌟 About the Project

Hi, I'm **Daniele**! 🕹️

This project has evolved into a professional **System Overlay** designed to faithfully replicate the SteamOS ecosystem. Version 3.1.0 marks a major milestone: moving away from user-specific hacks to a robust, **hardware-agnostic architecture** driven by `systemd`.

---

## ✨ Key Features (Agnostic Edition)

* **🔄 Native Session Switching**:
  Transition between **Gamescope** and **KDE Plasma** using the official UI buttons. No login screens, no passwords—just a clean handover managed by `systemd` unit conflicts.

* **🧠 Intelligent Hardware Detection**:
  The new launcher automatically detects resolution, refresh rates, and GPU capabilities. It configures itself on the fly, ensuring you reach the UI even on complex multi-monitor setups.

* **⚙️ Centralized Master Config**:
  No more hunting for hidden files. The entire system is now governed by a single, professional configuration file: `/etc/default/steamos-diy`.

* **🎮 Universal Game Wrapper (sdy)**:
  A powerful injection tool for your games. Add custom prefixes, or extra arguments globally or on a per-game basis.

---

## 🛡️ Clean Architecture & Safety

I value your system's integrity. The "Agnostic" version follows a strict system-safe philosophy:

* **Filesystem Hierarchy Standard**: Scripts are isolated in `/usr/local/bin/steamos-helpers/`, keeping your primary `/usr/bin/` clean while satisfying Steam's hardcoded path requirements through symbolic links.
* **Systemd-Driven**: Sessions are managed as proper system services (`steamos-gamemode@.service`), ensuring better logging and process recovery.
* **User-Agnostic**: Everything is built using dynamic UID/User detection. No hardcoded usernames.
* **Wayland-Native**: Optimized for KDE Plasma 6 and Wayland-based SDDM to prevent X11 socket conflicts.

---

## 🛠️ Prerequisites

* **GPU**: AMD Radeon (preferred) or Intel Graphics (Mesa drivers).
* **Display Manager**: **SDDM** (configured for Wayland).
* **Desktop Environment**: KDE Plasma 6.x.
* **Core Software**: `steam`, `gamescope`, `mangohud`, `gamemode`.

---

## 📖 Documentation & Wiki:

* **For detailed guides and technical information, please visit our Project Wiki.** https://github.com/dlucca1986/SteamMachine-DIY/wiki

---

## 🤝 Acknowledgments & Credits:

This project wouldn't have been possible without the amazing work and guides from the Linux gaming community. A special thanks to:

* **[shahnawazshahin](https://github.com/shahnawazshahin/steam-using-gamescope-guide):** For writing a wonderful guide that served as a primary inspiration for this project.
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

## 🛡️ Clean Architecture & Safety

I value your system's integrity. This project follows a "system-safe" philosophy to ensure your Arch Linux installation remains clean and stable:

* **Non-Intrusive**: Real binaries and scripts are isolated in `/usr/local/bin/`. We use a dedicated directory `/usr/bin/steamos-polkit-helpers/` for symbolic links. This satisfies Steam's hardcoded path requirements without cluttering or overwriting files in your primary `/usr/bin/` directory.

* **Transparent Sudoers**: Security is paramount. A minimal, dedicated policy file is added to `/etc/sudoers.d/steamos-switcher`. It grants passwordless execution *only* to the specific scripts required for session switching, following the principle of least privilege.
  
* **Wayland-First Approach**: The project configures SDDM to run on Wayland. This is a strategic choice to ensure **Gamescope** can reliably claim the primary display socket, preventing common X11 resource conflicts and ensuring a seamless transition between the Desktop and Gaming Mode.

* **Full Reversibility**: Every system change, link, and configuration entry is tracked. The included uninstaller can revert your system to its original state at any time.

---

## 🗑️ Uninstallation
If you wish to revert all changes, I’ve included a dedicated uninstaller. 

It will completely remove all scripts, symbolic links, desktop shortcuts, and the sudoers rule:

```bash
chmod +x uninstall.sh
sudo ./uninstall.sh
```
