# Recovering and swapping the stock gkapi/K3SysUi binaries (issue #198)
. tests/kobra3/lib.sh
. files/3-rinkhals/tools.sh 2> /dev/null

WORK=$(mktemp -d)
printf 'stock binary, complete\n' > $WORK/stock
printf 'patched binary, complete\n' > $WORK/patched
printf 'stock bin' > $WORK/trunc
STOCK_MD5=$(md5sum $WORK/stock | awk '{print $1}')
PATCHED_MD5=$(md5sum $WORK/patched | awk '{print $1}')
TRUNC_MD5=$(md5sum $WORK/trunc | awk '{print $1}')

# Fresh directory per case
new_dir() {
    D=$(mktemp -d -p $WORK)
}

# stock_md5_of
printf '#!/bin/sh\n# Before MD5: %s\n# After MD5: %s\n' $STOCK_MD5 $PATCHED_MD5 > $WORK/gkapi.patch.sh
printf '#!/bin/sh\n' > $WORK/nomd5.sh
assert_eq "$STOCK_MD5" "$(stock_md5_of $WORK/gkapi.patch.sh)" "stock_md5_of: reads Before MD5"
assert_eq "" "$(stock_md5_of $WORK/nomd5.sh)" "stock_md5_of: empty without Before MD5"

# restore: target missing, .original=stock
new_dir
cp $WORK/stock $D/gkapi.original
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 0 $rc "restore (missing, .original=stock): returns 0"
assert_file_md5 $D/gkapi $STOCK_MD5 "restore (missing, .original=stock): target is stock"
assert_eq no $([ -e $D/gkapi.original ] && echo yes || echo no) "restore (missing, .original=stock): no .original left"

# restore: target=patched, .original=stock
new_dir
cp $WORK/patched $D/gkapi; cp $WORK/stock $D/gkapi.original
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 0 $rc "restore (patched, .original=stock): returns 0"
assert_file_md5 $D/gkapi $STOCK_MD5 "restore (patched, .original=stock): target is stock"

# restore: target=trunc, .original=stock
new_dir
cp $WORK/trunc $D/gkapi; cp $WORK/stock $D/gkapi.original
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 0 $rc "restore (trunc, .original=stock): returns 0"
assert_file_md5 $D/gkapi $STOCK_MD5 "restore (trunc, .original=stock): target is stock"

# restore: target=stock, no .original
new_dir
cp $WORK/stock $D/gkapi
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 1 $rc "restore (stock, no .original): returns 1"
assert_file_md5 $D/gkapi $STOCK_MD5 "restore (stock, no .original): target unchanged"

# restore: target=trunc, .original=trunc
new_dir
cp $WORK/trunc $D/gkapi; cp $WORK/trunc $D/gkapi.original
OUT=$(restore_stock_binary $D gkapi $STOCK_MD5); rc=$?
assert_eq 1 $rc "restore (trunc, .original=trunc): returns 1"
assert_file_md5 $D/gkapi $TRUNC_MD5 "restore (trunc, .original=trunc): target unchanged"
assert_file_md5 $D/gkapi.original $TRUNC_MD5 "restore (trunc, .original=trunc): .original unchanged"
case "$OUT" in *'/!\'*) warned=yes ;; *) warned=no ;; esac
assert_eq yes $warned "restore (trunc, .original=trunc): logs a /!\\ warning"

# restore: target=stock, .original=hardlink to stock
new_dir
cp $WORK/stock $D/gkapi; ln $D/gkapi $D/gkapi.original
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 1 $rc "restore (stock, .original=hardlink): returns 1"
assert_file_md5 $D/gkapi $STOCK_MD5 "restore (stock, .original=hardlink): target unchanged"

# swap_in, then swap_back
check_swapped_back() {
    assert_file_md5 $D/gkapi $STOCK_MD5 "$1: target is stock"
    assert_file_md5 $D/gkapi.patch $PATCHED_MD5 "$1: .patch is patched"
    assert_eq no $([ -e $D/gkapi.original ] && echo yes || echo no) "$1: no .original"
    assert_eq no $([ -e $D/gkapi.tmp ] && echo yes || echo no) "$1: no .tmp"
}
new_dir
cp $WORK/stock $D/gkapi; cp $WORK/patched $D/gkapi.tmp
swap_in_patched_binary $D gkapi > /dev/null
assert_file_md5 $D/gkapi $PATCHED_MD5 "swap_in: target is patched"
assert_file_md5 $D/gkapi.original $STOCK_MD5 "swap_in: .original is stock"
swap_back_stock_binary $D gkapi > /dev/null
check_swapped_back "swap_in + swap_back"

# swap_in and swap_back with a failing ln (no hardlinks on the filesystem)
FAKE=$(mktemp -d -p $WORK)
printf '#!/bin/sh\ntouch %s/ln-called\nexit 1\n' $FAKE > $FAKE/ln
chmod +x $FAKE/ln
new_dir
cp $WORK/stock $D/gkapi; cp $WORK/patched $D/gkapi.tmp
OLD_PATH=$PATH
PATH=$FAKE:$PATH
swap_in_patched_binary $D gkapi > /dev/null 2>&1
swap_back_stock_binary $D gkapi > /dev/null 2>&1
PATH=$OLD_PATH
assert_eq yes $([ -e $FAKE/ln-called ] && echo yes || echo no) "failing ln: fake ln was used"
check_swapped_back "failing ln"

# recover_stock_binaries twice in a row: one restore, then nothing (no boot loop)
new_dir
cp $WORK/trunc $D/gkapi; cp $WORK/stock $D/gkapi.original
cp $WORK/stock $D/K3SysUi
recover_stock_binaries $D gkapi $STOCK_MD5 K3SysUi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 0 $rc "recover (1st run): returns 0"
assert_file_md5 $D/gkapi $STOCK_MD5 "recover (1st run): gkapi is stock"
recover_stock_binaries $D gkapi $STOCK_MD5 K3SysUi $STOCK_MD5 > /dev/null; rc=$?
assert_eq 1 $rc "recover (2nd run): returns 1"
assert_file_md5 $D/gkapi $STOCK_MD5 "recover (2nd run): gkapi still stock"

# recover without a stock MD5 for this firmware does nothing
new_dir
cp $WORK/trunc $D/gkapi; cp $WORK/stock $D/gkapi.original
recover_stock_binaries $D gkapi "" K3SysUi "" > /dev/null; rc=$?
assert_eq 1 $rc "recover (no stock MD5): returns 1"
assert_file_md5 $D/gkapi $TRUNC_MD5 "recover (no stock MD5): gkapi untouched"

# restore with a failing mv (e.g. /userdata remounted read-only): must report failure
new_dir
cp $WORK/trunc $D/gkapi; cp $WORK/stock $D/gkapi.original
FAKE_MV=$(mktemp -d -p $WORK)
printf '#!/bin/sh\nexit 1\n' > $FAKE_MV/mv
chmod +x $FAKE_MV/mv
OLD_PATH=$PATH
PATH=$FAKE_MV:$PATH
restore_stock_binary $D gkapi $STOCK_MD5 > /dev/null 2>&1; rc=$?
PATH=$OLD_PATH
assert_eq 1 $rc "restore (failing mv): returns 1"

rm -rf $WORK
finish
