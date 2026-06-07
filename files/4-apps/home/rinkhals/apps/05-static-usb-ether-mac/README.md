# Static USB Ethernet MAC

Override the MAC address of a USB Ethernet adapter connected to your printer. Useful for DHCP reservations or maintaining a consistent network identity across hardware swaps.

## Compatible Adapters

- ASIX AX88179 / AX88179A
- Realtek RTL8153
- ASIX AX88772

## How It Works

On startup, the app scans `/sys/class/net/eth*` to find the interface backed by a USB device (by checking `readlink -f /sys/class/net/<iface>/device` for a path containing `usb`). If a MAC address is configured and a USB Ethernet interface is found, it brings the interface down, applies the MAC with `ifconfig hw ether`, and brings it back up.

The `05-` prefix ensures it runs before `10-hostname-dns`, so the MAC is set before DHCP and mDNS start.

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| MAC address | *(empty)* | MAC address to apply to the USB Ethernet adapter (format: `aa:bb:cc:dd:ee:ff`) |

## Set a Static MAC Address

SSH into the printer and run:

```bash
source /useremain/rinkhals/.current/tools.sh
set_app_property 05-static-usb-ether-mac mac_address aa:bb:cc:dd:ee:ff
```

The MAC address must be in colon-separated hexadecimal format (`xx:xx:xx:xx:xx:xx`). Invalid values are skipped and logged.

Then restart the app (or reboot the printer):

```bash
/useremain/home/rinkhals/apps/05-static-usb-ether-mac/app.sh stop
/useremain/home/rinkhals/apps/05-static-usb-ether-mac/app.sh start
```

## View the Current MAC Address

```bash
cat /sys/class/net/$(for iface in /sys/class/net/eth*; do
    iface=$(basename $iface)
    dev=$(readlink -f /sys/class/net/$iface/device 2>/dev/null)
    case "$dev" in *usb*) echo "$iface"; break ;; esac
done)/address
```

## Dependencies

`ifconfig` from busybox/net-tools only — no additional packages required.
