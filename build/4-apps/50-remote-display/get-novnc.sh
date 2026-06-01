#!/bin/sh

# Used by main Dockerfile

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cd "$WORK"

FILES_DIR="${FILES_DIR:-/files}"

NOVNC_VERSION="1.6.0"
APP_DIRECTORY=$FILES_DIR/4-apps/home/rinkhals/apps/50-remote-display

echo "Downloading noVNC..."

wget -O novnc.zip https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.zip
unzip -d novnc novnc.zip

# Remove everything except the web files
find "$WORK"/novnc/*/* -mindepth 1 ! -name 'vnc.html' ! -name 'app' ! -name 'core' ! -name 'vendor' \
  ! -path "$WORK/novnc/*/app/*" \
  ! -path "$WORK/novnc/*/core/*" \
  ! -path "$WORK/novnc/*/vendor/*" \
  -exec rm -rf {} +

mkdir -p $APP_DIRECTORY/novnc
rm -rf $APP_DIRECTORY/novnc/*
cp -pr "$WORK"/novnc/*/* $APP_DIRECTORY/novnc
mv $APP_DIRECTORY/index.vnc $APP_DIRECTORY/novnc/
