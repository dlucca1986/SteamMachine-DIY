#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Uninstaller (v4.2.2 SSoT)
# Architecture: Clean Restoration & SSoT Cleanup
# =============================================================================

set -uo pipefail

# --- Environment & Colors ---
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Detection logic (SSoT)
GLOBAL_CONF="/etc/default/steamos-diy"

if [[ -f "$GLOBAL_CONF" ]]; then
    # Estraiamo l'utente reale dal Master per chiudere i servizi corretti
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
# Fermiamo e disabilitiamo i servizi principali istanziati per l'utente
systemctl stop "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl stop "steamos-desktop@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-desktop@${REAL_USER}.service" 2>/dev/null || true

# --- 2. Remove Infrastructure & Symlinks ---
info "Removing binaries, apps and symlinks..."
# Rimozione directory helpers e polkit
rm -rf "$HELPERS_DEST"
rm -rf "$POLKIT_LINKS_DIR"

# Pulizia residui vecchie versioni (Bonifica /usr/share)
rm -rf "/usr/share/steamos-diy"

# Rimozione binari diretti (v4.0.0)
rm -f "$BIN_DEST/steamos-session-launch" \
      "$BIN_DEST/steamos-session-select" \
      "$BIN_DEST/steamos-diy-control" \
      "$BIN_DEST/sdy"

# Rimozione symlink globali in /usr/bin
rm -f "/usr/bin/steamos-session-launch" \
      "/usr/bin/steamos-session-select" \
      "/usr/bin/sdy"

# Rimozione Desktop entries (tutte le .desktop del progetto)
rm -f "$APPS_DEST/steamos-diy-control.desktop" \
      "$APPS_DEST/steamos-switch-gamemode.desktop" \
      "$APPS_DEST/steamos-switch-desktop.desktop"

# --- 3. Systemd & Security Restoration ---
info "Cleaning up Systemd and Security policies..."
# Rimuove tutti i servizi steamos (sia gamemode che desktop)
rm -f "$SYSTEMD_DEST/steamos-"*@.service
# Rimuove l'autologin configurato per la TTY1
rm -rf "$SYSTEMD_DEST/getty@tty1.service.d"

# Rimozione del hook di shutdown (Splash finale)
rm -f "/usr/lib/systemd/system-shutdown/steamos-diy-final"

# Rimozione configurazioni globali e sicurezza
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
            break # Ne abilitiamo solo uno per evitare conflitti
        fi
    fi
done

# B. Personal Configuration Wipe
if [[ -d "$USER_CONF_DIR" ]]; then
    echo -e "${YELLOW}[DATA]${NC} User configs detected in $USER_CONF_DIR"
    read -p "Wipe all user settings, profiles and logs? (y/N): " wipe_choice
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

# Reset capabilities di Gamescope (ripristino stato vanilla)
if [ -x /usr/bin/gamescope ]; then
    setcap -r /usr/bin/gamescope 2>/dev/null || true
fi

echo -e "\n${GREEN}==============================================${NC}"
success "Uninstall Complete! System is now SteamOS-Free."
info "It is recommended to reboot now."
echo -e "${GREEN}==============================================${NC}"
