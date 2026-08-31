[![Version](https://img.shields.io/badge/Version-2.1.7-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Common questions about the architecture, gaming setup, and maintenance.

---

## 🛠️ General Questions

### 1. Why replace SDDM/plasmalogin?
Traditional display managers conflict with Gamescope's requirement for exclusive display control. Replacing them with `steamos_diy.service` means:
* The service authenticates the session directly via `PAMName=login` (no login prompt, no display manager). `getty@tty1` is masked.
* The GPU is handed over cleanly before switching between Steam and Plasma.
* No background display manager processes consuming resources.

### 2. Is NVIDIA supported?
Yes, both open-source (**NVK/Nouveau** via Mesa) and proprietary NVIDIA drivers are supported. The installer automatically deploys the appropriate packages. For the best experience (HDR, advanced frame-pacing), AMD (Mesa/RADV) remains the recommended hardware.

> [!IMPORTANT]
> Proprietary drivers require DRM Kernel Mode Setting to work with Gamescope (`nvidia-drm.modeset=1` on your bootloader). See the [README](https://github.com/dlucca1986/SteamMachine-DIY#️-hardware-support) for details.

### 3. How do I access the terminal if the UI is frozen?
Since there is no Desktop Environment behind Steam Mode, use the Linux Virtual Terminals:
* Press `Ctrl + Alt + F2` to switch to **TTY2**.
* Login and run: `steamos-session-select desktop`

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
This is expected on non-Valve hardware. We provide **Compatibility Shims** that intercept these calls and return a safe exit code to maintain Steam UI stability.
* `steamos-update` exits **7** (RAUC convention: "no update available") — Steam treats this as "up to date".
* `jupiter-dock-updater` exits **7** (same RAUC convention — "firmware up to date").
* All other helpers (`jupiter-biosupdate`, `steamos-set-timezone`, `steamos-select-branch`) exit **0** (success).
---

## 💻 Logic & Control Center

### 7. What is the "Atomic Write" technique?
A write pattern (tmp file → `fdatasync()` → `rename()`) that ensures files like `config.yaml` and `next_session` are never left in a partial state after a power loss. The full protocol is documented in [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine).

### 8. How do I switch to Desktop Mode?
1. **From Steam**: Use the "Switch to Desktop" button in the Steam Power menu.
2. **From the terminal**: Run `steamos-session-select desktop`.
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

### 11. How do I update SteamMachine-DIY itself?
From the Control Center: **Maintenance → ⬆️ Check for Updates** — it downloads the latest release and runs the installer for you (user configs and the SSoT are preserved; the system reboots when done). Or manually with `sudo ./install.sh --update` on an unpacked release. Full details in [Updating](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Updating).

### 12. Does `uninstall.sh` restore the system completely?
It removes every file and symlink the project deployed (libraries, shims, SSoT, service, desktop entries, pacman hook), restores the boot chain (getty on TTY1, your display manager, the default target), resets the Gamescope capabilities, and optionally wipes your user configs. Three things are deliberately **left in place**: the installed packages (`steam`, `gamescope`, Mesa drivers…), the `[multilib]` repository, and the groups your user was added to — they are standard system components, not project files, and removing them could break software unrelated to the project.

### 13. Where are the configuration files?
| Level | Path | Purpose |
| :--- | :--- | :--- |
| System | `/etc/default/steamos_diy.conf` | Binary paths, log level, timeouts |
| User | `~/.config/steamos_diy/config.yaml` | Gamescope flags and global env vars |
| Game | `~/.config/steamos_diy/games.d/*.yaml` | Per-game overrides |

See [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture) for the complete filesystem hierarchy.

### 14. Where can I find the logs for debugging?
We use the **System Journal**. Use the following commands or check the **Diagnostics** tab in the Control Center:
```bash
# Session logs (Gaming/Desktop lifecycle, crash recovery)
journalctl -u steamos_diy.service -f

# Full log stream including helper shims and backup/restore
# (helpers run outside the service cgroup, so -u alone misses them)
journalctl -t CORE -t STEAM -t SYSTEM -f
```

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
