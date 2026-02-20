#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer
# VERSION:      1.2.0 - DM Management & SSoT Optimized
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

info "Starting installation for user: $REAL_USER (UID: $REAL_UID)"

# --- 1. Hardware & Driver Audit ---
check_gpu_and_drivers() {
    info "Auditing Hardware and Drivers..."
    GPU_INFO=$(lspci | grep -i vga)
    DRIVER_PKGS=""

    if echo "$GPU_INFO" | grep -iq "nvidia"; then
        if lsmod | grep -q "nvidia"; then
            warn "Proprietary Nvidia drivers detected. SKIPPING open-source driver install."
        else
            info "Nvidia GPU detected. Suggesting Nouveau."
            DRIVER_PKGS="vulkan-nouveau lib32-vulkan-nouveau"
        fi
    elif echo "$GPU_INFO" | grep -iq "amd"; then
        info "AMD GPU detected."
        pacman -Qs "vulkan-radeon" > /dev/null || DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon"
    elif echo "$GPU_INFO" | grep -iq "intel"; then
        info "Intel GPU detected."
        pacman -Qs "vulkan-intel" > /dev/null || DRIVER_PKGS="vulkan-intel lib32-vulkan-intel"
    fi
}

# --- 2. Dependencies & Groups ---
install_dependencies() {
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        info "Enabling multilib repository..."
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    # Added python-ruamel-yaml for Control Center compatibility
    BASE_PKGS="python python-pyqt6 python-yaml python-ruamel-yaml steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils pciutils procps-ng"    
    
    info "Installing core dependencies..."
    pacman -S --needed --noconfirm $BASE_PKGS

    if [[ -n "$DRIVER_PKGS" ]]; then
        info "Installing drivers: $DRIVER_PKGS"
        pacman -S --needed --noconfirm $DRIVER_PKGS
    fi

    info "Updating user groups for $REAL_USER..."
    # Including systemd-journal for Control Center log access
    for grp in video render input audio wheel storage autologin systemd-journal; do
        groupadd -f "$grp"
        usermod -aG "$grp" "$REAL_USER"
    done
}

# --- 3. File Deployment & SSoT ---
deploy_files() {
    info "Deploying and personalizing files..."

    # 3.1 SSOTH Config (The Agnostic SSoT)
    mkdir -p /etc/default
    cp etc/default/steamos_diy.conf /etc/default/steamos_diy.conf
    sed -i "s|/home/lelo|/home/$REAL_USER|g" /etc/default/steamos_diy.conf
    
    # 3.2 User Config (Skel to Home)
    info "Deploying user configuration to $USER_HOME..."
    mkdir -p "$USER_HOME/.config/steamos_diy/games.d"
    cp etc/skel/.config/steamos_diy/*.yaml "$USER_HOME/.config/steamos_diy/"
    chown -R "$REAL_USER:$REAL_USER" "$USER_HOME/.config/steamos_diy"

    # 3.3 Core Library & Helpers
    mkdir -p /usr/local/lib/steamos_diy/helpers
    cp -r usr/local/lib/steamos_diy/* /usr/local/lib/steamos_diy/
    chmod 755 /usr/local/lib/steamos_diy/*.py
    chmod 755 /usr/local/lib/steamos_diy/helpers/*.py

    # 3.4 Applications & Icons
    mkdir -p /usr/local/share/applications
    cp usr/local/share/applications/*.desktop /usr/local/share/applications/

    # 3.5 State Directory
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
    # Common Display Managers list
    for dm in sddm gdm lightdm lxdm; do
        if systemctl is-enabled "$dm" &>/dev/null; then
            warn "Disabling $dm service..."
            systemctl disable "$dm"
        fi
    done
    success "Display Managers disabled. Your DIY service will manage the session."
}

# --- Execution Flow ---
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
setup_systemd
disable_display_managers

finalize() {
    success "INSTALLATION COMPLETE! Please REBOOT."
}
finalize
