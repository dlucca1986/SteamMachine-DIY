#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      1.3.5 - Atomic Restoration
# DESCRIPTION:  Interactive removal of DIY components and system restoration.
# PHILOSOPHY:   Aggressive VT takeover to prevent black screens and lockups.
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# PATH:         /usr/local/lib/steamos_diy/uninstall.sh
# LICENSE:      MIT
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

# --- Root & Environment Check ---
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./uninstall.sh)"
    exit 1
fi

REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# --- Cgroup Escape (Survival Mechanism) ---
# Prevents the script from being killed when steamos_diy.service stops.
if grep -q "steamos_diy" /proc/$$/cgroup 2>/dev/null; then
    warn "Active DIY session detected. Relocating process to safe scope..."
    exec systemd-run --scope --slice=app.slice --unit="sdy-uninstaller-$(date +%s)" bash "$(realpath "$0")" "$@"
    exit 0
fi

info "Starting Atomic Uninstallation for user: $REAL_USER"

# --- 1. Service & TTY Restoration (Emergency First) ---
cleanup_services() {
    info "Preparing system restoration..."

    # Disable DIY to prevent respawning
    systemctl disable steamos_diy.service 2>/dev/null || true

    # CRITICAL: Force TTY1 Getty to be ready and active
    info "Unmasking and forcing Getty on TTY1 (Emergency Access)..."
    systemctl unmask getty@tty1.service 2>/dev/null || true
    systemctl enable getty@tty1.service 2>/dev/null || true

    # Force kernel to switch to VT1 immediately to avoid black screen hang
    chvt 1 || true

    # Clean unit files
    rm -f /etc/systemd/system/steamos_diy.service
    systemctl daemon-reload
}

# --- 2. Robust Display Manager Restoration ---
restore_display_manager() {
    info "Detecting system Display Manager..."
    local dm_service=""

    # Prioritize standard DM services
    if systemctl list-unit-files | grep -q "plasmalogin.service"; then
        dm_service="plasmalogin.service"
    elif systemctl list-unit-files | grep -q "sddm.service"; then
        dm_service="sddm.service"
    elif systemctl list-unit-files | grep -q "gdm.service"; then
        dm_service="gdm.service"
    elif systemctl list-unit-files | grep -q "lightdm.service"; then
        dm_service="lightdm.service"
    fi

    if [ -n "$dm_service" ]; then
        echo -e "${YELLOW}>>> Found $dm_service. Re-enable as default? (y/n)${NC}"
        read -r -p "> " confirm_dm
        if [[ "$confirm_dm" =~ ^[Yy]$ ]]; then
            systemctl unmask "$dm_service" 2>/dev/null || true
            systemctl enable "$dm_service" --force
            systemctl set-default graphical.target
            success "Target set to graphical.target ($dm_service)."
        else
            warn "Setting system to multi-user.target (CLI mode)."
            systemctl set-default multi-user.target
        fi
    else
        warn "No standard Display Manager found. Defaulting to CLI."
        systemctl set-default multi-user.target
    fi
}

# --- 3. Comprehensive File Cleanup ---
remove_components() {
    info "Removing DIY shims and libraries..."

    # SteamOS Shims
    rm -rf /usr/bin/steamos-polkit-helpers
    rm -f /usr/bin/steamos-session-launch /usr/bin/steamos-session-select \
          /usr/bin/steamos-select-branch /usr/bin/jupiter-biosupdate \
          /usr/bin/steamos-update /usr/bin/steamos-set-timezone

    # SDY Tools (Sync with utils.py standards)
    rm -f /usr/local/bin/sdy /usr/local/bin/sdy-control-center \
          /usr/local/bin/sdy-backup /usr/local/bin/sdy-restore

    # Project Files
    rm -rf /usr/local/lib/steamos_diy
    rm -rf /var/lib/steamos_diy
    rm -f /etc/default/steamos_diy.conf
    rm -f /usr/local/share/applications/Control_Center.desktop
    rm -f /usr/local/share/applications/Game_Mode.desktop
    rm -f /usr/share/libalpm/hooks/gamescope-privs.hook

    # Reset Capabilities
    if [ -x /usr/bin/gamescope ]; then
        setcap -r /usr/bin/gamescope 2>/dev/null || true
    fi

    # User Configs
    echo -e "${RED}>>> Delete user data in $USER_HOME/.config/steamos_diy? (y/n)${NC}"
    read -r -p "> " confirm_wipe
    if [[ "$confirm_wipe" =~ ^[Yy]$ ]]; then
        rm -rf "$USER_HOME/.config/steamos_diy"
        info "User configurations purged."
    fi
}

# --- 4. Finalize & Session Handoff ---
finalize_uninstallation() {
    if systemctl is-active steamos_diy.service &>/dev/null; then
        warn "Terminating DIY session in 2 seconds..."
        # We stop the service in the background and immediately start Getty
        ( sleep 2; systemctl stop steamos_diy.service; systemctl start getty@tty1.service ) &
    fi
}

# --- Execution Flow ---
cleanup_services
restore_display_manager
remove_components

success "UNINSTALLATION COMPLETED!"
info "The system has been restored. TTY1 is now the primary output."

finalize_uninstallation

echo -e "${CYAN}>>> Reboot now to ensure a clean state? (y/n)${NC}"
read -r -p "> " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
