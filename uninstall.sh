#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      2.1.7
# DESCRIPTION:  Interactive removal of DIY components and system restoration.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
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
if [ -z "$USER_HOME" ]; then
    error "Cannot resolve home directory for user: $REAL_USER"
    exit 1
fi

# --- Filesystem Layout (must mirror install.sh / utils.py constants) ---
readonly LIB_DIR="/usr/local/lib/steamos_diy"
readonly POLKIT_DIR="/usr/bin/steamos-polkit-helpers"
readonly BIN_DIR="/usr/local/bin"
readonly SSOT_CONF="/etc/default/steamos_diy.conf"
readonly SERVICE_FILE="/etc/systemd/system/steamos_diy.service"
readonly STATE_DIR="/var/lib/steamos_diy"
readonly APP_DIR="/usr/local/share/applications"
readonly ALPM_HOOKS_DIR="/usr/share/libalpm/hooks"
readonly USER_CONFIG_REL=".config/steamos_diy"

# --- Cgroup Escape (Survival Mechanism) ---
# Prevents the script from being killed when steamos_diy.service stops.
if grep -q "steamos_diy" /proc/$$/cgroup 2>/dev/null; then
    warn "Active DIY session detected. Relocating process to safe scope..."
    exec systemd-run --scope --slice=app.slice --unit="sdy-uninstaller-$(date +%s)" bash "$(realpath "$0")" "$@"
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

    # Clean unit files
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
}

# --- 2. Robust Display Manager Restoration ---
restore_display_manager() {
    info "Detecting system Display Manager..."
    local dm_service=""
    local dm_units
    dm_units=$(systemctl list-unit-files)

    # First match wins — order encodes priority.
    for candidate in plasmalogin.service sddm.service; do
        if echo "$dm_units" | grep -q "$candidate"; then
            dm_service=$candidate
            break
        fi
    done

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

    # SteamOS shims — polkit dir gone wholesale; aliases removed one-by-one
    # to match the explicit list created by install.sh::setup_shim_links.
    rm -rf "$POLKIT_DIR"
    for name in steamos-session-launch steamos-session-select \
                steamos-select-branch jupiter-biosupdate \
                steamos-update steamos-set-timezone; do
        rm -f "/usr/bin/$name"
    done

    # SDY CLI tools
    for name in sdy sdy-control-center sdy-backup sdy-restore; do
        rm -f "$BIN_DIR/$name"
    done

    # Project files (.new = template staged by install.sh --update)
    rm -rf "$LIB_DIR" "$STATE_DIR"
    rm -f "$SSOT_CONF" "${SSOT_CONF}.new"
    rm -f "$APP_DIR/Control_Center.desktop" "$APP_DIR/Game_Mode.desktop"
    rm -f "$ALPM_HOOKS_DIR/gamescope-privs.hook"

    # Reset Capabilities
    if [ -x /usr/bin/gamescope ]; then
        setcap -r /usr/bin/gamescope 2>/dev/null || true
    fi

    # User Configs
    local user_cfg="$USER_HOME/$USER_CONFIG_REL"
    echo -e "${RED}>>> Delete user data in $user_cfg? (y/n)${NC}"
    read -r -p "> " confirm_wipe
    if [[ "$confirm_wipe" =~ ^[Yy]$ ]]; then
        rm -rf "$user_cfg"
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

echo -e "${CYAN}>>> Reboot now to ensure a clean state? (y/n)${NC}"
read -r -p "> " confirm_reboot

finalize_uninstallation

if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
