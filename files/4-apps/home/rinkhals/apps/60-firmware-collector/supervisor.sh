#!/bin/sh
#
# Lightweight scheduler for the firmware collector.
#
# The actual Anycubic query (collector.py) runs for ~20s once a day. Rather
# than keep a ~14 MB Python interpreter resident 24/7 just to sleep between
# checks, this shell supervisor owns the sleeping (a few hundred KB, sharing
# libs already loaded by the other shells on the system) and only spawns
# Python for each check. Python then exits and frees all of its memory, so
# the app's steady-state footprint is effectively zero with a brief ~14 MB
# spike once per interval.
#
# The printer's busybox has no cron, so we schedule ourselves.
#
# Expects INGEST_ENDPOINT, INTERVAL_HOURS, DRY_RUN, KOBRA_MODEL_CODE,
# RINKHALS_VERSION and RINKHALS_LOGS in the environment (set by app.sh).

APP_ROOT=$(dirname $(realpath "$0"))
cd "$APP_ROOT" || exit 1

LOG="${RINKHALS_LOGS:-/tmp/rinkhals}/app-firmware-collector.log"
INTERVAL_HOURS="${INTERVAL_HOURS:-24}"
INTERVAL_SECONDS=$(awk -v h="$INTERVAL_HOURS" 'BEGIN { print int(h * 3600) }')

# Sleep in the background and wait on it, so a TERM/INT can interrupt the nap
# immediately (a foreground `sleep` would block the trap until it returns).
SLEEP_PID=""
trap 'kill "$SLEEP_PID" 2>/dev/null; exit 0' TERM INT

nap() {
    sleep "$1" &
    SLEEP_PID=$!
    wait "$SLEEP_PID"
    SLEEP_PID=""
}

# rand_between LO HI -> integer in [LO, HI]
rand_between() {
    awk -v lo="$1" -v hi="$2" 'BEGIN { srand(); print lo + int(rand() * (hi - lo + 1)) }'
}

# Startup jitter (1 to 30 min) so opted-in printers don't all hit Anycubic at
# the same minute after a community-wide reboot or update.
nap "$(rand_between 60 1800)"

while true; do
    python3 collector.py >> "$LOG" 2>&1

    # Interval plus or minus up to 1h of jitter, floored at 60s, so checks
    # stay spread out over time instead of resynchronizing.
    JITTER=$(rand_between -3600 3600)
    NEXT=$(awk -v b="$INTERVAL_SECONDS" -v j="$JITTER" 'BEGIN { n = b + j; if (n < 60) n = 60; print n }')
    nap "$NEXT"
done
