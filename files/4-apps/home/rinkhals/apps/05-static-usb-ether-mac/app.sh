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

status() {
    report_status $APP_STATUS_STOPPED
}

start() {
    local MAC=$(get_app_property $APP_NAME mac_address)

    if [ -z "$MAC" ]; then
        log "No MAC address configured, skipping"
        return
    fi

    if ! validate_mac "$MAC"; then
        log "/!\ Invalid MAC address '$MAC', skipping"
        return
    fi

    local IFACE=$(find_usb_eth)

    if [ -z "$IFACE" ]; then
        log "No USB Ethernet interface found, skipping"
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
