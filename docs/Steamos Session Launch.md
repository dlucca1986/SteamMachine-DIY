[![Version](https://img.shields.io/badge/Version-1.5.5-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: PEP8](https://img.shields.io/badge/Code%20Style-PEP8-brightgreen.svg)](https://www.python.org/dev/peps/pep-0008/)
[![Language: Python](https://img.shields.io/badge/Language-Python-3776AB.svg?logo=python&logoColor=white)](#)

This page outlines the Python-based supervisor responsible for session transitions and environment control.

---

## 🏗️ Technical Architecture

### 1. Configuration Management
All runtime values (binary paths, log level, timeouts) are read from `/etc/default/steamos_diy.conf` via `get_ssot_var()`, which caches results in-process. If `libcore.so` is missing at `utils.py` import time, the process exits with code 127. See [Utilities Engine](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Utilities-Engine) for the full SSoT API.

### 2. Dynamic Gamescope Mapping (DGM)
Execution arguments are generated from a **YAML configuration**.

#### **Transformation Logic**
The `_build_gamescope_args()` function constructs the execution string:
* **Flag Injection**: Parses the `flags` list from the YAML and appends them to the `gamescope` command.
* **Environment Overrides**: Injects custom variables (e.g., `MANGOHUD=1`) into the session environment.
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
Steam is passed as a child process to Gamescope (after `--`) rather than launched directly:

```python
gs_args.extend(["--", steam_bin, "-gamepadui", "-steamos3"])
```

* **`-gamepadui`**: Enables the Deck-optimized interface.
* **`-steamos3`**: Activates SteamOS-specific features, including system update channels and controller mapping.

---

## 🛡️ Watchdog & Recovery
The supervisor uses an event-driven mechanism to monitor process health and prevent boot loops.

* **Process monitoring**: Uses `proc.wait()` instead of a polling loop. If the session exits before `VALIDATION_TIMEOUT` elapses, it is treated as a crash.
* **Validation Window**: Governed by `VALIDATION_TIMEOUT` in the SSoT configuration. Default is `5.0s`; lower values (e.g. `3.0s`) suit fast NVMe storage.
* **Emergency Recovery**: If a crash occurs within the validation window, the supervisor writes `desktop` to the state file atomically and terminates the process. Termination sends `SIGTERM` and waits up to 5 s; if the process doesn't exit, `SIGKILL` is sent.

---

## 📊 Diagnostics
The launcher utilizes the `jlog` system. Session logs can be monitored via journalctl:
`journalctl -u steamos_diy.service -f`

* **Core Tags**: `CORE`, `STEAM`, `SYSTEM`.
* **Configuration**: Logging verbosity is defined by `LOG_LEVEL` in `steamos_diy.conf`.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
