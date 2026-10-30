export TZ=UTC

LEASE_FILE="/useremain/home/rinkhals/dhcp.lease"
NTP_SERVER="pool.ntp.org"

# Ask for a fresh lease on the interface that carries the default route, so the
# lease file has the NTP server from the DHCP reply. This used to always ask on
# wlan0 and never give up, which hung here forever on a printer connected by
# Ethernet and left the clock at 1970 (#143). Wait up to a minute for the network
# to come up, and give up on DHCP after a few tries; pool.ntp.org still works.
# Only the lease file script runs, so the interface is never reconfigured: the
# stock script would clear its address first and leave it cleared on a timeout.
IFACE=
for i in $(seq 1 12); do
    IFACE=$(awk '$2 == "00000000" { print $1; exit }' /proc/net/route)
    [ -n "$IFACE" ] && break
    sleep 5
done

if [ -n "$IFACE" ]; then
    /sbin/udhcpc -i "$IFACE" -n -q -t 3 -T 3 -s /usr/share/udhcpc/default.script.d/lease-file.script > /dev/null 2>&1
fi

if [ -f "$LEASE_FILE" ]; then
    LEASE_NTP=$(grep "NTP-Server:" "$LEASE_FILE" | awk '{print $2}')
    
    if [ -n "$LEASE_NTP" ] && [ "$LEASE_NTP" != "NONE" ]; then
        NTP_SERVER="$LEASE_NTP"
    fi
fi

while true; do
    timeout -t 5 sh -c "ntpclient -s -h $NTP_SERVER" > /dev/null 2>&1

    YEAR=$(date +%Y)
    if [ "$YEAR" -ne "1970" ]; then
        break
    fi

    sleep 5
done
