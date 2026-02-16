#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer 
# VERSION:      1.2.1 - Unified Agnostic Logic
# DESCRIPTION:  Installer with Hardware Audit & Template Personalization.
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
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
    SKIP_DRIVERS=false
    DRIVER_PKGS=""

    if echo "$GPU_INFO" | grep -iq "nvidia"; then
        if lsmod | grep -q "nvidia"; then
            warn "Proprietary Nvidia drivers detected. SKIPPING open-source driver install."
            SKIP_DRIVERS=true
        else
            info "Nvidia GPU detected (no proprietary drivers). Suggesting Nouveau."
            DRIVER_PKGS="vulkan-nouveau lib32-vulkan-nouveau"
        fi
    elif echo "$GPU_INFO" | grep -iq "amd"; then
        info "AMD GPU detected."
        if pacman -Qs "vulkan-radeon" > /dev/null; then
            warn "AMD Vulkan drivers already detected. Skipping driver re-installation."
            SKIP_DRIVERS=true
        else
            info "Suggesting vulkan-radeon for AMD hardware."
            DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon"
        fi
    elif echo "$GPU_INFO" | grep -iq "intel"; then
        info "Intel GPU detected."
        if pacman -Qs "vulkan-intel" > /dev/null; then
            warn "Intel Vulkan drivers already detected. Skipping driver re-installation."
            SKIP_DRIVERS=true
        else
            info "Suggesting vulkan-intel for Intel hardware."
            DRIVER_PKGS="vulkan-intel lib32-vulkan-intel"
        fi
    fi
}

# --- 2. Dependencies & Repositories ---
install_dependencies() {
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        info "Enabling multilib repository..."
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
        pacman -Sy
    fi

    echo -ne "${YELLOW}Update system (pacman -Syu) first? [y/N] ${NC}"
    read -r confirm_update
    [[ $confirm_update == [yY] ]] && pacman -Syu --noconfirm

    BASE_PKGS="steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng"
    
    info "Installing core dependencies..."
    pacman -S --needed --noconfirm $BASE_PKGS

    if [[ "$SKIP_DRIVERS" == "false" && -n "$DRIVER_PKGS" ]]; then
        info "Installing drivers: $DRIVER_PKGS"
        pacman -S --needed --noconfirm $DRIVER_PKGS
    fi
}

# --- 3. File Deployment & Personalization ---
deploy_files() {
    info "Deploying and personalizing files..."

    # 3.1 SSOTH Config
    if [ -f etc/default/steamos_diy.conf ]; then
        cp etc/default/steamos_diy.conf /etc/default/steamos_diy.conf
        sed -i "s|\[USERNAME\]|$REAL_USER|g" /etc/default/steamos_diy.conf
        sed -i "s|\[USERID\]|$REAL_UID|g" /etc/default/steamos_diy.conf
    fi

    # 3.2 TTY1 Autologin
    mkdir -p /etc/systemd/system/getty@tty1.service.d/
    if [ -f etc/systemd/system/getty@tty1.service.d/override.conf ]; then
        cp etc/systemd/system/getty@tty1.service.d/override.conf /etc/systemd/system/getty@tty1.service.d/
        sed -i "s|\[USERNAME\]|$REAL_USER|g" /etc/systemd/system/getty@tty1.service.d/override.conf
    fi

    # 3.3 Core Library & Helpers
    mkdir -p /usr/local/lib/steamos_diy/helpers
    cp -r usr/local/lib/steamos_diy/* /usr/local/lib/steamos_diy/
    chmod 755 /usr/local/lib/steamos_diy/*.py
    chmod 755 /usr/local/lib/steamos_diy/helpers/*.py

    # 3.4 Gamescope Caps & Hook
    [ -f /usr/bin/gamescope ] && setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    mkdir -p /usr/share/libalpm/hooks/
    [ -f usr/share/libalpm/hooks/gamescope-privs.hook ] && cp usr/share/libalpm/hooks/gamescope-privs.hook /usr/share/libalpm/hooks/

    # 3.5 State Directory
    mkdir -p /var/lib/steamos_diy
    chown "$REAL_USER:$REAL_USER" /var/lib/steamos_diy

    # 3.6 Skel & Home
    info "Configuring user environment..."
    mkdir -p /etc/skel/.config/steamos_diy
    cp -r etc/skel/.config/steamos_diy/* /etc/skel/.config/steamos_diy/ 2>/dev/null || true
    [ -f etc/skel/.bash_profile ] && cp etc/skel/.bash_profile /etc/skel/

    mkdir -p "$USER_HOME/.config/steamos_diy"
    cp -r etc/skel/.config/steamos_diy/* "$USER_HOME/.config/steamos_diy/" 2>/dev/null || true
    
    # Sostituzione placeholder nei config utente
    find "$USER_HOME/.config/steamos_diy" -type f -exec sed -i "s|\[USERNAME\]|$REAL_USER|g" {} +

    # Sync .bash_profile
    if [ -f etc/skel/.bash_profile ]; then
        cp etc/skel/.bash_profile "$USER_HOME/.bash_profile"
    fi

    chown -R "$REAL_USER:$REAL_USER" "$USER_HOME/.config/steamos_diy"
    chown "$REAL_USER:$REAL_USER" "$USER_HOME/.bash_profile"
}

# --- 4. Shim Layer (Symlinks) ---
setup_shim_links() {
    info "Creating SteamOS shim layer symlinks..."
    mkdir -p /usr/bin/steamos-polkit-helpers

    ln -sf /usr/local/lib/steamos_diy/session_launch.py /usr/bin/steamos-session-launch
    ln -sf /usr/local/lib/steamos_diy/session_select.py /usr/bin/steamos-session-select
    ln -sf /usr/local/lib/steamos_diy/sdy.py /usr/bin/sdy

    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py /usr/bin/jupiter-biosupdate
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-select-branch.py /usr/bin/steamos-select-branch
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-update.py /usr/bin/steamos-update
    
    ln -sf /usr/local/lib/steamos_diy/helpers/jupiter-biosupdate.py /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    ln -sf /usr/local/lib/steamos_diy/helpers/steamos-update.py /usr/bin/steamos-polkit-helpers/steamos-update
    ln -sf /usr/local/lib/steamos_diy/helpers/set-timezone.py /usr/bin/steamos-polkit-helpers/steamos-set-timezone
}

# --- 5. Display Manager Management ---
manage_display_manager() {
    info "Managing Display Managers..."
    CURRENT_DM=$(systemctl list-unit-files --type=service | grep display-manager | awk '{print $1}' | head -n 1) || true
    
    if [[ -n "$CURRENT_DM" ]]; then
        warn "Detected active Display Manager: $CURRENT_DM"
        echo -ne "${YELLOW}Disable $CURRENT_DM to boot directly into Game Mode? [y/N] ${NC}"
        read -r confirm_dm
        if [[ $confirm_dm == [yY] ]]; then
            systemctl disable "$CURRENT_DM"
            success "$CURRENT_DM disabled."
        fi
    fi
}

# --- 6. Finalization ---
finalize() {
    systemctl daemon-reload
    systemctl enable getty@tty1.service
    echo -e "\n${GREEN}==================================================${NC}"
    success "INSTALLATION COMPLETE!"
    warn "Please REBOOT to enter Game Mode."
    echo -e "${GREEN}==================================================${NC}\n"
}

# --- Execution Flow ---
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
manage_display_manager
finalize
