#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: a78d7022704e4d53e9f43b22ea22c698
# After MD5: 40c321058549e103819d8cd44071cc43

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "40c321058549e103819d8cd44071cc43" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "a78d7022704e4d53e9f43b22ea22c698" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'BkoA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6tjzGAAEjvrrZOMEyQAAn+UAAADqPvQYAP6N+usPAFDj9///CgAAn+UAAADqmvQYAPiN+utAABvlAACQ5QQg4wEQoOPmd/7rQAAb5QAAkAQQoONHe/7rGbb/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1494176 obs=1 count=4 conv=notrunc # 0x16cca0 / 0x17cca0 > 0x064a00ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1569748 obs=1 count=133 conv=notrunc # 0x17f3d4 / 0x18f3d4 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1569882 obs=1 count=63 conv=notrunc # 0x17f45a / 0x18f45a > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1569946 obs=1 count=36 conv=notrunc # 0x17f49a / 0x18f49a > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1569984 obs=1 count=17 conv=notrunc # 0x17f4c0 / 0x18f4c0 > 0x00009fe5000000ead8f31800048efaeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1570003 obs=1 count=3 conv=notrunc # 0x17f4d3 / 0x18f4d3 > 0xe304c9
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1570008 obs=1 count=50 conv=notrunc # 0x17f4d8 / 0x18f4d8 > 0x00009fe5000000ea3ef41800fe8dfaeb0f0050e3f7ffff0a00009fe5000000ea9af41800f88dfaeb40001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1570059 obs=1 count=16 conv=notrunc # 0x17f50b / 0x18f50b > 0xe30110a0e3e677feeb40001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1570076 obs=1 count=12 conv=notrunc # 0x17f51c / 0x18f51c > 0x0410a0e3477bfeeb19b6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=4167612 obs=1 count=9 conv=notrunc # 0x3f97bc / 0x4097bc > 0x52696e6b68616c7300

rm $PATCH_FILE
