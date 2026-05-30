#!/bin/sh

# From a Windows machine:
#   docker run --rm -it -e KOBRA_MODEL_CODE="K3" -v .\build:/build -v .\files:/files ghcr.io/rinkhals-community/rinkhals/build /build/swu-tools/installer/build-swu.sh
#   docker run --rm --privileged tonistiigi/binfmt --install all
#   docker run --platform=linux/arm/v7 --rm -it -e KOBRA_MODEL_CODE="K3" -v .\build:/build -v .\files:/files ghcr.io/rinkhals-community/armv7-uclibc:rinkhals /build/swu-tools/installer/build-swu.sh


if [ "$KOBRA_MODEL_CODE" = "" ]; then
    echo "Please specify your Kobra model using KOBRA_MODEL_CODE environment variable"
    exit 1
fi

set -e

BUILD_ROOT=$(dirname $(realpath $0))
. $BUILD_ROOT/../../tools.sh

FILES_DIR="${FILES_DIR:-/files}"

# Prepare update
WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT

# Libraries for Python
cp $FILES_DIR/1-buildroot/usr/lib/libffi.so.8 "$WORK"/libffi.so.8
cp $FILES_DIR/1-buildroot/usr/lib/libstdc++.so.6 "$WORK"/libstdc++.so.6
cp $FILES_DIR/1-buildroot/usr/lib/libpython3.11.so.1.0 "$WORK"/libpython3.11.so.1.0
cp $FILES_DIR/1-buildroot/usr/lib/libz.so.1 "$WORK"/libz.so.1
cp $FILES_DIR/1-buildroot/lib/libc.so.0 "$WORK"/libc.so.0
cp $FILES_DIR/1-buildroot/lib/libgcc_s.so.1 "$WORK"/libgcc_s.so.1
cp $FILES_DIR/1-buildroot/lib/ld-uClibc.so.0 "$WORK"/ld-uClibc
cp $FILES_DIR/1-buildroot/lib/ld-uClibc.so.1 "$WORK"/ld-uClibc.so.1

# Libraries for SSH
cp $FILES_DIR/3-rinkhals/usr/local/etc/dropbear/dropbear_rsa_host_key "$WORK"/dropbear_rsa_host_key
cp $FILES_DIR/1-buildroot/usr/lib/libcrypto.so.1.1 "$WORK"/libcrypto.so.1.1
cp $FILES_DIR/1-buildroot/usr/lib/libssl.so.1.1 "$WORK"/libssl.so.1.1
cp $FILES_DIR/1-buildroot/lib/libatomic.so.1 "$WORK"/libatomic.so.1

# Python runtime
mkdir -p "$WORK"/lib
cp -r $FILES_DIR/1-buildroot/usr/lib/python3.11 "$WORK"/lib

# Tool
cp -r $FILES_DIR/3-rinkhals/opt/rinkhals/ui/assets "$WORK"/
cp -r $FILES_DIR/3-rinkhals/opt/rinkhals/ui/lvgl "$WORK"/
cp -r $FILES_DIR/3-rinkhals/opt/rinkhals/tools "$WORK"/
cp $FILES_DIR/start.sh.patch "$WORK"/start.sh.patch
cp $FILES_DIR/3-rinkhals/opt/rinkhals/ui/*.* "$WORK"/
cp $BUILD_ROOT/update.sh "$WORK"/update.sh

# Clean Python
rm -rf "$WORK"/lib/python3.11/config-3.11-arm-linux-gnueabihf
rm -rf "$WORK"/lib/python3.11/ensurepip
rm -rf "$WORK"/lib/python3.11/distutils
rm -rf "$WORK"/lib/python3.11/xml
rm -rf "$WORK"/lib/python3.11/unittest
rm -rf "$WORK"/lvgl/*.dll

# TODO: Embed Python libraries
# cd /tmp/update_swu/lib/python3.11
# zip -r /tmp/update_swu/python.zip .
# rm -rf /tmp/update_swu/lib
# cp BUILD_ROOT/python._pth /tmp/update_swu/python._pth
# cp -r /files/1-buildroot/usr/lib/python3.11/lib-dynload/zlib.cpython-311-arm-linux-gnueabihf.so /tmp/update_swu/zlib.cpython-311-arm-linux-gnueabihf.so

# Python libraries
mkdir -p "$WORK"/lib/python3.11/site-packages
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/cffi* "$WORK"/lib/python3.11/site-packages
cp $FILES_DIR/2-python/usr/lib/python3.11/site-packages/_cffi_backend*.so "$WORK"/lib/python3.11/site-packages
cp $FILES_DIR/2-python/usr/lib/python3.11/site-packages/_cffi_backend*.so "$WORK"/
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/requests* "$WORK"/lib/python3.11/site-packages
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/certifi* "$WORK"/lib/python3.11/site-packages
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/idna* "$WORK"/lib/python3.11/site-packages
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/urllib* "$WORK"/lib/python3.11/site-packages
cp -r $FILES_DIR/2-python/usr/lib/python3.11/site-packages/paho* "$WORK"/lib/python3.11/site-packages

# Precompile LVGL
find "$WORK" -name '*.pyc' -type f -exec rm {} \;

# Patch python for local interpreter
cat $FILES_DIR/1-buildroot/usr/bin/python |
    sed "s/\/lib\/ld-uClibc.so.0/\/tmp\/rin\/\/ld-uClibc/g" \
    > "$WORK"/python

# Patch dropbear to run sftp-server locally
cat $FILES_DIR/1-buildroot/usr/sbin/dropbear |
    sed "s/\/lib\/ld-uClibc.so.0/\/tmp\/rin\/\/ld-uClibc/g" |
    sed "s/\/usr\/libexec\/sftp-server/\/tmp\/rin\/sftp-server    /g" \
    > "$WORK"/dropbear

cat $FILES_DIR/1-buildroot/usr/libexec/sftp-server |
    sed "s/\/lib\/ld-uClibc.so.0/\/tmp\/rin\/\/ld-uClibc/g" \
    > "$WORK"/sftp-server

# Create .version files
mkdir -p "$WORK"/rinkhals
if [ -n "$RINKHALS_VERSION" ]; then
    echo "$RINKHALS_VERSION" > "$WORK"/.version
    echo "$RINKHALS_VERSION" > "$WORK"/rinkhals/.version
else
    echo "dev" > "$WORK"/.version
    echo "dev" > "$WORK"/rinkhals/.version
fi
# Create the update.swu
echo "Building update package..."

SWU_PATH=${1:-/build/dist/update.swu}
build_swu $KOBRA_MODEL_CODE "$WORK" $SWU_PATH

echo "Done, your update package is ready: $SWU_PATH"
