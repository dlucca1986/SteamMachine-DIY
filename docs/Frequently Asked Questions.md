[![Version](https://img.shields.io/badge/Version-1.0.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Support](https://img.shields.io/badge/Support-Documentation-blue.svg)](#)
[![Status](https://img.shields.io/badge/Status-Active-success.svg)](#)

This page outlines common technical inquiries regarding the SteamMachine-DIY architecture, philosophy, and implementation.

---

## 🛠️ General Questions

### 1. Why replace SDDM/GDM?
Traditional display managers conflict with Gamescope's requirement for exclusive display control. Replacing them with `steamos_diy.service` means:
* The service starts immediately after TTY auto-login on `graphical.target`.
* The GPU is released before switching between Steam and Plasma.
* No background display manager processes consuming resources.

### 2. Is NVIDIA supported?
Yes, both open-source (**NVK/Nouveau** via Mesa) and proprietary NVIDIA drivers are supported. The installer automatically deploys the appropriate packages.
> [!IMPORTANT]
> For the best experience (HDR, advanced frame-pacing), AMD (Mesa/RADV) remains the recommended hardware.
>
> **Proprietary drivers + Gamescope**: To use Gamescope with proprietary drivers, you **must** enable DRM Kernel Mode Setting (KMS) by adding `nvidia-drm.modeset=1` to your bootloader. See the [Arch Wiki: NVIDIA DRM kernel mode setting](https://wiki.archlinux.org/title/NVIDIA#DRM_kernel_mode_setting) for instructions.

### 3. How do I access the terminal if the UI is frozen?
Since there is no Desktop Environment behind Steam Mode, use the Linux Virtual Terminals:
* Press `Ctrl + Alt + F2` to switch to **TTY2**.
* Login and use the `sdy-mode-desktop` alias to recover.

---

## 🎮 Gaming & Steam Mode

### 4. How do I apply custom game overrides?
To use the per-game YAML profiles created in the Control Center, you must use the **SDY Wrapper**:
1. Go to the game's **Properties** in Steam.
2. In **Launch Options**, type: `sdy %command%`.
The system will automatically identify the game (via AppID or executable name) and apply the specific tweaks from `~/.config/steamos_diy/games.d/`.

### 5. Does `sdy` work with non-Steam games?
Yes. `sdy` is binary-agnostic. It scans the executable path and looks for a matching YAML profile. You can use it with Heroic, Lutris, or standalone binaries.

### 6. Steam shows "Update Error" or "BIOS Update Failed".
This is expected on non-Valve hardware. We provide **Compatibility Shims** that intercept these calls and return a "Success" code to maintain Steam UI stability.
---

## 💻 Logic & Control Center

### 7. What is the "Atomic Write" technique?
A write pattern (tmp file → `fdatasync()` → `rename()`) that ensures files like `config.yaml` and `next_session` are never left in a partial state after a power loss. The full protocol is documented in [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine).

### 8. How do I switch to Desktop Mode?
1. **From Steam**: Use the "Switch to Desktop" button in the Steam Power menu.
2. **From the Dashboard**: Use the "Switch to Desktop" button in the Control Center.
The logic handles the termination signals and ensures a clean transition to KDE Plasma.

---

## 🔊 Audio & Peripherals

### 9. Why is there no sound?
This project is optimized for **Pipewire**. Ensure `pipewire-alsa`, `pipewire-pulse`, and `wireplumber` are active. Gamescope requires a functional Pipewire node to route audio from the containerized session to your hardware.

---

## 🛠️ System & Updates

### 10. Will a system update (`pacman -Syu`) break the setup?
The project uses a **non-destructive** approach. We don't modify core system binaries. Standard updates are safe.
> [!IMPORTANT]
>
> If you update the Kernel, ensure your **Early KMS** is rebuilt so the driver loads before the `steamos_diy` service starts.

### 11. Where are the configuration files?
| Level | Path | Purpose |
| :--- | :--- | :--- |
| System | `/etc/default/steamos_diy.conf` | Binary paths, log level, timeouts |
| User | `~/.config/steamos_diy/config.yaml` | Gamescope flags and global env vars |
| Game | `~/.config/steamos_diy/games.d/*.yaml` | Per-game overrides |

See [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture) for the complete filesystem hierarchy.

### 12. Where can I find the logs for debugging?
We use the **System Journal**. Use the following command or check the **Logs** tab in the Control Center:
```bash
journalctl -u steamos_diy.service -f
````

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
