# 🎮 SteamMachine-DIY


[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
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
* **SSoT**: binary paths, config paths, timeouts and the log level live in one file, `/etc/default/steamos_diy.conf`.
* **Session Launcher**: Manages transitions between Gamescope and KDE Plasma with atomic state updates and crash recovery.
* **Compatibility Shims**: Stand-ins for SteamOS helper commands that Steam's Game Mode can call (OS update, BIOS update, timezone, branch); each returns a fixed exit code and changes nothing.
* **Dynamic Parameter Mapping**: The `flags` list in `config.yaml` is passed to Gamescope as command-line arguments.
* **Game Wrapper (`sdy`)**: With `sdy %command%` as a game's launch option, applies its per-game YAML profile: environment variables, a wrapper command (e.g. `mangohud`, `gamemoderun`) and extra arguments.
* **Zero-DM Boot**: No display manager (SDDM/plasmalogin): the session launcher runs as a systemd service on TTY1.
* **Control Center**: PyQt6 dashboard for system management, log analysis, and profile editing.

## 🛡️ Design Principles
* **Standard Hierarchy**: The code lives in `/usr/local/lib/steamos_diy/`; everything deployed outside it is listed in the [Installer Workflow](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Installer-Workflow) wiki page.
* **No hardcoded user**: the installer resolves the installing user's name, UID and home.
* **Reversible**: An uninstaller removes the project's files and puts getty back on TTY1; it offers to re-enable your display manager.

## 🛠️ Hardware Support
* **AMD**: RADV (Mesa).
* **Intel**: ANV (Mesa).
* **NVIDIA**:
    * **Proprietary driver** (`nvidia-open`, `nvidia-open-dkms`): when `nvidia-utils` is installed (all of them depend on it), the installer adds `lib32-nvidia-utils`.
    * **Open driver (NVK)**: otherwise it deploys the NVK Vulkan driver, `vulkan-nouveau` + `lib32-vulkan-nouveau`, with Mesa.
    * **Hybrid laptops** (Intel/AMD + NVIDIA) get the packages for both GPUs.

Tested on Intel and AMD hardware. The NVIDIA package selection is tested in a clean Arch container (detection, dependency resolution, installation); gamescope itself has not been run on an NVIDIA card by the project.

> [!IMPORTANT]
> **NVIDIA Proprietary Drivers & Gamescope**:
> 
> Gamescope needs the NVIDIA driver's DRM Kernel Mode Setting. Check it with `cat /sys/module/nvidia_drm/parameters/modeset` (it must print `Y`); if not, see the **[Arch Wiki: NVIDIA DRM kernel mode setting](https://wiki.archlinux.org/title/NVIDIA#DRM_kernel_mode_setting)**.
> 

### 📦 Core Dependencies
The `install.sh` script automatically enables the **[multilib]** repository and installs:

| Category | Packages |
| :--- | :--- |
| **Execution** | `steam`, `gamescope`, `mangohud`, `lib32-mangohud`, `gamemode`, `lib32-gamemode`, `xorg-xwayland` |
| **Python Stack** | `python`, `python-pyqt6`, `python-ruamel-yaml` |
| **System Tools** | `vulkan-icd-loader`, `lib32-vulkan-icd-loader`, `vulkan-tools`, `pciutils`, `gcc` |
| **Control Center GUI** | `kate`, `konsole`, `xdg-utils` — used directly by name (SSoT editing, terminal launch, "Browse Config Folder"), independent of your desktop environment |
| **Drivers (Auto)** | `vulkan-radeon`, `vulkan-intel` (+ Mesa layers; Intel also gets VAAPI via `intel-media-driver` + `libva-intel-driver`); NVIDIA: `lib32-nvidia-utils` with the proprietary driver, otherwise `vulkan-nouveau` (+ 32-bit) and Mesa; hybrid systems get both GPUs' packages |

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

## 🔄 Updating

From the Control Center: **Maintenance → ⬆️ Check for Updates** (downloads the latest release and runs the installer for you). Or from a terminal, on an unpacked release:

```bash
sudo ./install.sh --update
```

User configs and the SSoT are preserved; the system reboots automatically when done. Details in the **[Updating](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Updating)** wiki page.

## 🗑️ Uninstallation

```bash
chmod +x uninstall.sh
sudo ./uninstall.sh
```

> [!NOTE]
> The uninstaller removes every file the project deployed (your user configs only if you confirm), puts getty back on TTY1 and asks whether to re-enable your display manager (if you decline, the system boots to a text console). Installed packages (`steam`, `gamescope`, Mesa…), the `[multilib]` repository and the group memberships added for your user are deliberately **left in place** — they are standard system components, not project files, and removing them could break unrelated software.
