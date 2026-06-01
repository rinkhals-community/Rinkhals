#!/bin/sh

# Builds the Buildroot root filesystem.
# Must be run from the Buildroot source directory.
# Paths can be overridden via BUILDROOT_OUTPUT_DIR and EXTERNAL_DIR env vars.

set -e
export KCONFIG_NOSILENTUPDATE=1

BUILDROOT_OUTPUT_DIR="${BUILDROOT_OUTPUT_DIR:-/buildroot-output}"
EXTERNAL_DIR="${EXTERNAL_DIR:-/external}"

make O="$BUILDROOT_OUTPUT_DIR" BR2_EXTERNAL="$EXTERNAL_DIR" olddefconfig
make O="$BUILDROOT_OUTPUT_DIR" BR2_EXTERNAL="$EXTERNAL_DIR"

"$(dirname "$0")/prepare-final.sh"
