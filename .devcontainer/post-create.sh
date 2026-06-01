#!/bin/sh

# Runs once when the devcontainer is first created.
# Applies patches to the Buildroot source tree and sets up workspace symlinks.

set -e

WORKSPACE="/workspaces/Rinkhals"
FILES_DIR="/rinkhals-build/files"

echo "==> Setting up build staging directory..."
# Files dir is on the persistent build volume for fast I/O during builds.
# Only the final SWU outputs are exported to the workspace.
mkdir -p "$FILES_DIR"

# Symlink repo source files into $FILES_DIR so build scripts can find them
rm -rf "$FILES_DIR/3-rinkhals"
ln -sf "$WORKSPACE/files/3-rinkhals" "$FILES_DIR/3-rinkhals"
for f in "$WORKSPACE/files"/*; do
    [ -f "$f" ] && ln -sf "$f" "$FILES_DIR/$(basename "$f")"
done

echo "==> Applying Buildroot patches..."
cd /buildroot
for patch in "$WORKSPACE/build/1-buildroot/"*.patch; do
    echo "  Applying $patch"
    git apply "$patch"
done

echo "==> Registering QEMU binfmt_misc for ARM..."
qemu_ok=false
for i in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
        docker run --rm --privileged tonistiigi/binfmt --install all && qemu_ok=true
        break
    fi
    sleep 1
done
if [ "$qemu_ok" = false ]; then
    echo "  WARNING: QEMU registration failed. ARM Docker builds will not work until you run: just setup-qemu"
fi

echo "==> Setting up just shell completions..."
just --completions bash >> /root/.bashrc

echo ""
echo "Devcontainer setup complete."
echo "Run 'just' to see available build tasks."
