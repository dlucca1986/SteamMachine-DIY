# --- BEGIN STEAMOS-DIY TRIGGER ---
if [[ -z $DISPLAY && $XDG_VTNR -eq 1 ]]; then
    LAUNCHER="/usr/local/bin/steamos-session-launch"
    if [[ -x "$LAUNCHER" ]]; then
        [[ -f /etc/default/steamos-diy ]] && . /etc/default/steamos-diy
        exec "$LAUNCHER" >/dev/null 2>&1
    fi
fi
[[ -f ~/.bashrc ]] && . ~/.bashrc
# --- END STEAMOS-DIY TRIGGER ---
