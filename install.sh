#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Installer
# VERSION:      2.1.5
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

# --- Execution Mode ---
# --update: non-interactive upgrade over an existing installation.
# Preserves the live SSoT and user YAMLs, wipes the lib dir so files
# dropped by the new release cannot linger, then reboots on a countdown.
UPDATE_MODE=false
for arg in "$@"; do
    case "$arg" in
        --update) UPDATE_MODE=true ;;
        *) error "Unknown option: $arg (supported: --update)"; exit 1 ;;
    esac
done

# Run from the project root regardless of the caller's cwd — pkexec
# (Control Center one-click update) starts programs in root's home,
# and every deploy below uses paths relative to the repository root.
cd "$(dirname "$(readlink -f "$0")")"

# --- Environment Detection ---
# pkexec (Control Center one-click update) exposes PKEXEC_UID instead of
# SUDO_USER — resolve both, or user files would land in /root.
if [ -n "${SUDO_USER:-}" ]; then
    REAL_USER="$SUDO_USER"
elif [ -n "${PKEXEC_UID:-}" ]; then
    REAL_USER=$(id -nu "$PKEXEC_UID")
else
    REAL_USER=$(whoami)
fi
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
REAL_UID=$(id -u "$REAL_USER")

# --- Filesystem Layout (shared contract with utils.py constants) ---
readonly LIB_DIR="/usr/local/lib/steamos_diy"
readonly HELPERS_DIR="$LIB_DIR/helpers"
readonly POLKIT_DIR="/usr/bin/steamos-polkit-helpers"
readonly BIN_DIR="/usr/local/bin"
readonly SSOT_CONF="/etc/default/steamos_diy.conf"
readonly SERVICE_FILE="/etc/systemd/system/steamos_diy.service"
readonly STATE_DIR="/var/lib/steamos_diy"
readonly APP_DIR="/usr/local/share/applications"
readonly ALPM_HOOKS_DIR="/usr/share/libalpm/hooks"
readonly USER_CONFIG_REL=".config/steamos_diy"

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
        DRIVER_PKGS="vulkan-radeon lib32-vulkan-radeon vulkan-mesa-layers lib32-vulkan-mesa-layers mesa lib32-mesa"
    elif echo "$GPU_INFO" | grep -iq "intel"; then
        info "Intel GPU detected. Preparing ANV and Mesa layers..."
        DRIVER_PKGS="vulkan-intel lib32-vulkan-intel vulkan-mesa-layers lib32-vulkan-mesa-layers intel-media-driver libva-intel-driver lib32-libva-intel-driver mesa lib32-mesa"
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
    BASE_PKGS="python python-pyqt6 python-ruamel-yaml steam gamescope xorg-xwayland mangohud lib32-mangohud gamemode lib32-gamemode vulkan-icd-loader lib32-vulkan-icd-loader vulkan-tools pciutils gcc"

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
    mkdir -p "$(dirname "$SSOT_CONF")"
    if [ -f etc/default/steamos_diy.conf ]; then
        RENDERED_SSOT=$(mktemp)
        cp -f etc/default/steamos_diy.conf "$RENDERED_SSOT"
        sed -i "s|{{HOME}}|$USER_HOME|g" "$RENDERED_SSOT"
        if $UPDATE_MODE && [ -f "$SSOT_CONF" ]; then
            # Never clobber the live SSoT on update: user edits survive.
            # Stage the new template as .new (pacnew-style), but only when
            # it changed since the last deploy (pristine copy in STATE_DIR)
            # so users are not trained to ignore a .new on every update.
            if ! cmp -s "$RENDERED_SSOT" "$STATE_DIR/ssot.template" 2>/dev/null; then
                cp -f "$RENDERED_SSOT" "${SSOT_CONF}.new"
                warn "SSoT template changed: review ${SSOT_CONF}.new"
            fi
        else
            info "Patching SSoT with User Home: $USER_HOME"
            cp -f "$RENDERED_SSOT" "$SSOT_CONF"
        fi
        mkdir -p "$STATE_DIR"
        cp -f "$RENDERED_SSOT" "$STATE_DIR/ssot.template"
        rm -f "$RENDERED_SSOT"
    fi

    # --- Deploy User-space Configurations (with Safety Check) ---
    local CONFIG_DEST="$USER_HOME/$USER_CONFIG_REL"
    local CONFIG_SRC="etc/skel/$USER_CONFIG_REL"

    # Check for YAMLs on both sides BEFORE creating dest dirs. The src check
    # is the guard that prevents 'cp -f .../*.yaml' from crashing under
    # `set -e` when CONFIG_SRC exists but is empty (default bash glob does
    # not expand to nothing — it stays literal and the cp fails).
    local HAS_EXISTING_YAML=false
    local HAS_SRC_YAML=false
    compgen -G "$CONFIG_DEST/*.yaml" > /dev/null 2>&1 && HAS_EXISTING_YAML=true
    compgen -G "$CONFIG_SRC/*.yaml" > /dev/null 2>&1 && HAS_SRC_YAML=true

    mkdir -p "$CONFIG_DEST/games.d"

    if ! $HAS_SRC_YAML; then
        info "No template YAML configs to deploy in $CONFIG_SRC; skipping."
    elif $HAS_EXISTING_YAML; then
        if $UPDATE_MODE; then
            info "Update mode: preserving custom settings. Only deploying new configuration files..."
            cp -n "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
        else
            warn "Existing configuration found in $CONFIG_DEST"
            read -r -p "Do you want to overwrite existing YAML configs? (y/N): " overwrite_configs
            if [[ "$overwrite_configs" =~ ^[Yy]$ ]]; then
                info "Overwriting configurations as requested..."
                cp -f "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
            else
                info "Preserving custom settings. Only deploying new configuration files..."
                cp -n "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
            fi
        fi
    else
        # Fresh installation: no existing user configs, templates available.
        cp -f "$CONFIG_SRC"/*.yaml "$CONFIG_DEST/"
    fi
    chown -R "$REAL_USER:$REAL_USER" "$CONFIG_DEST"

    # Deploy Python Core Libraries, Helpers & C-Core
    if $UPDATE_MODE; then
        # Wipe first so files removed or renamed by the new release
        # cannot linger and shadow the fresh deployment.
        info "Update mode: clearing $LIB_DIR before redeploy..."
        rm -rf "$LIB_DIR"
    fi
    mkdir -p "$HELPERS_DIR"

    info "Installing Python modules and helpers..."
    cp -rf usr/local/lib/steamos_diy/* "$LIB_DIR/"

    info "Building C-Core from source (steamos_diy_core.c)..."
    # CFLAGS must match Makefile so dev (make) and prod (install.sh) builds agree.
    gcc -O2 -march=native -fPIC -Wall -Wextra -shared -o "$LIB_DIR/libcore.so" steamos_diy_core.c \
        || { error "C-Core compilation failed. Check gcc output above."; exit 1; }
    python3 -c "import ctypes; ctypes.CDLL('$LIB_DIR/libcore.so')" 2>/dev/null \
        || { error "libcore.so compiled but is not loadable. Check architecture/dependencies."; exit 1; }
    info "C-Core verified and loadable."

    chmod 755 "$LIB_DIR"
    chmod 644 "$LIB_DIR/libcore.so"
    chmod +x "$LIB_DIR"/*.py
    chmod +x "$HELPERS_DIR"/*.py

    # Initialize Session State tracking
    mkdir -p "$STATE_DIR"
    [ ! -f "$STATE_DIR/next_session" ] && echo "steam" > "$STATE_DIR/next_session"
    chown -R "$REAL_USER:$REAL_USER" "$STATE_DIR"
    chmod 775 "$STATE_DIR"

    # --- Desktop Entries ---
    info "Installing desktop applications entries..."
    mkdir -p "$APP_DIR"
    for f in Control_Center.desktop Game_Mode.desktop; do
        [ -f "usr/local/share/applications/$f" ] && cp -f "usr/local/share/applications/$f" "$APP_DIR/"
    done

    # --- ALPM Hooks ---
    info "Installing Pacman hooks..."
    mkdir -p "$ALPM_HOOKS_DIR"
    [ -f usr/share/libalpm/hooks/gamescope-privs.hook ] && cp -f usr/share/libalpm/hooks/gamescope-privs.hook "$ALPM_HOOKS_DIR/"

    # Grant Gamescope necessary capabilities for performance
    if [ -f /usr/bin/gamescope ]; then
        info "Applying Real-Time capabilities to Gamescope..."
        setcap 'cap_sys_admin,cap_sys_nice,cap_ipc_lock+ep' /usr/bin/gamescope
    fi
}

# --- 4. SteamOS Compatibility Shim Layer ---
setup_shim_links() {
    info "Constructing SteamOS Compatibility Layer (Shims)..."

    # Polkit Helper Structure (Intercepts Steam Deck UI Settings)
    mkdir -p "$POLKIT_DIR"
    ln -sf "$HELPERS_DIR/jupiter-biosupdate.py"    "$POLKIT_DIR/jupiter-biosupdate"
    ln -sf "$HELPERS_DIR/steamos-update.py"        "$POLKIT_DIR/steamos-update"
    ln -sf "$HELPERS_DIR/set-timezone.py"          "$POLKIT_DIR/steamos-set-timezone"
    ln -sf "$HELPERS_DIR/jupiter-dock-updater.py"  "$POLKIT_DIR/jupiter-dock-updater"

    # System Integration (Steam Client hardcoded paths)
    ln -sf "$LIB_DIR/session_launch.py"            /usr/bin/steamos-session-launch
    ln -sf "$LIB_DIR/session_select.py"            /usr/bin/steamos-session-select
    ln -sf "$HELPERS_DIR/steamos-select-branch.py" /usr/bin/steamos-select-branch

    # Direct Aliases for Global Visibility (two-hop chain ends in $POLKIT_DIR)
    for name in jupiter-biosupdate steamos-update steamos-set-timezone; do
        ln -sf "$POLKIT_DIR/$name" "/usr/bin/$name"
    done

    # Administrative & CLI Tools
    ln -sf "$LIB_DIR/sdy.py"             "$BIN_DIR/sdy"
    ln -sf "$LIB_DIR/control_center.py"  "$BIN_DIR/sdy-control-center"
    ln -sf "$LIB_DIR/backup.py"          "$BIN_DIR/sdy-backup"
    ln -sf "$LIB_DIR/restore.py"         "$BIN_DIR/sdy-restore"

    chmod +x "$POLKIT_DIR"/*
}

# --- 5. Boot & Systemd Configuration ---
setup_systemd_lockdown() {
    info "Configuring Systemd for Console Lockdown (TTY1)..."
    
    # Prevent Getty from interfering with Gamescope on TTY1
    systemctl mask getty@tty1.service
    
    # Deploy and personalize the main service
    if [ -f etc/systemd/system/steamos_diy.service ]; then
        cp -f etc/systemd/system/steamos_diy.service "$SERVICE_FILE"
        sed -i "s|{{USER}}|$REAL_USER|g" "$SERVICE_FILE"
        sed -i "s|{{UID}}|$REAL_UID|g" "$SERVICE_FILE"
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

if $UPDATE_MODE; then
    success "UPDATE COMPLETED SUCCESSFULLY!"
    warn "Rebooting in 10 seconds to apply the update — press CTRL+C to abort."
    for i in {10..1}; do
        printf '\r    Rebooting in %2d s... ' "$i"
        sleep 1
    done
    echo
    reboot
    exit 0
fi

success "INSTALLATION COMPLETED SUCCESSFULLY!"
info "TTY1 is now owned by steamos_diy.service."
warn "A system reboot is mandatory to initialize the DIY environment."

read -r -p "Reboot now? (y/n): " confirm_reboot
if [[ "$confirm_reboot" =~ ^[Yy]$ ]]; then
    reboot
fi
