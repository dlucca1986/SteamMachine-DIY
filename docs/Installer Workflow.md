[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

What `install.sh` does, stage by stage.

---

## ✅ Precondition Check
Before touching anything, the installer verifies `qdbus6` and `startplasma-wayland` are
on `$PATH`: it adds a gamescope-first boot to an existing **KDE Plasma 6 (Wayland)** install
and does not install Plasma itself. If either is missing it stops with an error — the later
steps disable SDDM/plasmalogin and mask `getty@tty1`, so without Plasma the first boot would
have no working desktop to fall back to. Install Plasma (`qt6-tools` + `plasma-workspace`,
or the full `plasma` group) first if this check fails.

---

## 🚀 Installation Stages

### 1. Hardware Audit & Driver Selection
The installer identifies the GPU via `lspci` (scanning both `VGA compatible controller` and `3D controller` entries, covering NVIDIA multi-GPU setups where the discrete card appears as a 3D controller) and installs that vendor's Vulkan drivers, 64- and 32-bit:

* **Intel (ANV):** Installs `vulkan-intel`, `lib32-vulkan-intel`, `vulkan-mesa-layers`, `lib32-vulkan-mesa-layers`, `intel-media-driver`, `libva-intel-driver`, `lib32-libva-intel-driver`, `mesa`, `lib32-mesa`. `intel-media-driver` (iHD) and `libva-intel-driver` (i965) are the two VA-API drivers; Arch has no 32-bit package of the former, so `lib32-libva-intel-driver` is the only 32-bit one.
* **AMD (RADV):** Installs `vulkan-radeon`, `lib32-vulkan-radeon`, `vulkan-mesa-layers`, `lib32-vulkan-mesa-layers`, `mesa`, `lib32-mesa` (VAAPI comes with `mesa`).
* **NVIDIA (Proprietary):** If `nvidia-utils` is installed — every Arch proprietary driver package (`nvidia-open`, `nvidia-open-dkms`) depends on it — installs `nvidia-utils`, `lib32-nvidia-utils`.
* **NVIDIA (NVK):** Otherwise, installs the open Vulkan driver `vulkan-nouveau`, `lib32-vulkan-nouveau`, plus `mesa`, `lib32-mesa`.
* **Hybrid laptops:** each vendor is checked separately, so an Intel or AMD GPU next to an NVIDIA one gets both sets.
* **Unrecognized GPU:** If no known vendor is detected, driver-specific packages are skipped and a warning is printed. The base stack is still installed.

The NVIDIA selection is tested in a clean Arch container (detection, dependency resolution, installation); gamescope has not been run on an NVIDIA card by the project.

### 2. Dependency Management & Database Sync

* **Full System Upgrade**: Before installing any package, the installer runs `pacman -Syu` to synchronize the package databases and upgrade all existing packages. Arch does not support partial upgrades, so the new packages are installed in the same transaction as the upgrade.
* **Core Stack:** Installs `python`, `python-pyqt6`, `python-ruamel-yaml`, `steam`, `gamescope`, `xorg-xwayland`, `mangohud`, `lib32-mangohud`, `gamemode`, `lib32-gamemode`, `vulkan-icd-loader`, `lib32-vulkan-icd-loader`, `vulkan-tools`, `pciutils`, `gcc`, `kate`, `konsole`, `xdg-utils`. The last three are explicit dependencies — the Control Center's "Edit SSoT", "Open Konsole Terminal", and "Browse Config Folder" buttons target these exact binaries by name, independent of whichever desktop environment is actually running.
* **Groups:** Adds the user to: `tty`, `video`, `render`, `input`, `audio`, `storage`, `gamemode`, `wheel`, `autologin`, and `systemd-journal`. `tty` is there for `notify()`'s writes to `/dev/tty1`.

### 3. File Deployment & SSoT Initialization

* **System Master:** Generates `/etc/default/steamos_diy.conf`, using `sed` to inject the real **Home** path (`{{HOME}}`). The **Username** (`{{USER}}`) and **UID** (`{{UID}}`) placeholders are patched into the systemd service file in stage 5.
* **User Config Deployment:** Copies YAML templates from `etc/skel/.config/steamos_diy/` to `~/.config/steamos_diy/`. On a **fresh install** (no existing YAMLs), all templates are copied directly. On **reinstall**, the script detects existing configs and interactively asks `"Do you want to overwrite existing YAML configs? (y/N):"` — answering yes overwrites all files (`cp -f`); answering no copies only new files without touching existing ones (`cp -n`).
* **Code:** Copies the Python modules and helpers to `/usr/local/lib/steamos_diy/` and marks them executable (the test suite is not installed).
* **C-Core Build:** Compiles `steamos_diy_core.c` into `libcore.so` with `gcc -O2 -march=native -fPIC -Wall -Wextra -shared` (the `Makefile`'s flags), into a temporary file next to `/usr/local/lib/steamos_diy` (not `/tmp`, which may be `noexec`), and checks it loads with `ctypes.CDLL()` **before** touching the existing install. If either step fails the installer stops with an error, and on `--update` the previous install is left as it was.
* **State file:** Creates `/var/lib/steamos_diy/next_session` with `steam` if it doesn't exist, owned by the user.
* **Desktop Entries:** Installs `Control_Center.desktop` and `Game_Mode.desktop` to `/usr/local/share/applications/`.
* **Gamescope capabilities:** Applies `cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep` to `/usr/bin/gamescope` (`cap_sys_nice` is the one gamescope checks, for realtime scheduling and higher-priority threads).
* **Pacman hook:** Installs `/usr/share/libalpm/hooks/gamescope-privs.hook`, which re-applies the capabilities after each install or upgrade of the `gamescope` package.

### 4. SteamOS Compatibility Shim Layer
Creates the symbolic links (full table in [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture)):

* **Polkit Helpers:** Links the BIOS, timezone, OS-update and dock-update shims into `/usr/bin/steamos-polkit-helpers/`.
* **`/usr/bin` aliases:** `steamos-update`, `jupiter-biosupdate`, `steamos-set-timezone`, `steamos-session-launch`, `steamos-session-select`.
* **Branch shim:** `/usr/bin/steamos-select-branch`.
* **User Tools:** Links `sdy`, `sdy-control-center`, `sdy-backup`, and `sdy-restore` in `/usr/local/bin/`.

### 5. Boot & Systemd Configuration
In this order (what the unit's settings do is in [Zero-DM Boot & TTY1](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Zero-DM-Setup)):
* **Service unit:** Copies `steamos_diy.service` to `/etc/systemd/system/` with the user name and UID filled in.
* **Service Activation:** `systemctl enable steamos_diy.service`.
* **Default Target:** `systemctl set-default graphical.target`.
* **Getty Masking:** Masks `getty@tty1.service`, last: if an earlier step fails, TTY1 still has its login prompt.

### 6. Cleanup
* **DM Deactivation:** Disables `sddm` and `plasmalogin`, so neither starts at boot.

---

## 🔄 Update Mode (`--update`)

`sudo ./install.sh --update` runs the same stages non-interactively over an existing installation — it is what the Control Center's **Check for Updates** button runs:

* **SSoT preserved:** the live `/etc/default/steamos_diy.conf` is never overwritten. The freshly rendered template is compared against the pristine copy of the previous deploy (`/var/lib/steamos_diy/ssot.template`); if it changed, it is staged as `steamos_diy.conf.new` (pacman `.pacnew` style) for manual review.
* **User YAMLs preserved:** existing files are kept without prompting; only files that don't exist yet are added (`cp -n`). This also means the `*.example.yaml` reference files already in your config folder are **not** refreshed by an update.
* **Clean redeploy:** `/usr/local/lib/steamos_diy/` is wiped before copying, so files removed or renamed by the new release cannot linger.
* **Automatic reboot:** after a 10-second countdown (`CTRL+C` aborts) instead of the interactive prompt.
* **pkexec aware:** the real user is resolved from `SUDO_USER` *or* `PKEXEC_UID`, so the Control Center's polkit-driven invocation deploys user files to the right home.

See **[Updating](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Updating)** for the full user-facing procedure.

## ⚠️ Requirements & Warnings

* **Root Access:** Must be run with `sudo`.
* **Multilib:** The script enables the `[multilib]` repository in `pacman.conf`.
* **No login at boot:** the machine boots straight into the user's session, with no password prompt. Anyone with physical access to it gets that session.
* **Post-Install:** Reboot to start the service (it is enabled, not started, by the installer). At the end of the installation the script prompts `"Reboot now? (y/n):"` — answering yes triggers an immediate reboot.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
