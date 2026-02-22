#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer
# VERSION:      1.5.0 - Target Locking & Architecture Fix
# DESCRIPTION:  Hardware Audit, Dependency Management, SSoT Patching & Hooks.
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

if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./install.sh)"
    exit 1
fi

REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
REAL_UID=$(id -u "$REAL_USER")

# --- 0. System Update Prompt ---
ask_system_update() {
    echo -e "${YELLOW}>>> Do you want to update the system before proceeding? (y/n)${NC}"
    read -r -p "> " confirm_update
    if [[ "$confirm_update" =~ ^[Yy]$ ]]; then
        info "Updating system repositories and packages..."
        pacman -Syu --noconfirm
    else
        info "Skipping system update."
    fi
}

# --- 1. Hardware & Driver Audit ---
check_gpu_and_drivers() {
    info "Auditing Hardware and Drivers..."
    GPU_INFO=$(lspci | grep -i vga)
    DRIVER_PKGS=""

    if echo "$GPU_INFO" | grep -iq "nvidia"; then
        if lsmod | grep -q "nvidia"; then
            warn "Active NVIDIA proprietary drivers detected. Skipping driver install."
        else
            info "Nvidia GPU detected. Preparing Nouveau open-source drivers."
            DRIVER_PKGS="vulkan-nouveau lib32-vulkan-nouveau"
        fi
    elif echo "$GPU_INFO" | grep -iq "amd"; then
        if lsmod | grep -q "amdgpu"; then
            warn "Active AMDGPU driver detected in kernel. Skipping driver install."
        else
            info "AMD GPU detected. Preparing Vulkan-Radeon."
            DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon"
        fi
    elif echo "$GPU_INFO" | grep -iq "intel"; then
        if lsmod | grep -q "i915" || lsmod | grep -q "xe"; then
            warn "Active Intel driver detected in kernel. Skipping driver install."
        else
            info "Intel GPU detected. Preparing Vulkan-Intel."
            DRIVER_PKGS="vulkan-intel lib32-vulkan-intel"
        fi
    fi
}

# --- 2. Dependencies & Groups ---
install_dependencies() {
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        info "Enabling multilib repository..."
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    BASE_PKGS="python python-pyqt6 python-yaml python-ruamel-yaml steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils pciutils procps-ng"

    info "Installing core dependencies..."
    pacman -S --needed --noconfirm $BASE_PKGS

    if [[ -n "$DRIVER_PKGS" ]]; then
        info "Installing detected driver packages: $DRIVER_PKGS"
        pacman -S --needed --noconfirm $DRIVER_PKGS
    fi

    info "Updating user groups for $REAL_USER..."
    for grp in video render input audio wheel storage autologin systemd-journal; do
        groupadd -f "$grp"
        usermod -aG "$grp" "$REAL_USER"
    done
}

