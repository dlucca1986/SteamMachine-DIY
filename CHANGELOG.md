# Changelog

All notable changes to SteamMachine-DIY are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `install.sh`: C-Core post-build verification — gcc failure and `ctypes.CDLL()` loadability check both abort installation with a clear error message.
- `utils.py`: `verify_archive()` — shared gzip-tar integrity check, eliminates duplicated logic from `backup.py` and `restore.py`.
- `utils.py`: `run_shim()` — single entry point for SteamOS compatibility shims, eliminates boilerplate duplication across all five helpers.

### Changed
- `utils.py`: `get_ssot_var()` now exposes two typed overloads — callers passing a `str` default receive `str` back; callers omitting default receive `str | None`. Eliminates downstream type-narrowing workarounds.
- `control_center.py`: Maintenance tab now uses absolute executable paths (`/usr/bin/python3`, `/usr/bin/konsole`, `/usr/bin/xdg-open`) consistent with the rest of the codebase.
- `control_center.py`: `_safe_spawn` error path now logs via `jlog` instead of `sys.stderr.write`, respecting the configured `LOG_LEVEL` filter.
- `helpers/*`: all five SteamOS shims (`steamos-update`, `jupiter-biosupdate`, `jupiter-dock-updater`, `set-timezone`, `steamos-select-branch`) rewritten to use `run_shim()` from `utils.py`.
- All subprocess calls now use absolute executable paths throughout (`/usr/bin/systemctl`, `/usr/bin/journalctl`, `/usr/bin/chown`, `/usr/bin/pkexec`).

### Fixed
- `control_center.py`: `_update_detection` was indexing `dict[str, str]` with a `str | None` value — added explicit `is not None` guards to match the logical guarantee already present in the data flow.
- `backup.py` / `restore.py`: `get_real_user()` returns `(str, Path)`; explicit `str(home)` conversion added to prevent `Path`-vs-`str` type errors at call sites.

---

## [1.3.5] — 2026-05-10 — Revision & Stability

Component versions at this release:
`install.sh 1.3.4` · `uninstall.sh 1.3.5` · `utils.py 1.7.9` · `session_launch.py 1.5.5` · `session_select.py 1.7.2` · `sdy.py 1.3.4` · `backup.py 1.3.0` · `restore.py 1.3.0` · `control_center.py 1.3.0`

### Changed
- `uninstall.sh`: removed unreachable `exit 0` after `exec systemd-run` (exec replaces the process).
- `uninstall.sh`: removed aggressive `chvt 1` VT takeover — no longer needed after cgroup escape approach.
- `uninstall.sh`: moved `finalize_uninstallation()` call to after the reboot prompt, so cleanup completes before any reboot.
- All components: normalized `PHILOSOPHY` header to `KISS (Keep It Simple, Stupid)` across all files.

### Fixed
- `uninstall.sh`: script could be killed by systemd when run from inside the service cgroup. Now escapes to a safe scope via `systemd-run --scope` before proceeding.

---

## [1.3.4] — 2026-04-xx — Critical Bug Fixes

### Fixed
- `utils.py`: `load_ssot()` existence check added before attempting to read SSoT file.
- `restore.py`: `getmember()` exception handling for missing archive members.
- `uninstall.sh`: multilib section no longer left enabled in `pacman.conf` after uninstall.
- Multiple critical bugs resolved across Python layer (see commit `7fc2757`).

---

## [1.3.0] — 2026-03-xx — Initial Public Release

### Added
- `steamos_diy_core.c`: C-Core shared library (`libcore.so`) with atomic writes, structured journal logging, process monitoring, and `sd_notify` integration.
- `session_launch.py`: systemd-driven session lifecycle manager with crash recovery (VALIDATION_TIMEOUT) and automatic fallback to Desktop Mode.
- `session_select.py`: atomic session switcher with native `steam -shutdown` / `qdbus6` dispatch.
- `sdy.py`: zero-fork game wrapper with three-step profile discovery (AppID → effective name → stem) and `os.execvpe` hand-off.
- `backup.py`: surgical backup with symlink recovery script embedded in archive and atomic rename.
- `restore.py`: path-traversal-safe restore with realpath normalization, allow-list validation, and TOCTOU-safe script execution.
- `control_center.py`: PyQt6 GUI with YAML editor (syntax highlighting, line numbers), game profile manager, journal viewer, and maintenance tools.
- `utils.py`: shared library — single C-Core gateway, SSoT cache, YAML loading, atomic writes, process management.
- Helpers (`steamos-update`, `jupiter-biosupdate`, `set-timezone`, `steamos-select-branch`, `jupiter-dock-updater`): SteamOS compatibility shims.
- `install.sh`: hardware audit (GPU detection), dependency management, C-Core compilation, systemd integration.
- `uninstall.sh`: interactive removal with cgroup escape and atomic system restoration.
- SSoT configuration: `/etc/default/steamos_diy.conf` as single source of truth for all paths and tunable parameters.
- Per-game YAML profiles with hierarchical override (global `config.yaml` ← per-game profile).
