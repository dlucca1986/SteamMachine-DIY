[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The DM-less boot: systemd service, TTY1 handover, and boot-time tuning.

---

## 🔄 1. The Startup Sequence (Boot Flow)

No login manager is involved:

1.  **Unit Initialization**: `systemd` triggers `steamos_diy.service` on TTY1 as part of the `graphical.target`.
2.  **Configuration Sourcing**: The launcher reads global variables from the SSoT file (`/etc/default/steamos_diy.conf`).
3.  **State Identification**: The engine queries `/var/lib/steamos_diy/next_session` to determine the target environment.
4.  **Session Execution**:
    *   **Gaming Mode**: builds the Gamescope command line and starts Gamescope with Steam inside it.
    *   **Desktop Mode**: starts KDE Plasma (`startplasma-wayland`).
    *   Either way the launcher then waits out the validation window: a session that exits within it is treated as a crash and the next one started is Desktop.
5.  **Session Transition**: `session_select.py` updates the state file and asks the active session to quit. The Launcher (`session_launch.py`) sees the session exit, prints the transition message on TTY1 and exits with code `75`; `systemd` then restarts the unit (`Restart=on-failure`).

---

## 🏗️ 2. Core Implementation

One systemd service takes the display manager's place.

### Systemd & TTY Control
*   **Targeting**: The unit is linked to `graphical.target.wants/`. The installer disables SDDM and plasmalogin.
*   **TTY1**: The installer masks `getty@tty1.service`, so no login prompt runs on TTY1; the unit attaches to it with `TTYPath=/dev/tty1`.
*   **PAM session**: `PAMName=login` with `User=` opens a logind session for the user on `seat0`/`tty1` without asking for a password (`loginctl list-sessions` shows it). That session is what gives Gamescope and Plasma access to the seat's devices and starts the user's systemd instance (PipeWire and the other user services).
*   **Readiness Notification**: `Type=notify` is set so systemd receives `READY=1` only after the session survives the validation window. This means dependent units and `systemctl start` calls block until the session is confirmed stable.

### Environment & Recovery
*   **Runtime Context**: The service sets `XDG_RUNTIME_DIR=/run/user/<UID>`, `XDG_SESSION_TYPE=wayland`, `SSOT_CONF=/etc/default/steamos_diy.conf`, and `XDG_DESKTOP_PORTAL_DIR=/usr/share/xdg-desktop-portal/portals` explicitly.
*   **Log Routing**: `StandardOutput=journal` and `StandardError=journal` send the process's stdout/stderr (gamescope's output, uncaught tracebacks) to the journal under the `python3` identifier. `PAMName=login` moves the process into its own login-session cgroup, and journald attributes messages by the sender's cgroup, so `journalctl -u steamos_diy.service` shows only systemd's own start/stop lines. Use `journalctl -t CORE -t STEAM -t SYSTEM` for the project's logs and `journalctl -t python3` for gamescope's output (see [Troubleshooting](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Troubleshooting)).
*   **Fault Tolerance**: A `Restart=on-failure` policy with a `1-second` delay recovers the session automatically from crashes and after session switches — this is frequent and expected (every switch exits `75` by design, see [SteamOS Session Launch](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Steamos-Session-Launch)).

> [!WARNING]
> **Restart limit — give-up condition**
>
> `StartLimitIntervalSec=120` / `StartLimitBurst=10` caps restarts at 10 within 120 seconds. This is deliberate: a Game Mode that dies at start already falls back to Desktop, so the runaway case is Desktop itself dying at start (e.g. a broken Wayland/Plasma install); the limit stops systemd from restarting it every second forever. It leaves room to spare for normal Steam↔Desktop switching.
>
> If the limit is ever hit, `steamos_diy.service` stops retrying — with `getty@tty1` masked, nothing else starts on TTY1. **Recovery**: switch to another TTY (`Ctrl+Alt+F2`) or SSH in, then run `sudo systemctl reset-failed steamos_diy.service && sudo systemctl start steamos_diy.service` after fixing the underlying issue (check `journalctl -t CORE -t STEAM -t SYSTEM` for the crash cause first — `-u steamos_diy.service` only shows the restart loop itself, not why each attempt failed).
*   **TTY Cleanup**: `TTYReset=yes` resets the terminal before and after each run; `TTYVTDisallocate=yes` clears the VT's screen and scrollback.
*   **Kill Policy**: `KillMode=mixed` sends `SIGTERM` to the main process only (not the whole cgroup), allowing `session_launch.py`'s signal handler to forward it to the session (gamescope/Steam or the desktop) and exit once that has ended. `TimeoutStopSec=10` sets the hard limit before systemd escalates to `SIGKILL` on everything left in the cgroup — the only escalation path for a session that ignores `SIGTERM` on a normal stop.

> [!IMPORTANT]
> **Plasma 6 & plasmalogin**
>
> Modern Plasma 6.x environments may use `plasmalogin.service`.
>
> The installer disables it (along with SDDM).
>
> Please refer to the **[Arch Wiki](https://wiki.archlinux.org/title/Plasma_Login_Manager)** for technical details.

---

## 🖥️ 3. Session Handover Mechanism

A session switch involves three components working in sequence:

1. `session_select.py` writes the new target (`steam` or `desktop`) to `/var/lib/steamos_diy/next_session` atomically, then sends a shutdown signal to the active session (`steam -shutdown` or `qdbus6 org.kde.Shutdown /Shutdown logout`). Only `plasma`, `desktop`, and `kde` resolve to `desktop` (`steamos-session-select plasma` works identically to `steamos-session-select desktop`) — any other argument, including an empty or unrecognized one, resolves to `steam`.
2. `session_launch.py` detects that its child process has exited, displays a transition message on TTY1, and exits with code `75` (`EX_TEMPFAIL`).
3. `steamos_diy.service` treats code `75` as a failure (`Restart=on-failure`, `RestartSec=1.0s`) and restarts the launcher, which reads the new target from the state file and spawns the next session. A deliberate stop (`systemctl stop`) exits with `0` and does **not** trigger a restart.

For the full lifecycle including crash recovery, see [SteamOS Session Launch](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Steamos-Session-Launch).

---

## 🏎️ 4. Optional: Removing Plymouth
Plymouth (the boot splash) isn't used by this setup. Removing it is optional; the project has not measured any boot-time difference.

### **Step 1: Initramfs Configuration**

#### **A. Systems using `mkinitcpio` (Standard Arch)**
1. Edit `/etc/mkinitcpio.conf` and remove `plymouth` from the `HOOKS` array.
2. Rebuild: `sudo mkinitcpio -P`

#### **B. Systems using `dracut` (EndeavourOS)**
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
Optional, a matter of taste: skips Plasma's splash when switching to Desktop.
1. Navigate to **System Settings** > **Colors & Themes** > **Splash Screen**.
2. Select **None** and click **Apply**.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
