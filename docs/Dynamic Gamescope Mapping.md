[![Version](https://img.shields.io/badge/Version-2.1.9-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

How YAML configuration becomes Gamescope arguments: global config, per-game overrides, and templates.

---

## 🌎 Global System Config
**Path:** `~/.config/steamos_diy/config.yaml`

This file defines the system-wide environment and the default behavior of the **Gamescope** compositor. It consists of two sections: `env_vars` and `flags`.

### 1. Execution Control & Environment Variables (`env_vars`)
The system manages two types of configuration inputs:

* **Execution Prefixes (`GAME_WRAPPER`)**: Defined as a string, this value is prepended to the game command (e.g., `gamemoderun` or `mangohud`). It is used by `sdy.py` to wrap the process execution.
* **Environment Variables**: Key-value pairs injected into the session environment before launch. gamescope itself tells Steam what the session supports (scaling filters, tearing, FPS limiter, VRR, HDR), so there is nothing to declare for that; use `env_vars` for your own variables. See [Steamos Session Launch](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Steamos-Session-Launch) for the few the launcher adds. **Note**: for the overlay in Game Mode use the `--mangoapp` flag; its level is then set from Steam's Quick Access menu (Performance). `MANGOHUD_CONFIG` and similar variables apply in per-game profiles that use `mangohud` as `GAME_WRAPPER`.

---

Per-game profiles in `games.d/` override individual keys from `config.yaml`. If a game profile defines its own `GAME_WRAPPER`, it replaces the global value for that game only. See [Game Wrapper (sdy)](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Game-Wrapper-(sdy)) for the full merge and execution logic.

### 2. Gamescope Flags (`flags`)
This is a **YAML List** that defines how Gamescope should render the session.
* **Resolution**: `-W 1280` and `-H 720` (Output resolution).
* **Upscaling**: `-F fsr` (FidelityFX Super Resolution) and `--sharpness 5` (0 = sharpest, 20 = softest).
* **Scheduling / flips**: `--rt` (realtime scheduling) and `--immediate-flips` (immediate flips, may tear).
* **VRR / MangoHud**: `--adaptive-sync` (adaptive sync / VRR, if available) and `--mangoapp` (gamescope starts MangoHud's `mangoapp` overlay itself; its help says to use this instead of running `mangohud` on gamescope or the game).

> [!NOTE]
> `--mangoapp` uses MangoHud's own files: `~/.config/MangoHud/MangoHud.conf` (which has a "mangoapp" section) and `presets.conf` (see `/usr/share/doc/mangohud/` for both examples).

#### ⚠️ Syntax
Each list item is split like a shell command line and the pieces are passed to gamescope in order. Writing a flag and its value in one item (`- "-F fsr"`) is the clearest form, but `- -F fsr` (no quotes), `- "-Ffsr"`, `- "--sharpness=5"` and `"-F"`/`"fsr"` as two separate items work too.

What actually breaks:
* ❌ `- "-F" "fsr"` — two quoted strings in one item is invalid YAML: the **whole file** is ignored (no flags or `env_vars`), logged as `YAML_PARSE_ERROR`.
* ❌ A TAB used for indentation — also invalid YAML, same result.
* ❌ A misspelled flag (`--hide-cursor-dealy 3000`) — gamescope refuses to start and the session falls back to Desktop.
* ❌ `flags: "-W 1280 -H 720"` — a string instead of a list: all flags are ignored.

**Maintenance → Validate Configuration** in the Control Center reports all four.

---

## 🎮 Per-Game Overrides (`sdy`)
**Path:** `~/.config/steamos_diy/games.d/[AnyName].yaml`

The global config sets up Gamescope; `sdy.py` handles each game's own launch. Profiles are matched by scanning file content for `SDY_ID:` or `STEAM_APPID:`, so the filename is irrelevant. If no ID matches, `sdy` searches by executable name or parent directory name. Any `env_vars` key defined here overwrites the corresponding key from `config.yaml` for this game only.

---

## 📝 Configuration Templates

### Global Config Reference (`config.example.yaml`)
```yaml
# --- GLOBAL ENVIRONMENT VARIABLES ---
env_vars:
  GAME_WRAPPER: "gamemoderun"
  GAME_EXTRA_ARGS: ""

# --- GLOBAL GAMESCOPE FLAGS ---
flags:
  - "-W 1280"
  - "-H 720"
  - "-r 60"
  - "-F fsr"
  - "--sharpness 5"
  - "--rt"
  - "--immediate-flips"
  - "--hide-cursor-delay 3000"
  - "--xwayland-count 2"
  - "--adaptive-sync"
  - "--mangoapp"
```

### Game Profile Template (`game.example.yaml`)
```yaml
# Identification (Used by sdy.py to match the game automatically)
SDY_ID: 1091500
STEAM_APPID: "1091500"

GAME_WRAPPER: "mangohud gamemoderun"
GAME_EXTRA_ARGS: ""

env_vars:
  PROTON_USE_WINED3D: "1"
  DXVK_HUD: "fps"
  MANGOHUD_CONFIG: "cpu_temp,gpu_temp,fps"
```

### Gamescope Flags Reference (`gamescope.example.yaml`)
`~/.config/steamos_diy/gamescope.example.yaml` is a reference document — it is **not** loaded by the launcher. It lists every long option of `gamescope --help` (checked against gamescope 3.17.0) in YAML form with a description, by category (general, HDR & performance, nested mode, embedded mode, VR, debug, shaders, keyboard shortcuts). A newer gamescope may add options: `gamescope --help` is the reference.

> [!WARNING]
> The Control Center's file selector lists it alongside `config.yaml` and `config.example.yaml`, and Save is **not** disabled while it's open (only entering **View Template** mode disables Save). If you open this file directly from the combo and press Ctrl+S, you will overwrite your own reference copy. Use **View Template** to browse it safely, or edit it outside the Control Center.

---

## 🚀 Dynamic Argument Mapping (DGM)
The launcher passes the `flags` list to gamescope as it is, so any option your gamescope version accepts can be used without a code change.

* **Find a new flag**: Check `gamescope --help` or consult `~/.config/steamos_diy/gamescope.example.yaml` for the full categorized reference.

* **Add it**: add a line to the `flags:` list in `config.yaml`.

* **Deploy**: The launcher applies the updated arguments on the next session start.

---

> [!TIP]
> These files can be edited from the Control Center. See:
>
> 🔍 **[SteamMachine-DIY Control Center Guide](https://github.com/dlucca1986/SteamMachine-DIY/wiki/SteamMachine-DIY-Control-Center)**.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
