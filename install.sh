#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Installer (v3.1.8)
# Fixed: Global permissions, broad desktop discovery, log handling
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
LOG_FILE="/var/log/steamos-diy.log"

info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

clear
echo -e "${CYAN}==============================================${NC}"
echo -e "${CYAN}   SteamOS-DIY Master Installer v3.1.8        ${NC}"
echo -e "${CYAN}==============================================${NC}"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Installing/Updating dependencies..."
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    local pkgs=(steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng)

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

    # 1. Scripts & Helpers - FORZA ESECUZIONE SU TUTTO IL CONTENUTO
    if [ -d "$SOURCE_DIR/usr/local/bin" ]; then
        cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
        info "Applying executable bits to all binaries..."
        chmod +x "$BIN_DEST"/* 2>/dev/null || true
        [ -d "$HELPERS_DEST" ] && chmod +x "$HELPERS_DEST"/* 2>/dev/null || true
    fi

    # 2. Systemd & Autologin Calibration
    cp "$SOURCE_DIR/etc/systemd/system/steamos-"*@.service "$SYSTEMD_DEST/" 2>/dev/null || true
    cp "$SOURCE_DIR/etc/systemd/system/steamos-exit-splash.service" "$SYSTEMD_DEST/" 2>/dev/null || true

    local AUTO_FILE="$SYSTEMD_DEST/getty@tty1.service.d/autologin.conf"
    if [ -f "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$AUTO_FILE"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$AUTO_FILE"
        info "Autologin calibrated for: $REAL_USER"
    fi

    # 3. Desktop Entries - SCOPERTA AMPIA
    for dir in "usr/share/applications" "usr/local/share/applications"; do
        if [ -d "$SOURCE_DIR/$dir" ]; then
            cp "$SOURCE_DIR/$dir/steamos-"*.desktop "$APP_ENTRIES/" 2>/dev/null || true
        fi
    done

    # Calibration per lo switch e il controllo
    for file in "$APP_ENTRIES"/steamos-*.desktop; do
        [ -f "$file" ] || continue
        sed -i "s/startsteamos/start steamos/g" "$file"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$file"
    done

    update-desktop-database "$APP_ENTRIES" 2>/dev/null || true
}

setup_configs() {
    info "Deploying user configurations..."
    rm -rf "$USER_HOME/\${CONF_DIR}" 2>/dev/null
    mkdir -p "$USER_CONF_DEST/games"

    if [ -d "$SOURCE_DIR/config" ]; then
        cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
        chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"
    fi

    echo "STEAMOS_USER=\"$REAL_USER\"" > "$GLOBAL_CONF"
    # Gestione LOG
    touch "$LOG_FILE" && chmod 666 "$LOG_FILE"
}

setup_security() {
    info "Configuring Sudoers & Privileges..."
    [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ] && cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_FILE" && chmod 440 "$SUDOERS_FILE"

    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    ln -sf "$BIN_DEST/steamos-session-select" "/usr/bin/steamos-session-select"

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
    [ -x /usr/bin/gamescope ] && setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
}

# --- Bootstrapping ---
install_dependencies
deploy_core
setup_configs
setup_security
enable_services

echo -e "\n${GREEN}==============================================${NC}"
success "Installation Complete! Ready for reboot."
