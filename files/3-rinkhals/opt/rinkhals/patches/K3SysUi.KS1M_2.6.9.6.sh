#!/bin/sh

# This script was automatically generated, don't modify it directly
# Before MD5: 501e7f3c1acef958f3cd93be9a00a200
# After MD5: 5d1e50ccbd5b833d08e42a6463a96a7c

TARGET=$1

MD5=$(md5sum $TARGET | awk '{print $1}')
if [ "$MD5" = "5d1e50ccbd5b833d08e42a6463a96a7c" ]; then
    echo $TARGET is already patched, skipping...
    exit 0
fi
if [ "$MD5" != "501e7f3c1acef958f3cd93be9a00a200" ]; then
    echo $TARGET hash does not match, skipping patch...
    exit 1
fi

PATCH_FILE=/tmp/patch-$RANDOM.bin
echo 'azkA6g7woOEvdXNlcmVtYWluL3JpbmtoYWxzLy5jdXJyZW50L29wdC9yaW5raGFscy91aS9yaW5raGFscy11aS5zaCAmIGVjaG8gJCEgPiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAB0aW1lb3V0IC10IDIgc3RyYWNlIC1xcXEgLWV0cmFjZT1ub25lIC1wICQoY2F0IC90bXAvcmlua2hhbHMvcmlua2hhbHMtdWkucGlkKSAyPiAvZGV2L251bGxybSAtZiAvdG1wL3JpbmtoYWxzL3JpbmtoYWxzLXVpLnBpZAAAAJ/lAAAA6qTvFQDuTvvrZOMlggAAn+UAAADqCvAVAOhO++sPAFDj9///CgAAn+UAAADqZvAVAOJO++s4ABvlAACQ5QQg4wEQoOMwsf7rOAAb5QAAkAQQoOMes/7rocb/6lJpbmtoYWxzAA==' | base64 -d > $PATCH_FILE

dd if=$PATCH_FILE skip=0 ibs=1 of=$TARGET seek=1313496 obs=1 count=4 conv=notrunc # 0x140ad8 / 0x150ad8 > 0x6b3900ea
dd if=$PATCH_FILE skip=4 ibs=1 of=$TARGET seek=1372064 obs=1 count=133 conv=notrunc # 0x14efa0 / 0x15efa0 > 0x0ef0a0e12f75736572656d61696e2f72696e6b68616c732f2e63757272656e742f6f70742f72696e6b68616c732f75692f72696e6b68616c732d75692e73682026206563686f202421203e202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069640074696d656f7574202d74203220737472616365202d717171202d65
dd if=$PATCH_FILE skip=137 ibs=1 of=$TARGET seek=1372198 obs=1 count=63 conv=notrunc # 0x14f026 / 0x15f026 > 0x74726163653d6e6f6e65202d70202428636174202f746d702f72696e6b68616c732f72696e6b68616c732d75692e7069642920323e202f6465762f6e756c6c
dd if=$PATCH_FILE skip=200 ibs=1 of=$TARGET seek=1372262 obs=1 count=36 conv=notrunc # 0x14f066 / 0x15f066 > 0x726d202d66202f746d702f72696e6b68616c732f72696e6b68616c732d75692e70696400
dd if=$PATCH_FILE skip=236 ibs=1 of=$TARGET seek=1372300 obs=1 count=17 conv=notrunc # 0x14f08c / 0x15f08c > 0x00009fe5000000eaa4ef1500ee4efbeb64
dd if=$PATCH_FILE skip=253 ibs=1 of=$TARGET seek=1372319 obs=1 count=3 conv=notrunc # 0x14f09f / 0x15f09f > 0xe32582
dd if=$PATCH_FILE skip=256 ibs=1 of=$TARGET seek=1372324 obs=1 count=50 conv=notrunc # 0x14f0a4 / 0x15f0a4 > 0x00009fe5000000ea0af01500e84efbeb0f0050e3f7ffff0a00009fe5000000ea66f01500e24efbeb38001be5000090e50420
dd if=$PATCH_FILE skip=306 ibs=1 of=$TARGET seek=1372375 obs=1 count=16 conv=notrunc # 0x14f0d7 / 0x15f0d7 > 0xe30110a0e330b1feeb38001be5000090
dd if=$PATCH_FILE skip=322 ibs=1 of=$TARGET seek=1372392 obs=1 count=12 conv=notrunc # 0x14f0e8 / 0x15f0e8 > 0x0410a0e31eb3feeba1c6ffea
dd if=$PATCH_FILE skip=334 ibs=1 of=$TARGET seek=3862368 obs=1 count=9 conv=notrunc # 0x3aef60 / 0x3bef60 > 0x52696e6b68616c7300

rm $PATCH_FILE
