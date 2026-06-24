[![Version](https://img.shields.io/badge/Version-2.1.3-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The DM-less boot: systemd service, TTY1 handover, and boot-time tuning.

---

## 🔄 1. The Startup Sequence (Boot Flow)

The system bypasses traditional login managers to initialize the graphical environment directly:

1.  **Unit Initialization**: `systemd` triggers `steamos_diy.service` on TTY1 as part of the `graphical.target`.
2.  **Configuration Sourcing**: The launcher reads global variables from the SSoT file (`/etc/default/steamos_diy.conf`).
3.  **State Identification**: The engine queries `/var/lib/steamos_diy/next_session` to determine the target environment.
4.  **Session Execution**:
    *   **Gaming Mode**: Generates Gamescope parameters ➔ Spawns Steam ➔ Activates Watchdog.
    *   **Desktop Mode**: Spawns a native KDE Plasma session.
5.  **Session Transition**: `session_select.py` updates the state file and sends a termination signal to the active session. The Launcher (`session_launch.py`) detects the session exit, handles the notification delay, and terminates. Finally, `systemd` triggers an automatic **Unit Restart**.

---

## 🏗️ 2. Core Implementation

The framework integrates directly into the systemd hierarchy, replacing the display manager with a single service.

### Systemd & TTY Control
*   **Targeting**: The unit is linked to `graphical.target.wants/`. Standard DMs (SDDM, plasmalogin) are disabled to avoid resource conflicts.
*   **TTY Exclusive Access**: The service masks `getty@tty1.service` to take direct control of `/dev/tty1`, preventing login prompts from flickering during boot.
*   **PAM Authentication**: By using `PAMName=login`, the service initializes a full authenticated session, ensuring proper permissions for **Pipewire**, **DRI/GPU acceleration**, and device mounting.
*   **Readiness Notification**: `Type=notify` is set so systemd receives `READY=1` only after the session survives the validation window. This means dependent units and `systemctl start` calls block until the session is confirmed stable.

### Environment & Recovery
*   **Runtime Context**: The service sets `XDG_RUNTIME_DIR=/run/user/<UID>` and `XDG_SESSION_TYPE=wayland` explicitly, ensuring Gamescope and Wayland clients operate correctly outside a standard desktop login session.
*   **Log Routing**: `StandardOutput=journal` and `StandardError=journal` route all session output to the systemd journal, visible via `journalctl -u steamos_diy.service`.
*   **Fault Tolerance**: A `Restart=on-failure` policy with a `1-second` delay ensures the session recovers automatically from crashes and restarts after session switches.
*   **TTY Cleanup**: `TTYReset=yes` and `TTYVTDisallocate=yes` ensure the terminal is fully reset between session restarts, preventing display artifacts.
*   **Kill Policy**: `KillMode=mixed` sends `SIGTERM` to the main process only (not the whole cgroup), allowing `session_launch.py`'s signal handler to drain the child process before exiting. `TimeoutStopSec=10` sets the hard limit before systemd escalates to `SIGKILL`.

> [!IMPORTANT]
> **Plasma 6 & plasmalogin**
>
> Modern Plasma 6.x environments may use `plasmalogin.service`.
>
> The installer automatically detects and disables it.
>
> Please refer to the **[Arch Wiki](https://wiki.archlinux.org/title/Plasma_Login_Manager)** for technical details.

---

## 🖥️ 3. Session Handover Mechanism

A session switch involves three components working in sequence:

1. `session_select.py` writes the new target (`steam` or `desktop`) to `/var/lib/steamos_diy/next_session` atomically, then sends a shutdown signal to the active session (`steam -shutdown` or `qdbus6 org.kde.Shutdown /Shutdown logout`).
2. `session_launch.py` detects that its child process has exited, displays a transition message on TTY1, and exits with code `75` (`EX_TEMPFAIL`).
3. `steamos_diy.service` treats code `75` as a failure (`Restart=on-failure`, `RestartSec=1.0s`) and restarts the launcher, which reads the new target from the state file and spawns the next session. A deliberate stop (`systemctl stop`) exits with `0` and does **not** trigger a restart.

For the full lifecycle including crash recovery, see [SteamOS Session Launch](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Steamos-Session-Launch).

---

## 🏎️ 4. Performance Optimization: Removing Plymouth
To minimize boot latency, removing Plymouth is recommended.

### **Step 1: Initramfs Configuration**

#### **A. Systems using `mkinitcpio` (Standard Arch)**
1. Edit `/etc/mkinitcpio.conf` and remove `plymouth` from the `HOOKS` array.
2. Rebuild: `sudo mkinitcpio -P`

#### **B. Systems using `dracut` (EndeavourOS / Modern Defaults)**
1. Remove package: `sudo pacman -Rs plymouth`.
2. Rebuild: `sudo dracut-rebuild` (or `sudo reinstall-kernels`).

### **Step 2: Bootloader Parameters**
Remove the `splash` flag from the kernel command line.

#### **If using GRUB:**
1. Edit `/etc/default/grub` and remove `splash` from `GRUB_CMDLINE_LINUX_DEFAULT`.
2. Update config: `sudo grub-mkconfig -o /boot/grub/grub.cfg`.

#### **If using systemd-boot:**
1. Edit the entry file in `/boot/loader/entries/*.conf` (or `/etc/kernel/cmdline`).
2. Remove `splash` from the `options` line.
3. Run `sudo reinstall-kernels`.

---

## 💡 5. Post-Installation Tips
### Disable Plasma Splash Screen
To prevent visual artifacts during the handover to the Wayland compositor:
1. Navigate to **System Settings** > **Colors & Themes** > **Splash Screen**.
2. Select **None** and click **Apply**.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
