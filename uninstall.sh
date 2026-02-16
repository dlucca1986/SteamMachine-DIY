#!/bin/bash
# =============================================================================
# PROJECT:      SteamMachine-DIY - Master Uninstaller
# VERSION:      1.0.0
# DESCRIPTION:  Surgical removal of DIY components and environment restoration.
# REPOSITORY:   https://github.com/dlucca1986/SteamMachine-DIY
# LICENSE:      MIT
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

# Root check
if [ "$EUID" -ne 0 ]; then
    error "Please run as root (sudo ./uninstall.sh)"
    exit 1
fi

# Detect actual user behind sudo
REAL_USER=${SUDO_USER:-$(whoami)}
USER_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# --- 1. Cleanup Triggers & Overrides ---
cleanup_system_config() {
    info "Cleaning up system configurations..."
    
    # Surgically remove the trigger block from .bash_profile
    BP_FILE="$USER_HOME/.bash_profile"
    if [ -f "$BP_FILE" ]; then
        # Eliminazione precisa del blocco tra i tag di inizio e fine
        sed -i '/# --- BEGIN STEAMOS-DIY TRIGGER ---/,/# --- END STEAMOS-DIY TRIGGER ---/d' "$BP_FILE"
        # Rimuove eventuali righe vuote eccessive lasciate da sed
        sed -i '${/^$/d;}' "$BP_FILE"
        info "Bash profile trigger removed from $BP_FILE."
    fi

    # Remove the TTY1 autologin override directory
    if [ -d /etc/systemd/system/getty@tty1.service.d/ ]; then
        rm -rf /etc/systemd/system/getty@tty1.service.d/
        info "TTY1 autologin override removed."
    fi
    
    # Reset Getty status
    systemctl unmask getty@tty1.service 2>/dev/null || true
    
    # Remove ALPM hooks and reset Gamescope capabilities
    rm -f /usr/share/libalpm/hooks/gamescope-privs.hook
    if [ -f /usr/bin/gamescope ]; then
        setcap -r /usr/bin/gamescope 2>/dev/null || true
        info "Gamescope capabilities reset."
    fi
}

# --- 2. Remove Files & Symlinks ---
cleanup_files() {
    info "Removing binaries, libraries and symlinks..."
    
    # List of symlinks created by the installer
    SYMLINKS=(
        "/usr/bin/steamos-session-launch"
        "/usr/bin/steamos-session-select"
        "/usr/bin/sdy"
        "/usr/bin/sdy-backup"
        "/usr/bin/sdy-restore"
        "/usr/bin/jupiter-biosupdate"
        "/usr/bin/steamos-select-branch"
        "/usr/bin/steamos-update"
        "/usr/bin/steamos-polkit-helpers"
    )

    # Clean up symlinks in /usr/bin/
    for link in "${SYMLINKS[@]}"; do
        if [ -L "$link" ]; then
            rm "$link"
        elif [ -d "$link" ]; then
            rm -rf "$link"
        fi
    done

    # Remove core directories and global configs
    rm -rf /usr/local/lib/steamos_diy
    rm -f /etc/default/steamos_diy.conf
    rm -rf /var/lib/steamos_diy
    
    # Cleanup /etc/skel
    rm -rf /etc/skel/.config/steamos_diy
    
    # Optional: cleanup user config folder
    echo -ne "${YELLOW}Remove user configuration folder (~/.config/steamos_diy)? [y/N] ${NC}"
    read -r remove_conf
    if [[ $remove_conf == [yY] ]]; then
        rm -rf "$USER_HOME/.config/steamos_diy"
        success "User configurations deleted."
    fi
}

# --- 3. Emergency DM Restoration ---
restore_display_manager() {
    info "Checking Display Manager status..."
    
    DMS=("sddm" "gdm" "lightdm" "lxdm")
    FOUND_DMS=()
    
    for dm in "${DMS[@]}"; do
        if systemctl list-unit-files | grep -q "^$dm.service"; then
            FOUND_DMS+=("$dm")
        fi
    done

    if [ ${#FOUND_DMS[@]} -gt 0 ]; then
        warn "Game Mode trigger removed. You need a Display Manager to return to a GUI boot."
        echo -e "Available DMs: ${FOUND_DMS[*]}"
        echo -ne "${CYAN}Enter the DM name to enable (leave empty to skip): ${NC}"
        read -r selected_dm
        
        if [[ -n "$selected_dm" ]]; then
            if systemctl list-unit-files | grep -q "^$selected_dm.service"; then
                systemctl enable "$selected_dm"
                success "$selected_dm enabled."
            else
                error "Service $selected_dm not found."
            fi
        fi
    else
        warn "No common Display Manager detected. You might boot into a TTY."
    fi
}

# --- 4. Execution Flow ---
echo -e "${RED}==================================================${NC}"
echo -e "${RED}        SteamMachine-DIY Uninstaller              ${NC}"
echo -e "${RED}==================================================${NC}"

cleanup_system_config
cleanup_files
restore_display_manager

# Refresh systemd
systemctl daemon-reload

echo -e "\n${GREEN}==================================================${NC}"
success "UNINSTALL COMPLETE. Please REBOOT to restore your desktop environment."
echo -e "${GREEN}==================================================${NC}\n"
