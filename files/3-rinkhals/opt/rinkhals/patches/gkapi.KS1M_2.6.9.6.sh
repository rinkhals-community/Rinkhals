#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 31980ee1f7457e261c70d8f3cf63ad80
# After MD5: e30c5a50dabec035a8d2592b4ea72223

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "e30c5a50dabec035a8d2592b4ea72223" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "31980ee1f7457e261c70d8f3cf63ad80" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'Oow=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6677504 obs=1 count=2 conv=notrunc # 0x65e400 / 0x66e400 > 0x3a8c

rm $PATCH_FILE
