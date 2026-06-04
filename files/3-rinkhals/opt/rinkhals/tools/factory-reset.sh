#!/bin/sh


# Tasks
# - Download current firmware
# - Stop Rinkhals if needed
# - In /useremain, delete everything except app/ and dev/
# - Delete /userdata/app/gk/config/ams_config.cfg
# - Delete /userdata/app/gk/config/para.cfg
# - Delete /userdata/app/gk/printer_mutabl*.cfg
# - Set /useremain/dev/remote_ctrl_mode to cloud
# - Create /useremain/dev/version from /userdata/app/gk/version_log.txt
# - Reinstall current firmware

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
