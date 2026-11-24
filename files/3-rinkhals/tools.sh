export RINKHALS_ROOT=$(realpath /useremain/rinkhals/.current)

# Reads the first line of file $2 into variable $1, without starting a process.
# This file is loaded by every login shell, every SSH command and every app.sh
# call, and the stock firmware restarts a login shell on its unused console
# about once a second, forever. Each "$(cat ...)" here used to cost the printer
# a process every time, so the values below are read with shell builtins.
read_first_line() {
    eval "$1="
    [ -r "$2" ] || return 0
    IFS= read -r "$1" < "$2" || true
}

read_first_line RINKHALS_VERSION $RINKHALS_ROOT/.version
export RINKHALS_VERSION
export RINKHALS_HOME=/useremain/home/rinkhals
export RINKHALS_LOGS=/tmp/rinkhals

export ROOT_HOME=/useremain/home/root

# The model id is the number in the line  "modelId" : "20025"  of api.cfg
KOBRA_MODEL_ID=
if [ -r /userdata/app/gk/config/api.cfg ]; then
    while IFS= read -r _line || [ -n "$_line" ]; do
        case "$_line" in
            *'"modelId"'*)
                _line=${_line#*\"modelId\"}
                _line=${_line#*\"}
                _line=${_line%%\"*}
                case "$_line" in
                    ''|*[!0-9]*) ;;
                    *) KOBRA_MODEL_ID=$_line; break ;;
                esac
                ;;
        esac
    done < /userdata/app/gk/config/api.cfg
fi
unset _line
export KOBRA_MODEL_ID

if [ "$KOBRA_MODEL_ID" == "20021" ]; then
    export KOBRA_MODEL="Anycubic Kobra 2 Pro"
    export KOBRA_MODEL_CODE=K2P
elif [ "$KOBRA_MODEL_ID" == "20024" ]; then
    export KOBRA_MODEL="Anycubic Kobra 3"
    export KOBRA_MODEL_CODE=K3
elif [ "$KOBRA_MODEL_ID" == "20025" ]; then
    export KOBRA_MODEL="Anycubic Kobra S1"
    export KOBRA_MODEL_CODE=KS1
elif [ "$KOBRA_MODEL_ID" == "20026" ]; then
    export KOBRA_MODEL="Anycubic Kobra 3 Max"
    export KOBRA_MODEL_CODE=K3M
elif [ "$KOBRA_MODEL_ID" == "20027" ]; then
    export KOBRA_MODEL="Anycubic Kobra 3 V2"
    export KOBRA_MODEL_CODE=K3V2
elif [ "$KOBRA_MODEL_ID" == "20029" ]; then
    export KOBRA_MODEL="Anycubic Kobra S1 Max"
    export KOBRA_MODEL_CODE=KS1M
fi

read_first_line KOBRA_VERSION /useremain/dev/version
read_first_line KOBRA_DEVICE_ID /useremain/dev/device_id
export KOBRA_VERSION KOBRA_DEVICE_ID

export ORIGINAL_ROOT=/tmp/rinkhals/original

msleep() {
    usleep $(($1 * 1000))
}
beep() {
    echo 1 > /sys/class/pwm/pwmchip0/pwm0/enable
    usleep $(($1 * 1000))
    echo 0 > /sys/class/pwm/pwmchip0/pwm0/enable
}
log() {
    TS=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$TS]: ${*}"

    mkdir -p $RINKHALS_LOGS
    echo "[$TS]: ${*}" >> $RINKHALS_LOGS/rinkhals.log
}
quit() {
    exit 1
}

# Prints the free (Available) space of the filesystem holding $1, in KB. -P keeps it on one line
free_space_kb() {
    df -kP $1 | tail -1 | awk '{print $4}'
}

