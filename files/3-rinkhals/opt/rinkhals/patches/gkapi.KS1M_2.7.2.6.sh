#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: b338e0fad8b2bc9bd05822b1337afea8
# After MD5: e9db15da07d600b352232a9f64d10b88

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "e9db15da07d600b352232a9f64d10b88" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "b338e0fad8b2bc9bd05822b1337afea8" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo '674=' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=6813976 obs=1 count=2 conv=notrunc # 0x67f918 / 0x68f918 > 0xebbe

rm $PATCH_FILE
