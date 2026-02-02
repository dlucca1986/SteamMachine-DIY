#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Installer
# Version: 3.0.0
# Description: Full deployment for SteamOS-like experience on Arch Linux
# Repository: https://github.com/dlucca1986/SteamMachine-DIY
# License: MIT
# =============================================================================

set -eou pipefail

# --- Environment & Colors ---
export LANG=C
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

SOURCE_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

# --- Destination Paths ---
BIN_DEST="/usr/local/bin"
HELPERS_DEST="/usr/local/bin/steamos-helpers"
POLKIT_LINKS_DIR="/usr/bin/steamos-polkit-helpers"
SDDM_CONF_DIR="/etc/sddm.conf.d"
SUDOERS_FILE="/etc/sudoers.d/steamos-switcher"
WAYLAND_SESSIONS="/usr/share/wayland-sessions"
APP_ENTRIES="/usr/share/applications"
HOOK_DIR="/etc/pacman.d/hooks"
LOG_FILE="/var/log/steamos-diy.log"

# --- UI Functions ---
info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()    { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_privileges() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run with sudo (e.g., sudo ./install.sh)"
    fi
}

install_dependencies() {
    info "Verifying hardware and installing dependencies..."
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        sed -i '/^#\[multilib\]/,+1 s/^#//' /etc/pacman.conf
        pacman -Sy
    fi
    local pkgs=(steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils)
    if lspci | grep -iq "AMD"; then pkgs+=(vulkan-radeon lib32-vulkan-radeon);
    elif lspci | grep -iq "Intel"; then pkgs+=(vulkan-intel lib32-vulkan-intel); fi
    pacman -S --needed --noconfirm "${pkgs[@]}" || error "Failed to install packages."
    success "Hardware dependencies ready."
}

setup_logging() {
    info "Initializing system log at $LOG_FILE..."
    touch "$LOG_FILE"
    chmod 666 "$LOG_FILE"
    success "Log file ready."
}

deploy_binaries() {
    info "Deploying binaries from $SOURCE_DIR/usr/local/bin..."
    mkdir -p "$HELPERS_DEST"

    # Percorsi corretti basati sul tuo ls -R
    cp "$SOURCE_DIR/usr/local/bin/os-session-select" "$BIN_DEST/"
    cp "$SOURCE_DIR/usr/local/bin/set-sddm-session" "$BIN_DEST/"
    cp "$SOURCE_DIR/usr/local/bin/steamos-session-launch" "$BIN_DEST/"
    cp "$SOURCE_DIR/usr/local/bin/steamos-helpers/"* "$HELPERS_DEST/"

    chmod +x "$BIN_DEST/os-session-select" \
             "$BIN_DEST/set-sddm-session" \
             "$BIN_DEST/steamos-session-launch"
    chmod +x "$HELPERS_DEST/"*
    success "Binaries and helpers deployed."
}

setup_integration() {
    info "Integrating with system (Desktop & SDDM)..."

    mkdir -p "$WAYLAND_SESSIONS"
    cp "$SOURCE_DIR/usr/share/wayland-sessions/steamos-switcher.desktop" "$WAYLAND_SESSIONS/"

    mkdir -p "$APP_ENTRIES"
    cp "$SOURCE_DIR/usr/share/applications/GameMode.desktop" "$APP_ENTRIES/"

    mkdir -p "$SDDM_CONF_DIR"
    cp "$SOURCE_DIR/etc/sddm.conf.d/10-wayland.conf" "$SDDM_CONF_DIR/"

    success "System integration entries created."
}

create_symlinks() {
    info "Creating compatibility symlinks..."
    mkdir -p "$POLKIT_LINKS_DIR"
    ln -sf "$BIN_DEST/os-session-select" "/usr/bin/steamos-session-select"
    for helper in "$HELPERS_DEST"/*; do
        name=$(basename "$helper")
        ln -sf "$helper" "$POLKIT_LINKS_DIR/$name"
    done
    success "Symlinks established."
}

setup_security() {
    info "Configuring NOPASSWD policies..."
    cat <<EOF > "$SUDOERS_FILE"
# SteamMachine DIY - Session Switching Policies
ALL ALL=(ALL) NOPASSWD: /usr/local/bin/set-sddm-session
ALL ALL=(ALL) NOPASSWD: /usr/local/bin/os-session-select
EOF
    chmod 440 "$SUDOERS_FILE"
    success "Sudoers rules updated."
}

setup_pacman_hooks() {
    info "Setting up Pacman hooks..."
    mkdir -p "$HOOK_DIR"
    cat <<EOF > "$HOOK_DIR/gamescope-capabilities.hook"
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = gamescope
[Action]
Description = Restoring Gamescope capabilities...
When = PostTransaction
Exec = /usr/bin/setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
EOF
    success "Pacman hook established."
}

setup_user_config() {
    info "Deploying User Configuration..."
    local REAL_USER=${SUDO_USER:-$USER}
    local USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
    local TARGET_DIR="$USER_HOME/.config/steamos-diy"

    mkdir -p "$TARGET_DIR"

    # Copia config e config.example dalla tua cartella ./config/
    if [[ ! -f "$TARGET_DIR/config" ]]; then
        cp "$SOURCE_DIR/config/config" "$TARGET_DIR/config"
    fi
    cp "$SOURCE_DIR/config/config.example" "$TARGET_DIR/config.example"

    chown -R "$REAL_USER":"$REAL_USER" "$TARGET_DIR"
    success "User config deployed to $TARGET_DIR"

    # Desktop Shortcut
    local DESKTOP_DIR=$(sudo -u "$REAL_USER" xdg-user-dir DESKTOP 2>/dev/null || echo "$USER_HOME/Desktop")
    if [[ -d "$DESKTOP_DIR" ]]; then
        cp "$SOURCE_DIR/usr/share/applications/GameMode.desktop" "$DESKTOP_DIR/"
        chown "$REAL_USER":"$REAL_USER" "$DESKTOP_DIR/GameMode.desktop"
        chmod +x "$DESKTOP_DIR/GameMode.desktop"
        sudo -u "$REAL_USER" dbus-launch gio set "$DESKTOP_DIR/GameMode.desktop" metadata::trusted true 2>/dev/null || true
    fi
}

# --- Execution ---
clear
check_privileges
install_dependencies
setup_logging
deploy_binaries
setup_integration
create_symlinks
setup_security
setup_pacman_hooks
setup_user_config

if [[ -x /usr/bin/gamescope ]]; then
    setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
fi

success "Installation Successful!"
