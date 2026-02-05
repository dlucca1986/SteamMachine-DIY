#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Uninstaller (v4.2.1 Enterprise)
# Architecture: SSoT-Compliant Cleanup & Deep System Restoration
# =============================================================================

set -uo pipefail

# --- Environment & Colors ---
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Detection logic
GLOBAL_CONF="/etc/default/steamos-diy"
SYSTEM_DEFAULTS_DIR="/usr/share/steamos-diy"

if [[ -f "$GLOBAL_CONF" ]]; then
    # Estraiamo l'utente reale per chiudere i servizi istanziati
    REAL_USER=$(grep 'export STEAMOS_USER=' "$GLOBAL_CONF" | cut -d'"' -f2)
else
    REAL_USER=${SUDO_USER:-$(whoami)}
fi

USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
USER_CONF_DIR="$USER_HOME/.config/steamos-diy"

# --- Destination Paths ---
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
POLKIT_LINKS_DIR="/usr/bin/steamos-polkit-helpers"
APPS_DEST="/usr/share/applications"
SYSTEMD_DEST="/etc/systemd/system"
SUDOERS_FILE="/etc/sudoers.d/steamos-diy"
HOOK_FILE="/etc/pacman.d/hooks/gamescope-capabilities.hook"

# --- UI Functions ---
info()    { echo -e "${CYAN}[UNINSTALL]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Root privilege check
[[ $EUID -ne 0 ]] && error "Please run as root (sudo)."

echo -e "${CYAN}==============================================${NC}"
info "Starting SteamOS-DIY Cleanup for user: $REAL_USER"
echo -e "${CYAN}==============================================${NC}"

# --- 1. Disable & Stop Services ---
info "Deactivating Systemd units..."
# Fermiamo e disabilitiamo i servizi principali
systemctl stop "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl stop "steamos-desktop@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-desktop@${REAL_USER}.service" 2>/dev/null || true

# --- 2. Remove Infrastructure & Symlinks ---
info "Removing binaries, apps and symlinks..."
rm -rf "$HELPERS_DEST"
rm -rf "$SYSTEM_DEFAULTS_DIR"
rm -rf "$POLKIT_LINKS_DIR"

# Rimozione binari diretti
rm -f "$BIN_DEST/steamos-session-launch" \
      "$BIN_DEST/steamos-session-select" \
      "$BIN_DEST/steamos-diy-control" \
      "$BIN_DEST/sdy"

# Rimozione symlink globali
rm -f "/usr/bin/steamos-session-launch" \
      "/usr/bin/steamos-session-select" \
      "/usr/bin/sdy"

# Rimozione Desktop entries
rm -f "$APPS_DEST/steamos-diy-control.desktop" \
      "$APPS_DEST/steamos-switch-gamemode.desktop"

# --- 3. Systemd & Security Restoration ---
info "Cleaning up Systemd and Security policies..."
rm -f "$SYSTEMD_DEST/steamos-"*@.service
rm -rf "$SYSTEMD_DEST/getty@tty1.service.d"
rm -f "$SUDOERS_FILE"
rm -f "$HOOK_FILE"
rm -f "$GLOBAL_CONF"

# --- 4. Restoration Choices ---
echo -e "\n${YELLOW}--- Restoration Choices ---${NC}"

# A. Display Manager Restoration
DMS=(sddm gdm lightdm lxdm)
for dm in "${DMS[@]}"; do
    if systemctl list-unit-files | grep -q "^$dm.service"; then
        echo -e "${CYAN}[DM]${NC} Found $dm installed."
        read -p "Re-enable $dm for graphical login? (y/N): " dm_choice
        if [[ "$dm_choice" =~ ^[Yy]$ ]]; then
            systemctl enable "$dm.service"
            success "$dm re-enabled. Graphical boot restored."
            break # Ne abilitiamo solo uno
        fi
    fi
done

# B. Personal Configuration Wipe
if [[ -d "$USER_CONF_DIR" ]]; then
    echo -e "${YELLOW}[DATA]${NC} User configs detected in $USER_CONF_DIR"
    read -p "Wipe all user settings and logs? (y/N): " wipe_choice
    if [[ "$wipe_choice" =~ ^[Yy]$ ]]; then
        rm -rf "$USER_CONF_DIR"
        success "User environment cleaned."
    else
        warn "User configurations preserved."
    fi
fi

# --- 5. Finalize ---
info "Finalizing system state..."
systemctl daemon-reload

# Reset capabilities (optional but clean)
if [ -x /usr/bin/gamescope ]; then
    setcap -r /usr/bin/gamescope 2>/dev/null || true
fi

echo -e "\n${GREEN}==============================================${NC}"
success "Uninstall Complete! System is now SteamOS-Free."
echo -e "${GREEN}==============================================${NC}"
