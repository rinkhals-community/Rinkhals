"""
Single-shot Anycubic OTA query for this printer.

Uses the printer's own device certificate (already present in
/userdata/app/gk/config/device.ini and /useremain/app/gk/cert3/*) to ask
Anycubic's MQTT OTA broker whether a firmware newer than the currently
installed version exists.

No data is sent to anywhere other than Anycubic's own OTA broker (which
already knows this printer exists). The result is returned to the caller
for the collector daemon to decide what to do with it.

Adapted from rinkhals-firmware-site/firmware-fetcher/check_updates.py
which Martin Bogomolni wrote for the central scrape pipeline. This
version is single-printer-single-shot, no model spoofing, no chain walk.
"""

import base64
import configparser
import hashlib
import json
import logging
import os
import ssl
import subprocess
import time
import urllib.parse
import uuid

import paho.mqtt.client as mqtt


log = logging.getLogger(__name__)


DEVICE_INI_PATH = "/userdata/app/gk/config/device.ini"
API_CFG_PATH = "/userdata/app/gk/config/api.cfg"
VERSION_PATH = "/useremain/dev/version"

# How long to wait for an MQTT response before giving up.
MQTT_TIMEOUT_SECONDS = 20


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _now_ms() -> int:
    return round(time.time() * 1000)


def _read_device_ini():
    if not os.path.exists(DEVICE_INI_PATH):
        raise RuntimeError(f"Missing device config: {DEVICE_INI_PATH}")
    config = configparser.ConfigParser()
    with open(DEVICE_INI_PATH, "r") as f:
        config.read_string(f.read())

    environment = config["device"]["env"]
    zone = config["device"]["zone"]
    section = f"cloud_{environment}" if zone == "cn" else f"cloud_{zone}_{environment}"
    return config[section], zone


def _read_api_cfg():
    if not os.path.exists(API_CFG_PATH):
        raise RuntimeError(f"Missing API config: {API_CFG_PATH}")
    with open(API_CFG_PATH, "r") as f:
        return json.loads(f.read())


def _read_current_version() -> str:
    if not os.path.exists(VERSION_PATH):
        raise RuntimeError(f"Missing version file: {VERSION_PATH}")
    with open(VERSION_PATH, "r") as f:
        return f.read().strip()


def _build_ssl_context(cert_path: str) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_ciphers("ALL:@SECLEVEL=0")
    ctx.load_cert_chain(f"{cert_path}/deviceCrt", f"{cert_path}/devicePk", None)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_verify_locations(f"{cert_path}/caCrt")
    return ctx


def _build_mqtt_credentials(cloud_config, model_id: str, device_id: str):
    """Replicates the username/password derivation the Anycubic firmware uses."""
    device_key = cloud_config["deviceKey"]
    cert_path = cloud_config["certPath"]

    # The encryption call uses the printer's own openssl; we keep the same
    # subshell invocation pattern as check_updates.py to avoid any divergence.
    cmd = (
        f'printf "{device_key}" | '
        f'openssl rsautl -encrypt -inkey {cert_path}/caCrt -certin -pkcs | '
        f'xxd -p -c 256'
    )
    encrypted = subprocess.check_output(["sh", "-c", cmd])
    encrypted = encrypted.decode().strip()
    encrypted = bytes.fromhex(encrypted)
    encrypted_b64 = base64.b64encode(encrypted).decode()

    taco = f"{device_id}{encrypted_b64}{device_id}"
    username = f"dev|fdm|{model_id}|{_md5(taco)}"
    return username, encrypted_b64


def query_anycubic_ota() -> dict:
    """
    Ask Anycubic if a firmware newer than the printer's current version exists.

    Returns:
      {
        "current_version": "...",
        "next_version": "...",         # may be None if no update
        "package_url": "...",          # may be None
        "package_md5": "...",          # may be None
        "package_size": int,           # may be None
        "model_id": "...",
        "zone": "us"|"eu"|"cn"|...,
        "raw": {...}                   # full Anycubic response data, for debugging
      }

    Raises RuntimeError on transport-level failure (missing config, MQTT
    refused, timeout). A response with no update available is NOT an error;
    it just returns next_version=None.
    """
    cloud_config, zone = _read_device_ini()
    api_config = _read_api_cfg()
    current_version = _read_current_version()

    model_id = api_config["cloud"]["modelId"]
    device_id = cloud_config["deviceUnionId"]
    mqtt_broker = cloud_config["mqttBroker"]

    username, password = _build_mqtt_credentials(cloud_config, model_id, device_id)

    state = {"result": None, "error": None}

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(
            f"anycubic/anycubicCloud/v1/+/printer/{model_id}/{device_id}/ota"
        )
        payload = {
            "type": "ota",
            "action": "reportVersion",
            "timestamp": _now_ms(),
            "msgid": str(uuid.uuid4()),
            "state": "done",
            "code": 200,
            "msg": "done",
            "data": {
                "device_unionid": device_id,
                "machine_version": "1.1.0",
                "peripheral_version": "",
                "firmware_version": current_version,
                "model_id": model_id,
            },
        }
        client.publish(
            f"anycubic/anycubicCloud/v1/printer/public/{model_id}/{device_id}/ota/report",
            json.dumps(payload),
        )

    def on_connect_fail(client, userdata):
        state["error"] = "Failed to connect to Anycubic MQTT broker"
        client.disconnect()

    def on_message(client, userdata, msg):
        try:
            response = json.loads(msg.payload.decode("utf-8"))
            state["result"] = response.get("data") or {}
        except Exception as exc:
            state["error"] = f"Malformed OTA response: {exc}"
        client.disconnect()

    endpoint = urllib.parse.urlparse(mqtt_broker)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
        client_id=device_id,
    )
    if endpoint.scheme == "ssl":
        client.tls_set_context(_build_ssl_context(cloud_config["certPath"]))
        client.tls_insecure_set(True)

    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_message = on_message
    client.username_pw_set(username, password)

    client.connect(endpoint.hostname, endpoint.port or 1883)

    # Loop with a timeout so a silent broker doesn't hang us forever.
    deadline = time.time() + MQTT_TIMEOUT_SECONDS
    client.loop_start()
    try:
        while time.time() < deadline:
            if state["result"] is not None or state["error"] is not None:
                break
            time.sleep(0.1)
    finally:
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass

    if state["error"]:
        raise RuntimeError(state["error"])
    if state["result"] is None:
        raise RuntimeError("Timed out waiting for Anycubic OTA response")

    data = state["result"]
    return {
        "current_version": current_version,
        "next_version": data.get("firmware_version"),
        "package_url": data.get("firmware_url") or data.get("package_url"),
        "package_md5": data.get("firmware_md5") or data.get("package_md5"),
        "package_size": data.get("firmware_size") or data.get("package_size"),
        "model_id": model_id,
        "zone": zone,
        "raw": data,
    }
