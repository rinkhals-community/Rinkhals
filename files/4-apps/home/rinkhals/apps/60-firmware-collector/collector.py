"""
Firmware collector, one-shot (opt-in).

Runs a single discovery cycle and exits. Scheduling (startup jitter, the
daily interval, per-cycle jitter) lives in supervisor.sh, not here: a shell
loop sleeps between checks for a few hundred KB instead of keeping a ~14 MB
Python interpreter (interpreter + paho.mqtt + ssl) resident 24/7 just to
wait. Each check spawns this script, which runs for ~20s and frees all of
its memory on exit.

One cycle:
  1. Test general internet reachability (cheap TCP connect). If offline,
     log and skip. Some users run their printer LAN-only.
  2. Ask Anycubic via MQTT (using this printer's own device cert) whether
     a firmware newer than the currently installed version exists.
  3. If a newer version is reported, send a small notification to the
     Rinkhals community ingest endpoint containing only the public URL
     and version metadata. Never sends device certs, account info, or
     any personal data.

All network operations have explicit timeouts so a hung Anycubic or
ingest server can't wedge the check.
"""

import json
import logging
import os
import socket
import sys
import urllib.error
import urllib.request

import firmware_query


INGEST_ENDPOINT = os.environ.get(
    "INGEST_ENDPOINT", "https://ingest.firmwareforge.org/v1/notify"
)
DRY_RUN = (os.environ.get("DRY_RUN", "False") or "False").lower() == "true"
KOBRA_MODEL_CODE = os.environ.get("KOBRA_MODEL_CODE", "unknown")
RINKHALS_VERSION = os.environ.get("RINKHALS_VERSION", "unknown")

# Used as the basic internet-reachability probe. Cloudflare DNS responds on
# TCP/443 and is unlikely to be blocked at the same time the printer can
# still reach Anycubic. Tested before each Anycubic call so a printer that
# was online yesterday but is offline today doesn't keep trying.
REACHABILITY_HOST = "1.1.1.1"
REACHABILITY_PORT = 443
REACHABILITY_TIMEOUT_SECONDS = 5

INGEST_REQUEST_TIMEOUT = 30


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("firmware-collector")


def _has_internet() -> bool:
    try:
        with socket.create_connection(
            (REACHABILITY_HOST, REACHABILITY_PORT),
            timeout=REACHABILITY_TIMEOUT_SECONDS,
        ):
            return True
    except OSError:
        return False


def _send_notification(payload: dict) -> bool:
    """
    POST the notification to the ingest endpoint.

    Returns True on a 2xx response, False otherwise. Never raises:
    a transient ingest outage should not crash the daemon.
    """
    if DRY_RUN:
        log.info("[dry_run] would POST %s to %s", json.dumps(payload), INGEST_ENDPOINT)
        return True

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        INGEST_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"rinkhals-firmware-collector/{RINKHALS_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=INGEST_REQUEST_TIMEOUT) as resp:
            status = resp.getcode()
            body_text = resp.read(2048).decode("utf-8", errors="replace")
            if 200 <= status < 300:
                log.info("Notification accepted (HTTP %d): %s", status, body_text)
                return True
            log.warning("Ingest returned HTTP %d: %s", status, body_text)
            return False
    except urllib.error.HTTPError as exc:
        log.warning("Ingest HTTP error %d: %s", exc.code, exc.reason)
        return False
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        log.warning("Ingest transport error: %s", exc)
        return False


def _version_tuple(s: str):
    """Best-effort numeric version compare. Non-numeric segments sort as 0."""
    out = []
    for part in (s or "").split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def _cycle():
    """One discovery cycle. All errors are caught and logged."""
    if not _has_internet():
        log.info("No internet reachability, skipping this cycle")
        return

    log.info("Querying Anycubic for %s firmware updates...", KOBRA_MODEL_CODE)
    try:
        result = firmware_query.query_anycubic_ota()
    except Exception as exc:
        log.warning("Anycubic query failed: %s", exc)
        return

    current = result.get("current_version")
    next_v = result.get("next_version")

    if not next_v:
        log.info("Anycubic reported no update available (current %s)", current)
        return

    if _version_tuple(next_v) <= _version_tuple(current):
        log.info(
            "Anycubic returned version %s but it is not newer than current %s, skipping",
            next_v,
            current,
        )
        return

    payload = {
        "model_code": KOBRA_MODEL_CODE,
        "model_id": result.get("model_id"),
        "current_version": current,
        "next_version": next_v,
        "package_url": result.get("package_url"),
        "package_md5": result.get("package_md5"),
        "package_size": result.get("package_size"),
        "zone": result.get("zone"),
        "rinkhals_version": RINKHALS_VERSION,
    }

    if not payload["package_url"]:
        log.warning(
            "Anycubic announced version %s but no package_url present in response; skipping",
            next_v,
        )
        return

    log.info(
        "New firmware discovered: %s %s -> %s (size=%s, md5=%s)",
        KOBRA_MODEL_CODE,
        current,
        next_v,
        payload["package_size"],
        payload["package_md5"],
    )

    _send_notification(payload)


def main():
    """Run one discovery cycle and exit. supervisor.sh calls this on a schedule."""
    log.info(
        "Running one check. Model=%s, dry_run=%s, ingest=%s",
        KOBRA_MODEL_CODE,
        DRY_RUN,
        INGEST_ENDPOINT,
    )
    _cycle()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception("Unexpected error: %s", exc)
        sys.exit(1)
