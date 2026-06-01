#!/bin/sh

# From a Windows machine:
#   docker run --rm -it -e KOBRA_MODEL_CODE="K3" -v .\build:/build -v .\files:/files ghcr.io/rinkhals-community/rinkhals/build /build/swu-tools/backup-partitions/build-swu.sh


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

cp $FILES_DIR/3-rinkhals/opt/rinkhals/tools/backup-partitions.sh "$WORK"/update.sh


# Create the update.swu
echo "Building update package..."

SWU_PATH=${1:-/build/dist/update.swu}
build_swu $KOBRA_MODEL_CODE "$WORK" $SWU_PATH

echo "Done, your update package is ready: $SWU_PATH"
