#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 3d2de27fd6e5052fc6b4868d805000b3
# After MD5: eb6bdf6cff1a99940a3cb934b582e160

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "eb6bdf6cff1a99940a3cb934b582e160" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "3d2de27fd6e5052fc6b4868d805000b3" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo '2LU=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6775904 obs=1 count=2 conv=notrunc # 0x676460 / 0x686460 > 0xd8b5

rm $PATCH_FILE
