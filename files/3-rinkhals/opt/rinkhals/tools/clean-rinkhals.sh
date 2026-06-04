#!/bin/sh


UPDATE_PATH="/useremain/update_swu"

RINKHALS_PATH="/useremain/rinkhals"
RINKHALS_CURRENT=$(realpath /useremain/rinkhals/.current)

# Find all directories in RINKHALS_PATH except symlinks
installs=$(find "$RINKHALS_PATH" -mindepth 1 -maxdepth 1 -type d ! -type l)

for i in $installs; do
    basename=$(basename "$i")
    
    # Never delete the currently active installation, or the standard dev workspace
    if [ "$i" = "$RINKHALS_CURRENT" ] || [ "$basename" = "dev" ] || [ "$basename" = "user_data" ]; then
        continue
    fi
    
    # Actually delete any other folder found in the Rinkhals root
    rm -rf "$i"
done

# Cleanup temporary update payloads

cd
rm -rf $UPDATE_PATH
sync

# Play ok jingle to notify completion
if [ ! -f /useremain/rinkhals/.mute-sounds ]; then
    B=/sys/class/pwm/pwmchip0/pwm0
    echo 0 > $B/enable; echo 0 > $B/duty_cycle
    echo 2551000 > $B/period; echo 1020400 > $B/duty_cycle; echo 1 > $B/enable
    usleep 120000; echo 0 > $B/enable; usleep 40000
    echo 0 > $B/duty_cycle
    echo 1912000 > $B/period; echo 764800 > $B/duty_cycle; echo 1 > $B/enable
    usleep 120000; echo 0 > $B/enable; usleep 40000
    echo 0 > $B/duty_cycle
    echo 1517000 > $B/period; echo 606800 > $B/duty_cycle; echo 1 > $B/enable
    usleep 180000; echo 0 > $B/enable
fi
