---
title: IPC commands
---

## Inter-process communication between Kobra processes

gklib, gkapi and k3sysui communicate mainly via UNIX domain sockets and TCP.

### Trace commands

Intercept gklib IO (can use gkapi or K3SysUi PID instead, or all three together):

```shell
strace -z -Y -y -f -e trace=read,write -e signal=none --strings-in-hex=non-ascii-chars -s 1000 -p <pid-of-gklib>
```

Intercept socket API:

```shell
2>&1 | grep 'socket:'
```

Intercept serial comms:

```shell
2>&1 | grep '/dev/tty'
```

## Go-klipper (gklib) API commands
The socket used by gklib (`/tmp/unix_uds1`) implements a limited [Klipper](https://www.klipper3d.org/API_Server.html) API. In addition it supports the following commands:

### query filament hub

```json
{"method":"objects/query","params":{"objects":{"filament_hub":null}},"id":30}\\x03
```

response:

```json
{"id":30,"result":{"eventtime":10406.219115208,"status":{"filament_hub":{"auto_refill":0,"current_filament":"","cutter_state":0,"ext_spool":0,"ext_spool_status":"ready","filament_hubs":[{"id":0,"status":"ready","dryer_status":{"status":"stop","target_temp":0,"duration":0,"remain_time":0},"temp":45,"slots":[{"index":0,"status":"ready","sku":"","type":"PLA","color":[158,166,180],"rfid":1,"source":2},{"index":1,"status":"ready","sku":"","type":"PLA","color":[255,255,255],"rfid":1,"source":2},{"index":2,"status":"empty","sku":"","type":"","color":[0,0,0],"source":3},{"index":3,"status":"empty","sku":"","type":"","color":[0,0,0],"source":3}]}],"statistics":{"unwind_stat":[0,0,0,0,0],"feed_stat":[29,0,0,0,0]}}}}}\\x03
```

### auto-refill

```json
{"method":"filament_hub/set_config","params":{"auto_refill":1},"id":31}\\x03
```

response:

```json
{"id":31,"result":{}}\\x03
```

### start drying

```json
{"method":"filament_hub/start_drying","params":{"duration":240,"fan_speed":0,"id":0,"temp":45},"id":33}\\x03
```

response:

```json
{"id":33,"result":{}}\\x03
```

### stop drying

```json
{"method":"filament_hub/stop_drying","params":{"id":0},"id":34}\\x03
```

response:

```json
{"id":34,"result":{}}\\x03
```

### set filament info
```json
{"method":"filament_hub/set_filament_info","params":{"color":{"B":65,"G":209,"R":254},"id":0,"index":2,"type":"PLA"},"id":34}\\x03
```

### get filament info

```json
"{"method":"filament_hub/filament_info",\\
"params":{"id": 0,"index":1},"id":31}"
```

response:

```json
{"id":31,"result":{"index":1,"sku":"","brand":"","type":"PLA","color":[255,255,255],"extruder_temp":{"min":0,"max":0},"hotbed_temp":{"min":0,"max":0},"diameter":0,"rfid":1,"source":2}}
```

### set led

1 = on, 0 = off

```json
{"method":"led/set_led","params":{"S":1},"id":37}\\x03
```

response:

```json
{"id":37,"result":{}}\\x03
```

### list registered endpoints

```json
{"method":"list_endpoints","params":{},"id":32}
```

## gkapi commands

gkapi communicates in Cloud/LAN mode with the Slicer and/or Cloud using MQTT (see [Reverse Engineering - MQTT](mqtt.md)).

K3Sysui, however, connects to gkapi via TCP on port `18086`. The protocol here is almost identical to the one used by the gklib socket. However, some commands are only handled by gkapi. This port also acts as a proxy between gklib and k3sysui.

### LAN mode

```json
{"id": 2017, "method": "Printer/QueryLanPrintStatus", "params": {}}\\x03
```

Returns `{"open": 1}` in LAN mode and `{"open": 0}` in cloud mode.

```json
{"id": 2015, "method": "Printer/OpenLanPrint", "params": {}}\\x03
{"id": 2016, "method": "Printer/CloseLanPrint", "params": {}}\\x03
```

Switch to LAN mode or cloud mode. gkapi updates `/useremain/dev/remote_ctrl_mode` itself. K3SysUi isn't notified when another client switches modes: it only asks with `Printer/QueryLanPrintStatus` when it starts and after its own switch.

When LAN mode is turned on from the touchscreen, K3SysUi sends `Cloud/Unbind` before `Printer/OpenLanPrint` (seen on the KS1 with 2.7.2.7), which removes the printer from the Anycubic account. Turning it off only sends `Printer/CloseLanPrint`. The [Cloud to LAN bridge](https://github.com/rinkhals-community/Rinkhals.Apps/tree/master/apps/cloud2lan-bridge) calls `Printer/OpenLanPrint` directly to keep the account.

### cloud account

```json
{"id": 2008, "method": "Cloud/BindQuery", "params": {}}\\x03
```

Returns `{"bind": 1, "iconpath": "", "nickname": "..."}` when the printer is on an Anycubic account. gkapi asks the cloud for this, so in LAN mode, where its cloud client is off, it returns `bind: 0` even when the printer is still on the account.

```json
{"id": 2010, "method": "Cloud/Unbind", "params": {}}\\x03
```

Removes the printer from the Anycubic account.

### set camera led

(does not work without gkcam)

```json
{"id": 2018,"method": "Led/SetCameraLed","params": {"enable": 1}}\\x03
```