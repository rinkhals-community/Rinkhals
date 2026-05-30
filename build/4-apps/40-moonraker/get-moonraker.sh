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

VERSION=$(echo $MOONRAKER_COMMIT | cut -c1-7)
sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"${VERSION}\"/" $MOONRAKER_DIRECTORY/app.json
