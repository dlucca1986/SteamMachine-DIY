[![Version](https://img.shields.io/badge/Version-2.1.3-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

How `sdy` finds the right profile and launches the game.

---

## 🧠 Discovery Logic
When `sdy %command%` is executed, the script performs a hierarchical lookup for a configuration profile in `~/.config/steamos_diy/games.d/` (first hit wins):

1. **Steam AppID**: If the `SteamAppId` environment variable is set, each YAML file's first 1024 bytes are scanned for a `STEAM_APPID: <id>` or `SDY_ID: <id>` declaration line. The declared ID must match **exactly** (searching `220` never hits `2201290`); quoted values and inline comments are tolerated.
2. **Effective name**: If no ID match is found, `sdy` derives a lookup key from the executable path. If the executable stem is a generic word (`start`, `run`, `launcher`, `launch`, `game`, `main`), the parent directory name is used instead. Then `<games.d>/<eff_name>.yaml` is checked.
3. **Raw stem fallback**: If the effective-name file is absent, `<games.d>/<stem>.yaml` is tried as a last resort.

---

## 🛠️ Configuration Hierarchy
`sdy.py` merges configurations in two layers (higher number wins):

1. **Global User Config**: `~/.config/steamos_diy/config.yaml` — `env_vars` applied first; `GAME_WRAPPER` / `GAME_EXTRA_ARGS` used as fallback when the profile does not define them.
2. **Game-Specific Profile**: `.yaml` file found in `games.d/` — `env_vars` applied on top of globals; `GAME_WRAPPER` / `GAME_EXTRA_ARGS` override the global values when present.

### Mapping Table
| Key | Type | Description |
| :--- | :--- | :--- |
| `GAME_WRAPPER` | Execution Prefix | Prepended to the command (e.g., `gamemoderun`). |
| `GAME_EXTRA_ARGS` | Flags | Appended to the end of the command. |
| `env_vars` | Dictionary | Environment variables injected into the process. |

---

## 🔄 Process Replacement
To maintain a clean process tree, `sdy` uses `os.execvpe`. The launcher process is replaced by the game process, ensuring that the `GAME_WRAPPER` becomes the direct parent of the game.

```python
# Construction of the final command list
full_cmd = shlex.split(wrapper) if wrapper else []
full_cmd.extend(raw_args)
if extra:
    full_cmd.extend(shlex.split(extra))

# Replace this process with the game
os.execvpe(full_cmd[0], full_cmd, os.environ)
```

**YAML Resilience**: If a profile YAML is missing or unparseable, `load_yaml_safe` returns `{}` silently. The game still launches using only the global `config.yaml` values — no error is raised and no message is logged.

---

## 🛠️ Usage in Steam
To enable the wrapper for any game:

* Right-click the game in Steam ➔ **Properties**.

* In **Launch Options**, paste:

   ```bash
   sdy %command%
   ```
---

## 📊 Logging Output

To verify if `sdy` has correctly identified your game and applied the right config, check the centralized log via the **Control Center** or the system journal.

| Log message | Level | Description |
| :--- | :--- | :--- |
| `GAME_LAUNCH: <stem> (AppID: <id>)` | INFO | Emitted just before `os.execvpe`; confirms the resolved stem and AppID. |
| `EXECUTION_FAILED: <err>` | ERROR | Binary not found or `execvpe` failed; process exits with code 1. |
| `SCAN_ERROR: <dir> - <err>` | DEBUG | `games.d/` directory could not be scanned (e.g. missing directory). |

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
