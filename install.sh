#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer
# VERSION:      1.3.4 - Sync-Enabled Production Ready
# DESCRIPTION:  Hardware Audit, Dependency Management, SSoT Patching & Systemd.
# PHILOSOPHY:   KISS (Keep It Simple, Stupid)
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# LICENSE:      MIT
# =============================================================================

set -e

# --- Colors & UI Elements ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info() { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- Root Privilege Check ---
if [ "$EUID" -ne 0 ]; then
    error "Elevated privileges required. Please run as root (sudo ./install.sh)"
    exit 1
fi

# --- Environment Detection ---
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
REAL_UID=$(id -u "$REAL_USER")

# --- 1. Hardware Audit & Driver Selection ---
check_gpu_and_drivers() {
    info "Auditing Hardware and Graphics Stack..."
    GPU_INFO=$(lspci | grep -iE "vga|3d controller")
    DRIVER_PKGS=""

    if echo "$GPU_INFO" | grep -iq "nvidia"; then
        if pacman -Qq nvidia &>/dev/null; then
            info "Nvidia GPU detected. Proprietary driver active — preparing userspace utilities..."
            DRIVER_PKGS="nvidia-utils lib32-nvidia-utils"
        else
            info "Nvidia GPU detected. NVK/Nouveau active — preparing Mesa Vulkan stack..."
            DRIVER_PKGS="mesa lib32-mesa"
        fi
    elif echo "$GPU_INFO" | grep -iq "amd"; then
        info "AMD GPU detected. Preparing RADV and Mesa layers..."
        DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon vulkan-mesa-layers lib32-vulkan-mesa-layers libva-mesa-driver lib32-libva-mesa-driver mesa lib32-mesa"
    elif echo "$GPU_INFO" | grep -iq "intel"; then
        info "Intel GPU detected. Preparing ANV and Mesa layers..."
        DRIVER_PKGS="vulkan-intel lib32-vulkan-intel vulkan-mesa-layers lib32-vulkan-mesa-layers libva-intel-driver lib32-libva-intel-driver mesa lib32-mesa"
    else
        warn "GPU not recognized. Skipping driver-specific packages."
    fi
}

# --- 2. Dependency Management & Database Sync ---
install_dependencies() {
    # 2.1. Enable Multilib for 32-bit gaming support
    if ! grep -q "^\[multilib\]" /etc/pacman.conf; then
        info "Enabling multilib repository..."
        echo -e "\n[multilib]\nInclude = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
    fi

    # Core system and gaming dependencies
    BASE_PKGS="python python-pyqt6 python-yaml python-ruamel-yaml steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader vulkan-tools mesa-utils pciutils procps-ng qt6-tools rsync gcc"

    info "Synchronizing package databases and installing core dependencies..."
    pacman -Syu --needed --noconfirm $BASE_PKGS $DRIVER_PKGS

    info "Configuring system groups for user: $REAL_USER"
    # TTY group is essential for Python notify() to write to /dev/tty1
    for grp in tty video render input audio wheel storage autologin systemd-journal gamemode; do
        groupadd -f "$grp"
        usermod -aG "$grp" "$REAL_USER"
    done
}

