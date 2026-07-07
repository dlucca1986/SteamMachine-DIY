[![Version](https://img.shields.io/badge/Version-2.1.5-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The supervisor behind session transitions: lifecycle, watchdog, signals and exit codes.

---

## 🏗️ Technical Architecture

### 1. Configuration Management
All runtime values (binary paths, log level, timeouts) are read from `/etc/default/steamos_diy.conf` via `get_ssot_var()`, which caches results in-process. If `libcore.so` is missing at `utils.py` import time, the process exits with code 127. See [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine) for the full SSoT API.

### 2. Dynamic Gamescope Mapping (DGM)
Execution arguments are generated from a **YAML configuration**.

#### **Transformation Logic**
The `_build_gamescope_args()` function constructs the execution string:
* **Flag Injection**: Parses the `flags` list from the YAML and appends them to the `gamescope` command.
* **Environment Overrides**: First applies `GAME_MODE_ENV` — a fixed set of session capabilities advertised to Steam (see *Session Capabilities* below) — then injects the user's `env_vars`, which are applied afterwards and therefore keep the last word. Configuration guidance (including the MangoHud/`--mangoapp` caveat) lives in [Dynamic Gamescope Mapping](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Dynamic-Gamescope-Mapping).
* **Safe Execution**: Uses `subprocess.Popen` with argument arrays to prevent shell-injection vulnerabilities.

### 3. Atomic State Management
The session target is persisted to `/var/lib/steamos_diy/next_session` via `write_atomic()` (fdatasync + rename). See [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine) for the write protocol.

---

## 🔄 Session Lifecycle

### **Transition Logic**
* **Gaming Mode ➔ Desktop**: `session_select.py` writes `desktop` to the state file and calls `steam -shutdown`. The launcher detects the child exit and terminates; `systemd` restarts it into Plasma.
* **Desktop Mode ➔ Gaming**: `session_select.py` writes `steam` to the state file and calls `qdbus6 org.kde.Shutdown /Shutdown logout`. The launcher restarts into Gamescope+Steam.
* **Session Persistence**: The state file is written in three cases: an explicit switch request (via `session_select.py`), a successful validation (confirming the running target is stable), or a crash recovery (forcing `desktop`). On reboot the system returns to whatever was last written.

---

## 🎮 Steam Execution Arguments
Gamescope is launched with two hardcoded flags, followed by the user-defined YAML flags, and finally the Steam process after `--`:

```python
gs_args = [gs_bin, "-e", "-f"]          # hardcoded: embedded + fullscreen
apply_env_map(GAME_MODE_ENV)            # session capabilities (see below)
apply_env_map(cfg.get("env_vars"))      # user env_vars — applied last, win
# ... flags from config.yaml appended here ...
gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3", "-steamdeck"])
```

* **`-e`**: Runs Gamescope in embedded mode, integrating with the existing DRM/KMS session rather than creating a new display server.
* **`-f`**: Forces fullscreen output.
* **`-gamepadui`**: Launches Steam in Big Picture / Gamepad UI mode — the controller-friendly interface optimised for TV/couch use.
* **`-steamos3`**: Activates SteamOS-specific features, including system update channels and controller mapping.
* **`-steamdeck`**: Unlocks the full Quick Access side menu and its live controls (scaling, frame limit, etc.). Additive to `-gamepadui`, not a replacement.

---

## 🧩 Session Capabilities (`GAME_MODE_ENV`)
Before the user's `env_vars`, the launcher applies a fixed map of **compositor/Mesa capabilities** so Steam's Game Mode exposes the matching Quick Access controls on **any GPU**. The user never needs to set these:

| Capability env | Steam control unlocked |
| :--- | :--- |
| `STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT`, `STEAM_GAMESCOPE_NIS_SUPPORTED` | Scaling Filter (FSR / NIS) |
| `STEAM_GAMESCOPE_HAS_TEARING_SUPPORT`, `STEAM_GAMESCOPE_TEARING_SUPPORTED` | Disable Vertical Sync (tearing) |
| `STEAM_GAMESCOPE_DYNAMIC_FPSLIMITER` | Frame Limit |
| `vk_xwayland_wait_ready=false` | Lower input latency (session tweak, no Steam control) |
| `SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0` | Keep SDL games up on focus loss (session tweak) |
| `ENABLE_GAMESCOPE_WSI=1`, `VKD3D_SWAPCHAIN_LATENCY_FRAMES=3`, `WINEDLLOVERRIDES=dxgi=n` | Proton/vkd3d session defaults (session tweak, no Steam control) |

These are **panel-independent** — the control is always safe to expose; only its *benefit* depends on hardware. **Display-dependent** capabilities — VRR (`STEAM_GAMESCOPE_VRR_SUPPORTED`) and HDR (`STEAM_GAMESCOPE_HDR_SUPPORTED`) — are deliberately left out: declare them in your own `env_vars` **only when your monitor supports them**, otherwise Steam shows controls that do nothing. Since user `env_vars` are applied after `GAME_MODE_ENV`, they can override any of these defaults.

---

## ⚙️ Post-Start Hook
After Gamescope is spawned, the launcher checks `post_start_cmds` from `config.yaml`. If the list is non-empty, a **daemon thread** is started that sleeps `POST_START_DELAY` seconds (SSoT, default `2.0s`) and then fires each command via `spawn_native` (detached, `start_new_session=True`). The delay is shorter than `VALIDATION_TIMEOUT`, so all commands are executed before the session is declared stable.

This mechanism is designed for runtime calls that require the Gamescope socket to be open (e.g. `gamescopectl`). Commands are only dispatched for the `steam` session target — the Plasma desktop session does not trigger this hook.

* **Tags used by this module**: `STEAM` — `POST_START_CMD: <cmd>` logged at INFO after each command fires.

---

## 🛡️ Watchdog & Recovery
The supervisor uses an event-driven mechanism to monitor process health and prevent boot loops.

* **Process monitoring**: Uses `proc.wait()` instead of a polling loop. If the session exits before `VALIDATION_TIMEOUT` elapses, it is treated as a crash.
* **Validation Window**: Governed by `VALIDATION_TIMEOUT` in the SSoT configuration. Default is `5.0s`; lower values (e.g. `3.0s`) suit fast NVMe storage.
* **Emergency Recovery**: If a crash occurs within the validation window, the supervisor writes `desktop` to the state file atomically and terminates the process. Termination sends `SIGTERM` and waits up to `TERM_TIMEOUT` seconds (SSoT, default `5`); if the process doesn't exit, `SIGKILL` is sent.

## 🔌 Signal Handling & Exit Codes
The launcher registers handlers for `SIGTERM` and `SIGINT` at startup. The exit code controls whether `systemd` restarts the service:

| Event | Handler | Exit code | systemd effect |
| :--- | :--- | :--- | :--- |
| `systemctl stop` / `SIGTERM` / `SIGINT` | `_handle_term` — terminates child gracefully, then exits | `0` | No restart (`Restart=on-failure` does not trigger on 0) |
| Session ended naturally (switch or crash recovery) | `run()` — exits after `NOTIFY_DELAY` pause | `75` (`EX_TEMPFAIL`) | Restart triggered — launcher re-reads `next_session` and spawns the new target |

`NOTIFY_DELAY` (SSoT, default `0.4s`) is a brief sleep inserted between the TTY transition message and `sys.exit(75)`, giving the user time to read the message before the service restarts.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
