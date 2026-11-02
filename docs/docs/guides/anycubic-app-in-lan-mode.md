---
title: Anycubic app in LAN mode
---

In LAN mode, the stock firmware stops talking to Anycubic's cloud, so the Anycubic app can no longer reach the printer. The [Cloud to LAN bridge](https://github.com/rinkhals-community/Rinkhals.Apps/tree/master/apps/cloud2lan-bridge) app connects to Anycubic's cloud on the printer's behalf, so you can keep using the Anycubic app (status, controls and the camera) while the printer stays in LAN mode for Mainsail, Orca and the rest of Rinkhals.

!!! warning "Don't turn on LAN mode from the touchscreen"

    On recent firmware (seen on the Kobra S1 with 2.7.2.7), turning on LAN mode with the touchscreen's own toggle also **removes the printer from your Anycubic account**. The Anycubic app then shows "Scan to add device", and the bridge has nothing left to connect to.

    Use the bridge's **LAN mode** setting instead, as described below. It switches the printer to LAN mode without removing it from your account.

## Setting it up

1. With the printer in cloud mode (the default), add it to your Anycubic account by scanning the QR code in the Anycubic app, if you haven't already.
2. Install the Cloud to LAN bridge app (version 1.2 or later), then enable and start it.
3. On the touchscreen, go to Settings (gear icon) > Rinkhals > Apps > Cloud to LAN bridge, open its settings and turn on **LAN mode (keeps the printer on your Anycubic account, reboot after changing)**.
4. **Reboot the printer.**

After the reboot, the printer is in LAN mode, the bridge starts by itself, and the Anycubic app shows the printer online again. It can take a minute after boot while the printer's clock and network come up.

If you prefer SSH, `set_app_property cloud2lan-bridge lan_mode True` does the same as step 3, while the bridge is running.

## Why reboot?

The touchscreen only checks whether LAN mode is on when it starts. After you change the bridge's setting, its LAN mode toggle keeps showing the old state until you reboot. If it shows LAN mode as off and you tap it to turn LAN mode on, the printer is removed from your Anycubic account.

## Going back to cloud mode

Turn off the bridge's **LAN mode** setting and reboot. Turning LAN mode off from the touchscreen is also fine, only turning it on removes the printer from your account. The bridge keeps its setting in step with the printer's real mode either way.

## If the printer already disappeared from the Anycubic app

1. Switch the printer back to cloud mode, using the touchscreen toggle or the bridge's setting.
2. Scan the QR code again in the Anycubic app.
3. Turn on LAN mode from the bridge's setting, then reboot.

## Notes

- The camera in the Anycubic app uses the printer's own camera service, so it won't work while the mjpg-streamer app has the camera (see the [FAQ](../faq.md#after-installing-rinkhals-the-camera-doesnt-work-in-anycubic-apps)).
- On the same network as the printer, Anycubic Slicer and the Anycubic app may talk to the printer directly instead of through the cloud. To check that the bridge itself works, try the Anycubic app on mobile data.
