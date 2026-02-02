#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Installer (v3.1.7)
# Dynamic User Calibration & Config Deployment
# =============================================================================

set -uo pipefail

# --- Environment & Colors ---
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

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

info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

clear
echo -e "${CYAN}==============================================${NC}"
echo -e "${CYAN}   SteamOS-DIY Master Installer v3.1.7        ${NC}"
echo -e "${CYAN}==============================================${NC}"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Installing/Updating dependencies..."
    # Abilitazione multilib se mancante
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    local pkgs=(steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng)
    
    # Auto-detection GPU per Vulkan
    if lspci | grep -iq "AMD"; then
        pkgs+=(vulkan-radeon lib32-vulkan-radeon)
    elif lspci | grep -iq "Intel"; then
        pkgs+=(vulkan-intel lib32-vulkan-intel)
    fi

    pacman -S --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Agnostic Core..."
    mkdir -p "$HELPERS_DEST" "$SYSTEMD_DEST/getty@tty1.service.d" "$APP_ENTRIES" "$POLKIT_LINKS_DIR"

    # 1. Scripts & Helpers
    cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
    chmod +x "$BIN_DEST/steamos-session-launch" "$BIN_DEST/sdy" 2>/dev/null || true
    [ -d "$HELPERS_DEST" ] && chmod +x "$HELPERS_DEST/"* 2>/dev/null || true

    # 2. Systemd & Autologin Calibration
    cp "$SOURCE_DIR/etc/systemd/system/steamos-"*@.service "$SYSTEMD_DEST/" 2>/dev/null || true
    cp "$SOURCE_DIR/etc/systemd/system/steamos-exit-splash.service" "$SYSTEMD_DEST/" 2>/dev/null || true

    local AUTO_FILE="$SYSTEMD_DEST/getty@tty1.service.d/autologin.conf"
    if [ -f "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$AUTO_FILE"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$AUTO_FILE"
        info "Autologin calibrated for: $REAL_USER"
    fi

    # 3. Desktop Entries & Switch Calibration
    if [ -d "$SOURCE_DIR/usr/share/applications" ]; then
        cp "$SOURCE_DIR/usr/share/applications/steamos-"*.desktop "$APP_ENTRIES/"
        
        local SWITCH_FILE="$APP_ENTRIES/steamos-switch-gamemode.desktop"
        if [ -f "$SWITCH_FILE" ]; then
            # Fix space and placeholder
            sed -i "s/startsteamos/start steamos/g" "$SWITCH_FILE"
            sed -i "s/\[USERNAME\]/$REAL_USER/g" "$SWITCH_FILE"
            info "Desktop Mode switch calibrated."
        fi
    fi
    update-desktop-database "$APP_ENTRIES" 2>/dev/null || true
}

setup_configs() {
    info "Deploying user configurations..."
    
    # Rimuove residui errati se presenti
    rm -rf "$USER_HOME/\${CONF_DIR}" 2>/dev/null

    # Crea la struttura .config/steamos-diy
    mkdir -p "$USER_CONF_DEST/games"

    if [ -d "$SOURCE_DIR/config" ]; then
        # Copia il contenuto della cartella config del repo nella destinazione
        cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
        chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"
        success "Configs deployed to $USER_CONF_DEST"
    fi

    # Enforce global default
    echo "STEAMOS_USER=\"$REAL_USER\"" > "$GLOBAL_CONF"
}

setup_security() {
    info "Configuring Sudoers & Privileges..."
    [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ] && cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_FILE" && chmod 440 "$SUDOERS_FILE"

    # Symlinks per compatibilità
    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    
    # Helpers links
    if ls "$HELPERS_DEST/"* >/dev/null 2>&1; then
        for helper in "$HELPERS_DEST"/*; do
            ln -sf "$helper" "$POLKIT_LINKS_DIR/$(basename "$helper")"
        done
    fi
}

enable_services() {
    info "Enabling Systemd Units..."
    systemctl daemon-reload
    systemctl enable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
    
    # Gamescope Cap bit
    [ -x /usr/bin/gamescope ] && setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
}

# --- Bootstrapping ---
install_dependencies
deploy_core
setup_configs
setup_security
enable_services

echo -e "\n${GREEN}==============================================${NC}"
success "Installation Complete! Reboot and enjoy your DIY SteamOS."
echo -e "${GREEN}==============================================${NC}"
