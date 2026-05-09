#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      1.3.4 - Precision Cleanup
# DESCRIPTION:  Interactive removal of DIY components and system restoration.
# PHILOSOPHY:   Ensures system accessibility and clean symlink removal.
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
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

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./uninstall.sh)"
    exit 1
fi

REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

info "Starting uninstallation for user: $REAL_USER"

# --- 1. Service & Getty Restoration (Anti-Lockdown) ---
cleanup_services() {
    info "Disarming DIY services and restoring Getty access..."

    if systemctl is-enabled steamos_diy.service &>/dev/null; then
        systemctl disable steamos_diy.service || true
    fi

    # Remove unit files
    rm -f /etc/systemd/system/steamos_diy.service
    
    # CRITICAL: Restore TTY1 Getty immediately
    info "Unmasking Getty on TTY1 (Emergency Access)..."
    systemctl unmask getty@tty1.service
    systemctl enable getty@tty1.service || true

    systemctl daemon-reload
}

# --- 2. Restore Display Manager & Target ---
restore_display_manager() {
    echo -e "${YELLOW}>>> Do you want to re-enable a standard Display Manager (KDE/SDDM/GDM)? (y/n)${NC}"
    read -r -p "> " confirm_dm
    if [[ "$confirm_dm" =~ ^[Yy]$ ]]; then
        # Check for Plasmalogin (Plasma 6), SDDM, or GDM
        if systemctl list-unit-files | grep -q "plasmalogin.service"; then
            systemctl enable plasmalogin.service
            success "Plasma Login Manager re-enabled."
        elif systemctl list-unit-files | grep -q "sddm.service"; then
            systemctl enable sddm.service
            success "SDDM re-enabled."
        elif systemctl list-unit-files | grep -q "gdm.service"; then
            systemctl enable gdm.service
            success "GDM re-enabled."
        fi
        systemctl set-default graphical.target || true
    else
        warn "Restoring system to default CLI (multi-user.target)..."
        systemctl set-default multi-user.target || true
    fi
}

# --- 3. Remove Shim Links (Speculated to Installer 1.3.2) ---
remove_shim_links() {
    info "Removing SteamOS compatibility shim layer..."

    # 1. Polkit Helpers Directory
    rm -rf /usr/bin/steamos-polkit-helpers

    # 2. Global Binaries (Specularity with Installer)
    rm -f /usr/bin/steamos-session-launch
    rm -f /usr/bin/steamos-session-select
    rm -f /usr/bin/steamos-select-branch
    rm -f /usr/bin/jupiter-biosupdate
    rm -f /usr/bin/steamos-update
    rm -f /usr/bin/steamos-set-timezone

    # 3. User CLI Tools (In /usr/local/bin as per standards)
    rm -f /usr/local/bin/sdy
    rm -f /usr/local/bin/sdy-control-center
    rm -f /usr/local/bin/sdy-backup
    rm -f /usr/local/bin/sdy-restore
    
    success "Symlinks cleaned."
}

# --- 4. Remove System Files ---
remove_files() {
    info "Removing DIY libraries and system configurations..."
    
    rm -rf /usr/local/lib/steamos_diy
    rm -rf /var/lib/steamos_diy
    rm -f /etc/default/steamos_diy.conf
    
    # Desktop entries and ALPM hooks
    rm -f /usr/local/share/applications/Control_Center.desktop
    rm -f /usr/local/share/applications/Game_Mode.desktop
    rm -f /usr/share/libalpm/hooks/gamescope-privs.hook

    # Reset capabilities for gamescope
    if [ -x /usr/bin/gamescope ]; then
        info "Resetting gamescope binary capabilities..."
        setcap -r /usr/bin/gamescope 2>/dev/null || true
    fi

    # Optional: Remove multilib from pacman.conf
    if grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "${YELLOW}>>> Remove [multilib] from /etc/pacman.conf? (y/n)${NC}"
        read -r -p "> " confirm_ml
        if [[ "$confirm_ml" =~ ^[Yy]$ ]]; then
            sed -i '/^\[multilib\]/,/^Include = \/etc\/pacman.d\/mirrorlist$/d' /etc/pacman.conf
            info "Multilib removed from pacman.conf."
        fi
    fi

    # Optional Wipe of User Configurations
    echo -e "${RED}>>> Delete user configurations in $USER_HOME/.config/steamos_diy? (y/n)${NC}"
    read -r -p "> " confirm_wipe
    if [[ "$confirm_wipe" =~ ^[Yy]$ ]]; then
        rm -rf "$USER_HOME/.config/steamos_diy"
        info "User configurations deleted."
    fi
}

# --- 5. Finalize Session ---
finalize_session() {
    if systemctl is-active steamos_diy.service &>/dev/null; then
        warn "Active DIY session detected. Terminating in 3 seconds..."
        ( sleep 3; systemctl stop steamos_diy.service ) & 
    fi
}

# --- Execution Flow ---
cleanup_services
restore_display_manager
remove_shim_links
remove_files

success "UNINSTALLATION COMPLETED!"
info "System restored. TTY1 Getty is now active."

finalize_session

echo -e "${CYAN}>>> Reboot now to apply all changes? (y/n)${NC}"
read -r -p "> " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
