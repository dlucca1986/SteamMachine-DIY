[![Version](https://img.shields.io/badge/Version-2.1.4-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

The shared utility module (`utils.py`) and its integration with the native `libcore.so`.

---

## 🔌 C-Core Integration

`utils.py` delegates a narrow set of operations to **`libcore.so`** — only those where C provides measurable value: atomic writes via `fdatasync`, `O_NOCTTY` TTY notification, `syslog()` journal logging, and `NOTIFY_SOCKET` readiness signalling. Everything else (config parsing, YAML loading, process spawning) stays in pure Python, since `subprocess` and stdlib `open()` already cover those cases.

The shared library is loaded via `ctypes` at import time. If `/usr/local/lib/steamos_diy/libcore.so` is missing, the import fails immediately with `sys.exit(127)`.

---

## 🏗️ Core Responsibilities

### 1. Data Integrity (`write_atomic`)
Files persisted via `write_atomic()` follow a three-step protocol executed entirely in the C-Core:

1. Write data to `<path>.tmp`.
2. Call `fdatasync()` to flush write buffers to physical storage.
3. Call `rename()` to atomically replace the target file.

The target file is never left in a partial state, even after a sudden power loss. Used for the session state file (`next_session`) and Control Center YAML saves.

### 2. Configuration Management (`get_ssot_var`, `get_ssot_num`, `clear_ssot_cache`)
`get_ssot_var(key)` serves values from the module-level `_SSOT_CACHE` dict, which the **first call** fills by parsing the whole of `/etc/default/steamos_diy.conf` in a single disk read (pure-Python `key=value` parser with quote-stripping via `_strip_quotes`; first occurrence wins on duplicate keys). Every later call — cache hit *or* miss — is a dict lookup with no disk I/O, so a key absent from the file never triggers a re-read. All resolved values are exported into `os.environ` at load time so child processes inherit them.

`get_ssot_num(key, default)` wraps `get_ssot_var` for the numeric parameters (the timings `VALIDATION_TIMEOUT`, `TERM_TIMEOUT`, `POST_START_DELAY`, `NOTIFY_DELAY`, plus `BACKUP_KEEP`). It returns a `float`, falling back to `default` and logging a `WARN` if the value is missing or malformed. Since the SSoT file is hand-editable, this keeps a typo (e.g. `5s`, a stray comma) from raising an unguarded `ValueError` that would otherwise abort the session boot loop.

`clear_ssot_cache()` empties `_SSOT_CACHE` so the next read hits disk. The session launcher reads config once at boot and benefits from the cache, but a long-lived tool — the Control Center doctor (`health.run_preflight`) — must re-validate the *current* on-disk config after the user edits it, instead of seeing stale cached values.

### 3. YAML (`load_yaml_safe`, `apply_env_map`)
`load_yaml_safe(path)` parses a YAML file and returns a dict. Returns `{}` on any error (missing file, parse error) and on a valid document whose root is not a mapping — callers do `cfg.get(...)` on the result, so a list/scalar root is degraded to empty and logged as `YAML_NOT_MAPPING` (WARN). Never raises.

`apply_env_map(data_dict)` injects all key/value pairs from a dict into `os.environ`. Non-dict input and `None` values are silently ignored.

### 4. Session State (`read_session_target`)
`read_session_target(path, default="steam")` opens `path`, reads the first line and runs it through `_strip_quotes`. Returns the cleaned string, or `default` if the file is missing or unreadable.

### 5. Backup Format Contract (`USER_CONFIG_REL`, `BACKUP_MANIFEST_NAME`, `get_backup_mapping`)
Single source of truth for the on-disk format shared between `backup.py` and `restore.py`:

* `USER_CONFIG_REL` — relative path of the user-config directory (`".config/steamos_diy"`). Also reused by `control_center.py`.
* `BACKUP_MANIFEST_NAME` — name of the embedded links manifest (`"links.txt"`), a plain-data list of `link<TAB>target` rows.
* `BACKUP_SCRIPT_NAME` — name of the link-recreation script (`"restore_links.sh"`) embedded by pre-manifest releases. Kept only so restore can recognise the entry in old archives; new backups never write it.
* `get_backup_mapping(home)` — returns the `{archive_path: filesystem_path}` dict. Adding a new entry here propagates simultaneously to backup (where to read from) and restore (where to write to); they can never disagree about the archive layout.

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
| `verify_archive(path, tag)` | Gzip-tar integrity check via `tarfile.open` + member iteration. Logs failure under `tag` and returns `False` on any error. Shared by `backup.py` and `restore.py`. |
| `run_shim(tag, message, exit_code)` | Logs the shim intercept via `jlog(tag, message)` and exits with `exit_code`. Single entry point for all five SteamOS compatibility shims. |

---

## 📂 Framework Dependencies

| Component | `utils` imports used |
| :--- | :--- |
| `session_launch.py` | `NEXT_SESSION_PATH`, `write_atomic`, `read_session_target`, `load_yaml_safe`, `apply_env_map`, `notify`, `jlog`, `sd_notify_ready`, `spawn_native`, `get_ssot_var`, `get_ssot_num` |
| `session_select.py` | `NEXT_SESSION_PATH`, `write_atomic`, `spawn_native`, `notify`, `jlog`, `get_ssot_var` |
| `sdy.py` | `load_yaml_safe`, `apply_env_map`, `jlog`, `get_ssot_var` |
| `backup.py` | `BACKUP_MANIFEST_NAME`, `CORE_LIB_DIR`, `SSOT_CONF_PATH`, `USER_CONFIG_REL`, `check_root`, `fix_ownership`, `get_backup_mapping`, `get_real_user`, `get_ssot_num`, `jlog`, `verify_archive` |
| `restore.py` | `BACKUP_MANIFEST_NAME`, `BACKUP_SCRIPT_NAME`, `SSOT_CONF_PATH`, `check_root`, `fix_ownership`, `get_backup_mapping`, `get_real_user`, `jlog`, `verify_archive` |
| `control_center.py` | `CORE_LIB_DIR`, `SSOT_CONF_PATH`, `USER_CONFIG_REL`, `spawn_native`, `write_atomic` |
| `health.py` | `CORE_LIB_DIR`, `NEXT_SESSION_PATH`, `SSOT_CONF_PATH`, `clear_ssot_cache`, `get_ssot_var` |
| Compatibility shims | `jlog`, `run_shim` |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
