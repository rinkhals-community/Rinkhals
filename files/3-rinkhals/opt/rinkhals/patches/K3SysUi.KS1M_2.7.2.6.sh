#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 62640d466c8617c518f802f1c80cc68c
# After MD5: 91807d6c14af62d5b26c0c6143c4e4ea

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "91807d6c14af62d5b26c0c6143c4e4ea" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "62640d466c8617c518f802f1c80cc68c" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo '2kkA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6oj9GAB8i/rrZON8xgAAn+UAAADq7v0YAHaL+usPAFDj9///CgAAn+UAAADqSv4YAHCL+utAABvlAACQ5QQg4wEQoOOxd/7rQAAb5QAAkAQQoONIe/7rRbb/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1496832 obs=1 count=4 conv=notrunc # 0x16d700 / 0x17d700 > 0xda4900ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1572228 obs=1 count=133 conv=notrunc # 0x17fd84 / 0x18fd84 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1572362 obs=1 count=63 conv=notrunc # 0x17fe0a / 0x18fe0a > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1572426 obs=1 count=36 conv=notrunc # 0x17fe4a / 0x18fe4a > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1572464 obs=1 count=17 conv=notrunc # 0x17fe70 / 0x18fe70 > 0x00009fe5000000ea88fd18007c8bfaeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1572483 obs=1 count=3 conv=notrunc # 0x17fe83 / 0x18fe83 > 0xe37cc6
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1572488 obs=1 count=50 conv=notrunc # 0x17fe88 / 0x18fe88 > 0x00009fe5000000eaeefd1800768bfaeb0f0050e3f7ffff0a00009fe5000000ea4afe1800708bfaeb40001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1572539 obs=1 count=16 conv=notrunc # 0x17febb / 0x18febb > 0xe30110a0e3b177feeb40001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1572556 obs=1 count=12 conv=notrunc # 0x17fecc / 0x18fecc > 0x0410a0e3487bfeeb45b6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=4174444 obs=1 count=9 conv=notrunc # 0x3fb26c / 0x40b26c > 0x52696e6b68616c7300

rm $PATCH_FILE
