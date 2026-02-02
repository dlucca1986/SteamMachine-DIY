#!/bin/bash
# =============================================================================
# SteamMachine-DIY - Master Installer (v3.1.1)
# Architecture: Systemd-Agnostic / Zero-DM
# =============================================================================

set -eou pipefail

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
HOOK_DIR="/etc/pacman.d/hooks"
LOG_FILE="/var/log/steamos-diy.log"

# --- UI Functions ---
info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_privileges() {
    [[ $EUID -ne 0 ]] && error "This script must be run with sudo."
}

install_dependencies() {
    info "Verifying hardware and installing dependencies..."
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        sed -i '/^#\[multilib\]/,+1 s/^#//' /etc/pacman.conf
        pacman -Sy
    fi

    local pkgs=(steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng)
    if lspci | grep -iq "AMD"; then pkgs+=(vulkan-radeon lib32-vulkan-radeon);
    elif lspci | grep -iq "Intel"; then pkgs+=(vulkan-intel lib32-vulkan-intel); fi

    pacman -S --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Agnostic Core..."
    mkdir -p "$HELPERS_DEST" "$SYSTEMD_DEST/getty@tty1.service.d"
    
    # Scripts
    cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/"
    chmod +x "$BIN_DEST/steamos-session-launch" "$BIN_DEST/steamos-diy-control" "$BIN_DEST/sdy" "$HELPERS_DEST/"*

    # Systemd & Autologin
    cp "$SOURCE_DIR/etc/systemd/system/steamos-"*@.service "$SYSTEMD_DEST/"
    cp "$SOURCE_DIR/etc/systemd/system/steamos-exit-splash.service" "$SYSTEMD_DEST/"
    cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$SYSTEMD_DEST/getty@tty1.service.d/"

    # Desktop entries
    mkdir -p "$APP_ENTRIES"
    cp "$SOURCE_DIR/usr/share/applications/steamos-"* ".desktop" "$APP_ENTRIES/" 2>/dev/null || true
}

setup_system() {
    info "Configuring system environment..."
    
    # 1. User Groups (Critical for Zero-DM)
    info "Adding $REAL_USER to required groups..."
    for grp in sys tty rfkill video storage render lp input audio wheel autologin; do
        groupadd -f "$grp"
        usermod -aG "$grp" "$REAL_USER"
    done

    # 2. Global Config
    cp "$SOURCE_DIR/etc/default/steamos-diy" "$GLOBAL_CONF"
    sed -i "s/STEAMOS_USER=.*/STEAMOS_USER=\"$REAL_USER\"/" "$GLOBAL_CONF"
    touch "$LOG_FILE" && chmod 666 "$LOG_FILE"

    # 3. Disable SDDM/GDM if active (Zero-DM Logic)
    for dm in sddm gdm lightdm; do
        if systemctl is-active --quiet "$dm"; then
            info "Disabling $dm to prevent TTY conflicts..."
            systemctl disable "$dm"
        fi
    done
}

setup_security() {
    info "Configuring Sudoers & Hooks..."
    cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"

    # Compatibility Symlinks
    mkdir -p "$POLKIT_LINKS_DIR"
    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    ln -sf "$BIN_DEST/steamos-session-select" "/usr/bin/steamos-session-select"
    for helper in "$HELPERS_DEST"/*; do
        ln -sf "$helper" "$POLKIT_LINKS_DIR/$(basename "$helper")"
    done

    # Pacman Hook (Restores setcap after updates)
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
}

enable_services() {
    info "Activating systemd units..."
    systemctl daemon-reload
    systemctl enable "steamos-gamemode@${REAL_USER}.service"
    setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope 2>/dev/null || true
}

# --- Main ---
clear
check_privileges
install_dependencies
deploy_core
setup_system
setup_security
enable_services

success "Installation Successful! Reboot to start Gaming Mode."
