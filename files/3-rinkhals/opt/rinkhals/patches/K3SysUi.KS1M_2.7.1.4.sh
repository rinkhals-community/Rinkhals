#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: b970de9971fbd988e42b687ab63afce4
# After MD5: 3332d0ac6b1c029b336604942f16596a

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "3332d0ac6b1c029b336604942f16596a" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "b970de9971fbd988e42b687ab63afce4" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'EEoA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6jykGACdofrrZONZ2wAAn+UAAADqoqQYAJeh+usPAFDj9///CgAAn+UAAADq/qQYAJGh+utAABvlAACQ5QQg4wEQoONDef7rQAAb5QAAkAQQoOOmfP7rD7b/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1473756 obs=1 count=4 conv=notrunc # 0x167cdc / 0x177cdc > 0x104a00ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1549368 obs=1 count=133 conv=notrunc # 0x17a438 / 0x18a438 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1549502 obs=1 count=63 conv=notrunc # 0x17a4be / 0x18a4be > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1549566 obs=1 count=36 conv=notrunc # 0x17a4fe / 0x18a4fe > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1549604 obs=1 count=17 conv=notrunc # 0x17a524 / 0x18a524 > 0x00009fe5000000ea3ca418009da1faeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1549623 obs=1 count=3 conv=notrunc # 0x17a537 / 0x18a537 > 0xe359db
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1549628 obs=1 count=50 conv=notrunc # 0x17a53c / 0x18a53c > 0x00009fe5000000eaa2a4180097a1faeb0f0050e3f7ffff0a00009fe5000000eafea4180091a1faeb40001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1549679 obs=1 count=16 conv=notrunc # 0x17a56f / 0x18a56f > 0xe30110a0e34379feeb40001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1549696 obs=1 count=12 conv=notrunc # 0x17a580 / 0x18a580 > 0x0410a0e3a67cfeeb0fb6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=4135228 obs=1 count=9 conv=notrunc # 0x3f193c / 0x40193c > 0x52696e6b68616c7300

rm $PATCH_FILE
