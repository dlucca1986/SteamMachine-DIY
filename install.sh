#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer
# VERSION:      1.4.0 - Ultra-Safe Driver Audit & Optimized Flow
# DESCRIPTION:  Hardware Audit, Dependency Management & Service Configuration.
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

# --- 1. Hardware & Driver Audit (Ultra-Safe) ---
check_gpu_and_drivers() {
    info "Auditing Hardware and Drivers..."
    GPU_INFO=$(lspci | grep -i vga)
    DRIVER_PKGS=""

    # --- NVIDIA Logic ---
    if echo "$GPU_INFO" | grep -iq "nvidia"; then
        if lsmod | grep -q "nvidia"; then
            warn "Active NVIDIA proprietary drivers detected. Skipping driver install."
        else
            info "Nvidia GPU detected (no proprietary driver). Suggesting Nouveau."
            DRIVER_PKGS="vulkan-nouveau lib32-vulkan-nouveau"
        fi

    # --- AMD Logic ---
    elif echo "$GPU_INFO" | grep -iq "amd"; then
        if lsmod | grep -q "amdgpu"; then
            warn "Active AMDGPU driver detected in kernel. Skipping driver install."
        else
            info "AMD GPU detected. Preparing Vulkan-Radeon."
            DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon"
        fi

    # --- Intel Logic ---
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

# --- 3. File Deployment & SSoT ---
deploy_files() {
    info "Deploying and personalizing files..."

    mkdir -p /etc/default
    cp etc/default/steamos_diy.conf /etc/default/steamos_diy.conf
    sed -i "s|/home/lelo|/home/$REAL_USER|g" /etc/default/steamos_diy.conf
    
    info "Deploying user configuration to $USER_HOME..."
    mkdir -p "$USER_HOME/.config/steamos_diy/games.d"
    cp etc/skel/.config/steamos_diy/*.yaml "$USER_HOME/.config/steamos_diy/"
    chown -R "$REAL_USER:$REAL_USER" "$USER_HOME/.config/steamos_diy"

    mkdir -p /usr/local/lib/steamos_diy/helpers
    cp -r usr/local/lib/steamos_diy/* /usr/local/lib/steamos_diy/
    chmod 755 /usr/local/lib/steamos_diy/*.py
    chmod 755 /usr/local/lib/steamos_diy/helpers/*.py

    mkdir -p /usr/local/share/applications
    cp usr/local/share/applications/*.desktop /usr/local/share/applications/

    mkdir -p /var/lib/steamos_diy
    if [ -f var/lib/steamos_diy/next_session ]; then
        cp var/lib/steamos_diy/next_session /var/lib/steamos_diy/next_session
    else
        echo "steam" > /var/lib/steamos_diy/next_session
    fi
    chown -R "$REAL_USER:$REAL_USER" /var/lib/steamos_diy
    chmod 775 /var/lib/steamos_diy
}

# --- 4. Shim Layer (Symlinks) ---
setup_shim_links() {
    info "Creating SteamOS shim layer symlinks..."
    mkdir -p /usr/bin/steamos-polkit-helpers
    mkdir -p /usr/local/bin

    ln -sf /usr/local/lib/steamos_diy/session_launch.py /usr/bin/steamos-session-launch
    ln -sf /usr/local/lib/steamos_diy/session_select.py /usr/bin/steamos-session-select
    ln -sf /usr/local/lib/steamos_diy/sdy.py /usr/bin/sdy
    ln -sf /usr/local/lib/steamos_diy/control_center.py /usr/local/bin/sdy-control-center
    
    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-update.py /usr/bin/steamos-polkit-helpers/steamos-update
    ln -sf /usr/local/lib/steamos_diy/helpers/set-timezone.py /usr/bin/steamos-polkit-helpers/steamos-set-timezone
}

# --- 5. Systemd Service ---
setup_systemd() {
    info "Configuring systemd service..."
    cp etc/systemd/system/steamos_diy.service /etc/systemd/system/
    sed -i "s/%u/$REAL_USER/g" /etc/systemd/system/steamos_diy.service
    
    systemctl daemon-reload
    systemctl enable steamos_diy.service
}

# --- 6. Display Manager Management ---
disable_display_managers() {
    info "Disabling standard Display Managers to avoid TTY1 conflicts..."
    for dm in sddm gdm lightdm lxdm; do
        if systemctl is-enabled "$dm" &>/dev/null; then
            warn "Disabling $dm service..."
            systemctl disable "$dm"
        fi
    done
}

# --- Execution Flow ---
info "Starting installation for user: $REAL_USER (UID: $REAL_UID)"
ask_system_update
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
setup_systemd
disable_display_managers

finalize() {
    success "INSTALLATION COMPLETE!"
    info "The DIY Steam Session will take control of TTY1 on next boot."
    success "Please REBOOT now."
}
finalize
