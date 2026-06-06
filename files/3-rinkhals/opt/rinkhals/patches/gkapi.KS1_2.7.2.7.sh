#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: efa64b0be1a947e34127379986fc7257
# After MD5: 7664502a40b756946a1588d33205d714

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "7664502a40b756946a1588d33205d714" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "efa64b0be1a947e34127379986fc7257" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo '5pY=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6692964 obs=1 count=2 conv=notrunc # 0x662064 / 0x672064 > 0xe696

rm $PATCH_FILE