# --- 3. File Deployment & SSoT Initialization ---
deploy_files() {
    info "Deploying Single Source of Truth (SSoT) and configurations..."

    # Initialize Global SSoT Configuration
    mkdir -p /etc/default
    if [ -f etc/default/steamos_diy.conf ]; then
        cp -f etc/default/steamos_diy.conf /etc/default/steamos_diy.conf
        info "Patching SSoT with User Home: $USER_HOME"
        sed -i "s|{{HOME}}|$USER_HOME|g" /etc/default/steamos_diy.conf
    fi

    # --- Deploy User-space Configurations (with Safety Check) ---
    local CONFIG_DEST="$USER_HOME/.config/steamos_diy"
    local CONFIG_SRC="etc/skel/.config/steamos_diy"

    # Check for existing user YAML configs BEFORE creating directories
    local HAS_EXISTING_YAML=false
    compgen -G "$CONFIG_DEST/*.yaml" > /dev/null 2>&1 && HAS_EXISTING_YAML=true

    mkdir -p "$CONFIG_DEST/games.d"

    if $HAS_EXISTING_YAML; then
        warn "Existing configuration found in $CONFIG_DEST"
        read -r -p "Do you want to overwrite existing YAML configs? (y/N): " overwrite_configs
        if [[ "$overwrite_configs" =~ ^[Yy]$ ]]; then
            info "Overwriting configurations as requested..."
            cp -f "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
        else
            info "Preserving custom settings. Only deploying new configuration files..."
            cp -n "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/" 2>/dev/null || true
        fi
    elif [ -d "$CONFIG_SRC" ]; then
        # Fresh installation flow
        cp -f "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
    fi
    chown -R "$REAL_USER:$REAL_USER" "$CONFIG_DEST"

    # Deploy Python Core Libraries, Helpers & C-Core
    LIB_DIR="/usr/local/lib/steamos_diy"
    mkdir -p "$LIB_DIR/helpers"

    info "Installing Python modules and helpers..."
    cp -rf usr/local/lib/steamos_diy/* "$LIB_DIR/"

    info "Building C-Core from source (steamos_diy_core.c)..."
    gcc -O2 -fPIC -Wall -shared -o "$LIB_DIR/libcore.so" steamos_diy_core.c \
        || { error "C-Core compilation failed. Check gcc output above."; exit 1; }
    python3 -c "import ctypes; ctypes.CDLL('$LIB_DIR/libcore.so')" 2>/dev/null \
        || { error "libcore.so compiled but is not loadable. Check architecture/dependencies."; exit 1; }
    info "C-Core verified and loadable."

    # Set strict permissions: readable utils/libs, executable binaries
    chmod 755 "$LIB_DIR"
    chmod 644 "$LIB_DIR/utils.py"
    chmod 644 "$LIB_DIR/libcore.so"
    chmod +x "$LIB_DIR"/*.py
    chmod +x "$LIB_DIR/helpers"/*.py

    # Initialize Session State tracking
    mkdir -p /var/lib/steamos_diy
    [ ! -f /var/lib/steamos_diy/next_session ] && echo "steam" > /var/lib/steamos_diy/next_session
    chown -R "$REAL_USER:$REAL_USER" /var/lib/steamos_diy
    chmod 775 /var/lib/steamos_diy

    # --- Desktop Entries ---
    info "Installing desktop applications entries..."
    mkdir -p /usr/local/share/applications
    [ -f usr/local/share/applications/Control_Center.desktop ] && cp -f usr/local/share/applications/Control_Center.desktop /usr/local/share/applications/
    [ -f usr/local/share/applications/Game_Mode.desktop ] && cp -f usr/local/share/applications/Game_Mode.desktop /usr/local/share/applications/

    # --- ALPM Hooks ---
    info "Installing Pacman hooks..."
    mkdir -p /usr/share/libalpm/hooks
    [ -f usr/share/libalpm/hooks/gamescope-privs.hook ] && cp -f usr/share/libalpm/hooks/gamescope-privs.hook /usr/share/libalpm/hooks/

    # Grant Gamescope necessary capabilities for performance
    if [ -f /usr/bin/gamescope ]; then
        info "Applying Real-Time capabilities to Gamescope..."
        setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    fi
}

# --- 4. SteamOS Compatibility Shim Layer ---
setup_shim_links() {
    info "Constructing SteamOS Compatibility Layer (Shims)..."
    
    local HELPERS="/usr/local/lib/steamos_diy/helpers"
    local CORE="/usr/local/lib/steamos_diy"

    # Polkit Helper Structure (Intercepts Steam Deck UI Settings)
    mkdir -p /usr/bin/steamos-polkit-helpers
    ln -sf "$HELPERS/jupiter-biosupdate.py"    /usr/bin/steamos-polkit-helpers/jupiter-biosupdate
    ln -sf "$HELPERS/steamos-update.py"       /usr/bin/steamos-polkit-helpers/steamos-update
    ln -sf "$HELPERS/set-timezone.py"         /usr/bin/steamos-polkit-helpers/steamos-set-timezone
    ln -sf "$HELPERS/jupiter-dock-updater.py" /usr/bin/steamos-polkit-helpers/jupiter-dock-updater

    # System Integration (Steam Client hardcoded paths)
    ln -sf "$CORE/session_launch.py"          /usr/bin/steamos-session-launch
    ln -sf "$CORE/session_select.py"          /usr/bin/steamos-session-select
    ln -sf "$HELPERS/steamos-select-branch.py" /usr/bin/steamos-select-branch
    
    # Direct Aliases for Global Visibility
    ln -sf /usr/bin/steamos-polkit-helpers/jupiter-biosupdate    /usr/bin/jupiter-biosupdate
    ln -sf /usr/bin/steamos-polkit-helpers/steamos-update        /usr/bin/steamos-update
    ln -sf /usr/bin/steamos-polkit-helpers/steamos-set-timezone /usr/bin/steamos-set-timezone

    # Administrative & CLI Tools
    ln -sf "$CORE/sdy.py"                    /usr/local/bin/sdy
    ln -sf "$CORE/control_center.py"         /usr/local/bin/sdy-control-center
    ln -sf "$CORE/backup.py"                 /usr/local/bin/sdy-backup
    ln -sf "$CORE/restore.py"                /usr/local/bin/sdy-restore

    chmod +x /usr/bin/steamos-polkit-helpers/*
}

# --- 5. Boot & Systemd Configuration ---
setup_systemd_lockdown() {
    info "Configuring Systemd for Console Lockdown (TTY1)..."
    
    # Prevent Getty from interfering with Gamescope on TTY1
    systemctl mask getty@tty1.service
    
    # Deploy and personalize the main service
    if [ -f etc/systemd/system/steamos_diy.service ]; then
        cp -f etc/systemd/system/steamos_diy.service /etc/systemd/system/
        sed -i "s|{{USER}}|$REAL_USER|g" /etc/systemd/system/steamos_diy.service
        sed -i "s|{{UID}}|$REAL_UID|g" /etc/systemd/system/steamos_diy.service
    fi

    # Refresh systemd state and set default target
    systemctl daemon-reload
    systemctl enable steamos_diy.service
    systemctl set-default graphical.target
}

# --- 6. Cleanup ---
disable_display_managers() {
    info "Disabling conflicting Display Managers..."
    # Including 'plasmalogin' for Plasma 6 support and other common DMs
    for dm in sddm plasmalogin; do
        systemctl disable "$dm" 2>/dev/null || true
    done
}

# --- Execution Flow ---
info "Initializing SteamMachine-DIY Deployment for user: $REAL_USER"
check_gpu_and_drivers
install_dependencies
deploy_files
setup_shim_links
setup_systemd_lockdown
disable_display_managers

success "INSTALLATION COMPLETED SUCCESSFULLY!"
info "TTY1 is now owned by steamos_diy.service."
warn "A system reboot is mandatory to initialize the DIY environment."

read -r -p "Reboot now? (y/n): " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
