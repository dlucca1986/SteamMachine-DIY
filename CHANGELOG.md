# Changelog

All notable changes to SteamMachine-DIY are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.1.8] — 2026-08-26 — Continuous Integration & Centralization Pass

### Added
- **Continuous Integration**: `.github/workflows/quality-gates.yml` runs on every push/PR to
  `testing` and `stable`, one job step per gate (pylint on production code, flake8, ruff,
  bandit, radon cc, radon mi, vulture, pytest, pylint on the test suite, shellcheck) —
  mirrors CLAUDE.md's local review checklist verbatim, so a red X in the Actions UI points
  straight at which tool failed. `radon cc`/`radon mi` don't have a built-in fail-on-threshold
  flag (they always exit 0 regardless of findings), so each gets a short inline check instead:
  fail the step if any function is grade C or worse, or any file drops below maintainability
  grade A.
- `vulture_whitelist.py` (repo root, generated via `vulture --make-whitelist`): covers exactly
  the Qt/tarfile/ruamel false positives CLAUDE.md already documented. vulture's own exit code
  is nonzero on any finding, including known false positives, so a whitelist was required for
  it to function as a real CI pass/fail gate instead of a manually-eyeballed report. Lives
  outside `usr/local/lib/steamos_diy/`, so `install.sh`'s deploy step never ships it.
- `shellcheck` added to the local/CI gate list now that it's available in the dev environment.
  `install.sh`'s only finding, `SC2086` on `pacman -Syu $BASE_PKGS $DRIVER_PKGS`, is intentional
  word-splitting on two fixed-literal, space-separated package lists (never user input) — each
  package must reach `pacman` as its own argv entry, so quoting would break installation.
  Documented with a `# shellcheck disable=SC2086` and a one-line reason. `uninstall.sh` is clean.

