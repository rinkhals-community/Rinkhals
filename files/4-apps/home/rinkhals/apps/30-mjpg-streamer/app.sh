. /useremain/rinkhals/.current/tools.sh

export APP_ROOT=$(dirname $(realpath $0))
export APP_LOG=$RINKHALS_LOGS/app-mjpg-streamer.log

# Track the monitor by pid instead of by name. The previous `get_by_name
# mjpg_monitor` check-then-spawn was a TOCTOU race: two starts could both see
# "not running" and each spawn a monitor. That is not benign here - every
# monitor's restart path begins with `kill_by_name mjpg_streamer`, so duplicate
# monitors kill each other's streamer in a loop and the camera flaps.
# (Observed on hardware: monitors at PID 535 and 1135 running concurrently.)
PIDFILE=/tmp/rinkhals/mjpg-monitor.pid

monitor_running() {
    [ -f "$PIDFILE" ] || return 1
    kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null
}

status() {
    PIDS=$(get_by_name mjpg_monitor)

    if [ "$PIDS" = "" ]; then
        report_status $APP_STATUS_STOPPED
    else
        PIDS=$(get_by_name mjpg_streamer)
        report_status $APP_STATUS_STARTED "$PIDS"
    fi
}
start() {
    cd $APP_ROOT
    echo "Starting mjpg_streamer app" >> $APP_LOG

    if monitor_running; then
        echo "mjpg_monitor already running (pid $(cat $PIDFILE)), not starting another" >> $APP_LOG
        return
    fi

    # A stale pidfile (monitor died) or a monitor started before this pidfile
    # existed: clear any strays so we don't end up with two.
    kill_by_name mjpg_monitor

    mkdir -p $(dirname $PIDFILE)
    chmod +x ./mjpg_monitor.sh
    ./mjpg_monitor.sh < /dev/null >> $APP_LOG 2>&1 &
    echo $! > $PIDFILE
}
debug() {
    kill_by_name mjpg_monitor
    rm -f $PIDFILE 2> /dev/null

    cd $APP_ROOT

    chmod +x ./mjpg_monitor.sh
    ./mjpg_monitor.sh
}
stop() {
    kill_by_name gkcam
    kill_by_name mjpg_streamer
    kill_by_name mjpg_monitor
    rm -f $PIDFILE 2> /dev/null
    sleep 1

    cd /userdata/app/gk

    LD_LIBRARY_PATH=/userdata/app/gk:$LD_LIBRARY_PATH \
        ./gkcam >> $RINKHALS_LOGS/gkcam.log 2>&1 &
}

case "$1" in
    status)
        status
        ;;
    start)
        start
        ;;
    debug)
        shift
        debug $@
        ;;
    stop)
        stop
        ;;
    *)
        echo "Usage: $0 {status|start|stop}" >&2
        exit 1
        ;;
esac