---
title: Vanilla Klipper
---

The **Klipper (vanilla)** app in the Rinkhals app store runs mainline Klipper on the printer in place of Anycubic's GoKlipper. It's Kobra-S1's (Antirad's) work: Klipper comes from his [Klipper fork](https://github.com/Kobra-S1/klipper-kobra-s1) with the Kobra drivers, and the ACE Pro support, ACE dashboard and printer configs come from [ACEPRO](https://github.com/Kobra-S1/ACEPRO). Rinkhals.Apps follows both, and new versions come through as app updates.

The [app's README](https://github.com/rinkhals-community/Rinkhals.Apps/blob/develop/apps/vanilla-klipper/README.md) has the full details, including the list of supported printers. This page covers what to know before you start.

## Before you install

* **Mainsail or Fluidd becomes the way to run the printer.** The app only replaces GoKlipper, not Anycubic's touchscreen program, which was written for GoKlipper. Homing and temperatures still work on the screen, but bed leveling, ACE and similar screens don't.
* **The first start takes a minute or more**, while Klipper compiles a helper on the printer. Mainsail and Fluidd won't respond until it's done.
* **It has its own config file**, `printer.klipper.cfg`, separate from GoKlipper's. Changes to `printer.cfg` or `printer.custom.cfg` don't affect it, and the other way around.
* **If Klipper doesn't come up**, the app starts GoKlipper again after three minutes (ten on the very first start), so a broken config doesn't leave you without a working printer. **KLIPPY.LOG** in Mainsail or Fluidd shows what went wrong.

## Using an ACE Pro

The ACE is **off** when the app is first installed, so a printer without one doesn't try to use it. If you have an ACE Pro or ACE 2 Pro, do these three things before your first print:

1. **Turn the ACE on.** In Mainsail, switch on **"ACE Pro"**, or type `SET_PIN PIN=ACE_Pro VALUE=1` in the console. Your choice is saved and stays after a restart. You can also set `value: 1` under `[output_pin ACE_Pro]` in `ace_<model>.cfg` (for example `ace_KS1.cfg`) and restart Klipper, but that only counts until the switch has been used once.
2. **Pass the starting tool from your slicer.** With the ACE on, the print start macro stops with "Missing required TOOL parameter" unless your slicer's start G-code passes `tool=[initial_tool]`:

    ```
    G9111 bedTemp=[first_layer_bed_temperature] extruderTemp=[first_layer_temperature[initial_tool]] tool=[initial_tool] SKIP_PURGE_FOR_ALREADY_LOADED_TOOL=1
    ```

3. **End prints with `PRINT_END CUT_TIP=1`** in your slicer's end G-code.

While the ACE is off, ACE commands fail with messages like "ACE Pro is disabled" or "Feed assist on slot 0 was not started after 3 attempts (no answer)", and the print start reports "TOOL not passed and ACE Pro is disabled". Those mean the switch is still off, not that the ACE is broken.

Filament types and colors, and the dryer, are set from the ACE dashboard at `http://<printer-ip>/ace/ace.html`. More than one ACE, adaptive purging and the other ACE options are covered in the README and in [ACEPRO](https://github.com/Kobra-S1/ACEPRO).

## Running Klipper on another computer

Two more apps let Klipper run on a separate computer, using the printer's own boards over a tunnel:

* **tunneled-klipper** connects a Raspberry Pi (or similar) to the printer over USB. See [Kobra-S1's tunneled-klipper guide](https://github.com/Kobra-S1/vanilla-klipper-swu/blob/main/tunneled-klipper.md).
* **Lan Tunnel KS1** does the same over Ethernet, on the Kobra S1 only.

While either one is running, the printer's own Mainsail shows Klipper as disconnected, since Klipper is on the other computer. From Rinkhals 20261117_01_test on, the Rinkhals web portal also holds off installs and updates while a tunnel app is running, since an update's reboot would cut off a print the other computer is running.

## Ported drivers

These Anycubic drivers were ported from Go to Python for Kobra-S1's Klipper fork:

- **lis2dw12**: [lis2dw12.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/lis2dw12.py) (ported from [extras_lis2dw12.go](https://github.com/ANYCUBIC-3D/Kobra3/blob/main/klipper-go/project/extras_lis2dw12.go))
- **cs1237**: [cs1237.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/cs1237.py) (ported from [cs1237.go](https://github.com/ANYCUBIC-3D/Kobra3/blob/main/klipper-go/project/cs1237.go))
- **probe_ks1**: [probe_ks1.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/probe_ks1.py)

There's no port of Anycubic's leviQ3, which is closed source. Probing still works through `probe_ks1`, which supports generic Klipper nozzle probing.
