#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      1.5.0 - Full Cleanup (Icons & Hooks)
# DESCRIPTION:  Interactive removal of DIY components and target cleanup.
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

# --- 1. Service & Target Cleanup ---
cleanup_services() {
    info "Cleaning up services and restoring targets..."

    if systemctl is-enabled steamos_diy.service &>/dev/null; then
        systemctl disable steamos_diy.service || true
    fi

    # Remove "Hard Lock" link
    if [ -L /etc/systemd/system/graphical.target.wants/steamos_diy.service ]; then
        info "Removing manual graphical.target link..."
        rm -f /etc/systemd/system/graphical.target.wants/steamos_diy.service
    fi

    if [ -f /etc/systemd/system/steamos_diy.service ]; then
        rm -f /etc/systemd/system/steamos_diy.service
    fi

    systemctl daemon-reload
}

# --- 2. Restore Display Manager & Target ---
restore_display_manager() {
    echo -e "${YELLOW}>>> Do you want to re-enable a standard Display Manager (SDDM/GDM)? (y/n)${NC}"
    read -r -p "> " confirm_dm
    if [[ "$confirm_dm" =~ ^[Yy]$ ]]; then
        if systemctl list-unit-files | grep -q "sddm.service"; then
            systemctl enable sddm.service
            success "SDDM re-enabled."
        elif systemctl list-unit-files | grep -q "gdm.service"; then
            systemctl enable gdm.service
            success "GDM re-enabled."
        fi
        systemctl set-default graphical.target || true
    else
        warn "Restoring system to CLI (multi-user.target)..."
        systemctl set-default multi-user.target || true
    fi
}

# --- 3. Remove Shim Links ---
remove_shim_links() {
    info "Removing all 15 shim layer symlinks..."

    # 3.1 Polkit Helpers
    rm -f /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    rm -f /usr/bin/steamos-polkit-helpers/steamos-update
    rm -f /usr/bin/steamos-polkit-helpers/steamos-set-timezone
    rm -f /usr/bin/steamos-polkit-helpers/jupiter-dock-updater
    [ -d /usr/bin/steamos-polkit-helpers ] && rmdir /usr/bin/steamos-polkit-helpers 2>/dev/null || true

    # 3.2 Core Session Binaries
    rm -f /usr/bin/steamos-session-launch
    rm -f /usr/bin/steamos-session-select
    rm -f /usr/bin/sdy

    # 3.3 DIY Tools
    rm -f /usr/bin/sdy-backup
    rm -f /usr/bin/sdy-restore
    rm -f /usr/local/bin/sdy
    rm -f /usr/local/bin/sdy-control-center

    # 3.4 Compatibility Helpers
    rm -f /usr/bin/jupiter-biosupdate
    rm -f /usr/bin/steamos-select-branch
    rm -f /usr/bin/steamos-update
}

# --- 4. Remove Files, Library, Icons & Hooks ---
remove_files() {
    info "Removing DIY system files..."
    rm -rf /usr/local/lib/steamos_diy
    rm -rf /var/lib/steamos_diy
    rm -f /etc/default/steamos_diy.conf

    # --- Cleanup Icons ---
    info "Removing desktop menu entries..."
    rm -f /usr/local/share/applications/Control_Center.desktop
    rm -f /usr/local/share/applications/Game_Mode.desktop

    # --- Cleanup Hooks ---
    info "Removing Pacman hooks..."
    rm -f /usr/share/libalpm/hooks/gamescope-privs.hook

    # Optional: Reset gamescope caps (safer to leave them, but for a "pure" uninstall...)
    if [ -f /usr/bin/gamescope ]; then
        info "Dropping gamescope capabilities..."
        setcap -r /usr/bin/gamescope 2>/dev/null || true
    fi

    echo -e "${RED}>>> Do you want to DELETE user configurations in $USER_HOME/.config/steamos_diy? (y/n)${NC}"
    read -r -p "> " confirm_wipe
    if [[ "$confirm_wipe" =~ ^[Yy]$ ]]; then
        info "Wiping user configuration directory..."
        rm -rf "$USER_HOME/.config/steamos_diy"
    fi
}

# --- Execution Flow ---
cleanup_services
restore_display_manager
remove_shim_links
remove_files

success "UNINSTALLATION COMPLETED!"
info "System target, links, and hooks restored."

echo -e "${CYAN}>>> Reboot now? (y/n)${NC}"
read -r -p "> " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
