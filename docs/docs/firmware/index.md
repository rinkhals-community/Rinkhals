---
title: Firmware Internals
weight: 3
---

# Firmware Internals & Research

This section is dedicated to the technical details, reverse engineering, and low-level workings of the Anycubic custom software stack (GoKlipper) as well as the underlying embedded Linux system on the Kobra series printers. 

It serves as a resource for developers, contributors, and curious users who want to understand what makes these printers tick under the hood.

## Topics Covered

* [**GoKlipper**](goklipper.md): Deep dive into Anycubic's proprietary Klipper replacement written in Go.
* [**File Structure**](file-structure.md): Overview of the printer's internal filesystem and Rinkhals integration paths.
* [**Binary Decompilation & Patching**](binary-decompilation-and-patching.md): Methods and findings for analyzing and modifying closed-source Anycubic binaries.
* [**IPC Commands**](ipc-commands.md): Details on the Inter-Process Communication used by the system UI and services.
* [**MQTT Protocol**](mqtt.md): How the printer communicates with Anycubic's cloud services and local broker configurations.
* [**Vanilla Klipper**](vanilla-klipper.md): Current status and research progress towards replacing GoKlipper with standard, open-source Klipper.

If you are looking to contribute to the development of Rinkhals or modify the core functionality of your printer, these documents provide the essential foundation.
