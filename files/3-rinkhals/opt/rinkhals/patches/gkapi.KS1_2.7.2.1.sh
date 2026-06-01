#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 5d65e665bf3343ac2920c4896ce1efca
# After MD5: fb62c1b74271d3f9bffff996273f6984

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "fb62c1b74271d3f9bffff996273f6984" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "5d65e665bf3343ac2920c4896ce1efca" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'KZM=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6687784 obs=1 count=2 conv=notrunc # 0x660c28 / 0x670c28 > 0x2993

rm $PATCH_FILE
