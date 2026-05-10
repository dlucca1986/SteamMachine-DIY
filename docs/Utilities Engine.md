[![Version](https://img.shields.io/badge/Version-1.7.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Logic](https://img.shields.io/badge/Logic-C--Core%20Bindings-orange.svg)](#)
[![Framework](https://img.shields.io/badge/Framework-SSoT%20Architecture-blue.svg)](#)

`utils.py` centralizes shared logic for all Python modules in the framework. Performance-critical operations (file I/O, process management, logging) are delegated to the **C-Core** (`libcore.so`). The shared library is loaded via `ctypes` at import time — if `/usr/local/lib/steamos_diy/libcore.so` is missing, the import fails immediately with `sys.exit(127)`.

---

## 🏗️ Core Responsibilities

### 1. Data Integrity (`write_atomic`)
State files are written via a three-step protocol executed entirely in the C-Core:

1. Write data to `<path>.tmp`.
2. Call `fdatasync()` to flush write buffers to physical storage.
3. Call `rename()` to atomically replace the target file.

The target file is never left in a partial state, even after a sudden power loss.

### 2. Configuration Management (`get_ssot_var`, `load_ssot`)
`get_ssot_var(key)` reads a value from `/etc/default/steamos_diy.conf` via the C-Core on the **first call** for that key, storing the result in the module-level `_SSOT_CACHE` dict. Subsequent calls return the cached value without disk I/O. Each resolved value is also written into `os.environ` so child processes inherit it.

`load_ssot()` returns `True` if the SSoT file exists and is readable.

### 3. YAML (`load_yaml_safe`, `apply_env_map`)
`load_yaml_safe(path)` parses a YAML file and returns a dict. Returns `{}` silently on any error (missing file, parse error, missing PyYAML module). Never raises.

`apply_env_map(data_dict)` injects all key/value pairs from a dict into `os.environ`. Non-dict input and `None` values are silently ignored.

### 4. Session State (`read_session_target`)
`read_session_target(path, default="steam")` reads the first line of `path` via the C-Core. Returns the stripped string, or `default` if the file is missing or unreadable.

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
| `spawn_native(path, args)` | Forks via C-Core (`fork` → `setsid` → `execv`), redirects child stdout/stderr to `/dev/null`. Returns the child PID, or `0` on failure. |
| `spawn_process(cmd)` | `subprocess.Popen` wrapper with `start_new_session=True` and both streams devnull'd. Returns the `Popen` object or `None` on `OSError`. |
| `monitor_pid(pid, timeout)` | Polls `/proc/<pid>` every 200 ms for up to `timeout` seconds. Returns `True` if the process is still alive at the end of the window. Avoids `waitpid` conflicts with Python's `subprocess`. |

---

## 📖 Journal Utilities

Used by `control_center.py` for log display and game discovery.

| Function | Description |
| :--- | :--- |
| `get_journal_cmd(tag)` | Returns the `journalctl` argv for a given tag (`CORE`, `STEAM`, `SYSTEM`, `ALL`, or any custom tag). Fixed window: last 12 hours, 300 entries, `--no-pager -o export`. |
| `extract_game_metadata(line)` | Parses a raw journal export line for a game name (`chdir` pattern) or AppID (`gameID` / `AppID` pattern). Non-Steam shortcut AppIDs wider than 32 bits are shifted right to their real AppID. Returns `("NAME", value)`, `("ID", value)`, or `(None, None)`. |

---

## 📂 Framework Dependencies

| Component | `utils` imports used |
| :--- | :--- |
| `session_launch.py` | `write_atomic`, `read_session_target`, `load_yaml_safe`, `apply_env_map`, `notify`, `jlog`, `sd_notify_ready`, `get_ssot_var` |
| `session_select.py` | `write_atomic`, `spawn_native`, `notify`, `jlog`, `get_ssot_var` |
| `sdy.py` | `load_yaml_safe`, `apply_env_map`, `jlog`, `get_ssot_var` |
| `backup.py` | `check_root`, `fix_ownership`, `get_real_user`, `get_ssot_var`, `jlog`, `load_ssot` |
| `restore.py` | `check_root`, `fix_ownership`, `get_real_user`, `get_ssot_var`, `jlog`, `load_ssot` |
| `control_center.py` | `get_ssot_var`, `get_journal_cmd`, `extract_game_metadata` |
| Compatibility shims | `jlog` |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
