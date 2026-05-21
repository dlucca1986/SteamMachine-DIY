[![Version](https://img.shields.io/badge/Version-2.0.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Language: Bash](https://img.shields.io/badge/Language-Bash-4EAA25.svg?logo=gnu-bash&logoColor=white)](#)
[![Logic](https://img.shields.io/badge/Logic-Systemd%20Service%20Architecture-blue.svg)](#)
[![Drivers](https://img.shields.io/badge/Drivers-Full%20Open--Source-orange.svg)](#)

This page outlines the deployment procedure for the framework and the associated systemd services.

---

## 🚀 Installation Stages

### 1. Hardware & Driver Audit
The installer identifies the GPU via `lspci` (scanning both `VGA compatible controller` and `3D controller` entries, covering NVIDIA multi-GPU setups where the discrete card appears as a 3D controller) to deploy the Vulkan stack (32/64-bit) required for Proton compatibility:

* **Intel (ANV):** Installs `vulkan-intel`, `lib32-vulkan-intel`, `vulkan-mesa-layers`, `lib32-vulkan-mesa-layers`, `libva-intel-driver`, `lib32-libva-intel-driver`, `mesa`, `lib32-mesa`.
* **AMD (RADV):** Installs `vulkan-radeon`, `lib32-vulkan-radeon`, `vulkan-mesa-layers`, `lib32-vulkan-mesa-layers`, `libva-mesa-driver`, `lib32-libva-mesa-driver`, `mesa`, `lib32-mesa`.
* **NVIDIA (Proprietary):** If the `nvidia` kernel module package is already installed, installs `nvidia-utils`, `lib32-nvidia-utils`.
* **NVIDIA (NVK/Nouveau):** If no proprietary driver is detected, installs `mesa`, `lib32-mesa` for the open-source Vulkan ICD.
* **Unrecognized GPU:** If no known vendor is detected, driver-specific packages are skipped and a warning is printed. The base stack is still installed.

### 2. Dependency & Privilege Management
Configures system access and installs the software stack:

* **Full System Upgrade**: Before installing any package, the installer runs `pacman -Syu` to synchronize the package databases and upgrade all existing packages. This ensures a consistent system state before the framework is deployed.
* **Core Stack:** Installs `python`, `python-pyqt6`, `python-ruamel-yaml`, `steam`, `gamescope`, `xorg-xwayland`, `mangohud`, `lib32-mangohud`, `gamemode`, `lib32-gamemode`, `vulkan-icd-loader`, `lib32-vulkan-icd-loader`, `vulkan-tools`, `mesa-utils`, `pciutils`, `procps-ng`, `qt6-tools`, `rsync`, `gcc`.
* **Hardware Groups:** Automatically manages user membership to ensure hardware access and system administration rights. Adds user to: `tty`, `video`, `render`, `input`, `audio`, `storage`, `gamemode`, `wheel`, `autologin`, and `systemd-journal`. The `tty` group is required for `notify()` to write to `/dev/tty1`.

### 3. SSOT Deployment & Filesystem Policy
Defines the Single **Source of Truth** (SSoT) strategy:

* **System Master:** Generates `/etc/default/steamos_diy.conf`, using `sed` to inject the real **Home** path (`{{HOME}}`). The **Username** (`{{USER}}`) and **UID** (`{{UID}}`) placeholders are patched into the systemd service file in stage 5.
* **User Config Deployment:** Copies YAML templates from `etc/skel/.config/steamos_diy/` to `~/.config/steamos_diy/`. On a **fresh install** (no existing YAMLs), all templates are copied directly. On **reinstall**, the script detects existing configs and interactively asks `"Do you want to overwrite existing YAML configs? (y/N):"` — answering yes overwrites all files (`cp -f`); answering no copies only new files without touching existing ones (`cp -n`).
* **Binary Hierarchy:** Installs all core logic in `/usr/local/lib/steamos_diy/` with execution permissions.
* **C-Core Build:** Compiles `steamos_diy_core.c` into `libcore.so` via `gcc -O2 -fPIC -Wall -Wextra -shared` (same flags as the project `Makefile` for dev/prod parity). After compilation, the library is verified with `ctypes.CDLL()` — if either step fails, installation is aborted with a clear error message.
* **State Management:** Initializes the session tracker at `/var/lib/steamos_diy/next_session`.
* **Desktop Entries:** Installs `Control_Center.desktop` and `Game_Mode.desktop` to `/usr/local/share/applications/`, making both accessible from the KDE application launcher.

### 4. SteamOS Compatibility Shim Layer
Deploys symbolic links to align the environment with **SteamOS** expectations:

* **Polkit Helpers:** Maps BIOS, Timezone, and Update helpers to `/usr/bin/steamos-polkit-helpers/`.
* **System Binaries:** Provides standard aliases like `steamos-update`, `jupiter-biosupdate`, and `steamos-session-launch`.
* **Branch Management:** Links `steamos-select-branch` for update channel selection.
* **User Tools:** Maps `sdy`, `sdy-control-center`, `sdy-backup`, and `sdy-restore` in `/usr/local/bin/`.

### 5. Systemd Service & TTY1 Lockdown
Replaces traditional Display Managers with a custom systemd service:
* **Getty Masking:** The installer **masks** `getty@tty1.service` to prevent terminal conflicts and ensures exclusive control of TTY1.
* **PAM Initialization:** Uses `PAMName=login` to grant the session full access to hardware resources (Pipewire, GPU) without a manual login.
* **Readiness Notification:** `Type=notify` is set so systemd only marks the service as active after `READY=1` is received — which happens only after the session passes the validation window.
* **Watchdog Protection:** Configured with `Restart=on-failure` for automatic session recovery.
* **Service Activation:** Enables the service at boot via `systemctl enable steamos_diy.service`, ensuring the session launcher starts automatically on every subsequent boot.
* **Default Target:** Sets `graphical.target` as the systemd default via `systemctl set-default graphical.target`.

### 6. Security Policy & ALPM Hooks
> [!IMPORTANT]
>
> The installer applies `setcap` privileges to the Gamescope binary.

* **Gamescope Privileges:** Applies `cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep` to `/usr/bin/gamescope` for HDR support and system priority.
* **Persistence:** Installs an **ALPM Hook** (`/usr/share/libalpm/hooks/gamescope-privs.hook`) to re-apply capabilities after every Gamescope update.
* **DM Deactivation:** Automatically disables `sddm` and `plasmalogin` (the two KDE display managers) to prevent session conflicts.

---

## ⚠️ Requirements & Warnings

* **Root Access:** Must be run with `sudo`.
* **Multilib:** The script automatically enables the `[multilib]` repository in `pacman.conf`.
* **Security:** By design, the machine boots directly into the session on TTY1.
* **Post-Install:** A **system reboot** is mandatory to initialize the driver stack and service architecture. At the end of the installation the script prompts `"Reboot now? (y/n):"` — answering yes triggers an immediate reboot.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
