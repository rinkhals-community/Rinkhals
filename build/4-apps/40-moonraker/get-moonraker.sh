#!/bin/sh

# Used by main Dockerfile

set -e

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cd "$WORK"

FILES_DIR="${FILES_DIR:-/files}"

MOONRAKER_COMMIT=3c1f31874ac0beba35747059637583e5d2c383c0
MOONRAKER_DIRECTORY=$FILES_DIR/4-apps/home/rinkhals/apps/40-moonraker

echo "Downloading Moonraker..."
wget -O moonraker.zip https://github.com/Arksine/moonraker/archive/${MOONRAKER_COMMIT}.zip
unzip -d moonraker moonraker.zip

mkdir -p $MOONRAKER_DIRECTORY/moonraker
rm -rf $MOONRAKER_DIRECTORY/moonraker/*
cp -pr "$WORK"/moonraker/*/* $MOONRAKER_DIRECTORY/moonraker

# Apply Rinkhals spoolman compatibility fix directly in Moonraker source.
# See: https://github.com/utkabobr/DuckPro-Kobra3/issues/54#issuecomment-2540040852
SPOOLMAN_FILE="$MOONRAKER_DIRECTORY/moonraker/moonraker/components/spoolman.py"
if [ -f "$SPOOLMAN_FILE" ] && ! grep -q "SPOOL_ID: Union\[int, None\]" "$SPOOLMAN_FILE"; then
	perl -0pi -e 's/def set_active_spool\(self, spool_id: Union\[int, None\]\) -> None:\n        assert spool_id is None or isinstance\(spool_id, int\)/def set_active_spool(self, spool_id: Union[int, None] = None, SPOOL_ID: Union[int, None] = None) -> None:\n        if spool_id is None and SPOOL_ID is not None:\n            spool_id = int(str(SPOOL_ID).lstrip("="))\n        assert spool_id is None or isinstance(spool_id, int)/' "$SPOOLMAN_FILE"
fi

VERSION=$(echo $MOONRAKER_COMMIT | cut -c1-7)
sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"${VERSION}\"/" $MOONRAKER_DIRECTORY/app.json
