[![Version](https://img.shields.io/badge/Version-2.1.7-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)


Log tags, diagnostic commands, and handy shell aliases.

---

## 🔍 1. System Journal Tags

The framework uses a unified tagging system. Use `journalctl` to filter logs and identify issues quickly.

| Tag | Origin | Diagnostic Value |
| :--- | :--- | :--- |
| `CORE` | `session_launch`, `session_select`, `sdy`, `utils` | Crash recovery, session switch requests, binary not found errors, SSoT/config read failures. |
| `STEAM` | `session_launch`, `sdy` | Gamescope launch args, game launch and execution failures, post-start hook commands. |
| `SYSTEM` | `backup`, `restore`, `journal`, `utils`, `helpers/*` | Backup/restore operations, self-update checks, and SteamOS shim intercepts. |

`control_center.py` (the GUI) never logs to the journal directly — failures there show as an on-screen message box or status-bar text instead, not a `journalctl` entry.

---

## 📖 2. Message Reference

Every `jlog(tag, message, level=...)` call in the codebase, grouped by the module that emits it. Use this when a tag alone (section 1) isn't specific enough — grep the exact prefix below against `journalctl -t <tag>` to jump straight to the relevant code path.

**How to read a level:**

| Level | Meaning | Typically needs action? |
| :--- | :--- | :--- |
| `DEBUG` | Internal detail, normal operation. Hidden by default (see below). | No — informational only. |
| `INFO` | A normal milestone (launch started, backup succeeded, switch requested). | No. |
| `WARN` | Something degraded gracefully — a hand-edited config had a typo, one item in a batch failed — but the operation still completed using a safe fallback. | Worth a look if it recurs, not urgent. |
| `ERROR` | The operation did not complete. | Usually yes — this is where to start when something visibly isn't working. |

The SSoT's `LOG_LEVEL` key (`/etc/default/steamos_diy.conf`, default `INFO`) sets the visibility floor: anything below it is discarded *before* it reaches the journal at all. Set `LOG_LEVEL=DEBUG` temporarily (then `sudo systemctl restart steamos_diy.service` or just relaunch a script) to see the `DEBUG` rows below — they're invisible at the default level.

Placeholders below (`<name>`) stand for the actual runtime value substituted into the message at log time.

### Session launch & switching (`session_launch.py`, `session_select.py`)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `STEAM` | `BAD_FLAG_ENTRY: <flag> - <error>` | WARN | A `flags:` entry had an unbalanced quote; degraded to a naive whitespace split and still ran. |
| `STEAM` | `LAUNCH_ARGS: <full gamescope+Steam argv>` | INFO | The exact command line used to launch this session — first place to look for a wrong flag. |
| `STEAM` | `POST_START_CMDS_SKIPPED: session crashed before delay elapsed` | DEBUG | `post_start_cmds` were **not** run because the session was already detected as crashed by the time the delay elapsed. |
| `STEAM` | `BAD_POST_START_CMD: <cmd> - <error>` | WARN | A `post_start_cmds` entry had an unbalanced quote; degraded to a naive split and still ran. |
| `STEAM` | `POST_START_CMD: <cmd>` | INFO | A post-start command fired successfully. |
| `STEAM` | `POST_START_CMDS_FAILED: <error>` | ERROR | The entire post-start daemon thread crashed unexpectedly (not a single bad command — something broke the loop itself). |
| `CORE` | `VALIDATED_<TARGET>_STABLE` | DEBUG | The session survived the validation window and was declared stable. |
| `CORE` | `SIGTERM_TIMEOUT: escalating to SIGKILL` | WARN | The session process ignored `SIGTERM`; force-killing with `SIGKILL`. |
| `CORE` | `SIGKILL_TIMEOUT: process still alive (D-state?)` | ERROR | The process survived even `SIGKILL` — almost always stuck in uninterruptible I/O (D-state). Nothing more the launcher can do; systemd's own `TimeoutStopSec` eventually reaps the cgroup. |
| `CORE` | `EARLY_EXIT_RECOVERY: process exited during the validation window...` | ERROR | A crash (or a switch request that raced the launch) was detected — forcing a fallback to Desktop. |
| `CORE` | `BINARY_NOT_FOUND: <path> - <error>` | ERROR | The configured session binary (gamescope/Steam/Plasma) doesn't exist at that path — check the relevant `bin_*` SSoT key. |
| `CORE` | `OS_ERROR: <error>` | ERROR | A generic OS-level failure spawning the session (permissions, resource limits, etc). |
| `CORE` | `BAD_LAUNCH_ARGV: <error>` | ERROR | The command line itself was malformed (e.g. an embedded null byte from a hand-edited config value) — the process was never even spawned. |
| `CORE` | `SIG_<N>: Shutting down...` | INFO | `SIGTERM`/`SIGINT` received — clean shutdown in progress, not a crash. |
| `CORE` | `SWITCH_REQUEST: <target>` | INFO | A session switch (`steamos-session-select`) was requested. |
| `CORE` | `DISPATCH_FAILED: target=<target> — state persisted, switch will apply on next session` | WARN | Couldn't restart the launcher service live to apply the switch immediately, but the target was still written to disk — it takes effect on the next boot/restart regardless. |

### Game launch (`sdy.py`)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `CORE` | `SCAN_ERROR: <directory> - <error>` | DEBUG | Couldn't scan a game-profile directory while looking for a header (`STEAM_APPID`/`SDY_ID`) match. |
| `STEAM` | `BAD_<FIELD>: <value> - <error>` | WARN | A per-game `GAME_WRAPPER` or `GAME_EXTRA_ARGS` had an unbalanced quote; degraded to a naive split and still ran. |
| `STEAM` | `GAME_LAUNCH: <name> (AppID: <id>)` | INFO | A game is being launched — the name/AppID identify which profile was matched. |
| `STEAM` | `EXECUTION_FAILED: <error>` | ERROR | `execvpe` failed — missing binary, permission denied, or a malformed argv. The game never started. |
| `STEAM` | `NO_TARGET: sdy invoked with no argv` | ERROR | `sdy.py` was invoked with nothing to launch — almost always a Steam-side invocation problem, not a config issue. |

### Diagnostics tab log fetch (`journal.py`)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `SYSTEM` | `GAMESCOPE_LOG_FETCH_FAIL: <error>` | WARN | Control Center's Diagnostics tab couldn't fetch gamescope's own logs from the journal — degrades to an empty result rather than raising, so this is the only trace left that the fetch itself failed (vs. gamescope genuinely having logged nothing recently). |

### Backup (`backup.py`)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `SYSTEM` | `BACKUP_SYMLINK_SCAN_FAIL: <path> - <error>` | WARN | Couldn't scan a directory for symlinks to record in the backup manifest. |
| `SYSTEM` | `BACKUP_LINK_SKIPPED: <path>` | WARN | A symlink was excluded from the manifest (unsafe path, or contains a tab/newline that would corrupt the manifest format). |
| `SYSTEM` | `BACKUP_ADD: <path>` | DEBUG | One source path was added to the archive. |
| `SYSTEM` | `BACKUP_TMP_CLEANUP_FAIL: <error>` | WARN | Couldn't remove a leftover `.tmp` archive from a previous failed/interrupted backup. |
| `SYSTEM` | `BAD_BACKUP_KEEP: <error> - using default` | WARN | The `BACKUP_KEEP` SSoT value was unusable as an integer (e.g. hand-edited to `nan`/`inf`) — pruning used the built-in default (5) instead. |
| `SYSTEM` | `BACKUP_PRUNED: <archive name>` | INFO | An old archive was deleted during rotation (only the newest `BACKUP_KEEP` are retained). |
| `SYSTEM` | `BACKUP_PRUNE_FAIL: <archive name> - <error>` | WARN | Couldn't delete an old archive during rotation — it was left in place. |
| `SYSTEM` | `BACKUP_FAILED: <error>` | ERROR | The backup did not complete (directory creation, tar write, or archive-level failure). The previous archive, if any, is untouched. |
| `SYSTEM` | `BACKUP_START: <archive name>` | INFO | A backup run has started. |
| `SYSTEM` | `BACKUP_RENAME_FAIL: <error>` | ERROR | The finished archive couldn't be atomically renamed into its final path — the backup did not land. |
| `SYSTEM` | `BACKUP_SUCCESS: <archive name>` | INFO | The backup completed and is ready to use. |

### Restore (`restore.py`)

Every `RESTORE_REJECTED_*`/`RESTORE_*_FAIL` line below is a **per-member** rejection — by design, one bad or unsafe archive entry is skipped and the rest of the restore continues (see `RESTORE_FATAL` at the bottom for the one case that aborts everything).

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `SYSTEM` | `RESTORE_REJECTED_TRAVERSAL: <member>` | WARN | Archive member's path contained `..` (traversal attempt) — rejected before any resolution. |
| `SYSTEM` | `RESTORE_REJECTED_PATH: <member> -> <target>` | WARN | The resolved filesystem target falls outside the restore allow-list — rejected. |
| `SYSTEM` | `RESTORE_REJECTED_LINK: <member>` | WARN | Archive contained a raw tar hardlink/symlink entry — rejected (only the plain-data links manifest is trusted for recreating symlinks). |
| `SYSTEM` | `RESTORE_REJECTED_SPECIAL: <member>` | WARN | Archive contained a device node or FIFO — rejected (only regular files and directories are ever extracted). |
| `SYSTEM` | `RESTORE_REJECTED_EXISTING_SYMLINK: <target>` | WARN | A symlink already exists at the write target — refused rather than followed, to block a redirect attack. |
| `SYSTEM` | `RESTORE_WRITE_FAIL: <target> - <error>` | WARN | A write I/O error (`makedirs`/copy/`replace`) hit while restoring this one member — skipped, restore continues. |
| `SYSTEM` | `RESTORE_REJECTED_TMP_SYMLINK: <tmp path> - <error>` | WARN | The temporary write path itself was a symlink — refused rather than written through. |
| `SYSTEM` | `RESTORE_CHMOD_FAIL: <target> - <error>` | WARN | The file was written but its permissions couldn't be restored. |
| `SYSTEM` | `RESTORE_EXTRACT: <target>` | DEBUG | One member was extracted and placed successfully. |
| `SYSTEM` | `RESTORE_REJECTED_LINK_PATH: <link> -> <target>` | WARN | A symlink pair from the manifest failed the path allow-list check — not recreated. |
| `SYSTEM` | `RESTORE_LINK_FAIL: <link> - <error>` | WARN | A symlink passed validation but couldn't actually be created/swapped into place. |
| `SYSTEM` | `RESTORE_DAEMON_RELOAD_FAIL: <error>` | ERROR | `systemctl daemon-reload` failed after restoring the service unit — the unit file changed on disk but systemd hasn't picked it up; a manual `daemon-reload` may be needed. |
| `SYSTEM` | `RESTORE_FAILED: Missing <archive path>` | ERROR | The archive file passed to restore doesn't exist. |
| `SYSTEM` | `RESTORE_PAYLOAD_DONE` | DEBUG | All archive members have been processed (some may have been rejected — see the per-member lines above). |
| `SYSTEM` | `RESTORE_LINKS_DONE` | DEBUG | All manifest symlinks have been processed. |
| `SYSTEM` | `RESTORE_EMPTY: no member matched the backup mapping` | ERROR | Every single member was rejected — almost always the wrong archive (foreign format, or from an incompatible layout), not a normal partial failure. |
| `SYSTEM` | `RESTORE_SUCCESS: Environment ready.` | INFO | The restore completed with at least one member restored. |
| `SYSTEM` | `RESTORE_FATAL: <ExceptionType>: <error>` | ERROR | An archive-level failure (corrupt gzip/tar, or an unexpected `OSError`) — unlike every line above, this aborts the **entire** restore. |

### SSoT / config reading (`utils.py`)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `CORE` | `SSOT_READ_ERROR: <error>` | DEBUG | Couldn't read or decode `/etc/default/steamos_diy.conf` — every SSoT lookup degrades to its own built-in default for the rest of the process. |
| `CORE` | `BAD_SSOT_NUM: <key> - using <default>` | WARN | A numeric SSoT value (a timeout, delay, or count) didn't parse as a valid finite number — the built-in default was used instead. |
| `CORE` | `YAML_LOAD_ERROR: <path> - <error>` | DEBUG | Couldn't read or decode a YAML config/profile file. |
| `CORE` | `YAML_PARSE_ERROR: <path> - <error>` | DEBUG | The YAML file has a syntax error. |
| `CORE` | `YAML_NOT_MAPPING: <path>` | WARN | The YAML file parsed successfully but its root isn't a `key: value` mapping (e.g. a bare list) — treated as empty. |
| `CORE` | `SPAWN_ERROR: <path> - <error>` | WARN | A detached process (Control Center's Maintenance-tab buttons, `post_start_cmds`) failed to launch. |
| `CORE` | `USER_LOOKUP_ERROR: <error>` | DEBUG | Couldn't resolve the real (non-root) invoking user while running privileged under `pkexec`. |
| `CORE` | `OWNERSHIP_ERROR: <path> - <error>` | WARN | `chown` failed while restoring ownership of a file/directory to the real user. |
| `SYSTEM` | `<CALLER>_FAILED: SSoT config not found` | ERROR | A privileged operation (backup/restore) refused to start because the SSoT conf file is missing. |
| `SYSTEM` | `<fail_tag>: <error>` | ERROR | Archive integrity verification failed (`verify_archive`) — default tag `ARCHIVE_VERIFY_FAIL`, reused by backup/restore/update with a caller-specific prefix. |

### Self-update (`utils.py`'s `check_latest_release`/`download_release` path)

| Tag | Message | Level | Meaning |
| :--- | :--- | :--- | :--- |
| `SYSTEM` | `<CALLER>_FAILED: non-https URL` | ERROR | A URL used by the update path wasn't `https://` — rejected before ever opening a connection. |
| `SYSTEM` | `UPDATE_CHECK_FAIL: malformed API reply` | WARN | GitHub's releases API replied with an unexpected shape (missing `tag_name`, etc). |
| `SYSTEM` | `UPDATE_CHECK_FAIL: <error>` | WARN | Network or parse error while checking for a new release. |
| `SYSTEM` | `UPDATE_CHECKSUM_FAIL: <error>` | ERROR | Couldn't fetch the release's `SHA256SUMS` asset. |
| `SYSTEM` | `UPDATE_CHECKSUM_FAIL: bad digest <text>` | ERROR | The `SHA256SUMS` asset's content isn't a valid 64-character hex digest. |
| `SYSTEM` | `UPDATE_DOWNLOAD_FAIL: <error>` | ERROR | Network or extraction error while downloading/unpacking the release tarball. |
| `SYSTEM` | `UPDATE_DOWNLOAD_FAIL: checksum mismatch` | ERROR | The downloaded tarball's SHA-256 didn't match `SHA256SUMS` — **fail-closed**, nothing was extracted. |
| `SYSTEM` | `UPDATE_DOWNLOAD_FAIL: install.sh not found` | ERROR | The tarball extracted successfully but doesn't contain an `install.sh` at its root — not a usable release layout. |

### SteamOS shim intercepts (`helpers/*.py`)

These scripts stand in for real `steamos-*`/`jupiter-*` system tools Steam calls directly in Game Mode — each just logs the interception and reports a fixed, harmless status back to Steam instead of running the real (often irrelevant on non-Deck hardware) system action.

| Tag | Message | Level | Shim |
| :--- | :--- | :--- | :--- |
| `SYSTEM` | `[Branch] Switch intercepted: <branch>. Status: OK` | INFO | `steamos-select-branch.py` |
| `SYSTEM` | `[Time] Set Time request intercepted. Reporting: OK (Simulated)` | INFO | `set-timezone.py` |
| `SYSTEM` | `[Bios] Jupiter update intercepted. Reporting: OK (Simulated)` | INFO | `jupiter-biosupdate.py` |
| `SYSTEM` | `[Update] OTA request intercepted. Status: UP TO DATE (Exit 7)` | INFO | `steamos-update.py` |
| `SYSTEM` | `[Dock] Jupiter updater intercepted. Status: UP TO DATE (Exit 7)` | INFO | `jupiter-dock-updater.py` |

### C-Core (`steamos_diy_core.c`)

One message is logged directly by the C library, not through Python's `jlog()` — it has no `CORE`/`STEAM`/`SYSTEM` tag prefix, so it won't match a `journalctl -t` filter; grep for the function name instead.

| Message | Level | Meaning |
| :--- | :--- | :--- |
| `c_write_atomic: rename <tmp> -> <path>: <errno message>` | `LOG_ERR` | The final atomic `rename()` step of a privileged config write failed — the write did not land; the target file still holds its previous content. |

---

## 🛡️ 3. Advanced Debugging Tools

| Command | Purpose |
| :--- | :--- |
| `journalctl -u steamos_diy.service -f` | Live logs from the session launcher (session_launch.py). |
| `journalctl -t CORE -t STEAM -t SYSTEM` | Full project log view — single tags can be filtered individually (see the table above). |
| `sudo fuser -v /dev/dri/card*` | Identify which process is currently locking the GPU. |
| `cat /sys/class/drm/*/modes` | List all resolutions natively detected by the Kernel (DRM). |
| `vulkaninfo --summary` | Verify that the Vulkan stack (Mesa/NVK) is operational. |
| `python3 -m py_compile script.py` | Check for syntax errors in the core logic after a manual edit. |
| `pkexec journalctl --rotate --vacuum-time=1s` | Rotate and purge system logs in a single invocation (mirrors the Control Center cleanup action). |

---

## 🩹 4. Known Issues & Fixes

### Black or corrupted Store / Library pages in Game Mode
On older or low-power GPUs, Steam's embedded Chromium (CEF) can fail at GPU-accelerated compositing, leaving the **Store** and **Library** pages black, flickering, or visually corrupted while the rest of Game Mode renders fine.

**Fix:** force CEF to software compositing with the Steam-client flag `-cef-disable-gpu-compositing` (or, for full software rendering, `-cef-disable-gpu`). These are **Steam client** flags, *not* gamescope flags — they go on the Steam invocation in `session_launch.py` (the `-gamepadui -steamos3 -steamdeck` line), **not** in `config.yaml`'s `flags`. Try the minimal `-cef-disable-gpu-compositing` first; fall back to `-cef-disable-gpu` only if the corruption persists.

### "Another privileged operation is already running…" won't go away
Backup and Restore each guard against a double-click, and if a `pkexec` call for either ever times out (after 5 minutes), its lock is deliberately left in place rather than cleared — the privileged process it started (a `chown -R`, `backup.py`, `restore.py`) may still be running, and there's no way to confirm it's actually finished. Backup and Restore share one lock (they touch the same files), so a timeout on either one blocks both. Journal-vacuum has its own separate lock and behaves differently: a timeout there almost always just means authentication at the polkit prompt took too long, not that the vacuum itself is stuck, so its lock always clears itself automatically — you don't need to restart to retry it.

**Fix:** restart the Control Center. This clears a stuck Backup/Restore guard; it does not itself confirm whether the original privileged process finished — check the Diagnostics logs or `journalctl` if you need to know for certain before retrying. Journal-vacuum never needs this — just try it again.

---

## 💡 5. Diagnostic Aliases (Terminal Power-User)
Add these to your `~/.bashrc` to control the architecture. These commands interact directly with the **Journal** and the **Next Session logic**.

```
# =============================================================================
# SteamMachine-DIY - Diagnostic Aliases
# =============================================================================

# --- 📝 JOURNAL MONITORING ---
# Service lifecycle logs (session start/stop/restart — use -t CORE -t STEAM -t SYSTEM for application logs)
alias sdy-logs='journalctl -u steamos_diy.service -f -n 100'

# Display only critical errors recorded by the service
alias sdy-errors='journalctl -u steamos_diy.service --priority=3'

# --- 🚀 SESSION MANAGEMENT ---
# Switch session (Desktop/Steam)
alias sdy-mode-desktop='steamos-session-select desktop'
alias sdy-mode-game='steamos-session-select steam'

# --- 🛠️ EMERGENCY & RESET ---
# Check session status
alias sdy-status='pgrep -a gamescope || pgrep -a steam || echo "No gaming session active."'

# Terminate session
alias sdy-kill='pkill -9 gamescope && pkill -9 steam'

# GPU Reset
alias sdy-gpu-fix='sudo fuser -k /dev/dri/card*'

# Restart systemd service
alias sdy-restart='sudo systemctl restart steamos_diy.service'
```

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
