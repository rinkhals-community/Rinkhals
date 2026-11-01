---
title: Vanilla Klipper
---

## Status

The Rinkhals vanilla-klipper app has been retired from the app store, and a replacement app is being worked on. Until it's available, there is no vanilla Klipper app from Rinkhals.

## K3 and KS1 Support

Vanilla Klipper works on KS1 and K3 printers, but it needs a current klipper base and some driver additions. Without them, you may run into startup errors (e.g., Error Code 22 on the printer display).

For KS1/K3 vanilla-klipper builds, this community repository contains the necessary klipper base and driver patches:

- [https://github.com/Kobra-S1/vanilla-klipper-swu](https://github.com/Kobra-S1/vanilla-klipper-swu)

### Ported Drivers

The following drivers have been ported from Go to Python and are available in the dev branch:

- **lis2dw12**: [lis2dw12.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/lis2dw12.py) (ported from [extras_lis2dw12.go](https://github.com/ANYCUBIC-3D/Kobra3/blob/main/klipper-go/project/extras_lis2dw12.go))
- **cs1237**: [cs1237.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/cs1237.py) (ported from [cs1237.go](https://github.com/ANYCUBIC-3D/Kobra3/blob/main/klipper-go/project/cs1237.go))
- **probe_ks1**: [probe_ks1.py](https://github.com/Kobra-S1/klipper-kobra-s1/blob/Kobra-S1-Dev/klippy/extras/probe_ks1.py)

Development branch: [https://github.com/Kobra-S1/klipper-kobra-s1/tree/Kobra-S1-Dev](https://github.com/Kobra-S1/klipper-kobra-s1/tree/Kobra-S1-Dev)

### leviQ3 Driver

There is no leviQ3 port available, as this is closed-source IP of Anycubic. However, probing is still possible using the `probe_ks1` driver, which supports generic Klipper nozzle probing.

## Tunneled Klipper for SBCs

An alternative Rinkhals APP build is available that allows running vanilla Klipper on SBCs like the Raspberry Pi 4/5. This utilizes a Rinkhals "tunnel" app which tunnels the serial MCU communication between the printer and RPi via OTG USB Serial Gadget mode.

More information: [https://github.com/Kobra-S1/vanilla-klipper-swu/blob/main/tunneled-klipper.md](https://github.com/Kobra-S1/vanilla-klipper-swu/blob/main/tunneled-klipper.md)