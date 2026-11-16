#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 1b4c6496442fd712b2eaae5ff645e80a
# After MD5: 5887354547d73ef2b4283a6b84bf4cdc

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "5887354547d73ef2b4283a6b84bf4cdc" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "1b4c6496442fd712b2eaae5ff645e80a" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'u78=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6809492 obs=1 count=2 conv=notrunc # 0x67e794 / 0x68e794 > 0xbbbf

rm $PATCH_FILE
