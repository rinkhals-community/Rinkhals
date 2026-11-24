#!/bin/sh

function log() {
    echo "${*}"
    echo "$(date): ${*}" >> /useremain/rinkhals/rinkhals.log
}

log
log "Starting Rinkhals..."

CALLER=$(cat /proc/$PPID/cmdline)
log "Rinkhals startup was called from $CALLER ($PPID)"

if [ ! -f /useremain/rinkhals/.version ]; then
    log "Rinkhals is installed but no version is selected to start"
    exit 1
fi

if [ -f /mnt/udisk/.enable-rinkhals ] || [ -f /useremain/rinkhals/.enable-rinkhals ]; then
    log "Forcing Rinkhals startup with the .enable-rinkhals file"

    rm /mnt/udisk/.disable-rinkhals
    rm /useremain/rinkhals/.disable-rinkhals
fi

# A power cut during a previous startup can leave gkapi/K3SysUi patched, truncated or missing, with the
# stock binary in .original (https://github.com/rinkhals-community/Rinkhals/issues/198). Put it back
# here, so it also happens when Rinkhals is disabled
STOCK_RECOVERED=0
# Its own variable: tools.sh sets RINKHALS_VERSION from .current, which may not be the selected version
SELECTED_ROOT=/useremain/rinkhals/$(cat /useremain/rinkhals/.version)
if [ -f $SELECTED_ROOT/tools.sh ]; then
    mkdir -p /tmp/rinkhals

    # In a subshell: a damaged tools.sh must not end this script (the ADB fallback below), and its
    # variables must not leak into start.sh
    if (
        . $SELECTED_ROOT/tools.sh

        # tools.sh brings its own log(), keep logging to this script's log
        function log() {
            echo "${*}"
            echo "$(date): ${*}" >> /useremain/rinkhals/rinkhals.log
        }

        PATCHES=$SELECTED_ROOT/opt/rinkhals/patches/patches.txt
        recover_stock_binaries /userdata/app/gk \
            gkapi "$(stock_md5_of $PATCHES gkapi $KOBRA_MODEL_CODE $KOBRA_VERSION)" \
            K3SysUi "$(stock_md5_of $PATCHES K3SysUi $KOBRA_MODEL_CODE $KOBRA_VERSION)"
    ); then
        STOCK_RECOVERED=1
    fi
fi

if [ ! -f /mnt/udisk/.disable-rinkhals ] && [ ! -f /useremain/rinkhals/.disable-rinkhals ]; then
    RINKHALS_VERSION=$(cat /useremain/rinkhals/.version)
    log "Rinkhals version $RINKHALS_VERSION selected"

    if [ ! -d /useremain/rinkhals/$RINKHALS_VERSION ]; then
        log "Rinkhals version $RINKHALS_VERSION does not exist"
        exit 1
    fi

    cd /useremain/rinkhals/$RINKHALS_VERSION

    chmod +x ./start.sh
    ./start.sh
fi

if [ -f /mnt/udisk/.disable-rinkhals ] || [ -f /useremain/rinkhals/.disable-rinkhals ]; then
    log "Rinkhals startup was stopped with the .disable-rinkhals file, trying to start ADB..."

    # The stock apps of this boot already started from the broken binaries, start them again from the
    # restored ones. Only a restore triggers this, so the next boot goes on without rebooting
    if [ "$STOCK_RECOVERED" = 1 ]; then
        log "Stock binaries were restored, rebooting to start them"
        sync
        reboot
        exit 1
    fi

    adbd &
    exit 1
fi
