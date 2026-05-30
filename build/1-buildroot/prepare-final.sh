#!/bin/sh

FILES_DIR="${FILES_DIR:-/files}"
BUILDROOT_OUTPUT_DIR="${BUILDROOT_OUTPUT_DIR:-/buildroot-output}"

rm -rf $FILES_DIR/1-buildroot
mkdir -p $FILES_DIR/1-buildroot

# Copy all files, preserving symlinks
rsync -a $BUILDROOT_OUTPUT_DIR/target/ $FILES_DIR/1-buildroot/

# Fix a broken symlink in iptables
cd $FILES_DIR/1-buildroot/usr/bin
ln -f ../sbin/xtables-legacy-multi iptables-xml

# Clean unused files
rm -rf $FILES_DIR/1-buildroot/dev
rm -rf $FILES_DIR/1-buildroot/lib32
rm -rf $FILES_DIR/1-buildroot/media
rm -rf $FILES_DIR/1-buildroot/mnt
rm -rf $FILES_DIR/1-buildroot/opt
rm -rf $FILES_DIR/1-buildroot/proc
rm -rf $FILES_DIR/1-buildroot/root
rm -rf $FILES_DIR/1-buildroot/run
rm -rf $FILES_DIR/1-buildroot/sys
rm -rf $FILES_DIR/1-buildroot/share
rm -rf $FILES_DIR/1-buildroot/tmp
rm -rf $FILES_DIR/1-buildroot/usr/lib32
rm -rf $FILES_DIR/1-buildroot/var
rm $FILES_DIR/1-buildroot/THIS_IS_NOT_YOUR_ROOT_FILESYSTEM

# Clean /etc except for ssl
for dir in $FILES_DIR/1-buildroot/etc/*; do
    [ "$dir" = "$FILES_DIR/1-buildroot/etc/ssl" ] && continue
    rm -rf "$dir"
done

# Create certificate bundle
cat $FILES_DIR/1-buildroot/etc/ssl/certs/*.pem > $FILES_DIR/1-buildroot/etc/ssl/cert.pem

# Clean GCC copies
rm -rf $FILES_DIR/1-buildroot/usr/bin/arm-buildroot-linux-uclibcgnueabihf-*

# Clean python packages
rm -rf $FILES_DIR/1-buildroot/usr/lib/python3.11/site-packages/*
rm -rf $FILES_DIR/1-buildroot/usr/lib/python3.*/site-packages/*

# Clean python .pyc files
find $FILES_DIR/1-buildroot/usr/lib/python3.* -name '*.pyc' -type f -delete
