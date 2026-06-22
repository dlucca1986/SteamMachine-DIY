# 🎮 SteamMachine-DIY


[![Version](https://img.shields.io/badge/Version-2.1.2-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Transform your Arch Linux machine into a dedicated gaming console using systemd, supporting AMD, Intel, and NVIDIA hardware.**

> [!IMPORTANT]
> This framework is designed for **KDE Plasma 6.x (Wayland)**.
> 
> Before proceeding, please review the documentation to ensure your system meets all hardware and software requirements.
>
> ### 📖 Documentation
> **Read the [Project Wiki](https://github.com/dlucca1986/SteamMachine-DIY/wiki) before installation.**

---

## ✨ Key Features
* **SSOT Architecture**: System lifecycle and identity are governed by a central configuration: `/etc/default/steamos_diy.conf`.
* **Session Launcher**: Manages transitions between Gamescope and KDE Plasma with atomic state updates and crash recovery.
* **Compatibility Shims**: Redirects SteamOS-specific system calls (e.g., updates, BIOS) to DIY logic, ensuring UI stability.
* **Dynamic Parameter Mapping**: Maps YAML configuration flags directly to Gamescope command-line arguments without modifying source code.
* **Game Wrapper (`sdy`)**: Intercepts game launches to apply per-game YAML profiles, environment variables, and wrappers (MangoHud, GameMode).
* **Zero-DM Boot**: Eliminates SDDM/plasmalogin overhead by running the session manager as a high-priority systemd service on TTY1.
* **Control Center**: PyQt6 dashboard for system management, log analysis, and profile editing.

## 🛡️ Design Principles
* **Standard Hierarchy**: Logic resides in `/usr/local/lib/steamos_diy/`, preserving host system integrity.
* **User-Agnostic**: Dynamically detects UIDs and environment paths.
* **Full Reversibility**: Includes an automated uninstaller to restore the original system state.

## 🛠️ Hardware Support
* **AMD**: RADV (Mesa).
* **Intel**: ANV (Mesa).
* **NVIDIA**:
    * **Open Source Drivers (NVK/Nouveau)**: Supported via Mesa. The installer detects the active driver and deploys `mesa` + `lib32-mesa`.
    * **Proprietary Drivers**: **Supported.** When the `nvidia` kernel module is detected, the installer deploys `nvidia-utils` + `lib32-nvidia-utils`.

> [!IMPORTANT]
> **NVIDIA Proprietary Drivers & Gamescope**:
> 
> To use Gamescope with proprietary drivers, you **must** enable DRM Kernel Mode Setting (KMS).
>
> **Recommendation**: Follow the official **[Arch Wiki: NVIDIA DRM kernel mode setting](https://wiki.archlinux.org/title/NVIDIA#DRM_kernel_mode_setting)** to apply the `nvidia-drm.modeset=1` parameter to your specific bootloader.
> 

### 📦 Core Dependencies
The `install.sh` script automatically enables the **[multilib]** repository and installs:

| Category | Packages |
| :--- | :--- |
| **Execution** | `steam`, `gamescope`, `mangohud`, `gamemode`, `xorg-xwayland` |
| **Python Stack** | `python`, `python-pyqt6`, `python-ruamel-yaml` |
| **System Tools** | `vulkan-icd-loader`, `lib32-vulkan-icd-loader`, `vulkan-tools`, `pciutils`, `gcc` |
| **Drivers (Auto)** | `vulkan-radeon`, `vulkan-intel` (+ Mesa layers; Intel also gets VAAPI via `intel-media-driver` + `libva-intel-driver`); NVIDIA: `nvidia-utils` or `mesa` depending on active driver (+ 32-bit counterparts) |

## 🤝 Acknowledgments
Special thanks to the Linux gaming community:
* **[shahnawazshahin](https://github.com/shahnawazshahin/steam-using-gamescope-guide):** For the primary inspiration.
* **[HikariKnight](https://github.com/HikariKnight/ScopeBuddy):** For the ScopeBuddy tool inspiration.
* **[berturion](https://www.reddit.com/r/archlinux/comments/1p2fmso/comment/nqjvr44/):** For technical insights on desktop switching.

## 🚀 Installation

```bash
git clone -b testing https://github.com/dlucca1986/SteamMachine-DIY.git
cd SteamMachine-DIY
chmod +x install.sh
sudo ./install.sh
```

## 🗑️ Uninstallation

```bash
chmod +x uninstall.sh
sudo ./uninstall.sh
```
