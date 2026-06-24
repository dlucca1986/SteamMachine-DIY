[![Version](https://img.shields.io/badge/Version-2.1.3-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

PyQt6 dashboard for system management, YAML configuration editing, and log analysis.

---

## 📂 UI Navigation & Tab Logic

### 1. Diagnostics (Tab Index 0)
Default tab. Logs are fetched in a background thread via `load_logs()` and auto-refresh each time the user switches to this tab. `on_tab_changed` detects the diagnostics tab dynamically via `self.tabs.indexOf(self.diag_tab)` — no magic index.

* **Component Filter**: Combo with `ALL`, `CORE`, `STEAM`, `SYSTEM`. Each selection calls `get_journal_cmd(tag)` which runs `journalctl -t <tag>` (last 12 hours, 300 entries, export format).
* **Gamescope integration**: When the filter is `ALL` or `STEAM`, a second journal query (`journalctl -t steam -t python3 --since "1 hour ago" -o short-iso`) fetches gamescope output and merges it into the display. Lines are accepted only when their payload matches the gamescope log format (`[Info]`/`[Warn]`/`[Error]`/`[Gamescope WSI]` or `/usr/bin/gamescope:`) so substring noise (e.g. file managers acting on `gamescope.example.yaml`) is filtered out. Already-seen `LAUNCH_ARGS` strings are deduplicated.
* **Filter box**: A search field live-filters the displayed log (`_apply_log_filter()`) to lines containing the typed text (case-insensitive), re-rendering from the cached fetch — no extra `journalctl` call. Clearing it restores the normal view; a query with no hits shows a *"No lines match the filter."* hint.
* **Log deduplication**: Consecutive identical lines are collapsed by `_display_colored_logs()` into a *"⤷ Repeated N times"* note (the active filter takes priority — filtered-out lines are skipped first).
* **Export**: Copy to clipboard (`copy_logs()`) copies the on-screen view. **Export Support Report** (`export_support_log()`) builds a full diagnostic file instead: kernel, service status, the complete preflight report, and the raw last-12h logs (all tags + gamescope) re-fetched independently of the active filter and without the display-side dedup — ready to attach to a GitHub issue. Default filename is timestamped (`sdy_support_YYYYMMDD_HHMMSS.log`).

### 2. Maintenance (Tab Index 1)
Privileged operations (backup, restore, log vacuum) run in a background `threading.Thread` via `_run_pkexec`. Results surface via the `process_finished` PyQt signal. Non-privileged launches (Switch to Steam, Open Konsole, Browse Config Folder) use `spawn_native` from `utils.py` (detached, `start_new_session=True`). Edit SSoT uses `subprocess.Popen` directly to preserve the GUI error dialog on failure.

Buttons in order:

| Button | Action |
| :--- | :--- |
| **Switch to Steam (Game Mode)** | Calls `session_select.py steam` via `spawn_native`. |
| **Edit System Config (SSoT)** | Opens `/etc/default/steamos_diy.conf` in `kate` (falls back to `kwrite`). |
| **Validate Configuration** | Runs `health.run_preflight()` off-thread and shows a colour-coded report (config presence, path resolution, YAML syntax, gamescope flag validity, group membership, C-Core, session state). See [Configuration Health](#-configuration-health-healthpy). |
| **Clean System Logs (Vacuum)** | Runs `pkexec journalctl --rotate --vacuum-time=1s` in a single invocation. |
| **Create Full System Backup** | Runs `pkexec python3 backup.py` in a background thread. |
| **Restore from Archive** | Opens a file picker for a `.tar.gz`, then runs `pkexec python3 restore.py <path>`. |
| **Open Konsole Terminal** | Spawns `konsole`. |
| **Browse Config Folder** | Opens `~/.config/steamos_diy/` via `xdg-open`. |
| **Open Project Wiki** | Opens the wiki URL via `QDesktopServices`. |

### 3. Global Options (Tab Index 2)
Text editor for YAML configuration files with real-time validation.

* **File selector**: Combo listing `config.yaml`, `config.example.yaml`, and `gamescope.example.yaml`. Switching the combo loads the selected file into the editor.
* **View Template**: Toggles between the active file and its `.example.yaml` counterpart. The editor's previous content is cached in `view_states["global"]` and restored on toggle-back. Saving is disabled while in template view.
* **Beautify**: `beautify_yaml()` runs the text through the ruamel.yaml round-trip parser — converting tabs to two spaces, fixing indentation and normalising spacing while preserving comments and quoting. The reformat is applied as a **single undoable edit** (one `Ctrl+Z` reverts it) and the scroll position is preserved; the outcome is reported in the status bar (`✨ YAML formatted` / `Already clean` / `Nothing to format` for a comments-only document / `Syntax error — see highlight`). It only reformats documents that already parse — broken YAML surfaces as a syntax error instead, and string *values* (e.g. the content inside each `flags` entry) are left verbatim.
* **Save**: `_atomic_save()` validates the YAML and delegates persistence to `write_atomic()` (C-Core) — the same `tmp + fdatasync + rename` protocol used for the session state file. **Ctrl+S** saves the editor on the active tab (`_save_current_tab()`).
* **Unsaved-changes guard**: closing the window with pending edits in either YAML editor prompts Save / Discard / Cancel (`closeEvent` → `_dirty_editors()`) instead of dropping them silently. The editor's modified flag is cleared on load, template toggle and save, so the prompt only appears for genuine unsaved edits — and template previews never count as dirty.
* **Error highlighting**: On a YAML parse error, the offending line gets a red background and the preceding line an orange background, helping identify root causes like unclosed quotes. The highlight clears on any user edit.

### 4. Game Overrides (Tab Index 3)
Per-game YAML profile editor backed by journal-based game discovery.

* **Scan History**: `refresh_detected_games()` runs `journalctl --since "24 hours ago" --no-hostname --no-pager` (no entry limit) in a background thread. `filter_game_journal_lines()` (from `journal.py`) then extracts game-related lines (matching `chdir`, `gameID`, or `AppID` patterns, noise-filtered), keeping at most the last **2000** matching lines. `parse_game_logs()` (from `journal.py`) then builds the `{name: appid}` dict by calling `extract_game_metadata()` per line.
* **On-disk merge**: After scanning, `_merge_on_disk_profiles()` adds any existing `games.d/*.yaml` file not already in the detection results, so profiles are always accessible even if the game wasn't recently launched.
* **Combo display**: Games are shown as `"Name (AppID)"` when an AppID is known, otherwise just `"Name"`. The combo is editable; the profile is loaded (or scaffolded) on selection — typing a new name does not reload until you confirm it.
* **Profile scaffold**: If no profile exists for the selected game, `_scaffold_game_profile()` generates a YAML stub including `SDY_ID` and `STEAM_APPID` headers when an AppID is available.
* **Unsaved edits**: `view_states["games"]` caches unsaved editor content while switching between games or toggling templates.
* **Save**: `save_game_profile()` writes to `games.d/<Name>.yaml` via `_atomic_save()`.

---

## 🩺 Configuration Health (`health.py`)

> A Qt-free backend module — like `journal.py`, it is pure functions with no project-module side effects, testable in isolation. It powers two surfaces: the **Validate Configuration** button and the status-bar service strip.

### Preflight (`run_preflight`)
The **🩺 Validate Configuration** button (Maintenance tab) runs `run_preflight()` off-thread and renders a colour-coded pass/fail report via the `preflight_ready` signal. Each check returns a `CheckResult(name, ok, detail)`:

| Check | Verifies |
| :--- | :--- |
| **SSoT config** | `/etc/default/steamos_diy.conf` exists |
| **Binary `bin_*`** | each handler (`bin_gs` / `bin_steam` / `bin_plasma` / `bin_dbus`) resolves to an executable |
| **`user_config` / `games_conf_dir`** | the declared SSoT path actually exists — a typo is flagged, not silently skipped |
| **YAML** | the global config and every `games.d/*.yaml` parse, reporting the offending line on failure |
| **`config flags` / `post_start_cmds`** | if present, are lists — the launcher iterates them directly, so a scalar would become per-character junk argv |
| **Gamescope flags** | every option token in `config flags` is recognised by the installed `gamescope --help` — an unknown or mistyped flag makes gamescope exit at launch (black TTY), so it is caught before boot. Skipped if gamescope can't be run |
| **User groups** | the user belongs to `tty` / `video` / `render` / `input` |
| **C-Core** | `libcore.so` is loadable |
| **Session state** | the `next_session` directory is writable |

`run_preflight()` calls `clear_ssot_cache()` first, so re-running the doctor after editing the config reflects the **current** on-disk state, not cached values.

> **Scope:** the preflight validates *presence, path resolution and YAML syntax*, plus the two field types the runtime does not guard. It deliberately does **not** perform full schema/semantic validation (unexpected keys, `LOG_LEVEL` values, timing sanity) — the runtime already degrades those gracefully.

### Service status strip
A permanent label in the window status bar reports `steamos_diy.service`, refreshed every **4 s** by a `QTimer` that fetches `get_service_status()` off-thread (`service_status_ready` signal):

```
● steamos_diy: <active> (<sub>) · restarts: <N> · last exit: <code>
```

Colour-coded green (`active`) / red (`failed`) / grey (unknown). `get_service_status()` reads `systemctl show` (no root needed) and `parse_service_status()` degrades missing or non-numeric fields to safe placeholders. **Note:** `restarts` (`NRestarts`) increments on every exit-75 session switch, so a high count is normal — `ActiveState=failed` is the real alarm.

---

## 🛠️ Method Mapping Table

| Tab | Action | Method | Logic |
| :--- | :--- | :--- | :--- |
| **0** | Load Logs | `load_logs()` | `get_journal_cmd(tag)` → `journalctl -t` (12h, 300 entries); `ALL`/`STEAM` also merge gamescope logs (last 1h, `short-iso`) |
| **0** | Filter Logs | `_apply_log_filter()` | Live case-insensitive filter of the cached logs (no re-query) |
| **0** | Export Report | `export_support_log()` | `QFileDialog` → `_build_support_report()` off-thread (service + preflight + raw logs) → `Path.write_text` |
| **1** | Validate Config | `validate_config()` | `health.run_preflight()` off-thread → colour-coded report |
| **1** | Clean Logs | `cleanup_logs_privileged()` | `pkexec journalctl --rotate --vacuum-time=1s` (single invocation) |
| **1** | Backup | `run_backup()` | `pkexec python3 backup.py` in `threading.Thread` |
| **1** | Restore | `run_restore()` | `QFileDialog` + `pkexec python3 restore.py <path>` in `threading.Thread` |
| **2** | Save Config | `_atomic_save()` | YAML validation → `write_atomic()` (C-Core, fdatasync + rename) |
| **2** | Beautify | `beautify_yaml()` | `ruamel.yaml` round-trip (indent/spacing fix, comments preserved); single undoable edit, scroll kept, status-bar feedback |
| **2** | View Template | `toggle_template("global")` | Loads/restores `.example.yaml`; disables save while active |
| **3** | Scan Games | `refresh_detected_games()` | `journalctl --since "24 hours ago"` → filter → last 2000 game lines |
| **3** | Save Profile | `save_game_profile()` | `_atomic_save()` → `games.d/<Name>.yaml` |
| **2/3** | Save (Ctrl+S) | `_save_current_tab()` | Saves the active tab's editor (skips template view) |
| **2/3** | Close guard | `closeEvent()` | `_dirty_editors()` → Save / Discard / Cancel prompt on pending edits |

---

## 🖊️ Editor Widgets

> Defined in `editors.py` — zero dependency on project modules, purely self-contained Qt widgets.

### YAMLEditor (`QPlainTextEdit` subclass)
Custom editor used in both the Global Options and Game Overrides tabs.

* **Line number gutter** (`LineNumberArea`): A side widget rendered via `QPainter`. Width scales dynamically with line count. Background `#2c3e50`, numbers `#95a5a6`.
* **Auto-indent**: On `Enter`/`Return`, the previous line's leading whitespace is replicated on the new line, preserving YAML indentation without manual spacing.
* **No word wrap**: `LineWrapMode.NoWrap` keeps long flag lines readable.

### YAMLSyntaxHighlighter (`QSyntaxHighlighter` subclass)
Rule-based highlighter applied to both editors. Rules are evaluated per visible block by Qt.

---

## 🎨 YAML Syntax Palette

| Element | Pattern | Colour | Style |
| :--- | :--- | :--- | :--- |
| Comments | `#...` | Grey `#7f8c8d` | Normal |
| Keys | `word:` | Blue `#3498db` | **Bold** |
| Strings | `"..."` / `'...'` | Yellow `#f1c40f` | Normal |
| List items | `- ...` | Green `#27ae60` | Normal |
| Numbers | `\d+` | Orange `#e67e22` | Normal |
| Colons & dashes | `:` `/` `-` | Red `#e74c3c` | **Bold** |
| Error line | — | Red `#e74c3c` α50 | Background |
| Preceding line | — | Orange `#f39c12` α50 | Background |

---

## 🔍 Log Analysis Colour Palette

### Framework tags (`log_styles`)
| Tag | Icon | Colour |
| :--- | :--- | :--- |
| `CORE:` | 🔵 | Blue `#3498db` |
| `STEAM:` | 🎮 | Green `#2ecc71` |
| `SYSTEM:` | ⚙️ | Orange `#f39c12` |
| `DEBUG:` | 🔍 | Grey `#95a5a6` |
| `ERROR:` | 🚫 | Red `#e74c3c` |

### Gamescope tags (`gs_levels` + inline)
| Tag | Icon | Colour |
| :--- | :--- | :--- |
| `[gamescope]` | — | Teal `#1abc9c` |
| `[Error]` | ❌ | Red `#ff4444` |
| `[Warn]` | ⚠️ | Amber `#ffbb33` |
| `[Info]` | ℹ️ | Blue `#33b5e5` |
| `LAUNCH_ARGS` | 🚀 | Green `#2ecc71` **bold** |

---

## 🛠️ Internal Logic: Round-Trip Engine

The module-level `yaml_parser` instance is shared across all save and beautify operations:

```python
yaml_parser = YAML()
yaml_parser.preserve_quotes = True
yaml_parser.indent(mapping=2, sequence=4, offset=2)
yaml_parser.width = 4096
```

`_atomic_save()` validates content through `yaml_parser.load()` before writing. A parse error surfaces the problem line in the editor without touching the file on disk.

---

## 📊 Troubleshooting Workflow

| Goal | Recommended Action |
| :--- | :--- |
| **Debug a Crash** | Open **Diagnostics**, filter by `ALL` or `STEAM`, look for `ERROR:` tags or `[Error]` gamescope lines. |
| **Verify Configuration** | Use **Global Options**; the editor highlights the error line (red) and its predecessor (orange) on invalid YAML. |
| **System Recovery** | If shims or symlinks are broken, use **Restore from Archive** in Maintenance. |
| **Game Specific Profile** | Use **Game Overrides** → Scan History → select the game → edit and save. |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
