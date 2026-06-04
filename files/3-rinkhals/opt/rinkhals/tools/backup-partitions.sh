#!/bin/sh


USB_DRIVE="/mnt/udisk"
if [ ! -e $USB_DRIVE ]; then
    exit 0
fi

# Backup userdata and useremain partitions on USB drive
cd /userdata
rm $USB_DRIVE/userdata.tar 2> /dev/null
tar -cvf $USB_DRIVE/userdata.tar \
    --exclude='./app/gk/printer_data/gcodes' \
    --exclude='*.1' \
    .

cd /useremain
rm $USB_DRIVE/useremain.tar 2> /dev/null
tar -cvf $USB_DRIVE/useremain.tar \
    --exclude='./rinkhals' \
    --exclude='./app/gk/gcodes' \
    --exclude='./update_swu' \
    --exclude='./dist' \
    --exclude='./tmp' \
    --exclude='./lost+found' \
    --exclude='./.cache' \
    .

# Cleanup
rm -rf /useremain/update_swu
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
