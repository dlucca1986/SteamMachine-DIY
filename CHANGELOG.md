# Changelog

All notable changes to SteamMachine-DIY are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] — Control Center Health Tooling

### Added
- `health.py`: new Qt-free backend module (mirrors `journal.py` — pure functions, testable in isolation, ready for a future `sdy doctor` CLI) exposing config-validation and service-status helpers.
  - `run_preflight()` returns a list of `CheckResult`s covering: SSoT config presence; binary handlers (`bin_gs`/`bin_steam`/`bin_plasma`/`bin_dbus`) resolving to executables; the declared SSoT paths (`user_config`, `games_conf_dir`) actually existing; YAML syntax of the global config and every game profile (reporting the offending line); session-critical group membership (`tty`/`video`/`render`/`input`); C-Core loadability; and a writable session-state directory.
  - It also flags the two top-level config fields the launcher iterates directly (`flags`, `post_start_cmds`) when mistyped as a scalar instead of a list — runtime would otherwise walk a string character-by-character into junk argv. Absent or null fields are correctly treated as empty and skipped. Full schema/semantic validation is deliberately out of scope (the runtime already degrades unexpected keys and bad `LOG_LEVEL`/timing values gracefully).
  - `get_service_status()` / `parse_service_status()` snapshot `steamos_diy.service` via `systemctl show` (no root) into a `ServiceStatus`, degrading missing or non-numeric fields to safe placeholders.
- `control_center.py`: **🩺 Validate Configuration** button (Maintenance tab) runs the preflight off-thread and renders a colour-coded pass/fail report (`preflight_ready` signal) — surfacing a broken config *before* it causes a black-screen boot.
- `control_center.py`: service-health strip in the window status bar — shows `steamos_diy.service` state/sub-state/restart-count/last-exit, colour-coded (green `active`, red `failed`), refreshed every 4 s by a `QTimer` fetching status off-thread (`service_status_ready` signal).
- `backup.py`: automatic archive rotation — after every successful backup, archives beyond the `BACKUP_KEEP` count (new SSoT key, default `5`; `0` disables pruning) are deleted oldest-first, so `~/.config/steamos_diy/backups/` never grows unbounded. The timestamped naming makes lexicographic order chronological and in-flight `.tmp` files are never matched. Removals are logged as `BACKUP_PRUNED`.
- `utils.py`: `clear_ssot_cache()` drops the in-process `_SSOT_CACHE` so long-lived tools (the Control Center doctor) re-validate the *current* on-disk config after an edit instead of returning cached values. `run_preflight()` calls it first, so re-running the doctor after fixing the config no longer requires restarting the Control Center.

### Changed
- `control_center.py`: **Export Support Report** (formerly *Export Support Log*) now produces a real diagnostic bundle instead of dumping the on-screen view. The file contains kernel, `steamos_diy.service` status, the full preflight report and the raw last-12h logs (all tags + gamescope), re-fetched independently of the active Diagnostics filter and without the display-side dedup collapse — complete and greppable for issue reports. Default filename is timestamped; the report is built in a worker thread (`_build_support_report`). The journal fetch is shared with the Diagnostics view via the new `journal.fetch_tagged_entries`, so the two paths cannot drift.
- `control_center.py`: `beautify_yaml` now applies the reformat as a single undoable edit (cursor edit-block) instead of `setPlainText`, so `Ctrl+Z` reverts it in one step; the editor's scroll position is preserved (no jump to the top); and the status bar reports the outcome (`✨ YAML formatted` / `Already clean` / `Syntax error — see highlight`).
- `health.py`: review pass — split `_check_yaml_files` into `_check_user_config` + `_check_game_profiles` (one check, one function, matching the structure of every other preflight check) and extracted `_load_user_config` out of `_check_config_types` (loading vs. checking separated). Behaviour identical.
- `install.sh`: the Intel driver set now also installs `intel-media-driver` (iHD) alongside the legacy `libva-intel-driver`. libva probes `iHD` before `i965` on i915, so 64-bit processes (Steam Remote Play encode, browsers) automatically get the actively-maintained VAAPI driver, while 32-bit processes keep falling back to `lib32-libva-intel-driver` (no official `lib32-intel-media-driver` exists — everything stays in the official repos).

