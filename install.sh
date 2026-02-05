#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Installer (v4.0.0 Enterprise)
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
SYSTEM_DEFAULTS_DIR="/usr/share/steamos-diy"
GLOBAL_CONF="/etc/default/steamos-diy"
USER_CONF_DEST="$USER_HOME/.config/steamos-diy"

info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Installing system dependencies..."
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi
    local pkgs=(steam gamescope xorg-xwayland mangohud python-pyqt6 pciutils mesa-utils procps-ng)
    pacman -S --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Core Infrastructure..."
    mkdir -p "$HELPERS_DEST" "$SYSTEM_DEFAULTS_DIR"
    
    # 1. Copia i binari e gli helper
    cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
    chmod +x "$BIN_DEST"/* "$HELPERS_DEST"/* 2>/dev/null || true

    # 2. Crea il file DEFAULTS (Sola Lettura per il sistema)
    if [ -f "$SOURCE_DIR/usr/share/steamos-diy/defaults" ]; then
        cp "$SOURCE_DIR/usr/share/steamos-diy/defaults" "$SYSTEM_DEFAULTS_DIR/defaults"
        success "System defaults deployed to $SYSTEM_DEFAULTS_DIR"
    fi
}

setup_configs() {
    info "Configuring SSoT Identity..."

    # 1. Configurazione Master (/etc/default/steamos-diy)
    if [ -f "$SOURCE_DIR/etc/default/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/default/steamos-diy" "$GLOBAL_CONF"
        # Popola SOLO l'utente. Il resto rimane variabile dinamica.
        sed -i "s/^export STEAMOS_USER=.*/export STEAMOS_USER=\"$REAL_USER\"/" "$GLOBAL_CONF"
        success "Master Config initialized for user: $REAL_USER"
    fi

    # 2. Home Config (Log e Game Configs)
    mkdir -p "$USER_CONF_DEST/games"
    if [ -d "$SOURCE_DIR/config" ]; then
        cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
    fi
    chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"

    # 3. Log Initialization (Home-based)
    local SESSION_LOG="$USER_CONF_DEST/session.log"
    touch "$SESSION_LOG"
    chown "$REAL_USER:$REAL_USER" "$SESSION_LOG"
    chmod 644 "$SESSION_LOG"
}

setup_security() {
    info "Applying Sudoers & Polkit policies..."
    if [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "/etc/sudoers.d/steamos-diy"
        chmod 440 "/etc/sudoers.d/steamos-diy"
    fi
}

enable_services() {
    info "Activating Systemd Units..."
    systemctl daemon-reload
    # Abilitazione dinamica tramite template
    systemctl enable "steamos-gamemode@${REAL_USER}.service" 2>/dev/null || true
}

# Workflow
install_dependencies
deploy_core
setup_configs
setup_security
enable_services

echo -e "\n${GREEN}Installation Complete! System is now SSoT compliant.${NC}"
