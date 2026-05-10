# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

SteamMachine-DIY transforms an Arch Linux machine (KDE Plasma 6 / Wayland) into a dedicated gaming console. It replaces the Display Manager with a single `systemd` service on TTY1 that launches either Gamescope+Steam (Game Mode) or Plasma (Desktop Mode), and provides a SteamOS compatibility shim layer so that Steam Big Picture's hardcoded SteamOS paths resolve to DIY logic.

The default branch for PRs is `stable`. Active work happens on `testing`.

## Repo layout mirrors install targets

The directory tree under the repo root **is the deployment layout** — files live at the same path they will install to. `install.sh` essentially copies trees in place and patches templates:

| Repo path | Install target |
| :--- | :--- |
| `etc/default/steamos_diy.conf` | `/etc/default/steamos_diy.conf` (SSoT, with `{{HOME}}` patched) |
| `etc/systemd/system/steamos_diy.service` | `/etc/systemd/system/` (with `{{USER}}` / `{{UID}}` patched) |
| `etc/skel/.config/steamos_diy/*.yaml` | `~/.config/steamos_diy/` (per real user, via `$SUDO_USER`) |
| `usr/local/lib/steamos_diy/*.py` | `/usr/local/lib/steamos_diy/` |
| `usr/local/lib/steamos_diy/helpers/*.py` | `/usr/local/lib/steamos_diy/helpers/` (SteamOS polkit shims) |
| `usr/share/libalpm/hooks/gamescope-privs.hook` | `/usr/share/libalpm/hooks/` (re-applies `setcap` after gamescope upgrades) |
| `steamos_diy_core.c` | compiled to `/usr/local/lib/steamos_diy/libcore.so` |
| `var/lib/steamos_diy/next_session` | initial state file (`steam` or `desktop`) |

Symlinks in `/usr/bin/`, `/usr/local/bin/`, `/usr/bin/steamos-polkit-helpers/` are created by `setup_shim_links` in `install.sh` — they don't exist in the repo. When adding a new shim/CLI tool, add the link there *and* update `backup.py`'s `_SYMLINK_SEARCH_PATHS` / `_SYMLINK_TARGET_MARKERS` so backups capture it.

## Build / install / develop

```bash
# Build only the C-Core (out-of-tree dev build):
make                    # → ./libcore.so
make clean

# Full deploy (requires root, modifies system):
sudo ./install.sh       # audits GPU, enables [multilib], installs deps,
                        # compiles libcore.so via gcc, deploys files,
                        # masks getty@tty1, enables steamos_diy.service
sudo ./uninstall.sh

# Service operations after install:
journalctl -u steamos_diy.service -f
systemctl restart steamos_diy.service
```

There is no test suite, no linter config, and no CI in-tree. The README badges PEP8 / Python — match the existing style (4-space indent, type hints, module-level constants prefixed `_`, structured docstrings) when editing Python.

## Architecture

### SSoT (`/etc/default/steamos_diy.conf`)

The single source of truth for system identity, binary paths, log level, and timing. All Python modules read it via `utils.get_ssot_var()`, which delegates to the C-Core for parsing and **caches values in `_SSOT_CACHE`** for the lifetime of the process. Side effect: each lookup also writes to `os.environ`, so child processes see the same view. Don't bypass `get_ssot_var` with raw file reads — you'll miss the cache and the env propagation.

The repo file uses `{{HOME}}` as a placeholder; the installer `sed`s in the real path. The systemd unit uses `{{USER}}` / `{{UID}}` similarly.

### C-Core (`libcore.so`) is mandatory

`utils.py` loads `/usr/local/lib/steamos_diy/libcore.so` via `ctypes` **at import time**. If the .so is missing, `utils.py` calls `sys.exit(127)` — every module that imports `utils` will fail. Functions exposed: `c_jlog`, `c_notify`, `c_write_atomic`, `c_get_conf_val`, `c_read_file_simple`, `c_spawn_detached`, `c_monitor_process`, `c_sd_notify_ready`. Adding a new C function means: declare in `steamos_diy_core.c` with `__attribute__((visibility("default")))`, register `argtypes`/`restype` in the `try` block at the top of `utils.py`, then expose a Python wrapper.

The C-Core handles the hot path (TTY writes, atomic file writes with `fdatasync`, fork/exec without Python overhead, `/proc` polling) precisely so the Python layer stays simple.

### Session lifecycle (`session_launch.py`)

The `steamos_diy.service` ExecStart runs `session_launch.py` on TTY1. Flow:

