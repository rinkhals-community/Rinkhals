#!/bin/sh


# Backup config
TMP_PATH="/tmp/rinkhals-config-reset"

mkdir -p $TMP_PATH
rm -rf $TMP_PATH/*

cp /useremain/home/rinkhals/printer_data/config/* $TMP_PATH 2> /dev/null
rm $TMP_PATH/*.zip 2> /dev/null

cd $TMP_PATH
DATE=$(date '+%Y%m%d-%H%M%S')
zip -r /useremain/config-backup-${DATE}.zip .

if [ -e /mnt/udisk ]; then
    cp /useremain/config-backup-${DATE}.zip /mnt/udisk/config-backup-${DATE}.zip
fi

# Read mute flag before deleting Rinkhals directory
MUTE_SOUNDS=0
[ -f /useremain/rinkhals/.mute-sounds ] && MUTE_SOUNDS=1

# Stop Rinkhals if needed
if [ -e /useremain/rinkhals/.current/stop.sh ]; then
    chmod +x /useremain/rinkhals/.current/stop.sh
    /useremain/rinkhals/.current/stop.sh
fi

# Delete Rinkhals completely
rm -rf /useremain/rinkhals 2> /dev/null
rm -rf /useremain/home/rinkhals 2> /dev/null
rm -rf /useremain/home/root 2> /dev/null
rm -rf /userdata/app/gk/K3SysUi.patch 2> /dev/null

sed -i '/# Rinkhals\/begin/,/# Rinkhals\/end/d' /userdata/app/gk/start.sh
if [ -f /userdata/app/gk/restart_k3c.sh ]; then
    sed -i '/# Rinkhals\/begin/,/# Rinkhals\/end/d' /userdata/app/gk/restart_k3c.sh
fi

# Play ok jingle to notify completion
if [ "$MUTE_SOUNDS" = "0" ]; then
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

sync 2> /dev/null
reboot
