---
title: Rinkhals project
weight: 0
---

## Core principles

The goal of Rinkhals is to expand existing Anycubic features with better compatibility, apps and more. It will likely not support all use cases, like running vanilla Klipper or your specific feature / plugin.

Even though progress have been made for running vanilla Klipper (still not working), the goal is NOT to provide a complete replacement for Anycubic firmware, but instead to complement stock firmware.

Rinkhals is targeted at a wide audience, not experts. I designed it to be as easy to use as possible with the default configuration for anyone to use. It is still a firmware mod and people should avoid using it if they are not comfortable potentially making their printer not work anymore. Because of that, experts might find the firmware still too limited, it's intended even though I exposed ways to go deeper if needed.

Rinkhals includes many firmware protection features. It is designed as an overlay and won't modify any files in stock firmware except for the launcher script. Then everyhting is isolated to allow reverting back to stock very easily. Rinkhals will disable itself if anything goes wrong during its startup.

For anyone curious enough: [Rinkhals internals](how-rinkhals-works.md)

## Kobra X status

Some Kobra X firmware images are available publicly and the SWU password is known.

However, the software stack differs significantly from the K3 family. Anycubic appears to have moved from GoKlipper-based firmware to a K4 base with a C++ Klipper port. Because of this, Kobra X support is not expected to be a straightforward Rinkhals port.

Additionally, Kobra X SWU updates appear to require certificate validation. Until a reliable method is found to bypass or satisfy this requirement, Rinkhals-style SWU injection is not currently feasible on Kobra X.


## Summary

- There are no prerequisites for Rinkhals, except version compatibility
- [Installation instructions](installation-and-firmware-updates.md)
- Rinkhals will not remove any feature from Anycubic, just add more
  - The only difference is the camera not being available in Anycubic apps by default. This can be changed, check the [FAQ](../faq.md)
- After installation; Orca, OctoApp, Mainsail and more will work directly without any special configuration (except adding the printer IP of course)

TLDR:
- SSH on port 22 (root: rockchip except for K3M)
- Rinkhals web portal on port 80 (the printer's bare IP) and port 8090
- Mainsail on port 4409
- Fluidd on port 4408
- Moonraker API on port 7125 (use this for OrcaSlicer and other slicer/automation uploads)


## Features and built-in apps

### ADB (Android Debug Bridge)

ADB is a protocol and client / server programs to help remote accessing and debugging Android devices. Nowadays it is used as a remote access protocol on many other devices.

ADB is bundled but disabled in most Anycubic Kobra firmwares (except for the KS1). Rinkhals re-enables ADB on startup. ADB listens on port 5555 by default.

To connect, you'll need to install the ADB client usually available in Android SDK platform tools: https://developer.android.com/tools/adb

Then, to connect and access a shell:
``` sh
adb connect PRINTER_IP:5555
adb shell
```


### SSH

OpenSSH is bundled but disbaled in most Anycubic Kobra firmwares (except for the KS1). 
Rinkhals bundles Dropbear, a lightweight SSH server alternative to OpenSSH.

During Rinkhals startup, Dropbear is started and listens on port 22. Default root credentials are used for password authentication exclusively.

On the K2P, K3, K3V2 and KS1, the root password is `rockchip`
On the K3M, the root password is not yet known.


### Default apps

System apps are normal Rinkhals apps that are bundled in every Rinkhals release. They can still be enabled or disabled depending on your preference, and they can be overriden by adding a user app with the same name.


#### Hostname & DNS

This app sets a custom hostname for the printer and advertises it on the local network. Useful when you have multiple Kobra printers and need to tell them apart.

On startup it sets the system hostname, runs a lightweight mDNS responder so the printer is reachable as `<hostname>.local` from any device on the network, and restarts `udhcpc` with the hostname so the router registers it for short-name resolution.

When no custom hostname is configured, one is auto-generated from the printer model and device ID, for example `kobra-k3-a1b2` or `kobra-ks1-f3e9`, so each printer gets a unique name without manual setup.

| 10-hostname-dns | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/10-hostname-dns/app.json) |
| Default state | Enabled |
| CPU usage | Negligible |
| Memory usage | ~1 MB |


#### Moonraker

Moonraker is an API gateway for Klipper. It exposes Klipper information and interactions to 3rd party clients using web API and websockets.

Rinkhals is using [vanilla Moonraker](https://github.com/Arksine/moonraker) plus [a special Kobra component](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/40-moonraker/kobra.py). This component is used to modify vanilla Moonraker behavior and adapt it to GoKlipper.

When using GoKlipper and LAN mode, this component will intercept Print calls from Mainsail, Fluid, Orca and more and replace it with a proprietary Anycubic call. This call allows a few settings to be changed, such as Bed leveling on print start, flow calibration and resonance testing.
By default, those settings are all disabled for every print. This behavior can be changed using [app configuration](apps/configuration.md).

!!! warning

    This app consumes a lot of memory. Be careful while using multiple frontends (Mainsail, Fluidd, ...) at the same time.

| 40-moonraker | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/40-moonraker/app.json) |
| Default state | Enabled |
| Port | 7125 |
| CPU usage | 10% ~ 20% |
| Memory usage | 25MB ~ 100+MB |


