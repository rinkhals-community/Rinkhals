#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 1494c17cdda2275b5ae221f40b83887d
# After MD5: 349a80a4beb01c33a39c5294fb933f30

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "349a80a4beb01c33a39c5294fb933f30" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "1494c17cdda2275b5ae221f40b83887d" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'da8=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6742896 obs=1 count=2 conv=notrunc # 0x66e370 / 0x67e370 > 0x75af

rm $PATCH_FILE
