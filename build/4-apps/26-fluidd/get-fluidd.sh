#!/bin/sh

# Used by main Dockerfile

WORK=$(mktemp -d)
trap "rm -rf $WORK" EXIT
cd "$WORK"

FILES_DIR="${FILES_DIR:-/files}"

FLUIDD_VERSION="1.35.0"
FLUIDD_DIRECTORY=$FILES_DIR/4-apps/home/rinkhals/apps/26-fluidd


echo "Downloading Fluidd..."

wget -O fluidd.zip https://github.com/fluidd-core/fluidd/releases/download/v${FLUIDD_VERSION}/fluidd.zip
unzip -d fluidd fluidd.zip

mkdir -p $FLUIDD_DIRECTORY/fluidd
rm -rf $FLUIDD_DIRECTORY/fluidd/*
cp -pr "$WORK"/fluidd/* $FLUIDD_DIRECTORY/fluidd

sed -i "s/\"version\": *\"[^\"]*\"/\"version\": \"${FLUIDD_VERSION}\"/" $FLUIDD_DIRECTORY/app.json
