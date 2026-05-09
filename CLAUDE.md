# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SteamMachine-DIY transforms an Arch Linux machine into a dedicated gaming console. It replaces the display manager with a systemd service that boots directly into Gamescope (a nested Wayland compositor) + Steam on TTY1, while preserving the ability to switch to KDE Plasma 6 desktop mode.

**Target**: Arch Linux + KDE Plasma 6 (Wayland), supporting AMD, Intel, and NVIDIA GPUs.

## Install / Uninstall

```bash
sudo ./install.sh     # deploys all files, installs packages, configures systemd
sudo ./uninstall.sh   # reverses all changes, restores display manager
```

The installer compiles `libcore.so` from `steamos_diy_core.c` during installation (`gcc` is installed as a dependency). To build manually:

```bash
make            # produce libcore.so in the repo root
make install    # copy to /usr/local/lib/steamos_diy/
make clean
```

A reboot is required after installation.

## Runtime Commands (post-install)

```bash
sdy %command%              # game wrapper — use as Steam launch option
sdy-control-center         # PyQt6 GUI dashboard
sdy-backup / sdy-restore   # backup/restore system state
```

Session switching is done via `session_select.py`:
```bash
python3 /usr/local/lib/steamos_diy/session_select.py steam    # switch to Game Mode
python3 /usr/local/lib/steamos_diy/session_select.py plasma   # switch to Desktop Mode
```

## Architecture

### Single Source of Truth (SSoT)

All runtime paths, timeouts, and log levels are read from `/etc/default/steamos_diy.conf`. This file is the canonical config; never hardcode paths. The `utils.py` module provides `get_conf_val(key)` with in-process caching.

### C-Core Library (`libcore.so`)

Source: `steamos_diy_core.c`. Compiled to `libcore.so` at install time via `Makefile`. Python binds it via `ctypes` in `utils.py`. Functions:

| Function | C signature | Notes |
|----------|-------------|-------|
| `c_jlog` | `void(tag, msg, priority)` | syslog with dynamic tag |
| `c_notify` | `void(status, clear)` | writes to `/dev/tty1` with ANSI escapes |
| `c_write_atomic` | `void(path, val)` | `open`+`fdatasync`+`rename` |
| `c_get_conf_val` | `int(path, key, dest, len)` | key=value SSoT parser |
| `c_read_file_simple` | `int(path, dest, len)` | reads first line |
| `c_spawn_detached` | `int(path, argv[])` | fork/exec, returns child PID or 0 |
| `c_monitor_process` | `int(pid, timeout_sec)` | polls `/proc/<pid>` every 200ms |
| `c_sd_notify_ready` | `void()` | sends `READY=1` over `NOTIFY_SOCKET` (handles abstract `@` sockets) |

All C-Core calls go through wrappers in `utils.py`. Do not call `ctypes` directly elsewhere.

### Session Manager (`session_launch.py`)

Runs as `steamos_diy.service` on TTY1 with the real user's environment. Reads session target from `/var/lib/steamos_diy/next_session`, builds a Gamescope command from SSoT + user YAML config, spawns the process, validates stability over `VALIDATION_TIMEOUT` seconds, then signals systemd readiness.

### Game Wrapper (`sdy.py`)

Intended as `sdy %command%` in Steam launch options. Matches the running game by `STEAM_APPID` or name to a per-game YAML profile in `~/.config/steamos_diy/games.d/`. Applies env vars, game wrappers (MangoHud, GameMode), and extra args before exec-ing the real game command.

### Session Switcher (`session_select.py`)

Writes the target session name to the `next_session` file, then tells systemd to restart `steamos_diy.service`. Also sends a D-Bus notification to the Steam client.

### SteamOS Compatibility Shims

Stub scripts in `/usr/bin/steamos-polkit-helpers/` intercept Steam Deck UI polkit calls (BIOS update, dock update, timezone, branch select) so the unmodified Steam client doesn't error out. These are intentionally no-ops. **Source lives in `usr/local/lib/steamos_diy/helpers/*.py`** — `install.sh` deploys them to `/usr/local/lib/steamos_diy/helpers/` and symlinks each into `/usr/bin/steamos-polkit-helpers/`. Edit the sources, not the symlink targets.

### Control Center (`control_center.py`)

PyQt6 GUI with tabs for system info, game history, log viewer, and YAML config editor. Parses `journalctl` output to extract game metadata (AppID, name). Filter tags: `CORE`, `STEAM`, `SYSTEM`, `DEBUG`.

## Configuration

| File | Purpose |
|------|---------|
| `/etc/default/steamos_diy.conf` | SSoT: all paths, timeouts, log level |
| `~/.config/steamos_diy/config.yaml` | User global env vars + Gamescope flags |
| `~/.config/steamos_diy/games.d/*.yaml` | Per-game overrides (env, wrapper, args) |
| `/etc/systemd/system/steamos_diy.service` | Systemd unit (runs as user on TTY1) |

YAML game profiles use `STEAM_APPID` or `SDY_ID` as the identifier. Global config `flags` are appended verbatim to the Gamescope CLI.

## Key Design Constraints

- **No DM**: `getty@tty1` is masked; the systemd service owns TTY1. Never re-enable without uninstalling.
- **Atomic writes**: Always use `c_write_atomic` (or its Python wrapper) for state files — never plain `open().write()` for files read by other components.
- **SSoT reads are cached**: `get_conf_val` caches after first read per process. Changes to `steamos_diy.conf` require a service restart to take effect.
- **Root for install, user for runtime**: The service drops to the real user's UID (resolved via `SUDO_UID` / `PKEXEC_UID`). The Python modules in `/usr/local/lib/steamos_diy/` run as user.
- **Gamescope capabilities**: `cap_sys_admin,cap_sys_nice,cap_ipc_lock` are set on the binary via `setcap`. Replacing the gamescope binary loses these and requires re-running `install.sh`.

## Coding Gotchas

- **`load_ssot()` returns `bool`** — always check the return value before proceeding. Ignoring it causes silent failures where backup/restore runs with wrong or default paths. Pattern: `if not load_ssot(): sys.exit(1)`.
- **`spawn_native(path, args)` — `args` includes `argv[0]`** — the full argv array is passed directly to `execv`, so `args[0]` must be the program name (e.g. `["/usr/bin/steam", "-shutdown"]`). Do not strip `argv[0]`.
- **`tar.getmember()` raises `KeyError`**, it never returns `None`. Use `try/except KeyError`, not `if member is None`.
- **`c_monitor_process` uses `/proc/<pid>` polling** — not `waitpid`. Do not mix it with Python's `subprocess.wait()` on the same PID; they are compatible precisely because neither reaps the process.
- **`uninstall.sh` removes `[multilib]` from `pacman.conf`** interactively — it only removes the block if the exact `[multilib]` + `Include` lines are present. If the user had multilib before installing, they will be asked anyway; they can safely answer `n`.
