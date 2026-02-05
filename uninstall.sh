#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Uninstaller (v4.0.0 Enterprise)
# Architecture: SSoT-Compliant Cleanup
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
    # Estraiamo l'utente direttamente senza caricare tutto il file
    REAL_USER=$(grep 'export STEAMOS_USER=' "$GLOBAL_CONF" | cut -d'"' -f2)
else
    REAL_USER=${SUDO_USER:-$(whoami)}
fi

USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
USER_CONF_DIR="$USER_HOME/.config/steamos-diy"

# --- Destination Paths ---
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
SYSTEMD_DEST="/etc/systemd/system"
SUDOERS_FILE="/etc/sudoers.d/steamos-diy"

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

# --- 1. Disable Services ---
info "Stopping and disabling systemd units..."
# Disabilita servizi istanziati
systemctl stop "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
systemctl stop "steamos-session-launch@${REAL_USER}.service" 2>/dev/null || true
systemctl disable "steamos-session-launch@${REAL_USER}.service" 2>/dev/null || true

# --- 2. Remove Core Infrastructure ---
info "Removing binaries and system defaults..."
rm -rf "$HELPERS_DEST"
rm -rf "$SYSTEM_DEFAULTS_DIR"
rm -f "$BIN_DEST/steamos-session-launch" \
      "$BIN_DEST/steamos-session-select" \
      "$BIN_DEST/steamos-diy-control" \
      "$BIN_DEST/sdy"

# --- 3. Systemd & Autologin Cleanup ---
info "Restoring Systemd configuration..."
rm -f "$SYSTEMD_DEST/steamos-"*@.service
rm -rf "$SYSTEMD_DEST/getty@tty1.service.d"

# --- 4. Security & Config Cleanup ---
info "Removing global configurations..."
rm -f "$SUDOERS_FILE"
rm -f "$GLOBAL_CONF"

# --- 5. Restoration Choices ---
echo -e "\n${YELLOW}--- Restoration Choices ---${NC}"

# A. Display Manager Restoration
# Cerchiamo DM installati per suggerire il ripristino
for dm in sddm gdm lightdm; do
    if systemctl list-unit-files | grep -q "^$dm.service"; then
        read -p "$dm detected. Re-enable it for graphical login? (y/N): " dm_choice
        if [[ "$dm_choice" =~ ^[Yy]$ ]]; then
            systemctl enable "$dm.service"
            success "$dm re-enabled."
        fi
        break # Ne abilitiamo solo uno
    fi
done

# B. Personal Configuration Wipe
if [[ -d "$USER_CONF_DIR" ]]; then
    read -p "Remove user configs and logs in $USER_CONF_DIR? (y/N): " wipe_choice
    if [[ "$wipe_choice" =~ ^[Yy]$ ]]; then
        rm -rf "$USER_CONF_DIR"
        success "User environment wiped."
    else
        warn "User configurations preserved."
    fi
fi

# --- 6. Finalize ---
systemctl daemon-reload
echo -e "\n${GREEN}Cleanup complete! System restored.${NC}"
