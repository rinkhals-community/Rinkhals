# Uninstalling puts the stock gkapi/K3SysUi back and removes the patch leftovers
. tests/kobra3/lib.sh
. files/3-rinkhals/tools.sh 2> /dev/null

WORK=$(mktemp -d)
printf 'stock binary, complete\n' > $WORK/stock
printf 'patched binary, complete\n' > $WORK/patched
printf 'stock bin' > $WORK/trunc
STOCK_MD5=$(md5sum $WORK/stock | awk '{print $1}')
PATCHED_MD5=$(md5sum $WORK/patched | awk '{print $1}')
TRUNC_MD5=$(md5sum $WORK/trunc | awk '{print $1}')

new_dir() {
    D=$(mktemp -d -p $WORK)
}
# K3SysUi has no stock MD5, as when only gkapi has a patch for this firmware
cleanup() {
    cleanup_patched_binaries $D gkapi $STOCK_MD5 K3SysUi ""
}
exists() {
    [ -e $1 ] && echo yes || echo no
}

# target=patched, .original=stock, .patch and .tmp present
new_dir
cp $WORK/patched $D/gkapi; cp $WORK/stock $D/gkapi.original
cp $WORK/patched $D/gkapi.patch; cp $WORK/patched $D/gkapi.tmp
cleanup > /dev/null
assert_file_md5 $D/gkapi $STOCK_MD5 "uninstall (patched, .original=stock): gkapi is stock"
assert_eq no $(exists $D/gkapi.original) "uninstall (patched, .original=stock): no .original"
assert_eq no $(exists $D/gkapi.patch) "uninstall (patched, .original=stock): no .patch"
assert_eq no $(exists $D/gkapi.tmp) "uninstall (patched, .original=stock): no .tmp"

# target=stock, only .patch (normal state after a startup)
new_dir
cp $WORK/stock $D/gkapi; cp $WORK/patched $D/gkapi.patch
cp $WORK/stock $D/K3SysUi; cp $WORK/patched $D/K3SysUi.patch
cleanup > /dev/null
assert_file_md5 $D/gkapi $STOCK_MD5 "uninstall (stock, .patch): gkapi unchanged"
assert_eq no $(exists $D/gkapi.patch) "uninstall (stock, .patch): gkapi.patch removed"
assert_eq no $(exists $D/K3SysUi.patch) "uninstall (stock, .patch): K3SysUi.patch removed"

# target=stock, .original=stock (interrupted between ln and mv): the copy goes
new_dir
cp $WORK/stock $D/gkapi; ln $D/gkapi $D/gkapi.original
cleanup > /dev/null
assert_file_md5 $D/gkapi $STOCK_MD5 "uninstall (stock, .original=stock): gkapi unchanged"
assert_eq no $(exists $D/gkapi.original) "uninstall (stock, .original=stock): .original removed"

# .original=trunc: nothing to restore from, keep it for a human
new_dir
cp $WORK/patched $D/gkapi; cp $WORK/trunc $D/gkapi.original
OUT=$(cleanup)
assert_file_md5 $D/gkapi $PATCHED_MD5 "uninstall (.original=trunc): gkapi unchanged"
assert_file_md5 $D/gkapi.original $TRUNC_MD5 "uninstall (.original=trunc): .original kept"
case "$OUT" in *'/!\'*'.original'*) warned=yes ;; *) warned=no ;; esac
assert_eq yes $warned "uninstall (.original=trunc): logs a /!\\ line about .original"

rm -rf $WORK
finish