### Removed
- `install.sh`: dropped `libva-mesa-driver` / `lib32-libva-mesa-driver` from the AMD driver set — obsolete split-package names absorbed into `mesa` / `lib32-mesa` (already in the same list) since mesa 1:24.2.7; pacman was resolving them as virtual providers of packages being installed anyway.
- `install.sh`: dropped `procps-ng` (dependency of the `base` meta-package — present on every Arch system by definition, and unused by the project) and `mesa-utils` (`glxinfo`/`glxgears` referenced nowhere in code, configs or docs — the stack is Vulkan-centric). `vulkan-tools` stays (`vulkaninfo` is part of the documented troubleshooting workflow) and so does `pciutils` (`lspci` is used by install.sh itself).

### Fixed
- `control_center.py`: `beautify_yaml` no longer destroys a comments-only document. ruamel loads such a document as `None` and would round-trip it to a literal `null`, wiping the user's comments from the editor; it is now left untouched ("Nothing to format").
- `steamos_diy_core.c`: `c_notify` clamped the `snprintf` would-be length to `sizeof(buf)` instead of `sizeof(buf) - 1`, sending the trailing NUL byte to the TTY; a negative return (encoding error) would also have reached `write()` as a huge unsigned length. Both paths are now guarded — the build is clean under `-Wconversion`.
- `steamos_diy_core.c`: `c_sd_notify_ready` passed `sizeof(struct sockaddr_un)` as the address length, which breaks abstract-socket addressing (`@` prefix): abstract names are length-delimited, so the kernel treated the NUL padding as part of the name and `READY=1` went to a non-existent socket. The length is now computed as `offsetof(sun_path) + strlen(path)`, valid for both abstract and filesystem sockets.

### Documentation
- `Utilities Engine.md`: documented `clear_ssot_cache` and added `health.py` to the framework-dependency matrix.
- `SteamMachine DIY Control Center.md`: documented the Validate Configuration button, the service-health strip, the `health.py` backend, and the improved beautify behaviour.
- Full docs/README review pass against the current code: package lists in `README.md` and `Installer Workflow.md` realigned with `install.sh` (Intel VAAPI drivers added, dropped packages removed); duplicated content consolidated to its home page (MangoHud/`--mangoapp` caveat → Dynamic Gamescope Mapping, optional-packages list → Useful Links & Resources, redundant per-tag journalctl rows → tag table); the boilerplate "This page outlines…" opener replaced with a direct per-page summary; minor wording and formatting cleanups.

---

## [2.1.1] — 2026-06-08 — Post-2.1.0 Hardening & KISS/Doc Cleanup Pass

### Added
- `utils.py`: `get_ssot_num(key, default)` — typed accessor that wraps `get_ssot_var` for numeric timing parameters, returning a `float` and falling back to `default` (with a `WARN`) when the value is missing or malformed.
- `steamos_diy.service`: `StartLimitIntervalSec=120` / `StartLimitBurst=10`. `session_launch.py` exits 75 on every session switch (intentional restart) and a crashed Steam already falls back to Desktop via `_handle_recovery`, so legitimate restarts are frequent and self-limiting. This guard only catches the pathological case (both targets crashing instantly, e.g. a broken Plasma/Wayland) — systemd gives up instead of hammering TTY1 at ~1 Hz. Tuned generous enough never to trip on normal Steam↔Desktop toggling.

### Changed
- `sdy.py`: dropped redundant `str()` casts in `_build_command` — `wrapper` and `extra` are already `str` from both branches that build them, so `shlex.split(str(x))` became `shlex.split(x)`.

### Removed
- `install.sh`: dropped `rsync` and `qt6-tools` from `BASE_PKGS`. Neither is used anywhere in the project — backup/restore use `tarfile` (not rsync) and the Control Center is pure PyQt6 at runtime (qt6-tools ships dev-only tooling like Designer). Removing them trims install-time dependency bloat.

