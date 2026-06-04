#!/bin/sh

if [ "$1" != "async" ]; then
    echo "Re-running async..."
    nohup $0 async > /dev/null &
    exit 0
fi


SOURCE_PATH="/useremain/update_swu"
USB_PATH="/mnt/udisk/aGVscF9zb3Nf"


. $SOURCE_PATH/rinkhals/tools.sh


log() {
    echo "${*}"
    echo "$(date): ${*}" >> /useremain/rinkhals/install.log
    if [ -e $USB_PATH ]; then
        echo "$(date): ${*}" >> $USB_PATH/install.log
    fi
}

FBIMG="/tmp/framebuffer.bmp"
ICON_GRID="$SOURCE_PATH/rinkhals/opt/rinkhals/ui/assets/snake-grid.webp"
ICON_ERR="$SOURCE_PATH/rinkhals/opt/rinkhals/ui/assets/snake-error.webp"
ICON=${ICON_GRID}

progress() {
    case "${KOBRA_MODEL_CODE}" in
        KS1)
            SCL=".5"
            TRANS="hflip,vflip"
            Y_OFF="(H/3.4)"
            X_OFF="((W/2)-(w/2))"
            ERR_X_OFF=""
            ERR_Y_OFF="-29"
            ;;
        KS1M)
            SCL=".5"
            TRANS="hflip,vflip"
            Y_OFF="(H/3.4)"
            X_OFF="((W/2)-(w/2))"
            ERR_X_OFF=""
            ERR_Y_OFF="-29"
            ;;
        K3M)
            SCL=".25"
            TRANS="transpose=2"
            X_OFF="(W-(W/6.8)-(128*${SCL}))"
            Y_OFF="((H/2)-(h/2))"
            ERR_X_OFF="-25"
            ERR_Y_OFF=""
            ;;
        *)
            SCL=".25"
            TRANS="transpose=1"
            X_OFF="(W/6.8)"
            Y_OFF="((H/2)-(h/2))"
            ERR_X_OFF="-15"
            ERR_Y_OFF=""
            ;;
    esac
    case "${1}" in
        "success")
            CROP="crop=1024:128:0:(1280*1)"
            ;;
        "error")
            ICON=${ICON_ERR}
            CROP="null"
            X_OFF="${X_OFF}${ERR_X_OFF}"
            Y_OFF="${Y_OFF}${ERR_Y_OFF}"
            ;;
        *)
            CROP="crop=1024:128:0:(1280*${1})"
            ;;
    esac
    fb_draw "-i ${ICON} -frames:v 1 -filter_complex [1]${CROP},scale=iw*${SCL}:ih*${SCL},${TRANS}[bar];[0][bar]overlay=x=${X_OFF}:y=${Y_OFF} "
}

quit() {
    sync
    progress error

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

    fb_restore
    exit 1
}

fb_capture() {
    if [ -f /ac_lib/lib/third_bin/ffmpeg ]; then
        /ac_lib/lib/third_bin/ffmpeg -f fbdev -i /dev/fb0 -frames:v 1 -y ${FBIMG} 1>/dev/null 2>/dev/null
    fi
}
fb_restore() {
    if [ -f /ac_lib/lib/third_bin/ffmpeg ]; then
        /ac_lib/lib/third_bin/ffmpeg -i ${FBIMG} -f fbdev /dev/fb0 1>/dev/null 2>/dev/null
    fi
}
fb_draw() {
    if [ -f /ac_lib/lib/third_bin/ffmpeg ]; then
        /ac_lib/lib/third_bin/ffmpeg -i ${FBIMG} ${*} -pix_fmt bgra -f fbdev /dev/fb0 1>/dev/null 2>/dev/null
    fi
}


log
log "Starting Rinkhals installation..."


# Capture initial framebuffer
fb_capture
progress 0


# Make sure we install on a compatible model
check_compatibility


# Check if we have enough space
FREE_SPACE=$(df -k /useremain | tail -1 | awk '{print $3}')
if [ "$FREE_SPACE" != "" ] && [ "$FREE_SPACE" -lt "500000" ]; then
    log "Not enough free space in /useremain"
    quit
fi


# Backup the machine-specific files
progress 0.1

log "Backing up machine-specific files..."

