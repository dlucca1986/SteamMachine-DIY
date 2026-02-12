#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer 
# VERSION:      1.0.0
# DESCRIPTION:  Installer Tool.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# LICENSE:      MIT
# =============================================================================

set -e # Exit on error

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

# --- Identity Detection ---
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./install.sh)"
    exit 1
fi

REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

info "Starting installation for user: $REAL_USER"
info "Home directory: $USER_HOME"

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

    echo -ne "${YELLOW}Highly recommended: Update system (pacman -Syu) first? [y/N] ${NC}"
    read -r confirm_update
    if [[ $confirm_update == [yY] ]]; then
        pacman -Syu --noconfirm
    fi

    BASE_PKGS="steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader mesa-utils python-pyqt6 pciutils procps-ng"
    
    info "Installing core dependencies..."
    pacman -S --needed --noconfirm $BASE_PKGS

    if [[ "$SKIP_DRIVERS" == "false" && -n "$DRIVER_PKGS" ]]; then
        info "Installing open-source drivers: $DRIVER_PKGS"
        pacman -S --needed --noconfirm $DRIVER_PKGS
    fi
}

# --- 3. File Deployment (Overlay) ---
deploy_files() {
    info "Deploying system and user files (Overlay)..."

    # --- 1. System Config & SSOTH ---
    if [ -f etc/default/steamos-diy ]; then
        cp etc/default/steamos-diy /etc/default/
        sed -i "s/\[USERNAME\]/$REAL_USER/g" /etc/default/steamos-diy
        sed -i "s/\[USERID\]/$(id -u $REAL_USER)/g" /etc/default/steamos-diy
    fi

    # --- 2. TTY1 Autologin Override ---
    mkdir -p /etc/systemd/system/getty@tty1.service.d/
    if [ -f etc/systemd/system/getty@tty1.service.d/override.conf ]; then
        cp etc/systemd/system/getty@tty1.service.d/override.conf /etc/systemd/system/getty@tty1.service.d/
        sed -i "s/\[USERNAME\]/$REAL_USER/g" /etc/systemd/system/getty@tty1.service.d/override.conf
    fi
    
    # 3.1 Gamescope Capabilities & Hook
    info "Setting Gamescope capabilities and Pacman hook..."
    if [ -f /usr/bin/gamescope ]; then
       setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    fi
    mkdir -p /usr/share/libalpm/hooks/
    [ -f usr/share/libalpm/hooks/gamescope-privs.hook ] && cp usr/share/libalpm/hooks/gamescope-privs.hook /usr/share/libalpm/hooks/

    # Binaries
    mkdir -p /usr/local/bin/steamos-helpers
    
    info "Copying binaries to /usr/local/bin..."
    cp usr/local/bin/steamos-* /usr/local/bin/ 2>/dev/null || true
    cp usr/local/bin/sdy /usr/local/bin/ 2>/dev/null || true
    cp usr/local/bin/restore_system /usr/local/bin/ 2>/dev/null || true
    cp usr/local/bin/backup_system /usr/local/bin/ 2>/dev/null || true
    cp usr/local/bin/steamos-helpers/* /usr/local/bin/steamos-helpers/ 2>/dev/null || true
    chmod +x /usr/local/bin/steamos-* \
             /usr/local/bin/sdy \
             /usr/local/bin/restore_system \
             /usr/local/bin/backup_system \
             /usr/local/bin/steamos-helpers/* 2>/dev/null || true

    # Applications (.desktop) & Database Refresh
    mkdir -p /usr/local/share/applications/
    cp usr/local/share/applications/*.desktop /usr/local/share/applications/ 2>/dev/null || true
    update-desktop-database /usr/local/share/applications 2>/dev/null || true

    # Skel & Home
    mkdir -p /etc/skel/.config/steamOs
    [ -f etc/skel/.bash_profile ] && cp etc/skel/.bash_profile /etc/skel/
    cp -r etc/skel/.config/steamOs/* /etc/skel/.config/steamOs/ 2>/dev/null || true

    mkdir -p "$USER_HOME/.config/steamOs"
    cp -r etc/skel/.config/steamOs/* "$USER_HOME/.config/steamOs/" 2>/dev/null || true
    
    chown -R "$REAL_USER:$REAL_USER" "$USER_HOME/.config/steamOs"
}

# --- 4. Shim Layer (Symlinks) ---
setup_shim_links() {
    info "Creating SteamOS shim layer (symlinks)..."
    mkdir -p /usr/bin/steamos-polkit-helpers

    ln -sf /usr/local/bin/steamos-session-select /usr/bin/steamos-session-select
    ln -sf /usr/local/bin/steamos-helpers/steamos-update /usr/bin/steamos-update
    ln -sf /usr/local/bin/steamos-helpers/steamos-update /usr/bin/steamos-polkit-helpers/steamos-update
    ln -sf /usr/local/bin/steamos-helpers/jupiter-biosupdate /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    ln -sf /usr/local/bin/steamos-helpers/steamos-set-timezone /usr/bin/steamos-polkit-helpers/steamos-set-timezone
}

# --- 5. Bash Profile Integration ---
setup_bash_profile() {
    info "Configuring .bash_profile..."
    BP_FILE="$USER_HOME/.bash_profile"
    
    # Crea il file se non esiste
    [ ! -f "$BP_FILE" ] && touch "$BP_FILE"

    if ! grep -q "steamos-session-launch" "$BP_FILE"; then
        # Scrittura del blocco tra i nuovi tag BEGIN/END
        cat << EOF >> "$BP_FILE"

# --- BEGIN STEAMOS-DIY TRIGGER ---
if [[ -z \$DISPLAY && \$XDG_VTNR -eq 1 ]]; then
    LAUNCHER="/usr/local/bin/steamos-session-launch"
    if [[ -x "\$LAUNCHER" ]]; then
        [[ -f /etc/default/steamos-diy ]] && . /etc/default/steamos-diy
        exec "\$LAUNCHER" >/dev/null 2>&1
    fi
fi
[[ -f ~/.bashrc ]] && . ~/.bashrc
# --- END STEAMOS-DIY TRIGGER ---
EOF
        # Imposta correttamente il proprietario del file
        chown "$REAL_USER:$REAL_USER" "$BP_FILE"
        success "Trigger added to .bash_profile"
    else
        info "Trigger already exists in .bash_profile"
    fi
}

# --- 6. Display Managers ---
manage_display_manager() {
    info "Checking for active Display Managers..."
    
    CURRENT_DM=$(systemctl list-unit-files --type=service | grep display-manager | awk '{print $1}') || true
    
    if [[ -z "$CURRENT_DM" ]]; then
        for dm in sddm gdm lightdm lxdm; do
            if systemctl is-enabled "$dm" &>/dev/null; then
                CURRENT_DM="$dm"
                break
            fi
        done
    fi

    if [[ -n "$CURRENT_DM" ]]; then
        warn "Detected active Display Manager: $CURRENT_DM"
        echo -ne "${YELLOW}To boot directly into Game Mode, we need to disable $CURRENT_DM. Proceed? [y/N] ${NC}"
        read -r confirm_dm
        if [[ $confirm_dm == [yY] ]]; then
            systemctl disable "$CURRENT_DM"
            success "$CURRENT_DM disabled. TTY1 is now free for SteamMachine-DIY."
        else
            warn "Display Manager remains enabled. This MIGHT cause conflicts with Game Mode."
        fi
    else
        info "No Display Manager detected. TTY1 is clear."
    fi
}

# --- 7. Finalization ---
finalize_system() {
    info "Reloading system daemons..."
    systemctl daemon-reload
    systemctl enable getty@tty1.service
    
    echo -e "\n${GREEN}==================================================${NC}"
    success "INSTALLATION COMPLETE!"
    echo -e "${GREEN}==================================================${NC}"
    warn "Please REBOOT your system to enter Game Mode."
    echo -e "SteamMachine-DIY is now configured for user: $REAL_USER"
    echo -e "${GREEN}==================================================${NC}\n"
}

# --- Execution ---
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
setup_bash_profile
manage_display_manager
finalize_system