#### Mainsail

Mainsail is a web interface for Klipper-based printers. It connects to Moonraker over web API and websocket to expose live control and metrics.

It's a SPA (Single Page Application) served using [Lighttpd](https://www.lighttpd.net) web server on port 4409.

Lighttpd is also configured to expose up to 4 cameras proxying to mjpg-streamer. Cameras are accessible using /webcam or /webcam0 for the first one, then /webcam1, /webcam2 and /webcam3 for the other.

!!! note

    Port 80 (the printer's bare IP) is served by the Rinkhals web portal (65-rinkhals-web), which links to Mainsail, Fluidd and the other tools from its dashboard.
    Earlier builds redirected port 80 to Mainsail or Fluidd using a per-connection socat process; that redirect has been removed in favor of the web portal owning port 80 directly. Mainsail and Fluidd are now reached on their own ports (4409 and 4408).

| 25-mainsail | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/25-mainsail/app.json) |
| Default state | Enabled |
| Port | 4409 |
| CPU usage | 0 ~ 3 % |
| Memory usage | 1 ~ 4 MB |


#### Fluidd

Fluidd is another web interface for Klipper-based printers. It connects to Moonraker over web API and websocket to expose live control and metrics.

Please refer to Mainsail documentation above as the behavior is exactly the same.

| 26-fluidd | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/26-fluidd/app.json) |
| Default state | Enabled |
| Port | 4408 |
| CPU usage | 0 ~ 3 % |
| Memory usage | 1 ~ 4 MB |


#### mjpg-streamer

mjpg-streamer is a lightweight web server to expose a camera stream over HTTP. In Rinkhals, it is used to expose the connected cameras in Mainsail, Fluidd and other Moonraker clients.

When starting, this app will scan for connected cameras and start one process for each of them. The first process will listen to port 8080, the next 8081 and so on.

By default, a low compatible resolution of 640x480 is used. Resolution can be changed using [app configuration](apps/configuration.md).

| 30-mjpg-streamer | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/30-mjpg-streamer/app.json) |
| Default state | Enabled |
| Port | 8080, 8081*, 8082*, 8083* |
| CPU usage | ? |
| Memory usage | ? |


#### VNC / Remote display

This app starts a VNC server on the printer to expose remote control of the display and its touch inputs.

When enabled and started, you can connect your VNC client to port 5900 or access a web version on port 5800.

| 50-remote-display | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/50-remote-display/app.json) |
| Default state | Disabled |
| Port | 5800, 5900 |
| CPU usage | 1% when idle, 15 ~ 25 % with active connections |
| Memory usage | ? |


#### Rinkhals monitor

This app allows to collect system metrics and expose them in a MQTT server. The data is preformatted to be discovered and used with Home Assistant but might be used by anything reading MQTT messages.

When enabled and started and if using LAN mode, this app will send metrics to the internal printer Mochi server. This server is available on port 9883 and you will need credentials to connect to it. Username and password can be found in `/userdata/app/gk/config/device_account.json`

Metrics are be collected and sent every 30s. High level system metrics are also written to the app log in `/useremain/rinkhals/.current/logs/app-monitor.log`

| 65-rinkhals-web | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/65-rinkhals-web/app.json) |
| Default state | Disabled |
| CPU usage | 0 ~ ? |
| Memory usage | 6 MB |


#### Firmware Collector (opt-in)

This app helps the community catch new Anycubic firmware releases faster. It is **disabled by default** and you must enable it explicitly before it does anything.

When enabled, once per day the app:

1. Tests basic internet reachability. If the printer cannot reach the internet (for example because it is configured in LAN-only mode), the app logs a message and waits until the next cycle.
2. Asks Anycubic's OTA server whether a firmware newer than the one currently installed exists for this printer model. This uses the printer's own existing Anycubic device certificate, the same way the touchscreen "Check for updates" button does.
3. If Anycubic announces a newer firmware version, the app sends a small notification to the Rinkhals community firmware archive at `https://ingest.firmwareforge.org/v1/notify`.

Only `model_code`, `model_id`, and `current_version` are transmitted, and only when a new firmware version is announced. **No certificates, account information, or personal data are ever sent.** A `Dry run` mode is available for users who want to verify behaviour without uploading.

The notification feeds the same `firmware-fetcher` task that maintains the [community firmware archive](https://rinkhals.firmwareforge.org), helping the project produce Rinkhals patches for new Anycubic releases sooner.

| 60-firmware-collector | |
|-|-|
| App manifest | [app.json](https://github.com/rinkhals-community/Rinkhals/blob/master/files/4-apps/home/rinkhals/apps/60-firmware-collector/app.json) |
| Default state | Disabled (opt-in) |
| CPU usage | Negligible |
| Memory usage | ~3 MB |
