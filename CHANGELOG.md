# Changelog

All notable changes to SteamMachine-DIY are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `editors.py`: new module — `LineNumberArea`, `YAMLEditor`, `YAMLSyntaxHighlighter` extracted from `control_center.py` (SRP: rendering responsibility).
- `journal.py`: new module — all journalctl/gamescope parsing and game detection extracted from `control_center.py` (SRP: system/data layer, no Qt dependency, fully testable in isolation).
- `install.sh`: C-Core post-build verification — gcc failure and `ctypes.CDLL()` loadability check both abort installation with a clear error message.

### Removed
- `steamos_diy_core.c`: `c_get_conf_val`, `c_read_file_simple`, `c_spawn_detached`, `c_monitor_process` — four functions duplicating Python stdlib without real performance gain (all one-shot, never on a hot path). C-Core surface reduced from 8 to 4 functions; the four retained (`c_jlog`, `c_notify`, `c_write_atomic`, `c_sd_notify_ready`) are the ones that actually justify the ctypes bridge: `syslog()` libc binding, `O_NOCTTY` tty write, `fdatasync()` durability, and `NOTIFY_SOCKET` abstract-socket protocol.
- `steamos_diy_core.c`: orphaned helper `trim_inplace` and `#include <ctype.h>` / `<errno.h>` removed after the four functions above were dropped.
- `utils.py`: constants `_SSOT_BUF_SIZE` and `_SESSION_BUF_SIZE` removed — no longer needed once the ctypes buffer round-trip was eliminated.

### Changed
- `install.sh`: filesystem layout paths (`LIB_DIR`, `HELPERS_DIR`, `POLKIT_DIR`, `BIN_DIR`, `SSOT_CONF`, `SERVICE_FILE`, `STATE_DIR`, `APP_DIR`, `ALPM_HOOKS_DIR`, `USER_CONFIG_REL`) hoisted to a single top-level `readonly` block. Previously, `/usr/local/lib/steamos_diy` and friends were repeated inline in 6+ places; `LIB_DIR` was set inside `deploy_files` as an implicit global. The new block is labelled as the shared contract with `utils.py`.
- `install.sh`: two-hop alias creation (`/usr/bin/<name>` → `$POLKIT_DIR/<name>`) collapsed into a `for` loop. Two desktop-entry copies collapsed likewise.
- `uninstall.sh`: same `readonly` top-level block as `install.sh` (must mirror it — every uninstall path corresponds to an install path). Both shim-alias and CLI-tool removals collapsed into `for` loops over the same name lists install.sh writes.
- `Makefile` + `install.sh`: build flags aligned. Both now use `-O2 -fPIC -Wall -Wextra -shared`. Previously `Makefile` had `-Wextra -Wno-unused-parameter` while `install.sh` had only `-Wall` — silent divergence between dev (`make`) and prod (`./install.sh`) builds. `-Wno-unused-parameter` removed since the post-pass-1 C-Core compiles clean without it. `docs/Installer Workflow.md` updated to match.
- `uninstall.sh`: DM detection cascade rewritten — four sequential `systemctl list-unit-files | grep -q X` calls (one per `elif` branch) replaced by a single cached `dm_units` query plus a `for | break` over the priority list. Extending the priority list is now a one-line edit.
- `utils.py`: new exports `USER_CONFIG_REL`, `BACKUP_SCRIPT_NAME`, and `get_backup_mapping(home)` — single source of truth for the backup-archive format contract. Adding/removing entries now happens in one place instead of being mirrored across `backup.py._backup_sources` and `restore.py._build_mapping`.
- `backup.py`: removed local constants `_USER_CONFIG_REL` and `_RESTORE_SCRIPT_NAME` (centralised in `utils.py`); removed `_backup_sources()` — `_add_payload` iterates `get_backup_mapping()` directly. `_USER_BACKUPS_REL` derived from `USER_CONFIG_REL`.
- `restore.py`: removed local constants `_USER_CONFIG_REL` and `_RESTORE_SCRIPT_ARCNAME`; removed `_build_mapping()` — `_prepare_restore` calls `get_backup_mapping()` directly.
- `restore.py`: `_extract_payload` now returns `TarInfo | None` instead of `bool`. `_run_restore_script` takes the member directly, eliminating the second `tar.getmember(BACKUP_SCRIPT_NAME)` lookup and its `try/except KeyError` guard.
- `control_center.py`: hardcoded `~/.config/steamos_diy` replaced by `Path.home() / USER_CONFIG_REL` — third duplicate of the user-config path eliminated.
- `control_center.py`: `cleanup_logs_privileged` and `_run_privileged_script` merged into a single `_run_pkexec(cmd, ok_title, ok_msg, err_title, err_msg)`. Same daemon-thread + signal-emit pattern was duplicated across two methods; one of them only differed by passing `python3 <script>` vs `journalctl` as the pkexec payload. All three privileged operations (vacuum, backup, restore) now share one code path.
- `control_center.py`: `_atomic_save` now reuses `_highlight_yaml_error` for the YAML parse-error case instead of re-implementing the `getattr(err, "problem_mark", None)` extraction inline.
- `session_launch.py`: `_run_session` no longer takes a `set_proc_ref` callback; the run-level `proc_holder` list is passed in directly. Removes the `lambda p: proc_holder.__setitem__(0, p)` indirection — same shared-cell semantics in fewer hops.
- `sdy.py`: removed single-use wrapper `_resolve_games_dir()`; replaced by `get_ssot_var("games_conf_dir", _FALLBACK_GAMES_DIR)` which already handles the default-fallback case natively.
- `utils.py`: `get_ssot_var` rewritten in pure Python (line-by-line `key=value` parse with quote-stripping via the new `_strip_quotes` helper). Same API and same in-process caching, but no ctypes round-trip — eliminates one buffer allocation and one UTF-8 decode per cache miss.
- `utils.py`: `read_session_target` rewritten as `open().readline()` + `_strip_quotes`. Removes the parallel C path for a one-line file read.
- `utils.py`: `spawn_native` now uses `subprocess.Popen(start_new_session=True)` instead of `c_spawn_detached`. `subprocess` already performs `fork` → `setsid` → `execv` with `/dev/null` redirection — the C reimplementation was pure duplication.
- `helpers/*`: `sys.path.insert` path derived dynamically via `os.path.dirname(os.path.abspath(__file__))` instead of hardcoded `/usr/local/lib/steamos_diy`. Resilient to installation path changes.
- `utils.py`: YAML backend unified on `ruamel.yaml` (`typ="safe"`) — PyYAML (`python-yaml`) dependency removed. Single YAML library across the entire project.
- `sdy.py`: `_resolve_effective_name` — single `Path` object instead of two redundant constructions from the same string.
- `install.sh`: `python-yaml` removed from `BASE_PKGS` — no longer a dependency.
- `utils.py`: `verify_archive()` — shared gzip-tar integrity check, eliminates duplicated logic from `backup.py` and `restore.py`.
- `utils.py`: `run_shim()` — single entry point for SteamOS compatibility shims, eliminates boilerplate duplication across all five helpers.

