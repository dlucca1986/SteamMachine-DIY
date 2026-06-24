[![Version](https://img.shields.io/badge/Version-2.1.2-blue.svg)](https://github.com/dlucca1986/SteamMachine-DIY)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

How YAML configuration becomes Gamescope arguments: global config, per-game overrides, and templates.

---

## 🌎 Global System Config
**Path:** `~/.config/steamos_diy/config.yaml`

This file defines the system-wide environment and the default behavior of the **Gamescope** compositor. It consists of three sections: `env_vars`, `flags`, and `post_start_cmds`.

### 1. Execution Control & Environment Variables (`env_vars`)
The system manages two types of configuration inputs:

* **Execution Prefixes (`GAME_WRAPPER`)**: Defined as a string, this value is prepended to the game command (e.g., `gamemoderun` or `mangohud`). It is used by `sdy.py` to wrap the process execution.
* **Environment Variables**: Key-value pairs injected into the session environment before launch. Universal session capabilities (FSR/NIS scaling, tearing, the dynamic FPS limiter, latency tweaks) are advertised automatically by the launcher via `GAME_MODE_ENV` — you do **not** set them here. Use `env_vars` for **display-dependent** capabilities that match your hardware (e.g. `STEAM_GAMESCOPE_VRR_SUPPORTED: "1"` on a VRR panel, `STEAM_GAMESCOPE_HDR_SUPPORTED: "1"` on an HDR panel) and for your own per-session variables. See [Steamos Session Launch](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Steamos-Session-Launch) for the full capability list. **Note**: MangoHud integration in Gamescope mode requires the `--mangoapp` flag — setting `MANGOHUD=1` as an env var has no effect inside the compositor. `MANGOHUD_CONFIG` and similar variables are valid in per-game profiles where `mangohud` is used as a `GAME_WRAPPER`.

---

Per-game profiles in `games.d/` override individual keys from `config.yaml`. If a game profile defines its own `GAME_WRAPPER`, it replaces the global value for that game only. See [Game Wrapper (sdy)](https://github.com/dlucca1986/SteamMachine-DIY/wiki/Game-Wrapper-(sdy)) for the full merge and execution logic.

### 2. Gamescope Flags (`flags`)
This is a **YAML List** that defines how Gamescope should render the session.
* **Resolution**: `-W 1280` and `-H 720` (Output resolution).
* **Upscaling**: `-F fsr` (FidelityFX Super Resolution — vendor-agnostic, runs on any GPU) and `--sharpness 5`.
* **Performance**: `--rt` (Realtime scheduling) and `--immediate-flips` (Low latency/Tearing).
* **VRR / MangoHud**: `--adaptive-sync` (enables FreeSync/VRR) and `--mangoapp` (native MangoHud overlay embedded directly into the Gamescope compositor).

> [!NOTE]
> When `--mangoapp` is active, the overlay reads its configuration from `~/.config/MangoHud/presets.conf` — **not** `MangoHud.conf`, which only applies when `mangohud` is used as a per-game `GAME_WRAPPER`. Create `presets.conf` manually to customise the overlay; if you use both modes, keep the two files in sync.

#### ⚠️ Essential Syntax Rule
In YAML, parameters and values must be enclosed in the **same set of quotes** to be parsed correctly by the launcher.
* ✅ **Correct**: `- "-F fsr"`
* ❌ **Wrong**: `- -F fsr` (missing quotes), `- "-F" "fsr"` (split into two items), `- "-Ffsr"` (missing space between flag and value)

### 3. Post-Start Commands (`post_start_cmds`)
This is a **YAML List** of shell commands executed once after Gamescope has started, in a background thread. This is the correct place for runtime configuration that requires the Gamescope socket to be available — commands that cannot be passed as flags at launch time.

Each command is run via `spawn_native` (detached, fire-and-forget) after `POST_START_DELAY` seconds (configured in `steamos_diy.conf`, default: `2.0s`). The delay ensures the Gamescope socket is ready before the commands are executed. Commands are only fired for the `steam` session target, never for the Plasma desktop session.

**Typical use case — VRR stability fix with `--mangoapp`:**
When `--mangoapp` is active, the overlay surface can interfere with VRR/adaptive sync decisions. The following command tells Gamescope to ignore the overlay when evaluating VRR:
```yaml
post_start_cmds:
  - "gamescopectl adaptive_sync_ignore_overlay 1"
```

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
# Universal capabilities (FSR/NIS, tearing, FPS limiter, latency) are applied
# automatically by the launcher — only declare display-dependent ones here.
env_vars:
  # Per-display (opt-in — only if your panel supports it):
  # STEAM_GAMESCOPE_VRR_SUPPORTED: "1"   # VRR / FreeSync / G-Sync
  # STEAM_GAMESCOPE_HDR_SUPPORTED: "1"   # HDR panels (pair with --hdr-enabled)
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
  - "--fade-out-duration 200"
  - "--adaptive-sync"
  - "--mangoapp"

# --- POST-START COMMANDS ---
post_start_cmds:
  - "gamescopectl adaptive_sync_ignore_overlay 1"
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
`~/.config/steamos_diy/gamescope.example.yaml` is a read-only reference document — it is **not** loaded by the launcher. It contains the full list of available Gamescope CLI flags translated to YAML format with descriptions, organized by category (general, HDR & performance, embedded mode, VR, debug, shaders, keyboard shortcuts).

---

## 🚀 Dynamic Argument Mapping (DGM)
The **DGM** engine maps **YAML** flags directly to the gamescope command line. This allows the system to support new Gamescope features without core script modifications.

* **Find a new flag**: Check `gamescope --help` or consult `~/.config/steamos_diy/gamescope.example.yaml` for the full categorized reference.

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
