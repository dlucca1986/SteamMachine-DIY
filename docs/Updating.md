[![Version](https://img.shields.io/badge/Version-2.1.6-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

How to move an existing installation to a new release. One procedure — `install.sh --update` — with two entry points: the Control Center (recommended) or a plain terminal.

---

## 🖥️ 1. Updating from the Control Center (recommended)

1. Open the **Maintenance** tab and click **⬆️ Check for Updates**. The Control Center queries the GitHub Releases API and tells you whether a newer version exists (your installed version is shown in the window title).
2. If a new release is available, review the release notes and click **Download & Install**. The release tarball is downloaded and unpacked into `~/.config/steamos_diy/updates/` (old downloads are pruned automatically, and this folder is excluded from backups).
3. A **Konsole window** opens and runs the installer for you. Authenticate in the polkit popup — no commands to type. You watch the live installer output (package sync, C-Core build, deployment).
4. When the update completes, the system **reboots automatically after a 10-second countdown** (press `CTRL+C` in the terminal to abort the reboot).

> ℹ️ Prefer reading first? **Open Release Page** in the same dialog takes you to the release on GitHub instead.

## ⌨️ 2. Updating from the terminal

Download and unpack the latest release (or `git pull` your clone), then run the installer in update mode from the project root:

```bash
sudo ./install.sh --update
```

Same behavior as the Control Center path: non-interactive, ends with the 10-second reboot countdown.

## 🔍 3. What `--update` does differently

| Area | Fresh install | `--update` |
|---|---|---|
| User YAML configs (`~/.config/steamos_diy/`) | Deployed (asks before overwriting) | **Preserved** — only new template files are added |
| SSoT (`/etc/default/steamos_diy.conf`) | Deployed from template | **Preserved** — if the shipped template changed, the new one is staged as `steamos_diy.conf.new` (pacman `.pacnew` style) for manual review |
| Core library (`/usr/local/lib/steamos_diy/`) | Deployed | **Wiped and redeployed** — files removed or renamed by the new release cannot linger |
| C-Core (`libcore.so`) | Built from source | Rebuilt from source |
| Packages | `pacman -Syu --needed` | Same — the system is brought fully up to date |
| Reboot | Asks | **Automatic** after a 10s countdown (`CTRL+C` aborts) |

After the reboot, check `steamos_diy.conf.new` if the installer warned about it, and merge any new SSoT keys you care about. Missing keys are never fatal: every SSoT read falls back to a sane default, and the Control Center preflight reports anything worth fixing.

## 🧹 4. The classic way still works

A clean reinstall remains fully supported and is functionally equivalent:

```bash
sudo ./uninstall.sh   # answer "n" to keep your user data
sudo ./install.sh
```

> ⚠️ `uninstall.sh` always removes the SSoT (`/etc/default/steamos_diy.conf`), even when you keep the user data. If you customized it, run **Create Full System Backup** from the Control Center first — the archive includes the SSoT — or note your changes down.
