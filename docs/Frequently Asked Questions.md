[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Common questions about the architecture, gaming setup, and maintenance.

---

## 🛠️ General Questions

### 1. Why replace SDDM/plasmalogin?
It is a design choice of this project: one systemd service does the display manager's job:
* `steamos_diy.service` opens the user's session itself via `PAMName=login` — no login prompt, no password at boot. `getty@tty1` is masked.
* Switching between Steam and Plasma means the running session exits and the service restarts into the other one; the two never run together.
* No display manager process runs.

### 2. Is NVIDIA supported?
The installer deploys the packages for both the open driver (**NVK**, `vulkan-nouveau`) and the proprietary one (`nvidia-open`). Tested on Intel and AMD hardware. The NVIDIA package selection is tested in a clean Arch container (detection, dependency resolution, installation); gamescope itself has not been run on an NVIDIA card by the project.

> [!IMPORTANT]
> Gamescope needs the NVIDIA driver's DRM Kernel Mode Setting: `cat /sys/module/nvidia_drm/parameters/modeset` must print `Y`. See the [README](https://github.com/dlucca1986/SteamMachine-DIY#️-hardware-support) for details.

### 3. How do I access the terminal if the UI is frozen?
Since there is no Desktop Environment behind Steam Mode, use the Linux Virtual Terminals:
* Press `Ctrl + Alt + F2` to switch to **TTY2**.
* Login and run: `steamos-session-select desktop`, then return to TTY1 (`Ctrl + Alt + F1`). Tested from TTY2 on a running Game Mode. If a frozen Steam doesn't respond, the Desktop target is already saved, so `sudo systemctl restart steamos_diy.service` should start the Desktop (follows from the code; not tested on a frozen session).

---

## 🎮 Gaming & Steam Mode

### 4. How do I apply custom game overrides?
To use the per-game YAML profiles created in the Control Center, you must use the **SDY Wrapper**:
1. Go to the game's **Properties** in Steam.
2. In **Launch Options**, type: `sdy %command%`.
`sdy` finds the game's profile in `~/.config/steamos_diy/games.d/` (by AppID, then by executable name) and applies it.

### 5. Does `sdy` work with non-Steam games?
Yes: without a Steam AppID, `sdy` looks for a profile named after the executable (`sdy /opt/Hades/hades` → `games.d/hades.yaml`). The project has only used `sdy` from Steam's launch options; Heroic and Lutris have not been tried.

### 6. Steam shows "Update Error" or "BIOS Update Failed".
The **Compatibility Shims** stand in for the SteamOS helper commands behind these functions and return a fixed exit code. If you see such an error, check that they are installed (`ls -l /usr/bin/steamos-update`):
* `steamos-update` exits **7** (SteamOS convention: "no update available") — Steam treats this as "up to date".
* `jupiter-dock-updater` exits **7** (same convention — "firmware up to date").
* All other helpers (`jupiter-biosupdate`, `steamos-set-timezone`, `steamos-select-branch`) exit **0** (success).
---

## 💻 Logic & Control Center

### 7. What is the "Atomic Write" technique?
A write pattern (tmp file → `fdatasync()` → `rename()`): files like `config.yaml` and `next_session` are replaced whole, so a crash or power loss leaves either the old content or the new one, not half a file. The full protocol is documented in [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine).

### 8. How do I switch to Desktop Mode?
1. **From Steam**: Use the "Switch to Desktop" button in the Steam Power menu.
2. **From the terminal**: Run `steamos-session-select desktop`.
Both save `desktop` as the next session and ask Steam to shut down; the service then restarts into Plasma.

---

## 🔊 Audio & Peripherals

### 9. Why is there no sound?
This project expects **PipeWire**. Ensure `pipewire-alsa`, `pipewire-pulse`, and `wireplumber` are installed and running for your user: the Game Mode session plays audio through them.

---

## 🛠️ System & Updates

### 10. Will a system update (`pacman -Syu`) break the setup?
The project uses a **non-destructive** approach: it replaces no file owned by a package (gamescope only gets file capabilities, re-applied by a pacman hook after each gamescope update), so `pacman -Syu` has nothing of the project's to overwrite. A new version of gamescope, Steam or Plasma can still change behavior the project relies on.

### 11. How do I update SteamMachine-DIY itself?
From the Control Center: **Maintenance → ⬆️ Check for Updates** — it downloads the latest release and runs the installer for you (user configs and the SSoT are preserved; the system reboots when done). Or manually with `sudo ./install.sh --update` on an unpacked release. Full details in [Updating](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Updating).

### 12. Does `uninstall.sh` restore the system completely?
It removes every file and symlink the project deployed (libraries, shims, SSoT, service, desktop entries, pacman hook), puts getty back on TTY1, asks whether to re-enable your display manager (if you decline, the system boots to a text console), resets the Gamescope capabilities, and optionally wipes your user configs. Three things are deliberately **left in place**: the installed packages (`steam`, `gamescope`, Mesa drivers, `kate`, `konsole`, `xdg-utils`…), the `[multilib]` repository, and the groups your user was added to — they are standard system components, not project files, and removing them could break software unrelated to the project.

### 13. Where are the configuration files?
| Level | Path | Purpose |
| :--- | :--- | :--- |
| System | `/etc/default/steamos_diy.conf` | Binary paths, log level, timeouts |
| User | `~/.config/steamos_diy/config.yaml` | Gamescope flags and global env vars |
| Game | `~/.config/steamos_diy/games.d/*.yaml` | Per-game overrides |

See [Architecture](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Architecture) for the complete filesystem hierarchy.

### 14. Where can I find the logs for debugging?
Logs go through the **System Journal**. Use the following commands or check the **Diagnostics** tab in the Control Center:
```bash
# Application logs: crash recovery, session switches, gamescope launch args,
# backup/restore, self-update, and helper shims — this is what you want.
journalctl -t CORE -t STEAM -t SYSTEM -f

# Systemd's own service lifecycle only (start/stop/restart, exit codes) —
# NOT the application logs above. PAMName=login moves session_launch.py
# into its own login-session cgroup, so its jlog() output never lands
# under this unit filter; see Troubleshooting for why.
journalctl -u steamos_diy.service -f
```

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
