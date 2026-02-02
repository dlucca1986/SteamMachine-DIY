#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Uninstaller
# Architecture: Systemd-Agnostic / Zero-DM Cleanup
# =============================================================================

set -eou pipefail

# --- Environment & Colors ---
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Rilevamento utente dalla config globale
GLOBAL_CONF="/etc/default/steamos-diy"
if [[ -f "$GLOBAL_CONF" ]]; then
    source "$GLOBAL_CONF"
    REAL_USER="$STEAMOS_USER"
else
    REAL_USER=${SUDO_USER:-$(whoami)}
fi
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# --- Paths ---
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
POLKIT_LINKS_DIR="/usr/bin/steamos-polkit-helpers"
SYSTEMD_DEST="/etc/systemd/system"
SUDOERS_FILE="/etc/sudoers.d/steamos-diy"
APP_ENTRIES="/usr/local/share/applications"
HOOK_FILE="/etc/pacman.d/hooks/gamescope-capabilities.hook"
LOG_FILE="/var/log/steamos-diy.log"
CONFIG_DIR="$USER_HOME/.config/steamos-diy"

info()    { echo -e "${CYAN}[UNINSTALL]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }

[[ $EUID -ne 0 ]] && echo "Please run as root (sudo)." && exit 1

# --- 1. Disable Services ---
info "Stopping and disabling systemd units..."
systemctl stop "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-desktop@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-exit-splash.service" 2>/dev/null || true

# --- 2. File Cleanup ---
info "Removing binaries, services and configurations..."
rm -rf "$HELPERS_DEST"
rm -f "$BIN_DEST/steamos-session-launch" "$BIN_DEST/steamos-session-select" \
      "$BIN_DEST/steamos-diy-control" "$BIN_DEST/sdy"

rm -f "$SYSTEMD_DEST/steamos-"*@.service
rm -f "$SYSTEMD_DEST/steamos-exit-splash.service"
rm -rf "$SYSTEMD_DEST/getty@tty1.service.d"

rm -f "$SUDOERS_FILE" "$HOOK_FILE" "$GLOBAL_CONF" "$LOG_FILE"
rm -f "$APP_ENTRIES/steamos-diy-control.desktop" \
      "$APP_ENTRIES/steamos-switch-gamemode.desktop"

# --- 3. Symlinks Cleanup ---
info "Removing compatibility symlinks..."
rm -f "/usr/bin/steamos-session-launch" "/usr/bin/steamos-session-select" \
      "/usr/bin/steamos-select-branch" "/usr/bin/steamos-set-timezone" \
      "/usr/bin/steamos-update"
rm -rf "$POLKIT_LINKS_DIR"

# --- 4. Interactive Restoration & Data Wipe ---
info "Restoring gamescope capabilities..."
[[ -x /usr/bin/gamescope ]] && setcap -r /usr/bin/gamescope 2>/dev/null || true

echo -e "\n${YELLOW}--- Final System Choices ---${NC}"

# Choice A: Display Manager
if systemctl list-unit-files | grep -q sddm.service; then
    read -p "SDDM detected. Re-enable it for graphical login? (y/N): " dm_choice
    if [[ "$dm_choice" =~ ^[Yy]$ ]]; then
        systemctl enable sddm.service
        success "SDDM re-enabled."
    fi
fi

# Choice B: Configuration Wipe
if [[ -d "$CONFIG_DIR" ]]; then
    read -p "Remove user game configurations in $CONFIG_DIR? (y/N): " wipe_choice
    if [[ "$wipe_choice" =~ ^[Yy]$ ]]; then
        rm -rf "$CONFIG_DIR"
        success "User configurations removed."
    else
        warn "User configurations preserved at $CONFIG_DIR."
    fi
fi

# --- 5. Finalize ---
systemctl daemon-reload
echo -e "\n${GREEN}Cleanup complete! System restored.${NC}"
