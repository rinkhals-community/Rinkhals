source /useremain/rinkhals/.current/tools.sh

APP_ROOT=$(dirname $(realpath $0))
APP_NAME="05-static-usb-ether-mac"

validate_mac() {
    local MAC=$1
    echo "$MAC" | grep -qE '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'
}

find_usb_eth() {
    for IFACE in /sys/class/net/eth*; do
        IFACE=$(basename $IFACE)
        DEVICE=$(readlink -f /sys/class/net/$IFACE/device 2>/dev/null)
        case "$DEVICE" in
            *usb*) echo "$IFACE"; return ;;
        esac
    done
}

resolve_mac() {
    local MAC=$(get_app_property $APP_NAME mac_address)

    if [ -n "$MAC" ]; then
        echo "$MAC"
        return
    fi

    if [ ! -f /userdata/ethaddr.txt ]; then
        return
    fi

    local FACTORY_MAC=$(cat /userdata/ethaddr.txt | tr -d ' \t\n\r' | tr 'A-F' 'a-f')
    if ! validate_mac "$FACTORY_MAC"; then
        return
    fi

    local HASH=$(echo -n "$FACTORY_MAC" | md5sum | cut -c 1-12)
    local FIRST_BYTE_HIGH=${HASH:0:1}
    local FIRST_BYTE_LOW=${HASH:1:1}
    local LOW_VAL=$((16#${FIRST_BYTE_LOW}))
    local NEW_LOW=$(( (LOW_VAL & 0xC) | 0x2 ))
    local NEW_LOW_HEX=$(printf '%x' $NEW_LOW)

    echo "${FIRST_BYTE_HIGH}${NEW_LOW_HEX}:${HASH:2:2}:${HASH:4:2}:${HASH:6:2}:${HASH:8:2}:${HASH:10:2}"
}

status() {
    report_status $APP_STATUS_STOPPED
}

start() {
    local IFACE=$(find_usb_eth)

    if [ -z "$IFACE" ]; then
        log "No USB Ethernet interface found, skipping"
        return
    fi

    local MAC=$(resolve_mac)

    if [ -z "$MAC" ]; then
        log "No MAC address configured and unable to derive one, skipping"
        return
    fi

    if ! validate_mac "$MAC"; then
        log "/!\ Invalid MAC address '$MAC', skipping"
        return
    fi

    log "Setting MAC address of $IFACE to $MAC"

    ifconfig $IFACE down
    ifconfig $IFACE hw ether $MAC
    ifconfig $IFACE up

    log "MAC address of $IFACE set to $(cat /sys/class/net/$IFACE/address)"
}

stop() {
    return 0
}

case "$1" in
    status)
        status
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    *)
        echo "Usage: $0 {status|start|stop}" >&2
        exit 1
        ;;
esac