# --- 3. File Deployment & SSoT Patching ---
deploy_files() {
    info "Deploying and personalizing files..."

    mkdir -p /etc/default
    cp -f etc/default/steamos_diy.conf /etc/default/steamos_diy.conf

    # Patch SSoT using {{HOME}} placeholder
    info "Patching SSoT configuration with Home: $USER_HOME"
    sed -i "s|{{HOME}}|$USER_HOME|g" /etc/default/steamos_diy.conf

    info "Deploying user configuration to $USER_HOME..."
    mkdir -p "$USER_HOME/.config/steamos_diy/games.d"

    if [ -d etc/skel/.config/steamos_diy/ ]; then
        cp -f etc/skel/.config/steamos_diy/*.yaml "$USER_HOME/.config/steamos_diy/"
    fi
    chown -R "$REAL_USER:$REAL_USER" "$USER_HOME/.config/steamos_diy"

    # --- Deploy Library & Helpers ---
    mkdir -p /usr/local/lib/steamos_diy/helpers
    cp -rf usr/local/lib/steamos_diy/* /usr/local/lib/steamos_diy/

    # FIX: Ensure directories are traversable and scripts are executable
    info "Ensuring library and helpers have correct execution bits..."
    chmod -R 755 /usr/local/lib/steamos_diy
    chmod +x /usr/local/lib/steamos_diy/*.py
    chmod +x /usr/local/lib/steamos_diy/helpers/*.py

    mkdir -p /var/lib/steamos_diy
    if [ ! -f /var/lib/steamos_diy/next_session ]; then
        echo "steam" > /var/lib/steamos_diy/next_session
    fi
    chown -R "$REAL_USER:$REAL_USER" /var/lib/steamos_diy
    chmod 775 /var/lib/steamos_diy

    # --- Desktop Entries (Icons/Menu) ---
    info "Installing desktop menu entries..."
    mkdir -p /usr/local/share/applications
    [ -f usr/local/share/applications/Control_Center.desktop ] && cp -f usr/local/share/applications/Control_Center.desktop /usr/local/share/applications/
    [ -f usr/local/share/applications/Game_Mode.desktop ] && cp -f usr/local/share/applications/Game_Mode.desktop /usr/local/share/applications/

    # --- ALPM Hooks & Gamescope Privileges ---
    info "Installing Pacman hooks for Gamescope persistence..."
    mkdir -p /usr/share/libalpm/hooks
    if [ -f usr/share/libalpm/hooks/gamescope-privs.hook ]; then
        cp -f usr/share/libalpm/hooks/gamescope-privs.hook /usr/share/libalpm/hooks/
        info "Installed Gamescope privileges hook."
    fi

    if [ -f /usr/bin/gamescope ]; then
        info "Applying immediate capabilities to gamescope binary..."
        setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    fi
}

# --- 4. Shim Layer (SteamOS compatibility) ---
setup_shim_links() {
    info "Creating SteamOS shim layer symlinks and helpers..."

    mkdir -p /usr/bin/steamos-polkit-helpers
    mkdir -p /usr/local/bin

    # 4.1 - SteamOS Polkit Helpers
    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-update.py /usr/bin/steamos-polkit-helpers/steamos-update
    ln -sf /usr/local/lib/steamos_diy/helpers/set-timezone.py /usr/bin/steamos-polkit-helpers/steamos-set-timezone
    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-dock-updater.py /usr/bin/steamos-polkit-helpers/jupiter-dock-updater

    # 4.2 - Core Session Binaries
    ln -sf /usr/local/lib/steamos_diy/session_launch.py /usr/bin/steamos-session-launch
    ln -sf /usr/local/lib/steamos_diy/session_select.py /usr/bin/steamos-session-select
    ln -sf /usr/local/lib/steamos_diy/sdy.py /usr/bin/sdy
    ln -sf /usr/local/lib/steamos_diy/sdy.py /usr/local/bin/sdy

    # 4.3 - DIY Tools
    ln -sf /usr/local/lib/steamos_diy/backup_tool.py /usr/bin/sdy-backup
    ln -sf /usr/local/lib/steamos_diy/restore.py /usr/bin/sdy-restore
    ln -sf /usr/local/lib/steamos_diy/control_center.py /usr/local/bin/sdy-control-center

    # 4.4 - System Helpers
    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py /usr/bin/jupiter-biosupdate
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-select-branch.py /usr/bin/steamos-select-branch
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-update.py /usr/bin/steamos-update

    success "All 15 symbolic links have been cross-linked correctly."
}

# --- 5. Systemd Service (Architecture Locking) ---
setup_systemd() {
    info "Configuring systemd service and locking architecture..."

    cp -f etc/systemd/system/steamos_diy.service /etc/systemd/system/

    # Patch for user and XDG runtime using {{USER}} and {{UID}} placeholders
    info "Patching service for user $REAL_USER (UID: $REAL_UID)"
    sed -i "s|{{USER}}|$REAL_USER|g" /etc/systemd/system/steamos_diy.service
    sed -i "s|{{UID}}|$REAL_UID|g" /etc/systemd/system/steamos_diy.service

    # HARD LOCK: Create the graphical.target.wants link manually
    mkdir -p /etc/systemd/system/graphical.target.wants
    ln -sf /etc/systemd/system/steamos_diy.service /etc/systemd/system/graphical.target.wants/steamos_diy.service

    info "Setting system default to graphical.target..."
    systemctl set-default graphical.target || true

    systemctl daemon-reload
    systemctl enable steamos_diy.service
}

# --- 6. Display Manager Management (Robust) ---
disable_display_managers() {
    info "Cleaning up conflicting Display Managers..."
    for dm in sddm gdm lightdm lxdm; do
        if systemctl is-enabled "$dm" &>/dev/null; then
            warn "Disabling $dm..."
            systemctl disable "$dm" || true
        fi
    done
}

# --- Execution Flow ---
info "Starting SteamMachine-DIY Installation for user: $REAL_USER"
ask_system_update
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
setup_systemd
disable_display_managers

success "INSTALLATION COMPLETE!"
info "Architecture: [graphical.target] -> [steamos_diy.service] -> [User: $REAL_USER]"
warn "A REBOOT IS REQUIRED to initialize the new graphics stack."

echo -e "${CYAN}>>> Reboot now? (y/n)${NC}"
read -r -p "> " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
