# A power cut left gkapi truncated while Rinkhals is disabled.
# start-rinkhals.sh must restore it and reboot exactly once, and not reboot on the next boot.
# Runs as root inside the throwaway alpine container (it writes to /useremain and /userdata).
. tests/kobra3/lib.sh

[ -f /.dockerenv ] || { echo "SKIP - needs the alpine container"; exit 0; }

VERSION=20261118_03_test
mkdir -p /useremain/rinkhals/$VERSION/opt/rinkhals/patches /userdata/app/gk /useremain/dev /mnt/udisk
cp files/3-rinkhals/tools.sh /useremain/rinkhals/$VERSION/tools.sh
echo $VERSION > /useremain/rinkhals/.version
echo 2.4.6.7 > /useremain/dev/version
mkdir -p /userdata/app/gk/config
printf '{\n  "modelId" : "20024"\n}\n' > /userdata/app/gk/config/api.cfg
touch /useremain/rinkhals/.disable-rinkhals

printf 'stock binary, complete\n' > /tmp/stock
STOCK_MD5=$(md5sum /tmp/stock | awk '{print $1}')
printf 'gkapi   K3   2.4.6.7  %s 0\n' $STOCK_MD5 > /useremain/rinkhals/$VERSION/opt/rinkhals/patches/patches.txt
printf 'stock bin' > /userdata/app/gk/gkapi
cp /tmp/stock /userdata/app/gk/gkapi.original

FAKE=$(mktemp -d)
printf '#!/bin/sh\necho reboot >> %s/calls\n' $FAKE > $FAKE/reboot
printf '#!/bin/sh\necho adbd >> %s/calls\n' $FAKE > $FAKE/adbd
chmod +x $FAKE/reboot $FAKE/adbd

count_calls() {
    [ -f $FAKE/calls ] || { echo 0; return; }
    grep -c "^$1\$" $FAKE/calls
}

PATH=$FAKE:$PATH sh files/start-rinkhals.sh > /dev/null 2>&1
assert_file_md5 /userdata/app/gk/gkapi $STOCK_MD5 "1st boot: gkapi restored to stock"
assert_eq 1 "$(count_calls reboot)" "1st boot: rebooted once"

: > $FAKE/calls
PATH=$FAKE:$PATH sh files/start-rinkhals.sh > /dev/null 2>&1
wait
assert_file_md5 /userdata/app/gk/gkapi $STOCK_MD5 "2nd boot: gkapi still stock"
assert_eq 0 "$(count_calls reboot)" "2nd boot: no reboot"
assert_eq 1 "$(count_calls adbd)" "2nd boot: falls through to ADB"

# The same with a failing mv (read-only /userdata): nothing restored, so no reboot loop
printf 'stock bin' > /userdata/app/gk/gkapi
cp /tmp/stock /userdata/app/gk/gkapi.original
printf '#!/bin/sh\nexit 1\n' > $FAKE/mv
chmod +x $FAKE/mv
: > $FAKE/calls
PATH=$FAKE:$PATH sh files/start-rinkhals.sh > /dev/null 2>&1
rm -f $FAKE/mv
assert_eq 0 "$(count_calls reboot)" "failing mv: no reboot"
assert_eq 1 "$(count_calls adbd)" "failing mv: falls through to ADB"

# A truncated tools.sh of the selected version must not cost the ADB fallback
cp /useremain/rinkhals/$VERSION/tools.sh /tmp/tools.sh.good
printf 'broken() {\n    if [ 1 = 1 ]; then\n' > /useremain/rinkhals/$VERSION/tools.sh
: > $FAKE/calls
PATH=$FAKE:$PATH sh files/start-rinkhals.sh > /dev/null 2>&1
cp /tmp/tools.sh.good /useremain/rinkhals/$VERSION/tools.sh
assert_eq 1 "$(count_calls adbd)" "truncated tools.sh: still falls through to ADB"
assert_eq 0 "$(count_calls reboot)" "truncated tools.sh: no reboot"

finish
