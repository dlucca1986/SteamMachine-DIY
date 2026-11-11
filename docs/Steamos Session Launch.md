[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
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
* **Flag Injection**: Parses the `flags` list from the YAML and appends them to the `gamescope` command. Each entry is split with `shlex.split`; an unbalanced quote falls back to a plain whitespace split (logged as `BAD_FLAG_ENTRY` at `WARN`) instead of crashing the launcher over one malformed entry.
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
gs_args = [gs_bin, "-e", "-f"]          # hardcoded: Steam integration + fullscreen
apply_env_map(GAME_MODE_ENV)            # session capabilities (see below)
apply_env_map(cfg.get("env_vars"))      # user env_vars — applied last, win
# ... flags from config.yaml appended here ...
gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3", "-steamdeck"])
```

* **`-e`** (`--steam`): Enables gamescope's Steam integration (overlay and Steam-driven features).
* **`-f`**: Forces fullscreen output.
* **`-gamepadui`**: Launches Steam in Big Picture / Gamepad UI mode — the controller-friendly interface optimised for TV/couch use.
* **`-steamos3`**: Tells Steam it runs on SteamOS 3, enabling the SteamOS-only parts of Game Mode.
* **`-steamdeck`**: Unlocks the full Quick Access side menu and its live controls (scaling, frame limit, etc.). Additive to `-gamepadui`, not a replacement.

---

## 🧩 Session Capabilities (`GAME_MODE_ENV`)
Before the user's `env_vars`, the launcher applies a fixed map of **session variables**: most make Steam's Game Mode expose the matching Quick Access controls on **any GPU**, the rest are session tweaks. The user never needs to set these:

| Capability env | Steam control unlocked |
| :--- | :--- |
| `STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT`, `STEAM_GAMESCOPE_NIS_SUPPORTED` | Scaling Filter (FSR / NIS) |
| `STEAM_GAMESCOPE_HAS_TEARING_SUPPORT`, `STEAM_GAMESCOPE_TEARING_SUPPORTED` | Disable Vertical Sync (tearing) |
| `STEAM_GAMESCOPE_DYNAMIC_FPSLIMITER` | Frame Limit |
| `vk_xwayland_wait_ready=false` | Lower input latency (session tweak, no Steam control) |
| `SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0` | Keep SDL games up on focus loss (session tweak) |
| `ENABLE_GAMESCOPE_WSI=1`, `VKD3D_SWAPCHAIN_LATENCY_FRAMES=3`, `WINEDLLOVERRIDES=dxgi=n` | Proton/vkd3d session defaults (session tweak, no Steam control) |
| `STEAM_MULTIPLE_XWAYLANDS=1` | Per-game Xwayland isolation (session tweak, no Steam control) |
| `SRT_LOG_TO_JOURNAL=1` | Routes Steam's own `steam-runtime-tools` logger to the journal (session tweak, no Steam control) |
| `SRT_URLOPEN_PREFER_STEAM=1` | Links clicked in Game Mode open in Steam's own overlay browser instead of `steam-runtime-tools`' `xdg-open` reaching for a desktop browser (session tweak, no Steam control) |
| `QT_QPA_PLATFORM_THEME=kde` | Correct icons/readable text for Qt apps inside gamescope (session tweak, no Steam control) |
| `XCURSOR_SCALE=256` | Cursor scale inside the embedded session (session tweak, no Steam control) |

These are **panel-independent** — the control is always safe to expose; only its *benefit* depends on hardware. **Display-dependent** capabilities — VRR (`STEAM_GAMESCOPE_VRR_SUPPORTED`) and HDR (`STEAM_GAMESCOPE_HDR_SUPPORTED`) — are deliberately left out: declare them in your own `env_vars` **only when your monitor supports them**, otherwise Steam shows controls that do nothing. Since user `env_vars` are applied after `GAME_MODE_ENV`, they can override any of these defaults.

---

## ⚙️ Post-Start Hook
After Gamescope is spawned, the launcher checks `post_start_cmds` from `config.yaml`. If the list is non-empty, a **background thread** sleeps `POST_START_DELAY` seconds (SSoT, default `2.0s`) and then runs each command via `spawn_native` (detached, `start_new_session=True`) — unless the session was already detected as crashed by then, in which case the commands are skipped (see Watchdog & Recovery below). This check, not the relation between `POST_START_DELAY` and `VALIDATION_TIMEOUT` (independent settings), is what keeps a failed session from running them.

This mechanism is designed for runtime calls that require the Gamescope socket to be open (e.g. `gamescopectl`). Commands are only dispatched for the `steam` session target — the Plasma desktop session does not trigger this hook.

* **Tags used by this module**: `STEAM` — `POST_START_CMD: <cmd>` logged at INFO after each command fires; a malformed entry (unbalanced quote) falls back to a plain whitespace split and still runs, logged as `BAD_POST_START_CMD` at `WARN`; skipped entirely after a detected crash, logged as `POST_START_CMDS_SKIPPED` at `DEBUG`.

---

## 🛡️ Watchdog & Recovery
The supervisor uses an event-driven mechanism to monitor process health and prevent boot loops.

* **Process monitoring**: Uses `proc.wait()` instead of a polling loop. If the session exits before `VALIDATION_TIMEOUT` elapses, it is treated as a crash.
* **Validation Window**: Governed by `VALIDATION_TIMEOUT` in the SSoT configuration (default `5.0s`): how long a session must stay up after starting to count as stable.
* **Emergency Recovery**: If a crash occurs within the validation window, the supervisor writes `desktop` to the state file atomically and terminates the process. Termination sends `SIGTERM` and waits up to `TERM_TIMEOUT` seconds (SSoT, default `5`); if the process doesn't exit, `SIGKILL` is sent.

## 🔌 Signal Handling & Exit Codes
The launcher registers handlers for `SIGTERM` and `SIGINT` at startup. The exit code controls whether `systemd` restarts the service:

| Event | Handler | Exit code | systemd effect |
| :--- | :--- | :--- | :--- |
| `systemctl stop` / `SIGTERM` / `SIGINT` | `_handle_term` (built by `_make_term_handler`) — forwards `SIGTERM` to the session and exits; the child is reaped on the way out. It deliberately does **not** wait/escalate itself: it runs on the main thread, which is blocked in `proc.wait()`, so a wait from inside the handler could never reap the child. Escalation for a session ignoring `SIGTERM` is left to the unit's `TimeoutStopSec` | `0` | No restart (`Restart=on-failure` does not trigger on 0) |
| Session ended naturally (switch or crash recovery) | `run()` — exits after `NOTIFY_DELAY` pause | `75` (`EX_TEMPFAIL`) | Restart triggered — launcher re-reads `next_session` and spawns the new target |

`NOTIFY_DELAY` (SSoT, default `0.4s`) is a brief sleep inserted between the TTY transition message and `sys.exit(75)`, giving the user time to read the message before the service restarts.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
