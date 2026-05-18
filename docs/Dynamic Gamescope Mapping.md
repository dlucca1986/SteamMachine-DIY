[![Version](https://img.shields.io/badge/Version-2.0.0-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Configuration](https://img.shields.io/badge/Logic-Dynamic%20YAML-blue.svg)](#)
[![Engine](https://img.shields.io/badge/Engine-DGM%20Injection-orange.svg)](#)

This page outlines the configuration system for managing global settings and per-game profiles via YAML.

---

## 🌎 Global System Config
**Path:** `~/.config/steamos_diy/config.yaml`

This file defines the system-wide environment and the default behavior of the **Gamescope** compositor. It consists of two main sections: `env_vars` and `flags`.

### 1. Execution Control & Environment Variables (`env_vars`)
The system manages two types of configuration inputs:

* **Execution Prefixes (`GAME_WRAPPER`)**: Defined as a string, this value is prepended to the game command (e.g., `gamemoderun` or `mangohud`). It is used by `sdy.py` to wrap the process execution.
* **Environment Variables**: Key-value pairs (like `DXVK_HUD` or `MANGOHUD_CONFIG`) injected directly into the process environment before launch.

---

Per-game profiles in `games.d/` override individual keys from `config.yaml`. If a game profile defines its own `GAME_WRAPPER`, it replaces the global value for that game only. See [Game Wrapper (sdy)](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Game-Wrapper-(sdy)) for the full merge and execution logic.

### 2. Gamescope Flags (`flags`)
This is a **YAML List** that defines how Gamescope should render the session.
* **Resolution**: `-W 1280` and `-H 720` (Output resolution).
* **Upscaling**: `-F fsr` (AMD FidelityFX) and `--sharpness 5`.
* **Performance**: `--rt` (Realtime scheduling) and `--immediate-flips` (Low latency/Tearing).

#### ⚠️ Essential Syntax Rule
In YAML, parameters and values must be enclosed in the **same set of quotes** to be parsed correctly by the launcher.
* ✅ **Correct**: `- "-F fsr"`
* ❌ **Wrong**: `- -F fsr` (missing quotes), `- "-F" "fsr"` (split into two items), `- "-Ffsr"` (missing space between flag and value)

---

## 🎮 Per-Game Overrides (`sdy`)
**Path:** `~/.config/steamos_diy/games.d/[AnyName].yaml`

While the Global Config handles the "window" (Gamescope), `sdy.py` handles the **individual game execution**. The system identifies the correct profile by scanning the **content** of the files for a matching ID, ensuring that logic remains consistent even if files are renamed.


Profiles are matched by scanning file content for `SDY_ID:` or `STEAM_APPID:`, so the filename is irrelevant. If no ID matches, `sdy` searches by executable name or parent directory name. Any `env_vars` key defined here overwrites the corresponding key from `config.yaml` for this game only.

---

## 📝 Configuration Templates

### Global Config Reference (`config.example.yaml`)
```yaml
# --- GLOBAL ENVIRONMENT VARIABLES ---
env_vars:
  STEAM_GAMESCOPE_VRR_SUPPORTED: "1"
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

## 🚀 Dynamic Argument Mapping (DGM)
The **DGM** engine maps **YAML** flags directly to the gamescope command line. This allows the system to support new `Gamescope`features without core script modifications.

* **Find a new flag**: Check `gamescope --help` for new features or the provided `gamescope.example`

* **Add it**: Simply add a new line to your `flags`: list in `config.yaml`.

* **Deploy**: The launcher applies the updated arguments on the next session start.

---

> [!TIP]
> **Don't struggle with manual file paths!**
> All configuration templates and active files are centrally managed within the GUI. For a full walkthrough on how to use the editor, check out the:
>
> 🔍 **[SteamMachine-DIY Control Center Guide](https://github.com/dlucca1986/SteamMachine-DIY/wiki/SteamMachine-DIY-Control-Center)**.

---
**[⬅️ Back to Home](https://github.com/dlucca1986/SteamMachine-DIY/wiki)**.