### Fixed
- `session_launch.py`: the four timing parameters (`VALIDATION_TIMEOUT`, `TERM_TIMEOUT`, `POST_START_DELAY`, `NOTIFY_DELAY`) were read via bare `int()`/`float()` on the SSoT value. Since `/etc/default/steamos_diy.conf` is hand-editable, a typo (`5s`, an empty value, a decimal comma) raised an unguarded `ValueError` — and for `VALIDATION_TIMEOUT` that aborts `run()` before the session launches, so systemd `Restart=on-failure` would retry, fail again, and loop until the start-limit trips (black TTY, no diagnostic). All four now read through `get_ssot_num`, degrading to their built-in default plus a `WARN` instead of crashing the boot. `TERM_TIMEOUT` in the conf template is now `5.0` for consistency with the float semantics (behaviour unchanged).
- `control_center.py`: the editable game-overrides combo was bound to `currentTextChanged`, which fires on every keystroke — re-scaffolding the editor and discarding edits while the user was still typing a profile name. Rebound to `activated` (selection/Enter only), so the profile loads or scaffolds on confirmation, not mid-type.
- `steamos_diy_core.c`: `c_notify` now clamps the `snprintf` return value before `write()`. `snprintf` returns the *would-be* length, so an oversized status string could make `write()` read past the 256-byte buffer; the length is capped at `sizeof(buf)`.
- `steamos_diy.service`: header `VERSION` corrected `2.0.0` → `2.1.0` — the unit file had been missed by the `.py`/`.sh`/`.conf` version bump.
- `steamos_diy_core.c`: the three fd-opening paths now set the close-on-exec flag — `c_notify` (`O_CLOEXEC` on `/dev/tty1`), `c_write_atomic` (`O_CLOEXEC` on the temp file), and `c_sd_notify_ready` (`SOCK_CLOEXEC` on the AF_UNIX socket). `ctypes` releases the GIL during each C call, so the `post_start_cmds` daemon thread (`session_launch.py`) can `fork`/`exec` a child while one of these fds is briefly open; without close-on-exec the spawned game/helper would inherit that descriptor. The flags close the leak at no added complexity.
- `utils.py`: `_JLOG_REENTRY` recursion guard moved from a shared `list[bool]` to `threading.local()`. The post-start daemon thread and the main thread both call `jlog`; with a single shared flag, a log emitted by one thread while the other held the guard would bypass the `LOG_LEVEL` threshold. Each thread now tracks its own re-entry state independently. (No crash was possible — Python's GIL makes the flag write atomic — but a suppressed-level line from a secondary thread could leak into the journal.)

### Documentation
- `Utilities Engine.md`: documented the new `get_ssot_num` accessor under the Configuration Management section and added it to the `session_launch.py` import matrix.
- `steamos_diy.conf`: noted under "Performance & Timing" that numeric values are plain numbers (no units/comma) and that a malformed value falls back to its default rather than aborting the boot.
- `restore.py`: comment in `_prepare_restore` explaining why `home_str` (unresolved, kept in lockstep with the paths `backup.py` wrote) and `home_real` (symlink-resolved, checked by the security allow-list) intentionally coexist — they are not redundant.
- `SteamMachine DIY Control Center.md`: game-overrides combo description updated — the profile loads (or scaffolds) on selection; typing a new name does not reload until confirmed.
- `control_center.py`: header `DESCRIPTION` corrected — it advertised a non-existent "Search functionality"; now describes the actual dashboard (diagnostics, maintenance, YAML editing). `_run_pkexec` docstring trimmed of the keyword-only rationale already stated in the adjacent pylint-disable comment.
- `sdy.py`: header `DESCRIPTION` reworded "global manifesto" → "global config".
- `Utilities Engine.md`: corrected the `control_center.py` dependency row — it listed `jlog`, but the module actually imports `spawn_native` from `utils`.
- `Installer Workflow.md`, `README.md`: dependency lists synced with `install.sh` (removed `rsync`/`qt6-tools`); documented `gcc` command updated to include `-march=native` (matches `install.sh` and the `Makefile`).
- `Game Wrapper (sdy).md`: the `_build_command` code snippet synced with the source after the redundant `str()` casts were removed.

---

## [2.1.0] — 2026-05-23 — KDE-Focused Hardening & Gamescope Integration

### Added
- `session_launch.py`: post-start hook mechanism — `_get_post_start_cmds()` reads a `post_start_cmds` YAML list from `config.yaml`; `_schedule_post_start_cmds()` fires each command via `spawn_native` in a daemon thread after `POST_START_DELAY` seconds. Enables runtime Gamescope socket commands (e.g. `gamescopectl`) that cannot be expressed as launch flags. Hook is skipped entirely when the list is empty or the target is not `steam`.
- `steamos_diy.conf`: `POST_START_DELAY=2.0` — configurable delay (seconds) before post-start commands are fired; joins the existing timing parameters (`VALIDATION_TIMEOUT`, `NOTIFY_DELAY`, `TERM_TIMEOUT`).
- `config.yaml`: `post_start_cmds:` key — empty by default; populated by the user.
- `config.example.yaml`: documented `--adaptive-sync` and `--mangoapp` flags under a new `VRR / MangoHud` group; added `post_start_cmds` section with `gamescopectl adaptive_sync_ignore_overlay 1` example and inline explanation of the VRR/overlay interaction.

### Fixed
- `helpers/*`: all five SteamOS shims silently fell back to `sys.exit(7/0)` (ImportError path) when invoked via the symlink chain (`/usr/bin/<name>` → `/usr/bin/steamos-polkit-helpers/<name>` → `.py`). The Linux kernel passes the original symlink path — not the resolved target — to the interpreter; `os.path.abspath(__file__)` returned the symlink path, so `sys.path.insert` added `/usr` or `/usr/bin` instead of `/usr/local/lib/steamos_diy`. `utils` was therefore never found and `run_shim` was never reached. Fixed by replacing `os.path.abspath` with `os.path.realpath`, which follows the full symlink chain and returns the canonical file path.
- `journal.py`: gamescope log filter no longer matches arbitrary lines containing "gamescope" as a substring. The Diagnostics tab was picking up Dolphin/kio `copy() QUrl(...)` operations and Plasma `PreviewJob` errors involving `gamescope.example.yaml` files — anything with the word "gamescope" anywhere on the line passed through. Now `journalctl` is invoked with `-t steam -t python3` (the only two identifiers that carry gamescope output: `steam` after the exec hop, `python3` for early CLI errors before exec), and lines must match the upstream gamescope log format (`[Info]`/`[Warn]`/`[Error]`/`[Gamescope WSI]` or `/usr/bin/gamescope:`) via the new `_GAMESCOPE_PAYLOAD` regex. Validated on a real session: 0 false positives, all genuine gamescope output preserved.

### Changed
- `control_center.py`: `_atomic_save()` no longer reimplements `tmp + fsync + rename` in Python; delegates to `write_atomic()` (C-Core, `fdatasync`). Single durability path for both session state writes and Control Center YAML saves.
- `utils.py`: `extract_game_metadata`, `_normalize_appid`, `get_journal_cmd` moved to `journal.py` — the only consumer is the journal pipeline. `journal.py` no longer imports from `utils.py`.
- `utils.py`: `write_atomic()` no longer strips whitespace from values — paranoid `.strip()` removed; all callers already pass clean strings.
- `utils.py`: `SERVICE_PATH` renamed to `_SERVICE_PATH` — the only internal user is `get_backup_mapping`, no external consumer.
- `utils.py`: dead `import re` removed after the regex-using functions were relocated to `journal.py`.
- `install.sh`: C-Core build flags aligned with `Makefile` — `-march=native` added to the `gcc` invocation. The installer always runs on the target machine, so native ISA optimisation is safe and consistent with `make` builds.
- `install.sh`: `disable_display_managers` scope limited to `sddm` and `plasmalogin` — the project targets KDE Plasma exclusively; GNOME and other DMs are out of scope.
- `session_launch.py`: user config YAML loaded once in `run()` and passed as `cfg: dict` to `_build_gamescope_args`, `_build_command_for`, `_get_post_start_cmds`, and `_run_session` — eliminates the duplicate `load_yaml_safe` call that was made separately by `_build_gamescope_args` and `_get_post_start_cmds` at every session start. Also drops the now-redundant `isinstance(cfg, dict)` guard (load_yaml_safe always returns dict).
- `control_center.py`: `_safe_spawn` removed — replaced by direct `spawn_native` calls from `utils.py`. `spawn_native` already provides the same error handling plus `start_new_session=True` (setsid) and stdout/stderr redirect, giving spawned tools (Konsole, xdg-open, session_select) proper process-group isolation from the Control Center.
- `restore.py`: `Path(home).resolve()` simplified to `home.resolve()` — `home` is already a `Path` object returned by `get_real_user()`, so the redundant `Path()` construction is removed.

### Removed
- `control_center.py`: `_safe_spawn` method — redundant wrapper around `subprocess.Popen` superseded by `spawn_native` from `utils.py`.
- `control_center.py`: `_SSOT_KEYS` tuple and `_load_ssot_to_env()` method. The preload had no consumer — no module reads the nine pre-loaded keys via `os.getenv`; subprocesses re-read the SSoT file via `get_ssot_var`. Drops the now-unused `get_ssot_var` import as well.
- `steamos_diy_core.c`: `#include <sys/stat.h>` — zero symbols used in the file, `-Wall -Wextra` still compiles clean.
- `control_center.py`: `OSError` removed from `beautify_yaml` except clause — `yaml_parser.load()` and `yaml_parser.dump()` are pure in-memory operations and cannot raise `OSError`; the handler was dead code.

### Documentation
- `Utilities Engine.md`: opening rewritten in one sentence (matching the other wiki pages); the C-Core philosophy now lives in a dedicated "🔌 C-Core Integration" section. "📖 Journal Utilities" section removed (functions relocated to `journal.py`). Framework Dependencies table updated accordingly.
- `SteamMachine DIY Control Center.md`: `_atomic_save()` and `extract_game_metadata()` descriptions updated to reflect the new module layout. Diagnostics section updated with the narrower journalctl invocation. Orphan paragraph on `_load_ssot_to_env()` removed.
- `Architecture.md`: `journal.py` function list extended with `get_journal_cmd` and `extract_game_metadata`.

---

## [2.0.0] — 2026-05-17 — KISS Audit & Robustness Pass

### Removed
- `utils.py`: `load_ssot()` — one-line wrapper around `os.path.isfile(SSOT_CONF_PATH)`; callers (`backup.py`, `restore.py`) now call it directly.
- `utils.py`: `_parse_yaml()` — private function called only by `load_yaml_safe`; merged into it, eliminating the split.
- `utils.py`: `_chown_recursive()` — private function called only by `fix_ownership`; inlined, error handling unified into a single `except`.
- `backup.py`: `_is_relevant_symlink()` — one-line predicate called only by `_resolve_symlink`; inlined.
- `restore.py`: `_apply_metadata()` — two-line function called only by `_extract_member`; inlined.
- `editors.py`: `_setup_rules()` — called only from `__init__`; inlined.
- `journal.py`: `_is_game_log_line()` — one-line predicate called only by `filter_game_journal_lines`; inlined.
- `session_launch.py`: `STATUS_MAP["crash"]` entry — used by a single fixed access in `_handle_recovery`; replaced by a string literal.
- `session_launch.py`: `_TERM_TIMEOUT` module constant — superseded by SSoT `TERM_TIMEOUT`.
- `install.sh`: `chmod 644 "$LIB_DIR/utils.py"` — dead code, immediately overwritten by `chmod +x "$LIB_DIR"/*.py`.

### Changed
- `utils.py`: `_JLOG_REENTRY` comment reduced to one line.
- `steamos_diy_core.c`: `c_write_atomic` — added `if (!path || !val) return;` NULL guard.
- `steamos_diy_core.c`: `c_notify` — `write(fd, cls, 11)` replaced by `write(fd, cls, strlen(cls))`.
- `steamos_diy.conf`: added `TERM_TIMEOUT=5` — last session-lifecycle timeout not previously SSoT-configurable.
- `session_launch.py`: `_terminate_gracefully` now reads `TERM_TIMEOUT` from SSoT instead of using a hardcoded constant.
- `session_launch.py`: `_monitor_process` parameter renamed `next_sess_path` → `next_path` for consistency with all other functions.
- `session_select.py`: constants renamed `BIN_STEAM_DEFAULT` → `DEFAULT_STEAM_BIN`, `BIN_DBUS_DEFAULT` → `DEFAULT_DBUS_BIN` to align with `session_launch.py` naming convention.
- `sdy.py`: `except (OSError, FileNotFoundError, PermissionError)` collapsed to `except OSError` — `FileNotFoundError` and `PermissionError` are subclasses of `OSError`.
- `sdy.py`: numbered step comments in `run()` removed; only the zero-fork note kept as inline.
- `restore.py`: `_allowed_prefixes` now receives `home_real` (already resolved) instead of `home_str`, eliminating the double `Path.resolve()` call.
- `editors.py`: `line_number_area_width` — `while` loop for digit counting replaced by `len(str(...))`.
- `control_center.py`: timestamp regex compiled as `_LOG_TIMESTAMP_RE` module-level constant instead of inline on every log line.
- `control_center.py`: `_safe_spawn` except clause narrowed from `(subprocess.SubprocessError, OSError)` to `OSError` — `SubprocessError` is never raised by `Popen()`.
- `install.sh`: `disable_display_managers` scope limited to `sddm` and `plasmalogin` — the project targets KDE Plasma exclusively; GNOME and other DMs are out of scope.
- `Makefile`: `DESTDIR` renamed to `INSTALL_DIR` — `DESTDIR` is a Make convention for staging prefixes, not direct install paths.
- `steamos_diy.service`: removed redundant inline comment on `ExecStart`.
- All modules and scripts: version set to `2.0.0`.

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
- `session_launch.py`: session switches went to a black screen on `Restart=on-failure`. When the user switched mode, the running child (Steam/Plasma) exited cleanly, `run()` returned, Python exited with code 0, and systemd's `Restart=on-failure` policy correctly treated that as "success — do not restart" — leaving TTY1 unmanaged. The fix flow now exits with `EX_TEMPFAIL` (75) after a natural child-process exit so systemd reboots the launcher, which then reads the freshly-persisted `next_session` value and spawns the new target. The SIGTERM/SIGINT handler still exits 0, so `systemctl stop` continues to work without a restart loop.
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
