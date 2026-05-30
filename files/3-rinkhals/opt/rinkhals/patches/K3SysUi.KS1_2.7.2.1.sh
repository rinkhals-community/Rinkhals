#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 429fdc2bb6bdba40b7d695a91bb7a3e4
# After MD5: d57b5f7bb64adfd3c1b44dcd869ea417

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "d57b5f7bb64adfd3c1b44dcd869ea417" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "429fdc2bb6bdba40b7d695a91bb7a3e4" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'YTkA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6tzvFQDgTvvrZOMXggAAn+UAAADqQvAVANpO++sPAFDj9///CgAAn+UAAADqnvAVANRO++s4ABvlAACQ5QQg4wEQoONCsf7rOAAb5QAAkAQQoOMws/7rs8b/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1313592 obs=1 count=4 conv=notrunc # 0x140b38 / 0x150b38 > 0x613900ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1372120 obs=1 count=133 conv=notrunc # 0x14efd8 / 0x15efd8 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1372254 obs=1 count=63 conv=notrunc # 0x14f05e / 0x15f05e > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1372318 obs=1 count=36 conv=notrunc # 0x14f09e / 0x15f09e > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1372356 obs=1 count=17 conv=notrunc # 0x14f0c4 / 0x15f0c4 > 0x00009fe5000000eadcef1500e04efbeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1372375 obs=1 count=3 conv=notrunc # 0x14f0d7 / 0x15f0d7 > 0xe31782
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1372380 obs=1 count=50 conv=notrunc # 0x14f0dc / 0x15f0dc > 0x00009fe5000000ea42f01500da4efbeb0f0050e3f7ffff0a00009fe5000000ea9ef01500d44efbeb38001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1372431 obs=1 count=16 conv=notrunc # 0x14f10f / 0x15f10f > 0xe30110a0e342b1feeb38001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1372448 obs=1 count=12 conv=notrunc # 0x14f120 / 0x15f120 > 0x0410a0e330b3feebb3c6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=3862504 obs=1 count=9 conv=notrunc # 0x3aefe8 / 0x3befe8 > 0x52696e6b68616c7300

rm $PATCH_FILE
