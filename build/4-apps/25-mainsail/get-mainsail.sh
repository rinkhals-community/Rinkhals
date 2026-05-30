#!/bin/sh

# Used by main Dockerfile

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cd "$WORK"

FILES_DIR="${FILES_DIR:-/files}"

MAINSAIL_VERSION="2.17.0"
MAINSAIL_DIRECTORY=$FILES_DIR/4-apps/home/rinkhals/apps/25-mainsail


echo "Downloading Mainsail..."

wget -O mainsail.zip https://github.com/mainsail-crew/mainsail/releases/download/v${MAINSAIL_VERSION}/mainsail.zip
unzip -d mainsail mainsail.zip

mkdir -p $MAINSAIL_DIRECTORY/mainsail
rm -rf $MAINSAIL_DIRECTORY/mainsail/*
cp -pr "$WORK"/mainsail/* $MAINSAIL_DIRECTORY/mainsail

sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"${MAINSAIL_VERSION}\"/" $MAINSAIL_DIRECTORY/app.json
