[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The session launcher: lifecycle, validation window, signals and exit codes.

---

## 🏗️ Technical Architecture

### 1. Configuration Management
All runtime values (binary paths, log level, timeouts) are read from `/etc/default/steamos_diy.conf` via `get_ssot_var()`, which caches results in-process. If `libcore.so` is missing at `utils.py` import time, the process exits with code 127. See [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine) for the full SSoT API.

### 2. Dynamic Gamescope Mapping (DGM)
Execution arguments are generated from a **YAML configuration**.

#### **Transformation Logic**
The `_build_gamescope_args()` function constructs the execution string:
* **Flag Injection**: Parses the `flags` list from the YAML and appends them to the `gamescope` command. Each entry is split with `shlex.split`; an unbalanced quote falls back to a plain whitespace split (logged as `BAD_FLAG_ENTRY` at `WARN`) instead of crashing the launcher over one malformed entry.
* **Environment Overrides**: First applies `GAME_MODE_ENV` — the few session variables gamescope doesn't set itself (see *Session Variables* below) — then injects the user's `env_vars`, which are applied afterwards and therefore keep the last word. Configuration guidance (including the MangoHud/`--mangoapp` caveat) lives in [Dynamic Gamescope Mapping](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Dynamic-Gamescope-Mapping).
* **No shell**: the command is started with `subprocess.Popen` and an argument list, so nothing in it is interpreted by a shell.

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
apply_env_map(GAME_MODE_ENV)            # session variables (see below)
apply_env_map(cfg.get("env_vars"))      # user env_vars — applied last, win
# ... flags from config.yaml appended here ...
gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3", "-steamdeck"])
```

* **`-e`** (`--steam`): "enable Steam integration" (gamescope's own description).
* **`-f`** (`--fullscreen`): fullscreen.
* **`-gamepadui`**: Launches Steam in the Gamepad UI (Big Picture).
* **`-steamos3`**, **`-steamdeck`**: Steam's flags for a SteamOS / Steam Deck session (Valve doesn't document them).

---

## 🧩 Session Variables (`GAME_MODE_ENV`)
Before the user's `env_vars`, the launcher sets only the variables gamescope doesn't set itself:

| Variable | Purpose |
| :--- | :--- |
| `SRT_LOG_TO_JOURNAL=1` | Read by Steam's `srt-logger` (journal logging). Steam's lines do appear under `-t steam`; not tested whether they depend on this variable |
| `VKD3D_SWAPCHAIN_LATENCY_FRAMES=3` | Per ChimeraOS's gamescope-session: "workaround older versions of vkd3d-proton setting this too low" |
| `WINEDLLOVERRIDES=dxgi=n` | Per ChimeraOS's gamescope-session: "to expose vram info from radv" (AMD) |

In Steam mode (`-e`) gamescope 3.17.0 exports the rest itself: the variables that make Steam show the scaling filter (FSR/NIS), tearing (when the display backend supports it), frame limit, VRR and HDR controls, `STEAM_MULTIPLE_XWAYLANDS=1` (only with `--xwayland-count` above 1), `ENABLE_GAMESCOPE_WSI=1`, `SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0` and `vk_xwayland_wait_ready=false` (source: `src/main.cpp`, `UpdateCompatEnvVars`; checked by running `gamescope -e` in an empty environment). gamescope doesn't overwrite a variable that is already set, so your own `env_vars` still win.

---

## 🛡️ Validation Window & Recovery
* **Process monitoring**: `proc.wait(timeout=VALIDATION_TIMEOUT)`. If the session exits before `VALIDATION_TIMEOUT` elapses, it is treated as a crash.
* **Validation Window**: Governed by `VALIDATION_TIMEOUT` in the SSoT configuration (default `5.0s`): how long a session must stay up after starting to count as stable.
* **Emergency Recovery**: If a crash occurs within the validation window, the launcher writes `desktop` to the state file atomically. The session process has already exited at that point, so nothing is signalled.

## 🔌 Signal Handling & Exit Codes
The launcher registers handlers for `SIGTERM` and `SIGINT` at startup. The exit code controls whether `systemd` restarts the service:

| Event | Handler | Exit code | systemd effect |
| :--- | :--- | :--- | :--- |
| `systemctl stop` / `SIGTERM` / `SIGINT` | `_handle_term` — forwards `SIGTERM` to the session and exits (it can't wait itself: the main thread it interrupts is blocked in `proc.wait()`). `_run_session` then gives the session 5 s and sends `SIGKILL` if it is still running (`STOP_TIMEOUT`) | `0` | No restart (`Restart=on-failure` does not trigger on 0) |
| Session ended naturally (switch or crash recovery) | `run()` — exits after `NOTIFY_DELAY` pause | `75` (`EX_TEMPFAIL`) | Restart triggered — launcher re-reads `next_session` and spawns the new target |

`NOTIFY_DELAY` (SSoT, default `0.4s`) is a sleep between the TTY transition message and `sys.exit(75)`, so the message stays on screen briefly before the service restarts.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