check_compatibility() {
    # KOBRA_MODEL_CODE is only set for the model ids tools.sh knows
    if [ -z "$KOBRA_MODEL_CODE" ]; then
        log "Your printer's model is not recognized, exiting"
        quit
    fi
}
is_supported_firmware() {
    SUPPORTED=0
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.7.2.6" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.7.2.1" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.7.1.4" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.6.9.6" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.6.9.3" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.6.6" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1M" ] && [ "$KOBRA_VERSION" = "2.1.6" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.7.3.5" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.7.2.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.7.2.1" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.7.0.9" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.7.0.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.6.0.0" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.5.9.9" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "KS1" ] && [ "$KOBRA_VERSION" = "2.5.8.8" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3V2" ] && [ "$KOBRA_VERSION" = "1.1.0.4" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3V2" ] && [ "$KOBRA_VERSION" = "1.1.0.1" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3V2" ] && [ "$KOBRA_VERSION" = "1.1.2.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3V2" ] && [ "$KOBRA_VERSION" = "1.1.2.8" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3M" ] && [ "$KOBRA_VERSION" = "2.5.1.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3M" ] && [ "$KOBRA_VERSION" = "2.5.1.3" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3M" ] && [ "$KOBRA_VERSION" = "2.5.2.8" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3" ] && [ "$KOBRA_VERSION" = "2.4.6.4" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3" ] && [ "$KOBRA_VERSION" = "2.4.6.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3" ] && [ "$KOBRA_VERSION" = "2.4.5" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K3" ] && [ "$KOBRA_VERSION" = "2.4.4.7" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K2P" ] && [ "$KOBRA_VERSION" = "3.1.4" ] && SUPPORTED=1
    [ "$KOBRA_MODEL_CODE" = "K2P" ] && [ "$KOBRA_VERSION" = "3.1.2.3" ] && SUPPORTED=1
    echo $SUPPORTED
}

