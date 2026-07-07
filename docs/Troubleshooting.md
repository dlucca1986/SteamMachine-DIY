[![Version](https://img.shields.io/badge/Version-2.1.5-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


Log tags, diagnostic commands, and handy shell aliases.

---

## 🔍 1. System Journal Tags

The framework uses a unified tagging system. Use `journalctl` to filter logs and identify issues quickly.

| Tag | Origin | Diagnostic Value |
| :--- | :--- | :--- |
| `CORE` | `session_launch`, `session_select`, `sdy` | Crash recovery, session switch requests, binary not found errors. |
| `STEAM` | `session_launch`, `sdy` | Gamescope launch args, game launch and execution failures. |
| `SYSTEM` | `backup`, `restore`, `helpers/*` | Backup/restore operations and SteamOS shim intercepts. |

---

## 🛡️ 2. Advanced Debugging Tools

| Command | Purpose |
| :--- | :--- |
| `journalctl -u steamos_diy.service -f` | Live logs from the session launcher (session_launch.py). |
| `journalctl -t CORE -t STEAM -t SYSTEM` | Full project log view — single tags can be filtered individually (see the table above). |
| `sudo fuser -v /dev/dri/card*` | Identify which process is currently locking the GPU. |
| `cat /sys/class/drm/*/modes` | List all resolutions natively detected by the Kernel (DRM). |
| `vulkaninfo --summary` | Verify that the Vulkan stack (Mesa/NVK) is operational. |
| `python3 -m py_compile script.py` | Check for syntax errors in the core logic after a manual edit. |
| `pkexec journalctl --rotate --vacuum-time=1s` | Rotate and purge system logs in a single invocation (mirrors the Control Center cleanup action). |

---

## 🩹 3. Known Issues & Fixes

### Black or corrupted Store / Library pages in Game Mode
On older or low-power GPUs, Steam's embedded Chromium (CEF) can fail at GPU-accelerated compositing, leaving the **Store** and **Library** pages black, flickering, or visually corrupted while the rest of Game Mode renders fine.

**Fix:** force CEF to software compositing with the Steam-client flag `-cef-disable-gpu-compositing` (or, for full software rendering, `-cef-disable-gpu`). These are **Steam client** flags, *not* gamescope flags — they go on the Steam invocation in `session_launch.py` (the `-gamepadui -steamos3 -steamdeck` line), **not** in `config.yaml`'s `flags`. Try the minimal `-cef-disable-gpu-compositing` first; fall back to `-cef-disable-gpu` only if the corruption persists.

---

## 💡 4. Diagnostic Aliases (Terminal Power-User)
Add these to your `~/.bashrc` to control the architecture. These commands interact directly with the **Journal** and the **Next Session logic**.

```
# =============================================================================
# SteamMachine-DIY - Diagnostic Aliases
# =============================================================================

# --- 📝 JOURNAL MONITORING ---
# Service lifecycle logs (session start/stop/restart — use -t CORE -t STEAM -t SYSTEM for application logs)
alias sdy-logs='journalctl -u steamos_diy.service -f -n 100'

# Display only critical errors recorded by the service
alias sdy-errors='journalctl -u steamos_diy.service --priority=3'

# --- 🚀 SESSION MANAGEMENT ---
# Switch session (Desktop/Steam)
alias sdy-mode-desktop='steamos-session-select desktop'
alias sdy-mode-game='steamos-session-select steam'

# --- 🛠️ EMERGENCY & RESET ---
# Check session status
alias sdy-status='pgrep -a gamescope || pgrep -a steam || echo "No gaming session active."'

# Terminate session
alias sdy-kill='pkill -9 gamescope && pkill -9 steam'

# GPU Reset
alias sdy-gpu-fix='sudo fuser -k /dev/dri/card*'

# Restart systemd service
alias sdy-restart='sudo systemctl restart steamos_diy.service'
```

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
