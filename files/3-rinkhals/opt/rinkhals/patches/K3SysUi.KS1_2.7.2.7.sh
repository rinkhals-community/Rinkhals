#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 1bd84d3856b09a13a634143bb42378e5
# After MD5: e4f32d218e073b43eafc7d5e98ee5293

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "e4f32d218e073b43eafc7d5e98ee5293" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "1bd84d3856b09a13a634143bb42378e5" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'gTkA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6swCFgAkSvvrZOOrfgAAn+UAAADqMgMWAB5K++sPAFDj9///CgAAn+UAAADqjgMWABhK++s4ABvlAACQ5QQg4wEQoOMIr/7rOAAb5QAAkAQQoONpsv7rk8b/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1318312 obs=1 count=4 conv=notrunc # 0x141da8 / 0x151da8 > 0x813900ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1376968 obs=1 count=133 conv=notrunc # 0x1502c8 / 0x1602c8 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1377102 obs=1 count=63 conv=notrunc # 0x15034e / 0x16034e > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1377166 obs=1 count=36 conv=notrunc # 0x15038e / 0x16038e > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1377204 obs=1 count=17 conv=notrunc # 0x1503b4 / 0x1603b4 > 0x00009fe5000000eacc021600244afbeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1377223 obs=1 count=3 conv=notrunc # 0x1503c7 / 0x1603c7 > 0xe3ab7e
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1377228 obs=1 count=50 conv=notrunc # 0x1503cc / 0x1603cc > 0x00009fe5000000ea320316001e4afbeb0f0050e3f7ffff0a00009fe5000000ea8e031600184afbeb38001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1377279 obs=1 count=16 conv=notrunc # 0x1503ff / 0x1603ff > 0xe30110a0e308affeeb38001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1377296 obs=1 count=12 conv=notrunc # 0x150410 / 0x160410 > 0x0410a0e369b2feeb93c6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=3879056 obs=1 count=9 conv=notrunc # 0x3b3090 / 0x3c3090 > 0x52696e6b68616c7300

rm $PATCH_FILE
