#!/bin/sh


UPDATE_PATH="/useremain/update_swu"


# Check if the printer has Rinkhals installed
if [ ! -e /useremain/rinkhals/.current ]; then
    if [ ! -f /useremain/rinkhals/.mute-sounds ]; then
        B=/sys/class/pwm/pwmchip0/pwm0
        echo 0 > $B/enable; echo 0 > $B/duty_cycle
        echo 3817000 > $B/period; echo 1526800 > $B/duty_cycle; echo 1 > $B/enable
        usleep 300000; echo 0 > $B/enable; usleep 100000
        echo 0 > $B/duty_cycle
        echo 4545000 > $B/period; echo 1818000 > $B/duty_cycle; echo 1 > $B/enable
        usleep 300000; echo 0 > $B/enable; usleep 100000
        echo 0 > $B/duty_cycle
        echo 5714000 > $B/period; echo 2285600 > $B/duty_cycle; echo 1 > $B/enable
        usleep 600000; echo 0 > $B/enable
    fi
    exit 1
fi


# Backup config
TMP_PATH="/tmp/rinkhals-config-reset"

mkdir -p $TMP_PATH
rm -rf $TMP_PATH/*

cp /useremain/home/rinkhals/printer_data/config/* $TMP_PATH 2> /dev/null
rm $TMP_PATH/*.zip 2> /dev/null

cd $TMP_PATH
DATE=$(date '+%Y%m%d-%H%M%S')
BACKUP_NAME=config-backup-${DATE}.zip
zip -r $BACKUP_NAME .

cp $BACKUP_NAME /useremain/home/rinkhals/printer_data/config/
if [ -e /mnt/udisk ]; then
    mkdir -p /mnt/udisk/aGVscF9zb3Nf
    cp $BACKUP_NAME /mnt/udisk/aGVscF9zb3Nf/
fi

# Restore default config
RINKHALS_HOME=/useremain/home/rinkhals

rm $RINKHALS_HOME/printer_data/config/*.conf 2> /dev/null
rm $RINKHALS_HOME/printer_data/config/*.cfg 2> /dev/null

rm /useremain/rinkhals/.disable-rinkhals


# Cleanup
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
