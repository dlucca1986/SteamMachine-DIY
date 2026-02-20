#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      1.1.0
# DESCRIPTION:  Interactive removal of DIY components and system restoration.
# =============================================================================

set -e

# --- Colors & UI ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./uninstall.sh)"
    exit 1
fi

REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

info "Starting uninstallation for user: $REAL_USER"

# --- 1. Service Cleanup ---
cleanup_services() {
    info "Stopping and disabling SteamMachine-DIY service..."
    systemctl stop steamos_diy.service || warn "Service already stopped."
    systemctl disable steamos_diy.service || warn "Service already disabled."
    rm -f /etc/systemd/system/steamos_diy.service
    systemctl daemon-reload
}

# --- 2. Restore Display Manager (Interactive) ---
restore_display_manager() {
    echo -e "${YELLOW}>>> Do you want to re-enable a standard Display Manager (SDDM/GDM)? (y/n)${NC}"
    read -r -p "> " confirm_dm
    if [[ "$confirm_dm" =~ ^[Yy]$ ]]; then
        if systemctl list-unit-files | grep -q "sddm.service"; then
            info "Re-enabling SDDM..."
            systemctl enable sddm.service
        elif systemctl list-unit-files | grep -q "gdm.service"; then
            info "Re-enabling GDM..."
            systemctl enable gdm.service
        else
            warn "No common Display Manager (SDDM/GDM) found installed."
        fi
    else
        info "Skipping Display Manager restoration."
    fi
}

# --- 3. Remove Files & Library ---
remove_files() {
    info "Removing DIY system files..."
    
    # Remove System Library & State
    rm -rf /usr/local/lib/steamos_diy
    rm -rf /var/lib/steamos_diy
    
    # Remove Desktop Entries & Icons
    info "Cleaning up application shortcuts and icons..."
    rm -f /usr/local/share/applications/sdy-*.desktop
    # If you have specific icons in /usr/share/icons, add them here
    
    # Remove SSoT Config
    rm -f /etc/default/steamos_diy.conf

    # Interactive User Config Wipe
    echo -e "${RED}>>> Do you want to DELETE user configurations in $USER_HOME/.config/steamos_diy? (y/n)${NC}"
    read -r -p "> " confirm_wipe
    if [[ "$confirm_wipe" =~ ^[Yy]$ ]]; then
        info "Wiping user configuration directory..."
        rm -rf "$USER_HOME/.config/steamos_diy"
    else
        info "Keeping user configuration directory."
    fi
}

# --- 4. Remove Shim Layer ---
remove_shim_links() {
    info "Removing shim layer symlinks..."
    rm -f /usr/bin/steamos-session-launch
    rm -f /usr/bin/steamos-session-select
    rm -f /usr/bin/sdy
    rm -f /usr/local/bin/sdy-control-center
    rm -rf /usr/bin/steamos-polkit-helpers
}

# --- Execution Flow ---
cleanup_services
restore_display_manager
remove_shim_links
remove_files

# --- Finalize & Reboot ---
success "UNINSTALLATION FINISHED!"

echo -e "${CYAN}>>> Do you want to REBOOT now? (y/n)${NC}"
read -r -p "> " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    info "Rebooting system..."
    reboot
else
    info "Uninstallation complete. Please remember to reboot later."
fi
