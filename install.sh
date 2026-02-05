#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Installer (v4.1.0 Enterprise + Hardware Aware)
# =============================================================================

set -uo pipefail

export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# Percorsi Destinazione
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
POLKIT_LINKS_DIR="/usr/bin/steamos-polkit-helpers"
SYSTEM_DEFAULTS_DIR="/usr/share/steamos-diy"
GLOBAL_CONF="/etc/default/steamos-diy"
USER_CONF_DEST="$USER_HOME/.config/steamos-diy"
SUDOERS_DEST="/etc/sudoers.d/steamos-diy"

info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Updating system and detecting hardware..."
    
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    local pkgs=(steam gamescope xorg-xwayland mangohud python-pyqt6 pciutils mesa-utils procps-ng lib32-mangohud gamemode lib32-gamemode)

    # GPU Driver Auto-Detection (Vital for Gaming)
    if lspci | grep -iq "AMD"; then
        info "AMD GPU detected. Adding Vulkan Radeon drivers..."
        pkgs+=(vulkan-radeon lib32-vulkan-radeon)
    elif lspci | grep -iq "Intel"; then
        info "Intel GPU detected. Adding Vulkan Intel drivers..."
        pkgs+=(vulkan-intel lib32-vulkan-intel)
    fi

    pacman -Syu --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Core Infrastructure & Binaries..."
    mkdir -p "$HELPERS_DEST" "$SYSTEM_DEFAULTS_DIR" "$POLKIT_LINKS_DIR"
    
    # 1. Copia Binari Originali
    if [ -d "$SOURCE_DIR/usr/local/bin" ]; then
        cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
        chmod +x "$BIN_DEST"/* "$HELPERS_DEST"/* 2>/dev/null || true
    fi

    # 2. Defaults (SSoT Level 2)
    if [ -f "$SOURCE_DIR/usr/share/steamos-diy/defaults" ]; then
        cp "$SOURCE_DIR/usr/share/steamos-diy/defaults" "$SYSTEM_DEFAULTS_DIR/defaults"
        success "System defaults deployed."
    fi

    # 3. Global Symlinks (Per accesso universale e Control Center)
    info "Creating global command symlinks..."
    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    ln -sf "$BIN_DEST/steamos-session-select" "/usr/bin/steamos-session-select"
    ln -sf "$BIN_DEST/sdy" "/usr/bin/sdy"
}

setup_configs() {
    info "Configuring SSoT Identity & Autologin..."

    # 1. Master Config
    if [ -f "$SOURCE_DIR/etc/default/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/default/steamos-diy" "$GLOBAL_CONF"
        sed -i "s/^export STEAMOS_USER=.*/export STEAMOS_USER=\"$REAL_USER\"/" "$GLOBAL_CONF"
    fi

    # 2. Autologin Calibration (Drop-in)
    local AUTO_DIR="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$AUTO_DIR"
    if [ -f "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$AUTO_DIR/autologin.conf"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$AUTO_DIR/autologin.conf"
    fi

    # 3. Home Config & Logs
    mkdir -p "$USER_CONF_DEST/games"
    [ -d "$SOURCE_DIR/config" ] && cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
    touch "$USER_CONF_DEST/session.log"
    chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"
}

setup_security() {
    info "Applying Sudoers & Polkit Mapping..."
    
    # 1. Popolamento Polkit Helpers (Symlinks verso /usr/bin)
    if ls "$HELPERS_DEST/"* >/dev/null 2>&1; then
        for helper in "$HELPERS_DEST"/*; do
            ln -sf "$helper" "$POLKIT_LINKS_DIR/$(basename "$helper")"
        done
        success "Polkit helpers mapped."
    fi

    # 2. Sudoers
    if [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_DEST"
        chmod 440 "$SUDOERS_DEST"
    fi
}

disable_conflicts() {
    info "Disabling Login Managers..."
    local dms=(sddm gdm lightdm lxdm)
    for dm in "${dms[@]}"; do
        if systemctl is-active --quiet "$dm"; then
            warn "Disabling $dm..."
            systemctl disable "$dm" && systemctl stop "$dm"
        fi
    done
}

enable_services() {
    info "Activating Services..."
    systemctl daemon-reload
    systemctl enable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
    
    # Set capabilities per Gamescope (Performance & Scheduling)
    [ -x /usr/bin/gamescope ] && setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
}

# --- Execution ---
install_dependencies
deploy_core
setup_configs
setup_security
disable_conflicts
enable_services

echo -e "\n${GREEN}==============================================${NC}"
success "Installation Complete! Reboot to start SteamOS-DIY."
echo -e "${GREEN}==============================================${NC}"