INSTALL_BACKUP_PATH=/tmp/rinkhals/install-backup
mkdir -p $INSTALL_BACKUP_PATH
rm -rf $INSTALL_BACKUP_PATH/*

mkdir -p $INSTALL_BACKUP_PATH/userdata/app/gk/config
cp /userdata/app/gk/config/device.ini $INSTALL_BACKUP_PATH/userdata/app/gk/config/device.ini
cp /userdata/app/gk/config/device_account.json $INSTALL_BACKUP_PATH/userdata/app/gk/config/device_account.json

mkdir -p $INSTALL_BACKUP_PATH/useremain/app/gk
cp -r /useremain/app/gk/cert1 $INSTALL_BACKUP_PATH/useremain/app/gk/
cp -r /useremain/app/gk/cert3 $INSTALL_BACKUP_PATH/useremain/app/gk/

PREVIOUS_WD=$(pwd)
cd $INSTALL_BACKUP_PATH
zip -r kobra-personnal-backup.zip . > /dev/null
cp -f kobra-personnal-backup.zip /useremain/kobra-personnal-backup.zip
if [ -e $USB_PATH ]; then
    cp -f kobra-personnal-backup.zip $USB_PATH/kobra-personnal-backup.zip
fi
cd $PREVIOUS_WD


# Find the right directory target
progress 0.3

RINKHALS_VERSION=$(cat $SOURCE_PATH/.version)

TARGET_PATH=/useremain/rinkhals/$RINKHALS_VERSION
CURRENT_RINKHALS_PATH=$(realpath /useremain/rinkhals/.current 2> /dev/null)

if [ "$CURRENT_RINKHALS_PATH" != "" ] && [ "$TARGET_PATH" = "$CURRENT_RINKHALS_PATH" ]; then
    TARGET_PATH="${TARGET_PATH}-2"
fi

log "Installing Rinkhals version $RINKHALS_VERSION to $TARGET_PATH"


# Copy Rinkhals
progress 0.4

log "Copying Rinkhals files"

mkdir -p $TARGET_PATH
rm -rf $TARGET_PATH/*
cp -r $SOURCE_PATH/rinkhals/* $TARGET_PATH

echo $RINKHALS_VERSION > $TARGET_PATH/.version

progress 0.8

log "Copying Rinkhals startup files"

cp -f $SOURCE_PATH/start-rinkhals.sh /useremain/rinkhals/start-rinkhals.sh
cp -f $SOURCE_PATH/start.sh.patch /useremain/rinkhals/start.sh.patch
echo $(basename $TARGET_PATH) > /useremain/rinkhals/.version

rm /useremain/rinkhals/.disable-rinkhals 2> /dev/null


# Install Rinkhals loader
progress 0.9

PRESENT=$(cat /userdata/app/gk/start.sh | grep "Rinkhals/begin")
if [ "$PRESENT" == "" ]; then
    log "Installing Rinkhals loader as it is missing"

    cat $SOURCE_PATH/start.sh.patch >> /userdata/app/gk/start.sh
    if [ -f /userdata/app/gk/restart_k3c.sh ]; then
        cat $SOURCE_PATH/start.sh.patch >> /userdata/app/gk/restart_k3c.sh
    fi
else
    log "Rinkhals loader was detected, skipping installation"
fi

# Prune older Rinkhals installs, keep current + previous as backup
progress 0.95

log "Pruning older Rinkhals installs (keeping current + previous)..."

KEEP_CURRENT="$TARGET_PATH"
KEEP_PREVIOUS=""
if [ "$CURRENT_RINKHALS_PATH" != "" ] && [ "$CURRENT_RINKHALS_PATH" != "$TARGET_PATH" ] && [ -d "$CURRENT_RINKHALS_PATH" ]; then
    KEEP_PREVIOUS="$CURRENT_RINKHALS_PATH"
fi

log "  Current:  $(basename $KEEP_CURRENT)"
if [ "$KEEP_PREVIOUS" != "" ]; then
    log "  Previous: $(basename $KEEP_PREVIOUS)"
fi

for DIR in /useremain/rinkhals/*; do
    [ -d "$DIR" ] || continue
    [ -L "$DIR" ] && continue
    BASENAME=$(basename "$DIR")

    # Only consider directories matching the YYYYMMDD_NN[_test][-N] version pattern.
    # Unknown directories (e.g. 'dev', 'tmp', user files) are left untouched.
    if ! echo "$BASENAME" | grep -qE '^20[0-9]{6}_[0-9]+(_test)?(-[0-9]+)?$'; then
        continue
    fi

    if [ "$DIR" = "$KEEP_CURRENT" ] || [ "$DIR" = "$KEEP_PREVIOUS" ]; then
        continue
    fi

    log "  Removing $BASENAME"
    rm -rf "$DIR"
done


log "Removing update files"

rm -rf $SOURCE_PATH
rm -f /useremain/update.swu
rm -f $USB_PATH/update.swu

sync
log "Rinkhals installation complete, rebooting..."


# Notify user
progress success

if [ ! -f /useremain/rinkhals/.mute-sounds ]; then
    B=/sys/class/pwm/pwmchip0/pwm0
    echo 0 > $B/enable; echo 0 > $B/duty_cycle
    echo 2551000 > $B/period; echo 1020400 > $B/duty_cycle; echo 1 > $B/enable
    usleep 180000; echo 0 > $B/enable; usleep 50000
    echo 0 > $B/duty_cycle
    echo 1912000 > $B/period; echo 764800 > $B/duty_cycle; echo 1 > $B/enable
    usleep 280000; echo 0 > $B/enable
fi

reboot