### Changed
- All Python modules: docstrings refactored — verbose Args/Returns blocks removed where the signature is self-explanatory, filler phrases replaced with concise imperative descriptions.
- `utils.py`: `get_ssot_var()` now exposes two typed overloads — callers passing a `str` default receive `str` back; callers omitting default receive `str | None`. Eliminates downstream type-narrowing workarounds.
- `utils.py`: Removed `spawn_process()` and `monitor_pid()` — confirmed dead code with no callers anywhere in the codebase. Removed the corresponding orphaned ctypes binding for `c_monitor_process`.
- `utils.py`: `load_yaml_safe` split into `_parse_yaml` (try/except body) + `load_yaml_safe` (guard layer). Signature extended to `str | Path | None` — honest, since the body already handled `None` via the `not path` guard.
- `sdy.py`: Removed `_load_profiles()` single-use wrapper — its `if x else {}` guards were redundant since `load_yaml_safe` already handles `None`. Calls inlined directly in `run()`.
- `session_launch.py`: `_post_session_message` simplified — `original_target` parameter removed; condition `target != original_target or target == "desktop"` reduced to `target == "desktop"` (the first clause is always subsumed by the second in the crash-recovery flow).
- `restore.py`: `run_restore` split into `_prepare_restore` (pre-flight validation: root check, SSoT, file existence, archive integrity) and `_execute_restore` (archive extraction, link script, systemd reload).
- `restore.py`: `_extract_payload` return type changed from `str | None` to `bool` — only its truthiness was ever used by the caller.
- `restore.py`: Removed duplicate `_RESTORE_SCRIPT_NAME` constant — identical value already held by `_RESTORE_SCRIPT_ARCNAME`.
- `control_center.py`: SRP refactoring — rendering and parsing layers moved to `editors.py` and `journal.py`; file reduced from ~1230 to ~400 lines. UI wiring, signal handling, and YAML editor operations remain.
- `control_center.py`: `on_tab_changed` — magic index `0` replaced with `self.tabs.indexOf(self.diag_tab)` (resilient to tab reordering).
- `control_center.py`: `load_logs` — redundant `re.sub` ASCII-strip on combo values removed (combo items are pure ASCII).
- `control_center.py`: `beautify_yaml` refactored — error-highlight logic extracted into `_highlight_yaml_error`; the `if hl:` guard removed (highlighter is always set after `_setup_ui()` and `beautify_yaml` is only reachable via button clicks after full init).
- `control_center.py`: Maintenance tab now uses absolute executable paths (`/usr/bin/python3`, `/usr/bin/konsole`, `/usr/bin/xdg-open`) consistent with the rest of the codebase.
- `control_center.py`: `_safe_spawn` error path now logs via `jlog` instead of `sys.stderr.write`, respecting the configured `LOG_LEVEL` filter.
- `journal.py`: `parse_game_logs` — game detection loop collapsed from four methods (`_parse_game_logs`, `_update_detection`, `_apply_name_hit`, `_apply_id_hit`) into a single readable loop. Orphan constants `_GAME_DIR_PATTERN` and `_GAME_ID_PATTERN` removed (parsing delegated to `extract_game_metadata()` in `utils.py`).
- `helpers/*`: all five SteamOS shims (`steamos-update`, `jupiter-biosupdate`, `jupiter-dock-updater`, `set-timezone`, `steamos-select-branch`) rewritten to use `run_shim()` from `utils.py`.
- All subprocess calls now use absolute executable paths throughout (`/usr/bin/systemctl`, `/usr/bin/journalctl`, `/usr/bin/chown`, `/usr/bin/pkexec`).
- `backup.py`: Corrected misleading comment on `_EXCLUDE_COMPONENTS` — old wording incorrectly implied "backups" was a safe name; corrected to clarify component-level exclusion behaviour.

