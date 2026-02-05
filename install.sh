#!/bin/bash
# =============================================================================
# SteamOS-DIY - Master Installer (v4.2.1 Enterprise)
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
HOOK_DIR="/etc/pacman.d/hooks"
SYSTEMD_DIR="/etc/systemd/system"
APPS_DEST="/usr/share/applications"

info()    { echo -e "${CYAN}[SYSTEM]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if [[ $EUID -ne 0 ]]; then
    error "This script must be run with sudo."
fi

install_dependencies() {
    info "Updating system and detecting GPU hardware..."
    
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    local pkgs=(steam gamescope xorg-xwayland mangohud python-pyqt6 pciutils mesa-utils procps-ng lib32-mangohud gamemode lib32-gamemode)

    if lspci | grep -iq "AMD"; then
        info "AMD GPU detected. Adding specific Vulkan drivers..."
        pkgs+=(vulkan-radeon lib32-vulkan-radeon)
    elif lspci | grep -iq "Intel"; then
        info "Intel GPU detected. Adding specific Vulkan drivers..."
        pkgs+=(vulkan-intel lib32-vulkan-intel)
    fi

    pacman -Syu --needed --noconfirm "${pkgs[@]}"
}

deploy_core() {
    info "Deploying Core Infrastructure..."
    mkdir -p "$HELPERS_DEST" "$SYSTEM_DEFAULTS_DIR" "$POLKIT_LINKS_DIR" "$APPS_DEST"
    
    # 1. Copia Binari & Helpers
    cp -r "$SOURCE_DIR/usr/local/bin/"* "$BIN_DEST/" 2>/dev/null || true
    chmod +x "$BIN_DEST"/* "$HELPERS_DEST"/* 2>/dev/null || true

    # 2. Copia Desktop Entries (Applicazioni nel menu)
    if [ -d "$SOURCE_DIR/usr/share/applications" ]; then
        cp "$SOURCE_DIR/usr/share/applications/"*.desktop "$APPS_DEST/" 2>/dev/null || true
    fi

    # 3. Defaults
    if [ -f "$SOURCE_DIR/usr/share/steamos-diy/defaults" ]; then
        cp "$SOURCE_DIR/usr/share/steamos-diy/defaults" "$SYSTEM_DEFAULTS_DIR/defaults"
    fi

    # 4. Global Symlinks
    ln -sf "$BIN_DEST/steamos-session-launch" "/usr/bin/steamos-session-launch"
    ln -sf "$BIN_DEST/steamos-session-select" "/usr/bin/steamos-session-select"
    ln -sf "$BIN_DEST/sdy" "/usr/bin/sdy"
    success "Infrastructure, Apps and Symlinks established."
}

setup_configs() {
    info "Configuring SSoT Identity & Autologin..."

    # 1. Master Config
    if [ -f "$SOURCE_DIR/etc/default/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/default/steamos-diy" "$GLOBAL_CONF"
        sed -i "s/^export STEAMOS_USER=.*/export STEAMOS_USER=\"$REAL_USER\"/" "$GLOBAL_CONF"
    fi

    # 2. Systemd Units (Servizi)
    info "Installing Systemd Services..."
    if [ -d "$SOURCE_DIR/etc/systemd/system" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/"*.service "$SYSTEMD_DIR/" 2>/dev/null || true
    fi

    # 3. Autologin Calibration
    local AUTO_DIR="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$AUTO_DIR"
    if [ -f "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" ]; then
        cp "$SOURCE_DIR/etc/systemd/system/getty@tty1.service.d/autologin.conf" "$AUTO_DIR/autologin.conf"
        sed -i "s/\[USERNAME\]/$REAL_USER/g" "$AUTO_DIR/autologin.conf"
    fi

    # 4. Home Config & Logs
    mkdir -p "$USER_CONF_DEST/games"
    [ -d "$SOURCE_DIR/config" ] && cp -r "$SOURCE_DIR/config/"* "$USER_CONF_DEST/"
    touch "$USER_CONF_DEST/session.log"
    chown -R "$REAL_USER:$REAL_USER" "$USER_CONF_DEST"
}

setup_security() {
    info "Applying Sudoers & Pacman Hooks..."
    
    # 1. Polkit Mapping
    if ls "$HELPERS_DEST/"* >/dev/null 2>&1; then
        for helper in "$HELPERS_DEST"/*; do
            ln -sf "$helper" "$POLKIT_LINKS_DIR/$(basename "$helper")"
        done
    fi

    # 2. Sudoers
    if [ -f "$SOURCE_DIR/etc/sudoers.d/steamos-diy" ]; then
        cp "$SOURCE_DIR/etc/sudoers.d/steamos-diy" "$SUDOERS_DEST"
        chmod 440 "$SUDOERS_DEST"
    fi

    # 3. Pacman Hook
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
    success "Security policies and hooks active."
}

disable_conflicts() {
    info "Disabling Display Managers..."
    local dms=(sddm gdm lightdm lxdm)
    for dm in "${dms[@]}"; do
        if systemctl is-active --quiet "$dm" || systemctl is-enabled --quiet "$dm"; then
            warn "Disabling $dm..."
            systemctl disable "$dm" 2>/dev/null || true
            systemctl stop "$dm" 2>/dev/null || true
        fi
    done
}

enable_services() {
    info "Activating Systemd Units..."
    systemctl daemon-reload
    # Abilitiamo il servizio gamemode per l'utente reale
    systemctl enable "steamos-gamemode@${REAL_USER}.service"
    
    # Setcap iniziale per Gamescope
    if [ -x /usr/bin/gamescope ]; then
        setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    fi
}

# --- Execution Flow ---
install_dependencies
deploy_core
setup_configs
setup_security
disable_conflicts
enable_services

echo -e "\n${GREEN}==============================================${NC}"
success "Installation Complete! Your SteamOS-DIY is ready."
info "Reboot now to enter Game Mode."
echo -e "${GREEN}==============================================${NC}"
