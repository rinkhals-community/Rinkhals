# Firmware Collector (opt-in)

This Rinkhals app helps the community catch new Anycubic firmware
releases faster. It is **disabled by default**. You must enable it
explicitly before it does anything.

## What it does

When enabled, the app once per day:

1. Tests basic internet reachability. If the printer cannot reach the
   internet (for example because it is configured in LAN-only mode),
   the app logs a message and waits until the next cycle.
2. Asks Anycubic's OTA server whether a firmware newer than the one
   currently installed exists for this printer model. This uses the
   printer's own existing Anycubic device certificate, the same way
   the touchscreen "Check for updates" button does.
3. If Anycubic announces a newer firmware version, the app sends a
   small notification to the Rinkhals community firmware archive at
   `https://ingest.firmwareforge.org/v1/notify`.

## What it sends

Only these fields, only when a new firmware is announced:

| Field              | Example                                       |
|--------------------|-----------------------------------------------|
| `model_code`       | `K3V2`                                        |
| `model_id`         | `20027`                                       |
| `current_version`  | `1.1.2.8`                                     |
| `next_version`     | `1.1.2.9`                                     |
| `package_url`      | `https://anycubic-cdn.example/K3V2_1.1.2.9.swu` |
| `package_md5`      | (Anycubic-supplied md5 of the blob)           |
| `package_size`     | (bytes)                                       |
| `zone`             | `us`, `eu`, `cn` (from device.ini)            |
| `rinkhals_version` | the Rinkhals build that sent the notification |

## What it does NOT send

The app never transmits:

- The printer's device certificate, private key, or CA cert
- The printer's `deviceUnionId`, account, email, or any Anycubic
  account information
- Print history, gcode, models, slicer settings, or print stats
- Network information beyond the model+version metadata above
- The printer's IP address or LAN topology (the ingest endpoint sees
  the public IP from which the HTTPS connection arrives, which is
  unavoidable for any internet request, but nothing is logged
  beyond standard request metadata)

## Why this is useful

The Rinkhals team needs to obtain new firmware as soon as Anycubic
releases it in order to produce Rinkhals patches. Today this is done
with a single test printer that has its own certificate. Anycubic's
OTA server only tells that printer what is newer than its currently
installed version, and only within that printer's geographic zone.
That means firmware can be released to other models or other regions
days or weeks before the central monitor sees it.

Opt-in printers spread out the discovery surface. A K3V2 user in Europe
asking Anycubic about K3V2 firmware will see results the central
monitor (a Kobra S1 in the US) cannot see. The app does not download
the firmware on the printer; only the URL is forwarded so the
community archive can fetch it from its own infrastructure.

## How to enable

Toggle this app on from the Rinkhals touchscreen UI, or create the
enable marker manually over SSH:

```sh
touch /useremain/home/rinkhals/apps/60-firmware-collector.enabled
```

To disable:

```sh
touch /useremain/home/rinkhals/apps/60-firmware-collector.disabled
```

## Logs

All activity is logged to `/tmp/rinkhals/app-firmware-collector.log`.

## Configuration

Tunable from the app properties in the Rinkhals UI, or by editing
`/useremain/home/rinkhals/apps/60-firmware-collector.config`:

- `ingest_endpoint` -- default `https://ingest.firmwareforge.org/v1/notify`
- `check_interval_hours` -- default `24`
- `dry_run` -- `True` to log what would be sent without actually sending

## License and source

Part of the Rinkhals project. See the top-level repository for license
and contribution information.