1. Read target from `/var/lib/steamos_diy/next_session` (`"steam"` or `"desktop"`, defaults to `"steam"`).
2. Build argv: for `steam`, run `_build_gamescope_args()` which prepends `gamescope -e -f`, applies `flags` and `env_vars` from `~/.config/steamos_diy/config.yaml` (the **DGM** — Dynamic Gamescope Mapping), then appends `-- /usr/bin/steam -gamepadui -steamos3`. For `desktop`, run `startplasma-wayland`.
3. Spawn via `subprocess.Popen` and watch it for `VALIDATION_TIMEOUT` seconds (default 5.0). If it exits inside the window → **crash recovery**: persist `desktop` to `next_session`, terminate gracefully (SIGTERM → SIGKILL after 5s), let systemd `Restart=always` cycle us into Plasma. If it survives → write the validated target back atomically and call `sd_notify_ready()`.
4. Signal handlers for SIGTERM/SIGINT terminate the live child via a closure cell, then `sys.exit(0)`.

`session_select.py` is the *switcher*: argv `desktop|kde|plasma` → write `desktop` to next_session and call `steam -shutdown`; anything else → write `steam` and call `qdbus6 org.kde.Shutdown /Shutdown logout`. The state is persisted **before** the dispatch, so a failed dispatch still takes effect on the next session.

### Game wrapper (`sdy.py`)

Invoked from Steam Launch Options as `sdy %command%`. Resolves the running game's `$SteamAppId` (or executable parent dir name, with generic stems like `start`/`run`/`launcher` mapped to the parent dir) against `~/.config/steamos_diy/games.d/*.yaml`, falling back to `/etc/steamos_diy/games.d`. Per-game YAMLs override the global `config.yaml`'s `env_vars` and inject `GAME_WRAPPER` (e.g. `mangohud gamemoderun`) plus `GAME_EXTRA_ARGS` around the original argv.

### SteamOS shims (`helpers/`)

Steam Big Picture calls hardcoded paths like `/usr/bin/jupiter-biosupdate`, `/usr/bin/steamos-update`, `/usr/bin/steamos-polkit-helpers/steamos-set-timezone`. The installer symlinks these to `helpers/*.py` so the UI doesn't error. The helpers are intentionally minimal — they exist to satisfy the UI contract, not to actually update firmware.

### Logging

Every module logs via `utils.jlog(tag, msg, level)` → `c_jlog` → `syslog` → `systemd-journal`. Tags in use: `CORE`, `STEAM`, `SYSTEM`, `DEBUG`. Filter at runtime via `LOG_LEVEL` in the SSoT (`DEBUG`/`INFO`/`WARN`/`ERROR`). `jlog` itself reads `LOG_LEVEL` through `get_ssot_var`, with a re-entry guard (`_JLOG_REENTRY`) for the case where the SSoT lookup fails and would recurse. View with `journalctl -u steamos_diy.service -f` or filtered: `journalctl -t CORE -t STEAM`.

### Control Center (`control_center.py`)

PyQt6 dashboard. Uses `ruamel.yaml` (not PyYAML) when editing user configs because it preserves comments and key order. Reads journal output via `utils.get_journal_cmd(tag)` which builds the canonical `journalctl --since "12 hours ago" -n 300 --no-hostname --no-pager -o export -t <tag>` command — reuse it instead of constructing journal commands ad-hoc.

### Backup / restore

`backup.py` produces a tarball capturing the SSoT, the systemd unit, `/usr/local/lib/steamos_diy/`, the next_session state, and the user's `~/.config/steamos_diy/`. It also enumerates symlinks in `_SYMLINK_SEARCH_PATHS` whose targets contain `_SYMLINK_TARGET_MARKERS`, so the shim graph can be reconstructed on restore. `restore.py` extracts to a private root-only temp dir (mode 0700, **not /tmp**, to close the chmod/exec TOCTOU window) and writes only to allow-listed prefixes.

## Conventions

- Python files start with the project banner docstring including `PATH:` (the install path, not the repo path) — preserve it.
- Module constants are uppercase with leading underscore for module-private (`_SSOT_BUF_SIZE`), no underscore for public defaults (`DEFAULT_GS_BIN`).
- Never call `subprocess.Popen` for fire-and-forget work when `utils.spawn_native` will do — it goes straight to `c_spawn_detached` (fork/exec/setsid in C, no Python GIL overhead).
- Atomic writes for any state file: `utils.write_atomic(path, val)`. Don't `open().write()` the next_session file — partial writes during power loss are exactly what this avoids.
- The framework is **user-agnostic**: never hardcode a username or UID. Use `utils.get_real_user()` (handles `SUDO_UID`/`PKEXEC_UID`) and `get_ssot_var("user_config")`.
