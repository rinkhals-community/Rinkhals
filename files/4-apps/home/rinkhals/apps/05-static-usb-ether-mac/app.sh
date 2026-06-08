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

increment_mac() {
    local MAC=$1
    local LAST_BYTE=${MAC##*:}
    local PREFIX=${MAC%:*}
    local DEC=$((16#${LAST_BYTE}))
    local NEW_DEC=$(( (DEC + 1) % 256 ))
    local NEW_LAST=$(printf '%02x' $NEW_DEC)
    echo "${PREFIX}:${NEW_LAST}"
}

resolve_mac() {
    local MAC=$(get_app_property $APP_NAME mac_address)

    if [ -n "$MAC" ]; then
        echo "$MAC"
        return
    fi

    if [ -f /userdata/ethaddr.txt ]; then
        local FACTORY_MAC=$(cat /userdata/ethaddr.txt | tr -d ' \t\n\r' | tr 'A-F' 'a-f')
        if validate_mac "$FACTORY_MAC"; then
            increment_mac "$FACTORY_MAC"
            return
        fi
    fi
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
        log "No MAC address configured and no factory MAC found, skipping"
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
