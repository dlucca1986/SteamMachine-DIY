# ~/.bash_profile

# 1. STEAMOS-DIY TRIGGER (Execute only on TTY1 without an active GUI)
if [[ -z $DISPLAY && $XDG_VTNR -eq 1 ]]; then
    
    # Path to the central session launcher
    LAUNCHER="/usr/local/bin/steamos-session-launch"
    
    if [[ -x "$LAUNCHER" ]]; then
        # Load the Global Configuration (SSOTH) before launching
        [[ -f /etc/default/steamos-diy ]] && . /etc/default/steamos-diy
        
        # Atomic Launch: 'exec' replaces the current shell with the launcher process.
        # Redirects hide terminal noise for a clean, console-like boot experience.
        exec "$LAUNCHER" >/dev/null 2>&1
    fi
fi

# 2. STANDARD SHELL CONFIGURATION
# Source the user's local bashrc for aliases, prompts, and environment settings
[[ -f ~/.bashrc ]] && . ~/.bashrc
