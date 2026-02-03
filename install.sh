#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Installer (v3.2.4)
# Fixed: Global variable expansion for cross-language compatibility (Python/Bash)
# Repository: https://github.com/dlucca1986/SteamMachine-DIY
# =============================================================================

set -uo pipefail

# --- Environment & Colors ---
# Force C locale to ensure consistent command output parsing
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Detection of source and user environment
SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# --- Destination Paths ---
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
POLKIT_LINKS_DIR="/usr/bin/steamos-polkit-helpers"
SYSTEMD_DEST="/etc/systemd/system"
SUDOERS_FILE="/etc/sudoers.d/steamos-diy"
GLOBAL_CONF="/etc/default/steamos-diy"
APP_ENTRIES="/usr/local/share/applications"
USER_CONF_DEST="$USER_HOME/.config/steamos-diy"
LOG_FILE="/var/log/steamos-diy.log"

# --- UI Functions ---
info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

clear
echo -e "${CYAN}==============================================${NC}"
echo -e "${CYAN}   SteamOS-DIY Master Installer v3.2.4        ${NC}"
echo -e "${CYAN}==============================================${NC}"

# Root check
if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Installing/Updating system dependencies..."
    
    # Enable multilib repository if not already present (required for 32-bit gaming libs)
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    # Core package list
    local pkgs=(steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng)

    # GPU Driver Auto-Detection
    if lspci | grep -iq "AMD"; then
        info "AMD GPU detected. Adding specific Vulkan drivers..."
        pkgs+=(vulkan-radeon lib32-vulkan-radeon)
    elif lspci | grep -iq "Intel"; then
        info "Intel GPU detected. Adding specific Vulkan drivers..."
        pkgs+=(vulkan-intel lib32-vulkan-intel)
    fi

    pacman -S --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Agnostic Core files..."
    mkdir -p "$HELPERS_DEST" "$SYSTEMD_DEST/getty@tty1.service.d" "$APP_ENTRIES" "$POLKIT_LINKS_DIR"

    # 1. Scripts & UI Helpers
    if [ -d "$SOURCE_DIR/usr/local/bin" ]; then
        cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
        chmod +x "$BIN_DEST"/* 2>/dev/null || true
        [ -d "$HELPERS_DEST" ] && chmod +x "$HELPERS_DEST"/* 2>/dev/null || true
    fi

    # 2. Systemd Services & Autologin Calibration
    # Deploys service units and replaces [USERNAME] placeholder with the actual user
    cp "$SOURCE_DIR/etc/systemd/system/steamos-"*@.service "$SYSTEMD_DEST/" 2>/dev/null || true

    local AUTO_FILE="$SYSTEMD_DEST/getty@tty1.service.d/autologin.conf"
    if [ -f "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$AUTO_FILE"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$AUTO_FILE"
        info "Autologin calibrated for user: $REAL_USER"
    fi

    # 3. Desktop Entries (Integration with KDE/GNOME application menus)
    for dir in "usr/share/applications" "usr/local/share/applications"; do
        if [ -d "$SOURCE_DIR/$dir" ]; then
            cp "$SOURCE_DIR/$dir/steamos-"*.desktop "$APP_ENTRIES/" 2>/dev/null || true
        fi
    done

    # Finalize .desktop files with correct username
    for file in "$APP_ENTRIES"/steamos-*.desktop; do
        [ -f "$file" ] || continue
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$file"
        chmod +x "$file"
    done

    update-desktop-database "$APP_ENTRIES" 2>/dev/null || true
}

setup_configs() {
    info "Deploying and flattening configurations..."

    if [ -f "$SOURCE_DIR/etc/default/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/default/steamos-diy" "$GLOBAL_CONF"
        
        # 1. Primary User Replacement
        sed -i "s/^STEAMOS_USER=.*/STEAMOS_USER=\"$REAL_USER\"/" "$GLOBAL_CONF"
        
        # 2. Expand ${STEAMOS_USER} throughout the file for absolute static paths
        sed -i "s/\${STEAMOS_USER}/$REAL_USER/g" "$GLOBAL_CONF"
        
        # 3. Expand ${CONF_DIR} (Fixes cross-references like GAMES_CONF_DIR)
        local REAL_CONF_DIR="/home/$REAL_USER/.config/steamos-diy"
        sed -i "s|\${CONF_DIR}|$REAL_CONF_DIR|g" "$GLOBAL_CONF"
        
        success "Global configuration flattened for universal cross-language access."
    else
        # Fallback if config file is missing from source
        echo "STEAMOS_USER=\"$REAL_USER\"" > "$GLOBAL_CONF"
    fi

    # Local user configuration directory
    mkdir -p "$USER_CONF_DEST/games"
    if [ -d "$SOURCE_DIR/config" ]; then
        cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
        chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"
    fi

    # Log file initialization
    touch "$LOG_FILE" && chmod 666 "$LOG_FILE"
}

setup_security() {
    info "Configuring Sudoers & Privilege Elevation..."
    # Grant permission for session switching without password prompts
    [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ] && \
        cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_FILE" && \
        chmod 440 "$SUDOERS_FILE"

    # Create binary symlinks for easier terminal access
    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    ln -sf "$BIN_DEST/steamos-session-select" "/usr/bin/steamos-session-select"

    # Map helpers to Polkit directory for privilege management
    if ls "$HELPERS_DEST/"* >/dev/null 2>&1; then
        for helper in "$HELPERS_DEST"/*; do
            ln -sf "$helper" "$POLKIT_LINKS_DIR/$(basename "$helper")"
        done
    fi
}

enable_services() {
    info "Enabling Systemd Units..."
    systemctl daemon-reload
    # Enable Game Mode by default for the installing user
    systemctl enable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
    
    # Set Gamescope capabilities for performance and scheduling (Real-time priority)
    [ -x /usr/bin/gamescope ] && \
        setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
}

# --- Execution Workflow ---
install_dependencies
deploy_core
setup_configs
setup_security
enable_services

echo -e "\n${GREEN}==============================================${NC}"
success "Installation Complete! Your SteamOS-DIY machine is ready for reboot."
