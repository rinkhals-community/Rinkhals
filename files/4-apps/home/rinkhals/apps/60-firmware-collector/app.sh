source /useremain/rinkhals/.current/tools.sh

APP_ROOT=$(dirname $(realpath $0))
APP_NAME="60-firmware-collector"

# supervisor.sh is only alive while sleeping between checks, so we track it by
# pid rather than by the (mostly-absent) collector.py process.
PIDFILE=/tmp/rinkhals/firmware-collector.pid

status() {
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
        report_status $APP_STATUS_STARTED "$(cat "$PIDFILE")"
    else
        report_status $APP_STATUS_STOPPED
    fi
}

start() {
    stop

    INGEST_ENDPOINT=$(get_app_property $APP_NAME ingest_endpoint)
    INTERVAL_HOURS=$(get_app_property $APP_NAME check_interval_hours)
    DRY_RUN=$(get_app_property $APP_NAME dry_run)

    log "Firmware collector starting (interval: ${INTERVAL_HOURS}h, dry_run: ${DRY_RUN})"
    log "Ingest endpoint: ${INGEST_ENDPOINT}"

    mkdir -p $RINKHALS_LOGS
    chmod +x $APP_ROOT/supervisor.sh

    # supervisor.sh owns scheduling and stays resident (a few hundred KB while
    # it sleeps) instead of a ~14 MB Python daemon. It spawns collector.py for
    # each check, which runs ~20s and exits, freeing its memory.
    INGEST_ENDPOINT="$INGEST_ENDPOINT" \
    INTERVAL_HOURS="$INTERVAL_HOURS" \
    DRY_RUN="$DRY_RUN" \
    KOBRA_MODEL_CODE="$KOBRA_MODEL_CODE" \
    RINKHALS_VERSION="$RINKHALS_VERSION" \
    RINKHALS_LOGS="$RINKHALS_LOGS" \
        $APP_ROOT/supervisor.sh &

    echo $! > "$PIDFILE"
}

stop() {
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null
        rm -f "$PIDFILE"
    fi
    # Also stop an in-flight one-shot check, if any.
    kill_by_name collector.py
}

case "$1" in
    status)
        status
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    *)
        echo "Usage: $0 {status|start|stop}" >&2
        exit 1
        ;;
esac
