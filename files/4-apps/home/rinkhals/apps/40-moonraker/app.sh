. /useremain/rinkhals/.current/tools.sh

APP_ROOT=$(dirname $(realpath $0))

status() {
    PIDS=$(get_by_name moonraker.py)

    if [ "$PIDS" == "" ]; then
        report_status $APP_STATUS_STOPPED
    else
        report_status $APP_STATUS_STARTED "$PIDS"
    fi
}
start() {
    stop

    cd $APP_ROOT

    chmod +x moonraker.sh
    # Detach stdin/stdout/stderr from /dev/null. moonraker.sh stays resident
    # (its restart loop waits on Moonraker), so if it inherited this shell's
    # fds it would hold them open. When start is invoked from the on-screen
    # menu (rinkhals-ui.py), which captures the command's output through a
    # pipe, that keeps the pipe's write end open and hangs the UI (a frozen
    # touchscreen). moonraker.sh writes everything to app-moonraker.log.
    ./moonraker.sh </dev/null >/dev/null 2>&1 &
}
debug() {
    stop

    cd $APP_ROOT
    
    python -m venv --without-pip .
    . bin/activate

    cp -rf kobra.py moonraker/moonraker/components/kobra.py
    cp -rf mmu_ace.py moonraker/moonraker/components/mmu_ace.py
    cp -rf mmu_ace_metadata.py moonraker/moonraker/components/mmu_ace_metadata.py
    python /opt/rinkhals/scripts/process-cfg.py moonraker.conf > /userdata/app/gk/printer_data/config/moonraker.generated.conf
    mkdir -p /userdata/app/gk/printer_data/logs
    chmod 777 /userdata/app/gk/printer_data/logs
    TMPDIR=/useremain/tmp HOME=/userdata/app/gk python ./moonraker/moonraker/moonraker.py -c /userdata/app/gk/printer_data/config/moonraker.generated.conf $@
}
stop() {
    kill_by_name moonraker.py
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
        echo "Usage: $0 {status|start|debug|stop}" >&2
        exit 1
        ;;
esac
