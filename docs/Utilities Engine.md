[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The shared utility module (`utils.py`) and its integration with the native `libcore.so`.

---

## 🔌 C-Core Integration

`utils.py` delegates a narrow set of operations to **`libcore.so`** — only those where C provides measurable value: atomic writes via `fdatasync`, `O_NOCTTY` TTY notification, `syslog()` journal logging, and `NOTIFY_SOCKET` readiness signalling. Everything else (config parsing, YAML loading, process spawning) stays in pure Python, since `subprocess` and stdlib `open()` already cover those cases.

The shared library is loaded via `ctypes` at import time. If `/usr/local/lib/steamos_diy/libcore.so` is missing, the import fails immediately with `sys.exit(127)`.

---

## 🏗️ Core Responsibilities

### 1. Data Integrity (`write_atomic`)
Files persisted via `write_atomic()` follow a four-step protocol executed entirely in the C-Core:

1. Write data to `<path>.tmp`.
2. Call `fdatasync()` to flush write buffers to physical storage.
3. Call `rename()` to atomically replace the target file.
4. Best-effort `fsync()` the containing directory, so the rename itself survives a power loss right after it.

The target file is never left in a partial state, even after a sudden power loss. Used for the session state file (`next_session`) and Control Center YAML saves. The new file always gets mode `0644` (tmp+rename creates a new inode), fine for both.

### 2. Configuration Management (`get_ssot_var`, `get_ssot_num`, `clear_ssot_cache`)
`get_ssot_var(key)` serves values from the `_SSOT_CACHE` dict, filled on the **first call** by parsing `/etc/default/steamos_diy.conf` once (`key=value` lines, surrounding quotes stripped, first occurrence wins). Later calls never re-read the file, even for a missing key. All values are also exported into `os.environ`, so child processes inherit them.

`get_ssot_num(key, default)` wraps `get_ssot_var` for the numeric parameters (the timings `VALIDATION_TIMEOUT`, `TERM_TIMEOUT`, `POST_START_DELAY`, `NOTIFY_DELAY`, plus `BACKUP_KEEP`). It returns a `float`, falling back to `default` and logging a `WARN` if the value is missing or malformed. Since the SSoT file is hand-editable, this keeps a typo (e.g. `5s`, a stray comma) from raising an unguarded `ValueError` that would otherwise abort the session boot loop.

`clear_ssot_cache()` empties `_SSOT_CACHE` so the next read hits disk. The session launcher reads config once at boot and benefits from the cache, but the long-lived Control Center must see the *current* file: its **Validate Configuration** check (`health.run_preflight`) and the reload after a restore both clear the cache first.

### 3. YAML (`load_yaml_safe`, `apply_env_map`)
`load_yaml_safe(path)` parses a YAML file and returns a dict. Returns `{}` on any error (missing file, parse error) and on a valid document whose root is not a mapping — callers do `cfg.get(...)` on the result, so a list/scalar root is degraded to empty and logged as `YAML_NOT_MAPPING` (WARN). Never raises.

`apply_env_map(data_dict)` injects all key/value pairs from a dict into `os.environ`. Non-dict input and `None` values are ignored; an entry the OS refuses as an environment variable (a name with `=`, an empty name, a NUL byte) is skipped with a `BAD_ENV_ENTRY` warning.

### 4. Session State (`read_session_target`)
`read_session_target(path, default="steam")` opens `path`, reads the first line and runs it through `_strip_quotes`. Returns the cleaned string, or `default` if the file is missing or unreadable.

### 5. Backup Format Contract (`USER_CONFIG_REL`, `BACKUP_MANIFEST_NAME`, `get_backup_mapping`)
Single source of truth for the on-disk format shared between `backup.py` and `restore.py`:

* `USER_CONFIG_REL` — relative path of the user-config directory (`".config/steamos_diy"`). Also reused by `control_center.py`.
* `BACKUP_MANIFEST_NAME` — name of the embedded links manifest (`"links.txt"`), a plain-data list of `link<TAB>target` rows.
* `BACKUP_SCRIPT_NAME` — name of the link-recreation script (`"restore_links.sh"`) embedded by pre-manifest releases. Kept only so restore can recognise the entry in old archives; new backups never write it.
* `get_backup_mapping(home)` — returns the `{archive_path: filesystem_path}` dict, read by backup (where to read from) and restore (where to write to). Restore matches archive entries against it with its own logic, so a new entry must be exercised on both sides (the tests round-trip every entry).

---

## 📊 Feedback & Logging

| Function | Output target | Notes |
| :--- | :--- | :--- |
| `jlog(tag, msg, level)` | `systemd-journal` via `syslog()` | Filtered against `LOG_LEVEL` from the SSoT before any C call. A re-entry guard (`_JLOG_REENTRY`) prevents recursion if the SSoT lookup itself triggers a log call. |
| `notify(status, clear_after)` | `/dev/tty1` | Written via `O_NOCTTY` to avoid acquiring the controlling terminal. |
| `sd_notify_ready()` | `NOTIFY_SOCKET` | Sends `READY=1` to systemd after session validation succeeds. Supports the `@` prefix for abstract Unix sockets. |

---

## 🛡️ Permissions & Process Management

| Function | Description |
| :--- | :--- |
| `check_root()` | Calls `sys.exit(1)` if the effective UID is not 0. |
| `get_real_user()` | Returns `(username, home_path)` for the real user behind `sudo` or `pkexec` (via `SUDO_UID` / `PKEXEC_UID`), falling back to the current effective UID. |
| `fix_ownership(path, user)` | `chown -R user:user path` for directories (via subprocess), `os.chown` for single files. No-op if `user` is empty or `"root"`. |
| `spawn_native(path, args)` | Detached spawn via `subprocess.Popen(start_new_session=True)`; stdout/stderr redirected to `/dev/null`. Returns the child PID, or `0` on failure. |
| `verify_archive(path, tag)` | Gzip-tar integrity check: walks every tar member, then reads the gzip stream to its end so the CRC32 in its trailer is actually validated (member iteration alone stops before it and misses content corruption). Logs failure under `tag` and returns `False` on any error. Shared by `backup.py` and `restore.py`. |
| `run_shim(tag, message, exit_code)` | Logs the shim intercept via `jlog(tag, message)` and exits with `exit_code`. Single entry point for all five SteamOS compatibility shims. |

---

## ⬆️ Update Check & Download (GitHub Releases)

Stdlib-only plumbing (`urllib` + `tarfile`) behind the Control Center's **Check for Updates** button — no Qt, testable standalone:

| Symbol | Description |
| :--- | :--- |
| `VERSION` | The running project version. Single runtime source, kept in sync with the file headers by the release bump. |
| `check_latest_release()` | Queries the GitHub Releases API (fixed `https` URL, 10s timeout) and returns a `ReleaseInfo(version, is_newer, notes, tarball_url, html_url, checksum_url)` — or `None` when the network or the reply is unusable (logged as `UPDATE_CHECK_FAIL`, never raised). `checksum_url` is the release's `SHA256SUMS` asset URL (`""` if the release has none). Versions compare as integer tuples, so `2.10.0 > 2.9.0`. |
| `download_release(info, dest_root)` | Requires `info.checksum_url`: fetches and validates the expected SHA-256 (`_fetch_expected_sha256()`), streams the tarball while hashing it (`_download_verified_tarball()`), and aborts — nothing extracted — if the checksum asset is missing, malformed, or doesn't match (`UPDATE_CHECKSUM_FAIL`/`UPDATE_DOWNLOAD_FAIL`). Only after the digest matches does it prune previous `v*` downloads and unpack under `dest_root/v<version>/`. Extraction uses the tarfile `data` filter (rejects absolute paths, traversal and special members) and only accepts `https://` URLs (`_require_https()`, shared with `_fetch_expected_sha256()`). Returns an `ExtractedRelease(dir, install_sh_sha256)` — the inner export directory holding `install.sh` plus that file's own SHA-256 — or `None` on failure. |
| `verify_file_sha256(path, expected)` | Re-hashes a file already on disk and compares it to `expected`. `updater.py::_on_download` calls this on `install.sh` immediately before handing it to `pkexec`, narrowing (not closing) the TOCTOU window between download-time verification and execution — pkexec's password prompt still follows the check, and the other extracted files aren't re-verified. |
| `_https_open(url, extra_headers=None)` | Shared `Request`/`urlopen(timeout=...)` plumbing behind every GitHub network call above — each caller keeps its own error handling since what's recoverable (and what to log) differs per call. |
| `UPDATES_DIR_NAME` | `"updates"` — the download folder name under `~/.config/steamos_diy/`, shared with `backup.py` which excludes it from archives. |

---

## 📂 Framework Dependencies

| Component | `utils` imports used |
| :--- | :--- |
| `session_launch.py` | `DEFAULT_GS_BIN`, `DEFAULT_PLASMA_BIN`, `DEFAULT_STEAM_BIN`, `NEXT_SESSION_PATH`, `apply_env_map`, `get_ssot_num`, `get_ssot_var`, `jlog`, `load_yaml_safe`, `notify`, `persist_next_session`, `read_session_target`, `sd_notify_ready`, `shlex_split_or_fallback`, `spawn_native` |
| `session_select.py` | `DEFAULT_DBUS_BIN`, `DEFAULT_STEAM_BIN`, `NEXT_SESSION_PATH`, `get_ssot_var`, `jlog`, `notify`, `persist_next_session`, `spawn_native` |
| `sdy.py` | `apply_env_map`, `default_games_conf_dir`, `get_ssot_var`, `jlog`, `load_yaml_safe`, `shlex_split_or_fallback` |
| `backup.py` | `BACKUP_MANIFEST_NAME`, `CORE_LIB_DIR`, `UPDATES_DIR_NAME`, `USER_CONFIG_REL`, `check_root`, `fix_ownership`, `get_backup_mapping`, `get_real_user`, `get_ssot_num`, `jlog`, `require_ssot_conf`, `verify_archive` |
| `restore.py` | `BACKUP_MANIFEST_NAME`, `BACKUP_SCRIPT_NAME`, `SYSTEMCTL_BIN`, `SYSTEMD_CALL_TIMEOUT`, `check_root`, `fix_ownership`, `get_backup_mapping`, `get_real_user`, `jlog`, `require_ssot_conf`, `verify_archive` |
| `control_center.py` | `CONFIG_FILE_NAME`, `CORE_LIB_DIR`, `GAMES_CONF_SUBDIR`, `JOURNALCTL_BIN`, `KONSOLE_BIN`, `PYTHON3_BIN`, `SSOT_CONF_PATH`, `SYSTEMD_CALL_TIMEOUT`, `USER_CONFIG_REL`, `VERSION`, `clear_ssot_cache`, `get_ssot_var`, `safe_emit`, `spawn_native`, `write_atomic` |
| `updater.py` | `KONSOLE_BIN`, `UPDATES_DIR_NAME`, `USER_CONFIG_REL`, `VERSION`, `check_latest_release`, `download_release`, `safe_emit`, `spawn_native`, `verify_file_sha256` |
| `health.py` | `CORE_LIB_PATH`, `DEFAULT_GS_BIN`, `DEFAULT_STEAM_BIN`, `DEFAULT_PLASMA_BIN`, `DEFAULT_DBUS_BIN`, `NEXT_SESSION_PATH`, `SSOT_CONF_PATH`, `SYSTEMCTL_BIN`, `clear_ssot_cache`, `get_ssot_var`, `shlex_split_or_fallback` |
| `journal.py` | `JOURNALCTL_BIN`, `SYSTEMD_CALL_TIMEOUT`, `jlog` |
| Compatibility shims | `run_shim` (which internally calls `jlog`) |

The `DEFAULT_*_BIN` fallbacks for the SSoT `bin_*` keys, `CORE_LIB_PATH`, and `GAMES_CONF_SUBDIR` (with `default_games_conf_dir()`, the `games_conf_dir` fallback shared by `sdy.py` and `control_center.py`) are defined only here; every module imports them. `SYSTEMCTL_BIN`/`JOURNALCTL_BIN` are not SSoT settings, just one shared literal for the modules that call those tools.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
