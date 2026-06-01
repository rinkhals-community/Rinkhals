#!/bin/sh

# From a Windows machine:
#   docker run --rm -it -e KOBRA_MODEL_CODE="K3" -v .\build:/build -v .\files:/files ghcr.io/rinkhals-community/rinkhals/build /build/swu-tools/ssh/build-swu.sh


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

cp "$BUILD_ROOT"/update.sh "$WORK"/update.sh
cp $FILES_DIR/3-rinkhals/usr/local/etc/dropbear/dropbear_rsa_host_key "$WORK"/dropbear_rsa_host_key
cp $FILES_DIR/1-buildroot/usr/lib/libcrypto.so.1.1 "$WORK"/libcrypto.so.1.1
cp $FILES_DIR/1-buildroot/usr/lib/libssl.so.1.1 "$WORK"/libssl.so.1.1
cp $FILES_DIR/1-buildroot/lib/libatomic.so.1 "$WORK"/libatomic.so.1
cp $FILES_DIR/1-buildroot/lib/libc.so.0 "$WORK"/libc.so.0
cp $FILES_DIR/1-buildroot/lib/ld-uClibc.so.0 "$WORK"/ld-uClibc


# Patch dropbear to run sftp-server locally
cat $FILES_DIR/1-buildroot/usr/sbin/dropbear |
    sed "s/\/lib\/ld-uClibc.so.0/\/tmp\/ssh\/\/ld-uClibc/g" |
    sed "s/\/usr\/libexec\/sftp-server/\/tmp\/ssh\/sftp-server    /g" \
    > "$WORK"/dropbear

cat $FILES_DIR/1-buildroot/usr/libexec/sftp-server |
    sed "s/\/lib\/ld-uClibc.so.0/\/tmp\/ssh\/\/ld-uClibc/g" \
    > "$WORK"/sftp-server


# Create the update.swu
echo "Building update package..."

SWU_PATH=${1:-/build/dist/update.swu}
build_swu $KOBRA_MODEL_CODE "$WORK" $SWU_PATH

echo "Done, your update package is ready: $SWU_PATH"
