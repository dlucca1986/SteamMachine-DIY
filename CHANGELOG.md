# Changelog

## [Unreleased] — 2026-05-10

### Added
- `steamos_diy_core.c` — sorgente C di `libcore.so` aggiunto al repo (precedentemente solo binario pre-compilato)
- `Makefile` con target `all`, `install`, `clean` per compilare `libcore.so` da sorgente
- `CLAUDE.md` con documentazione architettura, comandi e gotchas per Claude Code
- `CHANGELOG.md` (questo file)

### Fixed
**`steamos_diy_core.c`**
- `c_spawn_detached`: restituiva `0/1` (bool) invece del PID reale del processo figlio
- `c_monitor_process`: sostituito `waitpid` con polling `/proc/<pid>` per evitare conflitti con `subprocess` di Python
- `c_sd_notify_ready`: aggiunta gestione socket astratti systemd (prefisso `@` → `\0` in `sun_path`)
- Rimosso `#include <sys/wait.h>` non più necessario

**`install.sh`**
- `libcore.so` ora compilato da sorgente durante l'installazione invece di essere copiato da un binario pre-compilato; aggiunto `gcc` alle dipendenze

**`uninstall.sh`**
- Aggiunta rimozione interattiva della sezione `[multilib]` da `/etc/pacman.conf` (in precedenza `install.sh` la aggiungeva ma `uninstall.sh` non la rimuoveva)

**`backup.py` / `restore.py`**
- `load_ssot()` il cui valore di ritorno veniva ignorato: il backup/restore procedeva silenziosamente anche senza config SSoT; aggiunto controllo esplicito con `sys.exit(1)`

**`restore.py`**
- `tar.getmember()` solleva `KeyError` e non restituisce mai `None`: rimosso check `if member is None` (dead code), sostituito con `try/except KeyError`

**`utils.py`**
- Corretto docstring di `spawn_native`: `args` include `argv[0]` (comportamento standard `execv`), non lo esclude