### Security
- **Self-update integrity verification**: `download_release()` in `utils.py` previously
  fetched and extracted a GitHub release tarball with no integrity check before
  `install.sh` inside it ran with elevated privileges — flagged in CLAUDE.md as the
  project's highest-value supply-chain risk. It now requires a `SHA256SUMS` release
  asset (added to `ReleaseInfo` via `_release_from_api()`'s new `_find_checksum_url()`),
  fetches and validates the digest format via the new `_fetch_expected_sha256()`, and
  streams the tarball into a temp file while hashing it (`_download_verified_tarball()`)
  before ever calling `tarfile.extractall`. Missing, malformed, or mismatched checksums
  abort the download entirely (fail-closed) rather than degrading to an unverified
  extraction. This makes attaching a `SHA256SUMS` asset a required manual step of the
  release process from this version on (documented in CLAUDE.md's new "Release process"
  section) — a release published without one cannot be installed via the in-app updater.
  This defends against transport-level corruption/tampering of the download only, not
  against a compromised publishing account (no independent signature).
- **Subprocess timeout discipline** (CLAUDE.md review checklist item 14): every
  `subprocess.run()` call that talks to a system daemon (`systemctl`, `journalctl`, `pkexec`)
  now carries an explicit `timeout=` and a handler for `TimeoutExpired` — `health.py`'s
  `get_service_status` (`timeout=5`), `journal.py`'s `fetch_tagged_entries` and
  `_run_journalctl_iso` (`timeout=10` each), `restore.py`'s `_reload_systemd` (`timeout=10`),
  `utils.py`'s `fix_ownership` (`timeout=30`), and `control_center.py`'s `_run_pkexec` worker
  and journalctl-scan calls (`timeout=300`/`timeout=10`). Previously an unresponsive daemon —
  plausible on a handheld that can wedge or lose power mid-operation — could hang a worker
  thread indefinitely with no way to recover short of killing the process. Every widened
  `except` clause now catches `subprocess.SubprocessError` (the common superclass of both
  `CalledProcessError` and `TimeoutExpired`) instead of just `CalledProcessError`, so the new
  timeout path degrades the same way an existing failure already did, without adding a second
  exception type to every call site.

### Fixed
- `sdy.py`: `games_conf_dir`'s fallback (used only when the SSoT key is unset) hardcoded
  `/etc/steamos_diy/games.d` — a directory `install.sh` never creates and nothing else in the
  repo references, i.e. a dead path. `control_center.py` falls back to
  `~/.config/steamos_diy/games.d` instead, so on an installation with a missing/corrupted
  `games_conf_dir` key, the GUI would save per-game profiles to a directory the launcher would
  never look in — same silent-divergence risk as the `user_config`/`games_conf_dir` SSoT bug
  fixed in 2.1.7, but on the fallback value rather than the SSoT-read value. Now resolves via
  the new `utils.default_games_conf_dir()`, matching `control_center.py`'s actual default.
- `utils.py`: `download_release()` used to prune every previously-cached release download
  (`_prune_downloads()`) *before* verifying the new download's checksum. A corrupted or
  tampered-with download that failed `_download_verified_tarball()`'s SHA-256 check would
  abort correctly, but the last known-good cached release had already been deleted — a
  successful earlier update's cache was destroyed by an unrelated failed one. Pruning now
  runs only after the new tarball is downloaded and verified, immediately before extraction.
- `control_center.py`: `_run_pkexec`'s re-entrancy guard (`_pkexec_busy`) had two related gaps.
  First, replacing its old unconditional `finally:` reset with a `TimeoutExpired`-only skip
  meant *any* unforeseen exception in the worker (e.g. a cross-thread Qt signal emit racing
  window teardown) — not just the deliberate timeout case — could leave the guard silently
  stuck forever with no error shown; a `finally` guarded by a local flag now resets it on
  every outcome except the intentional timeout. Second, the guard was a single flag shared by
  three unrelated privileged operations (journal vacuum, backup, restore), so a timeout on
  vacuum (which touches no files backup/restore care about) permanently blocked the other two
  as well; it's now keyed per lock group (`lock_key="files"` for Backup/Restore, which do
  share target files and must stay mutually exclusive, `lock_key="vacuum"` for journal
  cleanup, which doesn't) so unrelated operations no longer block each other.
- `control_center.py`: `_resolve_config_paths`'s `games_conf_dir` fallback independently
  hardcoded the `"games.d"` subdirectory name instead of sharing it with
  `utils.default_games_conf_dir()` (the function whose own docstring already claimed to be
  the single source of truth for both files) — today's values happened to coincide, but
  nothing would have caught the two silently diverging if either literal were ever edited
  alone, the same class of bug already fixed once for this exact concept earlier in this
  release. Both now derive from a single shared `utils.GAMES_CONF_SUBDIR` constant.

### Changed
- `utils.py`: added `shlex_split_or_fallback()` — the "`shlex.split`, degrade to `str.split()`
  on an unbalanced quote" pattern was independently reimplemented in `sdy.py` (`_safe_split`),
  `session_launch.py` (the gamescope `flags` loop) and `health.py`
  (`_collect_unknown_flags`) instead of sharing one copy. This is the exact class of code that
  already caused a real crash in this project (the unguarded `shlex.split` fixed in 2.1.7) — a
  future hardening of the fallback logic would otherwise need three independent edits instead
  of one. `session_launch.py`'s `_schedule_post_start_cmds` keeps its own inline
  `shlex.split`/`continue`-on-failure handling unchanged: skipping a malformed command entirely
  is the safer choice there, since a degraded `str.split()` would still get natively exec'd via
  `spawn_native`, unlike a merely-wrong gamescope flag.
- `utils.py`: `check_latest_release()`, `_fetch_expected_sha256()`, and
  `_download_verified_tarball()` each independently rebuilt the same
  `urllib.request.Request`/`urlopen(timeout=...)` plumbing and the same "reject a non-https
  URL" guard. Both are now centralized — `_https_open()` for the request/urlopen/timeout
  boilerplate, `_require_https()` for the scheme guard — while each caller keeps its own
  error handling, since what counts as recoverable (and what to log) genuinely differs per
  caller (JSON parsing vs. raw digest text vs. streamed binary). `_fetch_expected_sha256()`'s
  digest parsing/validation was also simplified from a double `str.split()` call plus a
  hand-rolled per-character hex-alphabet loop to a single `re.fullmatch()` check.
- `utils.py`: `fix_ownership`'s failure log (including the new timeout case above) moved from
  `DEBUG` to `WARN` — a failed/timed-out `chown -R` after a backup/restore run leaves files
  owned by root, which previously left zero trace in the journal under the default
  `LOG_LEVEL=INFO`.
- `backup.py` / `journal.py`: two previously-silent failure paths now log. `backup.py`'s
  `_collect_symlinks` logs `BACKUP_SYMLINK_SCAN_FAIL` (WARN) if a symlink-search directory
  can't be scanned, instead of silently omitting those symlinks from the backup manifest with
  no trace. `journal.py`'s `_run_journalctl_iso` logs `GAMESCOPE_LOG_FETCH_FAIL` (WARN) if the
  gamescope-log `journalctl` call fails, instead of returning an empty result indistinguishable
  from "no gamescope activity in the last hour" — this required `journal.py` to start
  importing `jlog` from `utils.py`, the only production file that previously imported nothing
  from it.
- Suppression-comment justification pass: every bare `# nosec`, `# pylint: disable`, and
  `# shellcheck disable` marker across the codebase now carries the same one-line reason its
  more prominent siblings already had (see `session_launch.py`'s existing `# nosec B404`/
  `# nosec B603` pattern) — no behavior change, but a bare suppression is no longer
  indistinguishable from an unreviewed one on a future read.
- `utils.py`: added `SYSTEMCTL_BIN`/`JOURNALCTL_BIN` constants — `/usr/bin/systemctl` was
  hardcoded identically in `health.py` and `restore.py`, and `/usr/bin/journalctl` in
  `journal.py` (twice) and `control_center.py` (twice). Unlike the `DEFAULT_*_BIN` group these
  aren't SSoT-backed: every systemd distro ships them at this fixed path, so there's no
  legitimate per-deployment override — this is a same-file-concept centralization, not a new
  user-facing config knob.

---

## [2.1.7] — 2026-08-25 — Session Reliability & Regression Suite

### Added
- **Test suite**: `usr/local/lib/steamos_diy/tests/` — the project's first automated tests (84 cases, run with `pytest` from the repo root; scoped via the root `pyproject.toml`). Deliberately small and targeted rather than exhaustive: covers the fiddly pure logic in `backup.py` (path exclusion, archive pruning, symlink-manifest generation, plus an end-to-end `run_backup()` smoke test against a real `.tar.gz`), `restore.py`'s allow-list/traversal safety, and a regression test for every bug fixed below. `conftest.py` mocks `ctypes.CDLL` before any test imports `utils.py` (no `libcore.so` required to run the suite) and isolates the SSoT cache/`os.environ` per test so nothing touches the real `/etc/default/steamos_diy.conf`. `control_center.py`'s `_resolve_config_paths` was extracted as a pure function specifically so its SSoT-resolution logic (see Fixed, below) is testable without a `QApplication`. A follow-up pass added: `sdy.py`'s AppID/effective-name/stem profile-resolution precedence (pins the exact-match contract behind the 2.1.4 substring-match fix); a `get_backup_mapping()` ↔ `restore.py` symmetry check that round-trips every real backup key through the actual allow-list, so a future path relocation that breaks restore is caught immediately instead of silently; `get_ssot_num`'s malformed-value fallback; and — the highest-value addition — `session_launch.py`'s crash-detection/recovery-to-Desktop path (`_monitor_process`, `_terminate_gracefully`, `_run_session`), exercised against real short-lived subprocesses rather than mocks, since that mechanism is what decides whether the machine self-heals from a crash or is left with a black TTY1. A later pass added `health.py`'s `_check_groups` stale-gid isolation, `control_center.py`'s combo display-name parsing, and `journal.py`'s per-process AppID attribution (see Fixed, below), plus two previously-uncovered areas: `session_select.py`'s target-resolution keyword matching and its persist-state-before-spawn ordering (state must survive a helper-spawn failure so the next boot still has a valid target), and `utils.py`'s self-update path — `_version_tuple`/`_release_from_api` parsing, `_prune_downloads`, and `download_release()`'s HTTPS-only guardrail plus a full extract-and-locate-`install.sh` round-trip against a real in-memory release tarball, since this is the single highest-risk supply-chain surface in the project (the downloaded tarball's own `install.sh` later runs with elevated privileges).

### Fixed
- `session_launch.py` / `sdy.py`: an unbalanced quote in a hand-edited `flags:`/`post_start_cmds:`/`GAME_WRAPPER`/`GAME_EXTRA_ARGS` entry raised an uncaught `ValueError` from `shlex.split` — for `session_launch.py` this happened before any crash-recovery logic could engage, so the whole Game Mode launcher died, `Restart=on-failure` retried the same broken config, and the unit went to `failed` after `StartLimitBurst` with TTY1 stuck and no fallback to Desktop; for `sdy.py` the game simply never launched. `health.py`'s own preflight already guarded the same `shlex.split` call and degraded to `str.split()` on failure — the runtime paths now do the same instead of crashing.
- `restore.py`: `_write_member` wrote extracted files by `unlink()`-ing the target then `open(..., "wb")`, so a crash or power loss mid-restore could leave a system-critical file (the SSoT conf, the systemd unit) missing or truncated with no rollback. Rewritten to write to a `.sdy_restore_tmp` file and `os.replace()` it into place — atomic, and (like `backup.py`'s own archive write) `os.replace()` still sidesteps `ETXTBSY` on a currently-running binary by swapping the directory entry instead of truncating in place.
- `control_center.py`: the Global Options and Game Overrides tabs always read/wrote `~/.config/steamos_diy/...`, ignoring a customised `user_config`/`games_conf_dir` in the SSoT — `sdy.py` and `health.py` already resolved both dynamically, so a user who set either override would have the GUI "successfully" save edits to a file the session launcher never reads again, with no error surfaced. `conf_root`/`games_conf_dir` are now resolved from the SSoT the same way, via the new `_resolve_config_paths` helper.
- `control_center.py`: the Backup and Restore buttons (and journal vacuum) had no re-entrancy guard — a double-click, or Restore started while a Backup was still running, could launch two privileged `pkexec` operations writing the same files concurrently. `_run_pkexec` now tracks a `_pkexec_busy` flag and rejects a second invocation with a status-bar message until the first completes.
- `journal.py`: `_consume_export_line` parsed `__REALTIME_TIMESTAMP=` with a bare `int()`/`fromtimestamp()`, unlike every other malformed-input path in the same file (`_split_gamescope_line` already guards its parsing); a corrupted/truncated journal entry raised an uncaught `ValueError`. It now falls back to the existing "missing timestamp" path (`datetime.now()`), same as if the field were absent. Separately, `fetch_tagged_entries`/`_run_journalctl_iso` now decode `journalctl`'s output with `errors="replace"` — a `MESSAGE` field containing an embedded newline flips `journalctl -o export` to binary-safe encoding, which isn't guaranteed valid UTF-8, and `subprocess.run(text=True)` decoding that could otherwise raise `UnicodeDecodeError` — a type neither `control_center.py` `except` clause around these calls catches, leaving the Diagnostics tab stuck on "Loading logs..." indefinitely.
- `install.sh`: added `pipefail` (was plain `set -e`) and two related fixes it exposed. `USER_HOME=$(getent passwd ... | cut -d: -f6)` could silently resolve to an empty string if `getent` failed — under plain `set -e` a failing pipeline's exit status is only the *last* command's (`cut`, which "succeeds" on empty input), so the installer would carry on patching every user-space path with a missing `$HOME`; it now fails loudly with a clear error if `USER_HOME` comes back empty. Conversely, `GPU_INFO=$(lspci | grep -iE "vga|3d controller")` could abort the *entire* installer under `set -e` if `lspci`'s output didn't match either pattern (an exotic/unrecognised GPU) — now guarded with `|| true` so an unrecognised GPU degrades to the existing "skipping driver-specific packages" warning instead of a bare, unexplained installer death.
- `install.sh`: `cp -rf usr/local/lib/steamos_diy/* "$LIB_DIR/"` deployed the new `tests/` directory (added in this same release) onto every installed system — dev-only content with no business on a target machine, and `pytest` isn't a runtime dependency. Now removed with `rm -rf "$LIB_DIR/tests"` right after the copy.
- `utils.py`: `download_release()`'s nested `with urlopen(...): with tarfile.open(...):` merged into a single `with` statement (ruff SIM117); the adjacent `# nosec B310` bandit suppression was re-verified to still be attached to the right line after the merge.
- `backup.py` / `control_center.py` / `journal.py`: `datetime.now()` / `datetime.fromtimestamp()` calls now attach the local timezone via `.astimezone()` (ruff DTZ005/DTZ006) instead of building naive datetimes. Same wall-clock values as before — still local time, not switched to UTC — just with explicit tzinfo instead of implicit.
- `pyproject.toml`: the `[tool.pylint.MASTER]` `init-hook` (carried over from the now-deleted `tests/pylintrc`) had a latent bug — `os.path.dirname(__file__)` inside a pylint init-hook does not resolve to the config file's own location, it resolves to pylint's internal `config_initialization.py` module. The hook was silently inserting pylint's own package directory at the front of `sys.path`, and pylint ships its own internal `pylint/typing.py`, which shadowed the stdlib `typing` module during the production lint run — breaking `@overload` recognition in `utils.py::get_ssot_var` (spurious `E0102 function-redefined`) and, as a side effect, `NamedTuple` detection in `health.py`/`utils.py` (spurious `R0903`), dropping the score from the 10.00/10 baseline to 9.88. The bug was invisible while scoped to the old `tests/pylintrc`-only run because `import-error` is disabled there regardless, so the hook's (never-working) intended effect was never actually exercised. Re-anchored on `os.getcwd()` instead, correctly covering both documented invocations (repo root for the production run, `usr/local/lib/steamos_diy/tests` for the test run).
- `restore.py`: six call sites had been reformatted to single lines over 79 characters (an errant `ruff format` pass mid-migration — this project targets flake8's 79-char limit, not `ruff format`'s 88-char default), which flake8 flagged as `E501`. Re-wrapped to the project's existing multi-line style; no behavior change.
- `health.py`: `_check_groups` resolved every gid from `os.getgroups()` in a single set-comprehension — one stale/deleted gid (a group removed from `/etc/group` after the user's session started, e.g. by a package downgrade) raised `KeyError` and aborted the whole comprehension, falling back to an empty set. The preflight then reported every critical group (`tty`, `video`, `render`, `input`) as missing, even when the user belonged to all of them — a misleading "everything is broken" result caused by one unrelated entry. Now resolves each gid individually and skips only the one that fails.
- `control_center.py`: `load_game_file`/`save_game_profile` derived the profile filename with `raw.split(" (")[0]`, which truncates at the *first* `" ("` in the combo display string. `_format_combo_items` only ever appends the `(AppID)` suffix at the very end, so a detected game whose own name legitimately contains `" ("` (e.g. a shortcut titled "Portal (Test Build)") combined with a numeric AppID suffix silently truncated to `games.d/Portal.yaml` — colliding with, and overwriting, any unrelated game actually named "Portal". Extracted the shared `_extract_game_name_from_display` helper, anchored on the same trailing-`(digits)` regex `_scaffold_game_profile` already trusted for reading the AppID back out.
- `journal.py`: `parse_game_logs` tracked a single "current game name" reassigned on every `chdir` line regardless of which process logged it, so an interleaved `gameID`/`AppID` line from a second, concurrently-running process (e.g. two games launched close together) could get attributed to the wrong game — corrupting the AppID shown for both in the Scan History combo. Now tracks the last-seen name per source pid (parsed from journalctl's own `identifier[pid]:` line prefix) instead of one shared variable.

### Changed
- `utils.py`: added `DEFAULT_GS_BIN`, `DEFAULT_STEAM_BIN`, `DEFAULT_PLASMA_BIN`, `DEFAULT_DBUS_BIN`, and made `CORE_LIB_PATH` public — single source of truth for the session-binary fallbacks and the `libcore.so` path. Previously the four binary defaults were independently re-declared in `session_launch.py`, `session_select.py`, and twice inside `health.py` itself (once in `_BINARY_KEYS`, once inline in `_check_gamescope_flags`); `health.py` also re-derived `libcore.so`'s path from `CORE_LIB_DIR` instead of importing the one `utils.py` actually loads from. All five call sites now import from `utils.py`, so a future relocation of any of these binaries (`qdbus6` across Plasma versions is the realistic case) can't update one copy and silently miss another.
- Tool configuration (`ruff`, `pytest`, `pylint`) consolidated from `pytest.ini` + `usr/local/lib/steamos_diy/tests/pylintrc` into a single root `pyproject.toml` — one source of truth instead of three files that could silently drift apart.

---

## [2.1.6] — 2026-07-08 — Installer Permissions Fix

### Fixed
- `install.sh`: the SSoT was deployed mode `600 root:root` instead of `644` — 2.1.5 started rendering it on a `mktemp` file (created `0600`) and `cp` propagates the source mode to a newly created destination, so on a fresh install the user session could no longer read `/etc/default/steamos_diy.conf`: Control Center editing and the preflight check both failed. The SSoT, its `.new` staging copy and the pristine template are now written with `install -m 644`, and update mode additionally re-asserts `644` on the live SSoT to heal installations deployed by the 2.1.5 installer. Existing systems can be fixed immediately with `sudo chmod 644 /etc/default/steamos_diy.conf`.
- `uninstall.sh`: also removes `/etc/default/steamos_diy.conf.new` — the template staged by `install.sh --update` (introduced in 2.1.5) would otherwise survive uninstallation.

### Documentation
- README and FAQ now state explicitly what the uninstaller deliberately leaves in place (installed packages, the `[multilib]` repository, group memberships) and why — the previous "full reversibility" wording implied more than the scripts actually do.

## [2.1.5] — 2026-07-07 — In-App Updater

### Added
- **In-app updater**: the Control Center Maintenance tab gains **⬆️ Check for Updates** — it queries the GitHub Releases API (stdlib `urllib`, no new dependencies), compares against the running version and, when a newer release exists, shows the release notes and offers **Download & Install**: the tarball is unpacked into `~/.config/steamos_diy/updates/` (auto-pruned, excluded from backups) and the installer runs visibly in a Konsole window via a polkit prompt — no terminal commands to type. The Qt-side flow lives in the new `updater.py` module (`UpdateManager`), following the `editors.py`/`journal.py` isolation pattern; `utils.py` exposes the Qt-free plumbing (`VERSION`, `check_latest_release`, `download_release`). The extraction uses the tarfile `data` filter (rejects path traversal and special members) and only accepts `https://` tarball URLs.
- `install.sh --update`: non-interactive upgrade mode over an existing installation. Preserves the live SSoT (staging the new template as `steamos_diy.conf.new`, pacman-style, only when it actually changed since the last deploy — a pristine copy is kept in `/var/lib/steamos_diy/ssot.template`), preserves user YAML configs without prompting, wipes `/usr/local/lib/steamos_diy` before redeploying so files dropped by the new release cannot linger, and ends with an automatic reboot after a 10-second `CTRL+C`-abortable countdown.
- New documentation page **Updating**: both update entry points (Control Center and `install.sh --update`), what update mode preserves, and the classic uninstall+reinstall path with its SSoT caveat.

### Fixed
- `install.sh`: user detection only looked at `SUDO_USER`, so under `pkexec` (which exposes `PKEXEC_UID` instead) the "real user" resolved to root and user-space configs would be deployed to `/root`. Both are now resolved, matching `get_real_user()` in `utils.py`.
- `control_center.py`: the window title now shows the installed version.

## [2.1.4] — 2026-07-05 — Codebase Review & Hardening

### Changed
- `backup.py` / `restore.py`: the archive no longer carries executable code. Backup now embeds a plain-data links manifest (`links.txt`, one `link<TAB>target` row per symlink) instead of generating `restore_links.sh`; restore validates every pair against the same path allow-list used for file extraction (both ends must resolve inside it) and recreates the links with `os.symlink` — no shell involved. Archives from previous releases keep working: the legacy script entry is recognised and its `ln -sf` lines are parsed for the same pairs, but the script itself is never executed. This closes the inconsistency where restore carefully validated every extracted file yet ran an embedded shell script as root unvalidated.
- `restore.py`: file modes from the archive are now applied masked to `0o777`, so a crafted archive can no longer plant setuid/setgid files through a root-run restore.

### Fixed
- `health.py`: the gamescope-flags preflight treated `--flag=value` tokens as unknown flags (it compared the whole token against `gamescope --help` output); the flag part is now checked alone, so both `--nested-width 1280` and `--nested-width=1280` validate correctly.
- `control_center.py`: saving a game profile with a `/` in the name could write outside `games.d/`; the save path now applies the same guard as profile loading and reports the rejection in the status bar.
- `control_center.py`: log lines are HTML-escaped before styling, so a literal `<...>` in a journal payload is displayed instead of being swallowed as markup by the rich-text view.
- `steamos_diy_core.c`: `c_jlog` serialises the syslog tag switch with a mutex — ctypes releases the GIL during the call, so two Python threads (e.g. main + `post_start_cmds`) could interleave `closelog`/`openlog` and stamp a message with the wrong tag.
- `sdy.py`: profile lookup by AppID matched the ID as a plain substring, so looking up AppID `220` also matched a profile declaring `SDY_ID: 2201290` — another game's profile (env vars, wrapper) could be applied, with directory scan order deciding the winner. The header scan now uses an end-of-line-anchored declaration match compared for equality; quoted values, CRLF line endings, trailing whitespace and inline comments are all tolerated.
- `utils.py`: `load_yaml_safe` returned the YAML root whatever its type, so a global config whose root is a list or scalar (e.g. a file starting with `- flags:`) crashed the session launcher at boot — `cfg.get()` on a non-dict raised, systemd retried, and the loop ran until the start limit tripped (black TTY1). It now returns `{}` unless the root is a mapping, logging `YAML_NOT_MAPPING` at WARN so the degradation is visible in the journal.
- `health.py`: new preflight check **config root** — a global config that is valid YAML but has a non-mapping root previously passed the whole preflight (the syntax check saw valid YAML and the field-type check silently skipped it), so the doctor reported all-green on a config the launcher would degrade to empty. It is now reported as a failure (`must be a mapping, got <type>`). Empty documents, missing files and parse errors stay with their existing checks.
- `utils.py`: the `get_ssot_var` `@overload` stubs were separated from the implementation by the new cache helpers, tripping type checkers (overload without implementation / redefinition). Runtime was unaffected; mypy is clean again across the package.

### Performance
- `utils.py`: `get_ssot_var` now fills its cache with a single full parse of the SSoT file on first access; later lookups — including keys absent from the file — never re-read the disk (previously every miss re-scanned the whole file).
- `health.py`: the preflight parses the global config once and shares the result across the structural checks (root shape, field types, gamescope flags) instead of re-parsing it per check.

### Documentation
- `Game Wrapper (sdy).md`: AppID discovery wording aligned with the exact-match scan; `SteamMachine DIY Control Center.md`: added the **config root** row to the preflight table and the `--flag=value` note to the gamescope-flags row; `Utilities Engine.md`: documented the mapping-only contract of `load_yaml_safe`, the single-parse SSoT cache, the manifest-based backup contract (`BACKUP_MANIFEST_NAME`) and the missing `get_ssot_num` in the backup.py dependency table; `Backup & Recovery.md`: link-reconstruction and restore-security sections rewritten for the manifest model.
- Header cleanup in shipped templates: the SSoT template header now reads `SteamMachine-DIY - SSoT` (was `SteamOS-DIY - SSOTH`); `config.yaml` and the example templates drop the legacy header flavor (`Converted from Manifesto`, `Hardcore Libre Mode`, version suffixes).

---

## [2.1.3] — 2026-06-24 — Game Mode Session Capabilities

### Added
- `session_launch.py`: `GAME_MODE_ENV` — a fixed map of session environment variables applied before the user's `env_vars`, advertising compositor/Mesa capabilities to Steam so Game Mode exposes the matching Quick Access controls on any GPU. Covers FSR/NIS scaling filters (`STEAM_GAMESCOPE_FANCY_SCALING_SUPPORT`, `STEAM_GAMESCOPE_NIS_SUPPORTED`), tearing / "Disable Vertical Sync" (`STEAM_GAMESCOPE_HAS_TEARING_SUPPORT`, `STEAM_GAMESCOPE_TEARING_SUPPORTED`), the dynamic FPS limiter (`STEAM_GAMESCOPE_DYNAMIC_FPSLIMITER`), latency (`vk_xwayland_wait_ready=false`), embedded-session correctness (`SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS=0`), plus Proton/vkd3d session defaults from the official gamescope-session (`ENABLE_GAMESCOPE_WSI=1`, `VKD3D_SWAPCHAIN_LATENCY_FRAMES=3`, `WINEDLLOVERRIDES=dxgi=n`). All are panel-independent; the user's `env_vars` are applied afterwards and win. Display-dependent capabilities (VRR/HDR) deliberately stay in the user config. Mirrors the official SteamOS session.
- `session_launch.py`: `-steamdeck` added to the Steam launch flags (`-gamepadui -steamos3 -steamdeck`), unlocking the full Quick Access side menu and its live controls. Additive to `-gamepadui`, not a replacement.
- `config.yaml` (skel default): ships `--hide-cursor-delay 3000` — universal UX polish (hide the idle cursor).

### Changed
- `config.example.yaml`: documented the new model — universal capabilities are now provided automatically by the launcher (no need to set them); a per-display opt-in section shows VRR/HDR/`PROTON_ENABLE_HDR` to enable only when the panel supports it; added the `--hide-cursor-delay` UX flag.
- `docs/`: aligned *Steamos Session Launch* (capabilities table, `-steamdeck`), *Dynamic Gamescope Mapping* (env-var guidance, template) and *Project Overview* with the above. Clarified that `-F fsr` is vendor-agnostic (runs on any GPU), not AMD-only.

---

## [2.1.2] — 2026-06-22 — Control Center Health Tooling

### Added
- `health.py`: new Qt-free backend module (mirrors `journal.py` — pure functions, testable in isolation) exposing config-validation and service-status helpers.
  - `run_preflight()` returns a list of `CheckResult`s covering: SSoT config presence; binary handlers (`bin_gs`/`bin_steam`/`bin_plasma`/`bin_dbus`) resolving to executables; the declared SSoT paths (`user_config`, `games_conf_dir`) actually existing; YAML syntax of the global config and every game profile (reporting the offending line); session-critical group membership (`tty`/`video`/`render`/`input`); C-Core loadability; and a writable session-state directory.
  - It also flags the two top-level config fields the launcher iterates directly (`flags`, `post_start_cmds`) when mistyped as a scalar instead of a list — runtime would otherwise walk a string character-by-character into junk argv. Absent or null fields are correctly treated as empty and skipped. Full schema/semantic validation is deliberately out of scope (the runtime already degrades unexpected keys and bad `LOG_LEVEL`/timing values gracefully).
  - `get_service_status()` / `parse_service_status()` snapshot `steamos_diy.service` via `systemctl show` (no root) into a `ServiceStatus`, degrading missing or non-numeric fields to safe placeholders.
- `control_center.py`: **🩺 Validate Configuration** button (Maintenance tab) runs the preflight off-thread and renders a colour-coded pass/fail report (`preflight_ready` signal) — surfacing a broken config *before* it causes a black-screen boot.
- `control_center.py`: service-health strip in the window status bar — shows `steamos_diy.service` state/sub-state/restart-count/last-exit, colour-coded (green `active`, red `failed`), refreshed every 4 s by a `QTimer` fetching status off-thread (`service_status_ready` signal).
- `backup.py`: automatic archive rotation — after every successful backup, archives beyond the `BACKUP_KEEP` count (new SSoT key, default `5`; `0` disables pruning) are deleted oldest-first, so `~/.config/steamos_diy/backups/` never grows unbounded. The timestamped naming makes lexicographic order chronological and in-flight `.tmp` files are never matched. Removals are logged as `BACKUP_PRUNED`.
- `utils.py`: `clear_ssot_cache()` drops the in-process `_SSOT_CACHE` so long-lived tools (the Control Center doctor) re-validate the *current* on-disk config after an edit instead of returning cached values. `run_preflight()` calls it first, so re-running the doctor after fixing the config no longer requires restarting the Control Center.
- `health.py`: new preflight check **Gamescope flags** — validates the global-config `flags` against the installed `gamescope --help`, flagging any option the running gamescope does not recognise. An unknown or mistyped flag makes gamescope exit at launch, so the session never starts and TTY1 goes black with no hint; catching it before boot is the point. Mirrors the runtime split (`shlex.split` per entry), checks only option tokens (values and negative numbers ignored), and skips itself cleanly when `gamescope --help` can't be run.
- `control_center.py`: **log filter box** in the Diagnostics tab — a search field live-filters the displayed log to lines containing the query (case-insensitive), re-rendering from the cached fetch without re-querying journalctl. Empty query restores the normal deduplicated view; a no-match query shows a hint.
- `control_center.py`: **unsaved-changes guard** — closing the window with unedited-but-unsaved YAML now prompts Save / Discard / Cancel instead of silently dropping the edits, and **Ctrl+S** saves the editor on the active tab (Global Options or Game Overrides; ignored in template view). The editor's modified flag is cleared on load, template toggle and save, so the guard only trips on genuine pending edits.

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
- `steamos_diy_core.c`: `c_notify` clamped the `snprintf` would-be length to `sizeof(buf)` instead of `sizeof(buf) - 1`, sending the trailing NUL byte to the TTY; a negative return (encoding error) would also have reached `write()` as a huge unsigned length. Both paths are now guarded — the build is clean under `-Wall -Wextra`.
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