get_swu_password() {
    # Per-model SWU encryption password. Must match the stock firmware password
    # for that model. The same table lives in build/prepare-version.sh
    # (get_printer_swu_password) and opt/rinkhals/ui/common.py (extract_swu);
    # keep all three in sync.
    case "${1:-$KOBRA_MODEL_CODE}" in
        K2P|K3|K3V2) echo "U2FsdGVkX19deTfqpXHZnB5GeyQ/dtlbHjkUnwgCi+w=" ;;
        KS1|KS1M)    echo "U2FsdGVkX1+lG6cHmshPLI/LaQr9cZCjA8HZt6Y8qmbB7riY" ;;
        K3M)         echo "4DKXtEGStWHpPgZm8Xna9qluzAI8VJzpOsEIgd8brTLiXs8fLSu3vRx8o7fMf4h6" ;;
    esac
}
install_swu() {
    SWU_FILE=$(realpath $1)
    shift

    echo "> Extracting $SWU_FILE ..."

    SWU_PASSWORD=$(get_swu_password)
    if [ -z "$SWU_PASSWORD" ]; then
        echo "> Unknown printer model ($KOBRA_MODEL_CODE); cannot determine SWU password"
        return 1
    fi

    mkdir -p /useremain/update_swu
    rm -rf /useremain/update_swu/*

    cd /useremain/update_swu

    unzip -P "$SWU_PASSWORD" $SWU_FILE -d /useremain
    if [ -f /useremain/update_swu/setup.tar.gz ]; then
        tar -xzf /useremain/update_swu/setup.tar.gz -C /useremain/update_swu
    elif [ -f /useremain/update_swu/setup.tar ]; then
        tar -xf /useremain/update_swu/setup.tar -C /useremain/update_swu
    fi

    echo "> Running update.sh ..."

    chmod +x update.sh
    ./update.sh $@
}

get_command_line() {
    PID=$1

    CMDLINE=$(cat /proc/$PID/cmdline 2> /dev/null)
    CMDLINE=$(echo $CMDLINE | head -c 80)

    echo $CMDLINE
}
kill_by_id() {
    PID=$1
    SIGNAL=${2:-9}
    
    if [ "$PID" == "" ]; then
        return
    fi
    if [ ! -e /proc/$PID/cmdline ]; then
        return
    fi

    CMDLINE=$(get_command_line $PID)

    log "Killing $PID ($CMDLINE)"
    kill -$SIGNAL $PID
}

get_by_name() {
    echo $(ps | grep "$1" | grep -v grep | awk '{print $1}')
}
wait_for_name() {
    DELAY=250
    TOTAL=${2:-30000}

    while [ 1 ]; do
        PIDS=$(get_by_name $1)
        if [ "$PIDS" != "" ]; then
            return
        fi

        if [ "$TOTAL" -lt 0 ]; then
            if [ "$3" != "" ]; then
                log "$3"
            else
                log "/!\ Timeout waiting for $1 to start"
            fi

            quit
        fi

        msleep $DELAY
        TOTAL=$(( $TOTAL - $DELAY ))
    done
}
assert_by_name() {
    PIDS=$(get_by_name $1)

    if [ "$PIDS" == "" ]; then
        log "/!\ $1 should be running but it's not"
        quit
    fi
}
kill_by_name() {
    PIDS=$(get_by_name $1)
    SIGNAL=${2:-9}

    for PID in $(echo "$PIDS"); do
        kill_by_id $PID $SIGNAL
    done
}

get_by_port() {
    XPORT=$(printf "%04X" ${*})
    INODE=$(cat /proc/net/tcp | grep 00000000:$XPORT | awk '/.*:.*:.*/{print $10;}')

    if [[ "$INODE" != "" ]]; then
        PID=$(ls -l /proc/*/fd/* 2> /dev/null | grep "socket:\[$INODE\]" | awk -F'/' '{print $3}')
        echo $PID
    fi
}
wait_for_port() {
    DELAY=250
    TOTAL=${2:-30000}

    while [ 1 ]; do
        PID=$(get_by_port $1)
        if [ "$PID" != "" ]; then
            return
        fi

        if [ "$TOTAL" -lt 0 ]; then
            if [ "$3" != "" ]; then
                log "$3"
            else
                log "/!\ Timeout waiting for port $1 to open"
            fi

            quit
        fi

        msleep $DELAY
        TOTAL=$(( $TOTAL - $DELAY ))
    done
}
assert_by_port() {
    PID=$(get_by_port $1)

    if [ "$PID" == "" ]; then
        log "/!\ $1 should be open but it's not"
        quit
    fi
}
kill_by_port() {
    PID=$(get_by_port $1)
    SIGNAL=${2:-9}
    
    kill_by_id $PID $SIGNAL
}

# Resets the printer's MCUs through the reset line the mainboard gives Linux.
# Returns 1 on models where we don't know that line.
reset_mcus() {
    case "$KOBRA_MODEL_CODE" in
        KS1) MCU_RESET_GPIO=116 ;;
        *) return 1 ;;
    esac

    [ -d /sys/class/gpio/gpio$MCU_RESET_GPIO ] || echo $MCU_RESET_GPIO > /sys/class/gpio/export
    echo out > /sys/class/gpio/gpio$MCU_RESET_GPIO/direction
    echo 0 > /sys/class/gpio/gpio$MCU_RESET_GPIO/value
    sleep 1
    echo 1 > /sys/class/gpio/gpio$MCU_RESET_GPIO/value
}

# Waits for something to listen on unix socket $1, for $2 ms. On a timeout it
# logs $3 and quits, unless $3 is "return": then it only returns 1
wait_for_socket() {
    DELAY=250
    TOTAL=${2:-30000}

    while [ 1 ]; do
        # Only probe a socket that exists: given a path with nothing there,
        # socat creates an empty file, which then is in the way of the socket
        [ -S $1 ] && timeout -t 1 socat $1 $1 2> /dev/null
        if [ "$?" -gt 127 ]; then
            return
        fi

        if [ "$TOTAL" -lt 0 ]; then
            if [ "$3" = "return" ]; then
                return 1
            fi

            if [ "$3" != "" ]; then
                log "$3"
            else
                log "/!\ Timeout waiting for socket $1 to listen"
            fi

            quit
        fi

        msleep $DELAY
        TOTAL=$(( $TOTAL - $DELAY ))
    done
}

# Stock binaries patched at startup (gkapi, K3SysUi). Every step has to survive a power cut
# (https://github.com/rinkhals-community/Rinkhals/issues/198). Each function takes the directory
# first so it can be tested away from /userdata/app/gk

stock_binary_md5() {
    md5sum $1 2> /dev/null | awk '{print $1}'
}
# Prints "<stock MD5> <result>" for binary $2 on model $3, firmware $4 from patches.txt ($1), nothing
# if that firmware isn't listed. result is the MD5 rinkhals-patcher must produce, "unpatched" or "unverified"
known_binary() {
    awk -v t=$2 -v m=$3 -v v=$4 '$1 == t && $2 == m && $3 == v { print $4 " " $5 }' $1 2> /dev/null
}
# Prints the stock MD5 of binary $2 on model $3, firmware $4 from patches.txt ($1), nothing if not listed
stock_md5_of() {
    local known=$(known_binary $1 $2 $3 $4)
    echo ${known% *}
}
# Puts $2.original back at $1/$2 when $2 isn't stock and $2.original is. Returns 0 if it did
restore_stock_binary() {
    local dir=$1 target=$2 stock_md5=$3

    [ -n "$stock_md5" ] || return 1
    [ "$(stock_binary_md5 $dir/$target)" = "$stock_md5" ] && return 1
    [ -e $dir/$target.original ] || return 1

    if [ "$(stock_binary_md5 $dir/$target.original)" != "$stock_md5" ]; then
        log "/!\ $target doesn't match the stock firmware and neither does $target.original, leaving both as they are"
        return 1
    fi

    log "/!\ Restoring stock $target left over from an interrupted startup"
    # Only report success when the stock binary is really in place (a read-only /userdata fails the mv),
    # or the caller's reboot would loop
    if ! mv -f $dir/$target.original $dir/$target || [ "$(stock_binary_md5 $dir/$target)" != "$stock_md5" ]; then
        log "/!\ Failed to restore stock $target"
        return 1
    fi
    sync
    return 0
}
# Moves $2.tmp to $1/$2 and keeps the stock binary as $2.original. With a hardlink the stock
# path never is empty; without hardlinks it falls back to two moves
swap_in_patched_binary() {
    local dir=$1 target=$2

    rm -f $dir/$target.original
    if ln -f $dir/$target $dir/$target.original 2> /dev/null; then
        mv -f $dir/$target.tmp $dir/$target
    else
        mv $dir/$target $dir/$target.original
        mv $dir/$target.tmp $dir/$target
    fi
    sync
}
# Puts $2.original back at $1/$2 and keeps the patched binary as $2.patch
swap_back_stock_binary() {
    local dir=$1 target=$2

    [ -f $dir/$target.original ] || return 1

    rm -f $dir/$target.patch
    if ln -f $dir/$target $dir/$target.patch 2> /dev/null; then
        mv -f $dir/$target.original $dir/$target
    else
        mv $dir/$target $dir/$target.patch
        mv $dir/$target.original $dir/$target
    fi
    sync
}
# Restores the stock binaries in $1, given as pairs of name and stock MD5 ($2 $3 ...). A name without
# a stock MD5 is skipped. Returns 0 if any was restored
recover_stock_binaries() {
    local gk_dir=$1 restored=1
    shift

    while [ $# -ge 2 ]; do
        restore_stock_binary $gk_dir $1 "$2" && restored=0
        shift 2
    done

    return $restored
}

export APP_STATUS_STARTED=started
export APP_STATUS_STOPPED=stopped

report_status() {
    APP_STATUS=$1
    APP_PIDS=$2
    APP_LOG_PATH=$3

    echo "Status: $APP_STATUS"
    echo "PIDs: $APP_PIDS"
    echo "Log: $APP_LOG_PATH"
}
get_app_status() {
    APP=$1
    APP_ROOT=$(get_app_root $APP)

    if [ ! -f $APP_ROOT/app.sh ]; then
        return
    fi

    chmod +x $APP_ROOT/app.sh
    APP_STATUS=$($APP_ROOT/app.sh status | grep Status: | awk '{print $2}')

    echo $APP_STATUS
}
get_app_pids() {
    APP=$1
    APP_ROOT=$(get_app_root $APP)

    if [ ! -f $APP_ROOT/app.sh ]; then
        return
    fi

    chmod +x $APP_ROOT/app.sh
    APP_PIDS=$($APP_ROOT/app.sh status | grep PIDs: | awk '{$1=""; print $0}')

    echo $APP_PIDS
}
get_app_log() {
    APP=$1
    APP_ROOT=$(get_app_root $APP)

    if [ ! -f $APP_ROOT/app.sh ]; then
        return
    fi

    chmod +x $APP_ROOT/app.sh
    APP_PIDS=$($APP_ROOT/app.sh status | grep Log: | awk '{print $2}')

    echo $APP_PIDS
}

BUILTIN_APP_PATH=$RINKHALS_ROOT/home/rinkhals/apps
USER_APP_PATH=$RINKHALS_HOME/apps
TEMPORARY_APP_PATH=/tmp/rinkhals/apps

list_apps() {
    BUILTIN_APPS=$(find $BUILTIN_APP_PATH -type d -mindepth 1 -maxdepth 1 -exec basename {} \; 2> /dev/null)
    USER_APPS=$(find $USER_APP_PATH -type d -mindepth 1 -maxdepth 1 -exec basename {} \; 2> /dev/null)

    APPS=$(printf "$BUILTIN_APPS\n$USER_APPS" | sort -uV)
    echo $APPS
}
get_app_root() {
    APP=$1
    
    USER_APP_ROOT=$USER_APP_PATH/$APP
    BUILTIN_APP_ROOT=$BUILTIN_APP_PATH/$APP

    if [ -e "$USER_APP_ROOT" ]; then
        echo "$USER_APP_ROOT"
    else
        echo "$BUILTIN_APP_ROOT"
    fi
}
is_app_enabled() {
    app=$1
    app_root=$(get_app_root $app)

    if ([ -f $app_root/.enabled ] || [ -f $RINKHALS_HOME/apps/$app.enabled ]) && [ ! -f $app_root/.disabled ] && [ ! -f $RINKHALS_HOME/apps/$app.disabled ]; then
        echo 1
    else
        echo 0
    fi
}

# App dependencies. "depends" in an app's app.json lists the apps it can't work
# without (their folder names). An entry can name alternatives, separated by |,
# when any one of several apps will do: "vanilla-klipper|tunneled-klipper".
# The rules, enforced here so that the touch UI, the web portal and the boot
# sequence all agree:
#   - an app can only be enabled while everything it depends on is installed
#     and enabled
#   - an app can't be disabled while an enabled app depends on it
#   - an app can't be removed while an installed app depends on it (the callers
#     that remove apps check get_app_dependents)

is_app_installed() {
    local root=$(get_app_root $1)

    if [ -f $root/app.sh ] && [ -f $root/app.json ]; then
        echo 1
    else
        echo 0
    fi
}
# Lists the apps that $1 depends on, one per line
get_app_depends() {
    local root=$(get_app_root $1)

    # Most apps declare nothing, and this runs for every app at boot: don't start jq for those
    grep -q '"depends"' $root/app.json 2> /dev/null || return 0
    sed '/^[[:space:]]*\/\//d' $root/app.json | jq -r '(.depends // []) | .[]' 2> /dev/null
}
# Tells whether one "depends" entry ($1, alternatives separated by |) is met:
# one of its apps is installed and, with "enabled" as $2, enabled too. An app
# named in $3 is left out, to ask "would it still be met without that app?"
is_app_depend_met() {
    local need=$2
    local without=$3
    local alternative

    for alternative in $(echo $1 | tr '|' ' '); do
        if [ "$alternative" = "$without" ] || [ "$(is_app_installed $alternative)" != "1" ]; then
            continue
        fi
        if [ "$need" = "enabled" ] && [ "$(is_app_enabled $alternative)" != "1" ]; then
            continue
        fi
        echo 1
        return
    done
    echo 0
}
# Lists the "depends" entries of $1 that are not met: no app in the entry is
# installed and enabled
get_app_missing_depends() {
    local dep

    for dep in $(get_app_depends $1); do
        if [ "$(is_app_depend_met $dep enabled)" != "1" ]; then
            echo $dep
        fi
    done
}
# Lists the installed apps that would lose a dependency without $1: they name
# it in a "depends" entry and no alternative in that entry is installed. With
# "enabled" as $2, lists the enabled apps with no other enabled alternative
get_app_dependents() {
    local target=$1
    local only=$2
    local other
    local dep

    for other in $(list_apps); do
        if [ "$other" = "$target" ] || [ "$(is_app_installed $other)" != "1" ]; then
            continue
        fi
        if [ "$only" = "enabled" ] && [ "$(is_app_enabled $other)" != "1" ]; then
            continue
        fi
        for dep in $(get_app_depends $other); do
            case "|$dep|" in
                *"|$target|"*)
                    if [ "$(is_app_depend_met $dep "$only" $target)" != "1" ]; then
                        echo $other
                        break
                    fi
                    ;;
            esac
        done
    done
}
# list_apps, ordered so that every app comes after the apps it depends on
list_apps_in_start_order() {
    local remaining="$(list_apps)"
    local ordered=""
    local waiting
    local progress
    local ready
    local app
    local dep

    while [ -n "$remaining" ]; do
        waiting=""
        progress=0

        for app in $remaining; do
            ready=1
            for dep in $(get_app_depends $app | tr '|' ' '); do
                case " $remaining " in
                    *" $dep "*) [ "$dep" != "$app" ] && ready=0 ;;
                esac
            done

            if [ "$ready" = "1" ]; then
                ordered="$ordered $app"
                progress=1
            else
                waiting="$waiting $app"
            fi
        done

        remaining=$(echo $waiting)

        # Apps that depend on each other in a loop: keep them in their usual order
        if [ "$progress" = "0" ]; then
            ordered="$ordered $remaining"
            break
        fi
    done

    echo $ordered
}

enable_app() {
    app=$1
    app_root=$(get_app_root $app)

    local missing=$(echo $(get_app_missing_depends $app))
    if [ -n "$missing" ]; then
        echo "Can't enable $app. It needs these apps installed and enabled first: $(echo $missing | sed 's/|/ or /g')"
        return 1
    fi

    if [ ! -d $RINKHALS_HOME/apps ]; then
        mkdir -p $RINKHALS_HOME/apps
    fi

    # If this is a built-in app, handle app.enabled / app.disabled
    if [[ "$app_root" == "$BUILTIN_APP_PATH*" ]]; then
        if [ -e $RINKHALS_HOME/apps/$app.disabled ]; then
            rm $RINKHALS_HOME/apps/$app.disabled
        fi
        if [ ! -e $app_root/.enabled ]; then
            touch $RINKHALS_HOME/apps/$app.enabled
        fi

    # If this is a user app, handle app/.enabled / app/.disabled
    else
        rm -f $RINKHALS_HOME/apps/$app.enabled
        rm -f $RINKHALS_HOME/apps/$app.disabled
        rm -f $RINKHALS_HOME/apps/$app/.disabled
        touch $RINKHALS_HOME/apps/$app/.enabled
    fi
}
# Pass "force" as $2 to disable an app that enabled apps still depend on, when
# it is about to be removed along with them
disable_app() {
    app=$1
    app_root=$(get_app_root $app)

    if [ "$2" != "force" ]; then
        local dependents=$(echo $(get_app_dependents $app enabled))
        if [ -n "$dependents" ]; then
            echo "Can't disable $app. These apps depend on it, disable them first: $dependents"
            return 1
        fi
    fi

    if [ ! -d $RINKHALS_HOME/apps ]; then
        mkdir -p $RINKHALS_HOME/apps
    fi

    # If this is a built-in app, handle app.enabled / app.disabled
    if [[ "$app_root" == "$BUILTIN_APP_PATH*" ]]; then
        if [ -e $RINKHALS_HOME/apps/$app.enabled ]; then
            rm $RINKHALS_HOME/apps/$app.enabled
        fi
        touch $RINKHALS_HOME/apps/$app.disabled

    # If this is a user app, handle app/.enabled / app/.disabled
    else
        rm -f $RINKHALS_HOME/apps/$app.enabled
        rm -f $RINKHALS_HOME/apps/$app.disabled
        rm -f $RINKHALS_HOME/apps/$app/.enabled
        touch $RINKHALS_HOME/apps/$app/.disabled
    fi
}
start_app() {
    APP=$1
    TIMEOUT=${2:-60}

    APP_ROOT=$(get_app_root $APP)

    PWD=$(pwd)
    cd $APP_ROOT
    chmod +x $APP_ROOT/app.sh

    if [ "$TIMEOUT" = "" ]; then
        $APP_ROOT/app.sh start
    else
        timeout -t $TIMEOUT sh -c "$APP_ROOT/app.sh start"

        if [ "$?" != "0" ]; then
            log "/!\ Timeout while starting $APP ($APP_ROOT)"
            stop_app $APP
        fi
    fi

    cd $PWD
}
stop_app() {
    APP=$1
    APP_ROOT=$(get_app_root $APP)

    chmod +x $APP_ROOT/app.sh
    $APP_ROOT/app.sh stop
}

# list_app_properties() {
#     APP=$1
#     APP_ROOT=$(get_app_root $APP)

#     if [ ! -f $APP_ROOT/app.json ]; then
#         return
#     fi

#     cat $APP_ROOT/app.json | sed 's/\/\/.*//' | jq -r '.properties | keys[]'
# }
get_app_property() {
    APP=$1
    PROPERTY=$2

    CONFIG_PATH=$USER_APP_PATH/$APP.config
    TEMPORARY_CONFIG_PATH=$TEMPORARY_APP_PATH/$APP.config

    VALUE=$(cat $TEMPORARY_CONFIG_PATH 2>/dev/null | jq -r ".$PROPERTY")
    if [ "$VALUE" = "" ] || [ "$VALUE" = "null" ]; then
        VALUE=$(cat $CONFIG_PATH 2>/dev/null | jq -r ".$PROPERTY")
    fi
    if [ "$VALUE" = "null" ]; then
        VALUE=
    fi
    if [ "$VALUE" = "" ]; then
        APP_ROOT=$(get_app_root $APP)
        VALUE=$(cat $APP_ROOT/app.json 2>/dev/null | jq -r ".properties.$PROPERTY.default")
        if [ "$VALUE" = "null" ]; then
            VALUE=
        fi
    fi

    echo $VALUE
}
set_app_property() {
    APP=$1
    PROPERTY=$2
    VALUE=$3
    
    if [ ! -d $RINKHALS_HOME/apps ]; then
        mkdir -p $RINKHALS_HOME/apps
    fi

    CONFIG_PATH=$USER_APP_PATH/$APP.config
    CONFIG=$(cat $CONFIG_PATH 2>/dev/null)
    CONFIG=${CONFIG:-'{}'}

    echo $CONFIG | jq ".$PROPERTY = \"$VALUE\"" > $CONFIG_PATH
}
set_temporary_app_property() {
    APP=$1
    PROPERTY=$2
    VALUE=$3

    mkdir -p $TEMPORARY_APP_PATH

    TEMPORARY_CONFIG_PATH=$TEMPORARY_APP_PATH/$APP.config
    CONFIG=$(cat $TEMPORARY_CONFIG_PATH 2>/dev/null)
    CONFIG=${CONFIG:-'{}'}

    echo $CONFIG | jq ".$PROPERTY = \"$VALUE\"" > $TEMPORARY_CONFIG_PATH
}
remove_app_property() {
    APP=$1
    PROPERTY=$2
    
    if [ ! -d $RINKHALS_HOME/apps ]; then
        return
    fi

    CONFIG_PATH=$USER_APP_PATH/$APP.config
    CONFIG=$(cat $CONFIG_PATH 2>/dev/null)
    CONFIG=${CONFIG:-'{}'}

    echo $CONFIG | jq "del(.$PROPERTY)" > $CONFIG_PATH
}
clear_app_properties() {
    APP=$1
    
    if [ ! -d $RINKHALS_HOME/apps ]; then
        return
    fi

    CONFIG_PATH=$USER_APP_PATH/$APP.config
    rm $CONFIG_PATH 2>/dev/null
}
