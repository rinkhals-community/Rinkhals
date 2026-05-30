source /useremain/rinkhals/.current/tools.sh

APP_ROOT=$(dirname $(realpath $0))
APP_NAME="60-firmware-collector"

status() {
    PIDS=$(get_by_name collector.py)

    if [ "$PIDS" = "" ]; then
        report_status $APP_STATUS_STOPPED
    else
        report_status $APP_STATUS_STARTED "$PIDS"
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
    cd $APP_ROOT

    INGEST_ENDPOINT="$INGEST_ENDPOINT" \
    INTERVAL_HOURS="$INTERVAL_HOURS" \
    DRY_RUN="$DRY_RUN" \
    KOBRA_MODEL_CODE="$KOBRA_MODEL_CODE" \
    RINKHALS_VERSION="$RINKHALS_VERSION" \
        python3 collector.py >> $RINKHALS_LOGS/app-firmware-collector.log 2>&1 &
}

stop() {
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
