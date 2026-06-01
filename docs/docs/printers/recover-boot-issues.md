---
title: Boot Issues Recovery
---

!!! warning

    This page documents recovery for a soft-bricked printer. The procedures below
    range from low-risk (re-flashing a SWU via USB) to high-risk (writing
    partition images over a mainboard programming connection). Read the whole
    page before reaching for tools, and ask in the
    [Rinkhals Discord](https://discord.gg/bQcrsteFGU) if you are unsure which
    path applies to your symptoms.

If you modified files on your printer and it now refuses to start, in many
cases the printer can be recovered. Typical symptoms include:

- Anycubic logo with an empty progress bar that never completes
- Reboot loop before the printer UI loads
- Touchscreen unresponsive on boot, but the printer's USB networking
  (if previously enabled) may still appear briefly

If SSH or ADB still respond intermittently, capture logs from
`/useremain/rinkhals/logs/` before continuing — they will help diagnose what
happened and may guide a faster recovery than partition restoration.

## Try this first

Before opening the printer, attempt the recovery paths that don't require
hardware access:

### Re-flash a supported SWU via USB

This is the same path used for normal Rinkhals install/upgrade. If the printer
will still mount a USB drive and run an update on boot, this can rebuild
enough of the system to get you to a working state.

1. Download the official Anycubic SWU for **your printer model** and a
   supported firmware version (see the model-specific firmware history pages
   linked from the [printers index](index.md)).
2. Copy the file to a FAT32 USB drive, renamed to `update.swu`, inside a
   folder named `aGVscF9zb3Nf`.
3. Plug the USB drive in and power-cycle the printer. Wait for the install
   sequence (two beeps signals completion on most models).
4. After the stock firmware comes up, re-install Rinkhals normally.

### Restore a partition backup you took earlier

If you ran `/opt/rinkhals/tools/backup-partitions.sh` from a previous Rinkhals
install while the printer was healthy, you have a partition snapshot in
`/useremain/rinkhals/backups/`. Save that snapshot off-device now (before any
further tinkering) and use it for partition recovery via the mainboard
procedure below. A self-captured backup is always preferable to the generic
images linked further down this page because it preserves your printer's
machine-specific certificates and identifiers.

If you have not taken a backup and your printer is healthy, **stop and do that
first**. Recovery is far simpler when you have your own known-good partition
images.

## Restore broken partitions (mainboard-level recovery)

This is the path for printers that won't accept a USB update. It requires a
USB-to-mainboard programming connection (a soldered or pogo-pin cable) and
access to a Linux machine. Windows may work but is not currently documented.

### Mainboard connection

Follow the guide on this page: [Mainboard connection](mainboard-connection/index.md)

### SWU password

Anycubic SWU files are encrypted with a per-model password. The single
password that previously appeared on this page only works for K2P, K3, and
K3V2; using it on a KS1, KS1 Max, or K3 Max produces a `bad password` error
from `unzip` with no further explanation. The canonical table is:

| Models | Password |
|---|---|
| Kobra 2 Pro, Kobra 3, Kobra 3 V2 | `U2FsdGVkX19deTfqpXHZnB5GeyQ/dtlbHjkUnwgCi+w=` |
| Kobra S1, Kobra S1 Max | `U2FsdGVkX1+lG6cHmshPLI/LaQr9cZCjA8HZt6Y8qmbB7riY` |
| Kobra 3 Max | `4DKXtEGStWHpPgZm8Xna9qluzAI8VJzpOsEIgd8brTLiXs8fLSu3vRx8o7fMf4h6` |

This table is mirrored in three places in the Rinkhals source tree and is
expected to stay in sync:

- `build/prepare-version.sh` (`get_printer_swu_password`)
- `files/3-rinkhals/tools.sh` (`get_swu_password`, used by `install_swu`)
- `files/3-rinkhals/opt/rinkhals/ui/common.py` (`extract_swu`)

If you have already sourced Rinkhals' `tools.sh` (for example, on a different
working printer), `install_swu <path-to-swu>` will pick the correct password
automatically based on the model code.

### `userdata` partition

The `userdata` partition holds the Anycubic startup scripts that boot the
printer's UI and Klipper-equivalent stack. A deletion of its contents leaves
the printer unable to boot.

!!! note "Status: documented for Kobra 3 only"

    The procedure below was captured during a Kobra 3 recovery. Partition
    layouts and machine-specific paths differ between models. If you
    successfully recover a different printer, please contribute the steps via
    PR or share them in Discord so this section can be extended.

The basic shape of the recovery is:

1. Obtain an official SWU package for your model at a supported firmware
   version.
2. Unzip the SWU with the appropriate per-model password (see the table above).
3. Extract the `setup.tar.gz` you find inside.
4. Locate `update_shell/update_udisk_init.sh` in the extracted tree. This
   script initializes the partition from update contents.
5. Modify the script's path variables to write into a mounted copy of the
   target partition rather than the live one, removing any post-write
   reboot/finalization steps.

   ```shell
   update_file_path="./update_swu"
   to_update_path="./_userdata/app/gk"
   to_update_wifi_cfg="./_userdata/wifi_cfg"
   to_run_sh_path="./_userdata/app/kenv"
   ```

6. Run the modified script and verify that the expected files are present:

    - `/userdata/app/kenv/run.sh`
    - `/userdata/app/gk/start.sh`
    - `/userdata/app/gk/gkapi`, `gkcam`, `gklib` and `K3SysUi`
    - `/userdata/app/gk/device.ini`

7. Restore the machine-specific files from your records (a partition backup
   taken from this same printer is the only reliable source for these):

    - `/userdata/app/gk/config/device.ini`: `[cloud_prod]` and
      `[cloud_global_prod]` sections, with `mechineCode`, `deviceUnionId`,
      and `deviceKey` filled in
    - `/userdata/app/gk/config/device_account.json`: `deviceId`, `username`,
      and `password`. The `deviceId` must match `/useremain/dev/device_id`.
    - `/useremain/app/gk/cert1` and `/useremain/app/gk/cert3`: printer
      certificates

8. Write the partition image back to the mainboard.

### `useremain` partition

Detailed recovery for the `useremain` partition is not yet documented in this
guide. The Kobra 3 community has a writeup at
[Bushmills/Anycubic-Kobra-3-rooted discussion #5](https://github.com/Bushmills/Anycubic-Kobra-3-rooted/discussions/5#discussioncomment-11504611)
that may be helpful for K3 users; other models likely differ.

### Other partitions

The remaining partition images are bundled inside the official SWU files:

1. Unzip the SWU with the appropriate per-model password (see the table above).
2. Extract `setup.tar.gz`.
3. Extract `update_ota.tar` from inside.
4. The result contains `.img` files corresponding to the remaining partitions,
   which can be written via the same mainboard procedure.

## After recovery: prevention

Once the printer is healthy again:

- Run `/opt/rinkhals/tools/backup-partitions.sh` while the printer is in a
  known-good state, and save the resulting snapshot off-device. This gives
  you the cleanest possible source for future recovery, preserving your
  printer-specific certificates and identifiers.
- If you are about to experiment with files on the printer, consider working
  in `/useremain` and `/userdata/app/gk` snapshots first rather than modifying
  the live filesystem.

## Help expand this guide

Recovery details for Kobra 3 Max, Kobra S1, Kobra S1 Max, and Kobra 3 V2 are
not currently documented here. If you have recovered any of these models from
a soft brick, please contribute the steps via pull request or share them in
the [Rinkhals Discord](https://discord.gg/bQcrsteFGU) so this page can cover
the full Kobra family.