### Fixed
- `install.sh`: latent fresh-install crash — `cp -f "$CONFIG_SRC"/*.yaml ...` failed under `set -e` when the user-config template dir existed but was empty (default bash glob keeps `*.yaml` literal and `cp` errors out). Added a `compgen -G` guard mirroring the existing one on the destination side and restructured the `if/elif` so all three branches (no templates / merge / fresh) are handled explicitly.
- `restore.py`: path traversal vulnerability in `_resolve_target` — `realpath` lexical collapsing of `file/..` allowed a crafted archive member (e.g. `system/steamos_diy.conf/../../shadow`) to resolve to `/etc/shadow`, which legitimately matched the `/etc/` allow-list prefix. Fix: reject any member whose path contains `..` components before resolution.
- `steamos_diy_core.c`: `c_write_atomic` — `rename()` return value was ignored; failure (e.g. `EXDEV`) silently left the target unchanged and the `.tmp` file on disk. Fix: check return, log via `syslog(LOG_ERR, ...)`, unlink orphan on failure.
- `session_launch.py`: `_terminate_gracefully` — `proc.terminate()` called unconditionally; if the process had already exited (returncode set), `os.kill()` targeted a potentially recycled PID. Fix: guard with `proc.returncode is None`.
- `sdy.py`: `_build_command` — `GAME_WRAPPER or os.getenv(...)` treated an explicit empty string (`GAME_WRAPPER: ""`) as absent, silently falling back to the environment variable and ignoring the per-game override. Fix: use `None` as sentinel; fall back only when the key is absent from the profile.
- `control_center.py`: `cleanup_logs_privileged` — two sequential `pkexec journalctl` calls (rotate then vacuum) risked a polkit auth timeout between them, leaving the journal rotated but not vacuumed. Fix: single invocation with `--rotate --vacuum-time=1s`.
- `steamos_diy.service`: `Restart=always` prevented `systemctl stop` from working — the service restarted immediately, making maintenance and debug impossible without `systemctl disable`. Fix: `Restart=on-failure`; crash recovery behaviour is unchanged since `session_launch.py` exits 0 on clean SIGTERM.
- `steamos_diy.service`: missing `After=dbus.service systemd-logind.service` — the service could start before D-Bus was ready, causing silent failures in Steam's D-Bus integration.
- `restore.py`: Silent `except OSError: pass` in `_write_member` replaced with an explicit `WARN`-level log entry — unlink failures are now surfaced instead of swallowed silently.
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
