# Rinkhals Justfile — build orchestration
#
# Works inside the devcontainer out of the box. For non-devcontainer setups,
# copy .env.example to .env and adjust the paths for your environment.
# For CI or one-shot builds without just: docker build --output type=local,dest=./build/dist .

set dotenv-load
set shell := ["sh", "-ce"]
export LC_ALL := "C"

# Workspace root (the repo checkout)
workspace := justfile_directory()

# User-configurable paths (override via .env or environment)
rinkhals_build_dir := env("RINKHALS_BUILD_DIR", "/rinkhals-build")
buildroot_dir      := env("BUILDROOT_DIR", "/buildroot")

# Derived paths (exported to child processes; scripts default to /files etc. for Dockerfile compat)
export BR2_DL_DIR           := env("BR2_DL_DIR", rinkhals_build_dir / "buildroot-dl")
export BUILDROOT_OUTPUT_DIR := rinkhals_build_dir / "buildroot-output"
export FILES_DIR            := rinkhals_build_dir / "files"
export BUNDLE_DIR           := rinkhals_build_dir / "bundle"
export SWU_DIR              := rinkhals_build_dir / "swu"
export EXTERNAL_DIR         := workspace / "build" / "1-buildroot" / "external"

[private]
@default:
    just --list -u

[private, no-exit-message]
@require name path:
    test -e "{{path}}" || { echo "Missing requirement: run 'just {{name}}' first"; exit 1; }

# Show a how-to guide
[script]
how:
    cat <<'EOF'

    How To Build Rinkhals
    ---------------------
    For a full (dev) build from scratch, run:
      just build

    This runs the full pipeline in order:
      buildroot → arm-packages → apps → assembly

    The build is split into stages, or groups. Recipes from each group can be
    (re-)run independently, but most require recipes from preceding stages.

    Use 'just' to see all available recipes.

    buildroot       Build the cross-compiled root filesystem and toolchain. First
                    build takes ~30-60 min. Also has recipes to rebuild individual
                    packages and change configuration.

    arm-packages    Build ARM packages emulated via Docker.

    apps            Download web UIs (Mainsail, Fluidd) and other apps (Moonraker,
                    noVNC).

    assembly        Combine build outputs into a versioned bundle and produce SWU
                    firmware files for all printer models.

    dev             Development utilities and common tasks.

    Custom Dev Environments
    -----------------------
    Recipes work inside the dev container out of the box. For custom setups,
    copy .env.example to .env and adjust the paths for your environment.

    For CI or one-shot builds without just, use the main Dockerfile.

    EOF

# ─── Buildroot ────────────────────────────────────────────────────────────────

# Build the Buildroot root filesystem (first build ~30-60 min; rebuilds are faster)
[group('buildroot'), script]
buildroot:
    cp {{workspace}}/build/1-buildroot/.config {{BUILDROOT_OUTPUT_DIR}}/.config
    cp {{workspace}}/build/1-buildroot/busybox.config {{buildroot_dir}}/busybox.config
    cd {{buildroot_dir}} && {{workspace}}/build/1-buildroot/build.sh
    echo "Buildroot filesystem built: $BUILDROOT_OUTPUT_DIR"

# Clean the Buildroot build output and download cache
[group('buildroot'), script]
buildroot-clean:
    cd {{buildroot_dir}} && make O={{BUILDROOT_OUTPUT_DIR}} clean
    echo "Buildroot output cleaned"

# Rebuild specific Buildroot package(s) (space-separated, e.g. 'just buildroot-rebuild lv_micropython')
[group('buildroot'), script]
buildroot-rebuild +packages: (require "buildroot" BUILDROOT_OUTPUT_DIR / "build/toolchain-buildroot/.stamp_built")
    cp {{workspace}}/build/1-buildroot/.config {{BUILDROOT_OUTPUT_DIR}}/.config
    cp {{workspace}}/build/1-buildroot/busybox.config {{buildroot_dir}}/busybox.config
    cd {{buildroot_dir}}
    export KCONFIG_NOSILENTUPDATE=1
    make O={{BUILDROOT_OUTPUT_DIR}} BR2_EXTERNAL={{EXTERNAL_DIR}} olddefconfig
    echo "{{packages}}" | tr ' ' '\n' | while read -r p; do
        echo "Rebuilding: $p"
        make O={{BUILDROOT_OUTPUT_DIR}} "${p}-dirclean"
        make O={{BUILDROOT_OUTPUT_DIR}} "${p}-rebuild"
    done
    {{workspace}}/build/1-buildroot/prepare-final.sh
    echo "Buildroot package(s) rebuilt: {{packages}}"

# Open Buildroot interactive configuration menu
[group('buildroot'), script]
buildroot-menuconfig:
    cp {{workspace}}/build/1-buildroot/.config {{BUILDROOT_OUTPUT_DIR}}/.config
    cd {{buildroot_dir}} && make O={{BUILDROOT_OUTPUT_DIR}} BR2_EXTERNAL={{EXTERNAL_DIR}} menuconfig
    cp {{BUILDROOT_OUTPUT_DIR}}/.config {{workspace}}/build/1-buildroot/.config
    echo "Buildroot config saved"

# Open BusyBox interactive configuration menu
[group('buildroot'), script]
busybox-menuconfig: (require "buildroot" BUILDROOT_OUTPUT_DIR / "build/toolchain-buildroot/.stamp_built")
    cp {{workspace}}/build/1-buildroot/busybox.config {{buildroot_dir}}/busybox.config
    cd {{buildroot_dir}} && make O={{BUILDROOT_OUTPUT_DIR}} BR2_EXTERNAL={{EXTERNAL_DIR}} busybox-menuconfig
    cp {{buildroot_dir}}/busybox.config {{workspace}}/build/1-buildroot/busybox.config
    echo "BusyBox config saved"

# ─── Packages ─────────────────────────────────────────────────────────────────

# Build ARM Python packages via Docker
[group('arm-packages'), script]
python-packages:
    just setup-qemu
    mkdir -p $FILES_DIR/2-python
    docker run --rm --platform=linux/arm/v7 \
        -v {{workspace}}/build/2-python:/build/2-python \
        -v $FILES_DIR/2-python:/files/2-python \
        -e FILES_DIR=/files \
        ghcr.io/jbatonnet/armv7-uclibc:rinkhals \
        sh -c "/build/2-python/get-packages.sh"
    echo "Python ARM packages built"

# Build ARM Moonraker dependencies via Docker (requires: app-moonraker)
[group('arm-packages'), script]
moonraker-packages: (require "app-moonraker" FILES_DIR / "4-apps/home/rinkhals/apps/40-moonraker/moonraker")
    just setup-qemu
    docker run --rm --platform=linux/arm/v7 \
        -v $FILES_DIR/4-apps:/files/4-apps \
        -v {{workspace}}/build/4-apps/40-moonraker/get-packages.sh:/build/4-apps/40-moonraker/get-packages.sh \
        -e FILES_DIR=/files \
        ghcr.io/jbatonnet/armv7-uclibc:rinkhals \
        sh -c "/build/4-apps/40-moonraker/get-packages.sh"
    echo "Moonraker ARM packages built"

# ─── Apps ─────────────────────────────────────────────────────────────────────

# Download all apps
[group('apps')]
apps: app-mainsail app-fluidd app-moonraker app-remote-display
    @echo "All apps downloaded: $FILES_DIR"

# Download Fluidd web UI
[group('apps'), script]
app-fluidd:
    mkdir -p $FILES_DIR/4-apps/home/rinkhals/apps/26-fluidd
    cp {{workspace}}/files/4-apps/home/rinkhals/apps/26-fluidd/app.json $FILES_DIR/4-apps/home/rinkhals/apps/26-fluidd/app.json
    {{workspace}}/build/4-apps/26-fluidd/get-fluidd.sh
    echo "Fluidd downloaded"

# Download Mainsail web UI
[group('apps'), script]
app-mainsail:
    mkdir -p $FILES_DIR/4-apps/home/rinkhals/apps/25-mainsail
    cp {{workspace}}/files/4-apps/home/rinkhals/apps/25-mainsail/app.json $FILES_DIR/4-apps/home/rinkhals/apps/25-mainsail/app.json
    {{workspace}}/build/4-apps/25-mainsail/get-mainsail.sh
    echo "Mainsail downloaded"

# Download Moonraker source
[group('apps'), script]
app-moonraker:
    mkdir -p $FILES_DIR/4-apps/home/rinkhals/apps/40-moonraker
    cp {{workspace}}/files/4-apps/home/rinkhals/apps/40-moonraker/app.json $FILES_DIR/4-apps/home/rinkhals/apps/40-moonraker/app.json
    {{workspace}}/build/4-apps/40-moonraker/get-moonraker.sh
    echo "Moonraker downloaded"

# Download noVNC remote display app
[group('apps'), script]
app-remote-display:
    mkdir -p $FILES_DIR/4-apps/home/rinkhals/apps/50-remote-display
    cp {{workspace}}/files/4-apps/home/rinkhals/apps/50-remote-display/app.json $FILES_DIR/4-apps/home/rinkhals/apps/50-remote-display/app.json
    cp {{workspace}}/files/4-apps/home/rinkhals/apps/50-remote-display/index.vnc $FILES_DIR/4-apps/home/rinkhals/apps/50-remote-display/index.vnc
    {{workspace}}/build/4-apps/50-remote-display/get-novnc.sh
    echo "noVNC remote display downloaded"

# ─── Assembly ─────────────────────────────────────────────────────────────────

# Assemble all build outputs into a deployable bundle (requires: buildroot, apps, packages)
[group('assembly'), script]
bundle version="dev": \
    (require "buildroot" FILES_DIR / "1-buildroot/bin") \
    (require "python-packages" FILES_DIR / "2-python/usr/lib") \
    (require "apps" FILES_DIR / "4-apps")
    mkdir -p $BUNDLE_DIR/rinkhals
    cp -a $FILES_DIR/1-buildroot/. $BUNDLE_DIR/rinkhals/
    cp -a $FILES_DIR/2-python/. $BUNDLE_DIR/rinkhals/
    cp -a $FILES_DIR/4-apps/. $BUNDLE_DIR/rinkhals/
    cp -a {{workspace}}/files/3-rinkhals/. $BUNDLE_DIR/rinkhals/
    cp -a {{workspace}}/files/4-apps/. $BUNDLE_DIR/rinkhals/
    cp {{workspace}}/files/*.* $BUNDLE_DIR/
    {{workspace}}/build/prepare-bundle.sh $BUNDLE_DIR "{{version}}"
    echo "Bundle ready: $BUNDLE_DIR (version: {{version}})"

# Build all SWU outputs (update, installer, tools)
[group('assembly')]
swu-all: swu-update swu-installer swu-tools
    @echo "All SWU files built: $SWU_DIR"

# Build installer SWU files for all printer models (requires: buildroot, python-packages)
[group('assembly'), script]
swu-installer: (require "buildroot" FILES_DIR / "1-buildroot/bin") (require "python-packages" FILES_DIR / "2-python/usr/lib")
    mkdir -p $SWU_DIR
    parallel --halt now,fail=1 --tagstring '[installer-{2}]' \
        'KOBRA_MODEL_CODE={1} {{workspace}}/build/swu-tools/installer/build-swu.sh '$SWU_DIR'/installer-{2}.swu' \
        ::: K3 K3M KS1 KS1M :::+ k2p-k3 k3m ks1 ks1m
    echo "Installer SWU files built: $SWU_DIR"

# Build tool SWU zip files for all printer models (requires: buildroot, python-packages)
[group('assembly'), script]
swu-tools: (require "buildroot" FILES_DIR / "1-buildroot/bin") (require "python-packages" FILES_DIR / "2-python/usr/lib")
    SCRIPT_DIR={{workspace}}/build/swu-tools
    mkdir -p "$SWU_DIR"
    tools=""
    for tool in $(ls "$SCRIPT_DIR"); do
        [ "$tool" = "installer" ] && continue
        [ -f "$SCRIPT_DIR/$tool/build-swu.sh" ] || continue
        tools="$tools $tool"
    done
    parallel --halt now,fail=1 --tagstring '[{1}-{3}]' \
        'KOBRA_MODEL_CODE={2} '"$SCRIPT_DIR"'/{1}/build-swu.sh '"$SWU_DIR"'/{1}-{3}.swu' \
        ::: $tools ::: K3 K3M KS1 KS1M :::+ k2p-k3 k3m ks1 ks1m
    cd "$SWU_DIR"
    parallel --halt now,fail=1 --tagstring '[tools-{1}]' \
        'zip -j tools-{1}.zip ./*.swu -i "*-{1}.swu" -x "installer-*" "update-*"' \
        ::: k2p-k3 k3m ks1 ks1m
    echo "Tools SWU zip files built: $SWU_DIR"

# Build firmware update SWU files for all printer models (requires: bundle)
[group('assembly'), script]
swu-update: (require "bundle" BUNDLE_DIR / ".version")
    mkdir -p $SWU_DIR
    . {{workspace}}/build/tools.sh
    prepare_tgz $BUNDLE_DIR $SWU_DIR
    parallel --halt now,fail=1 --tagstring '[update-{2}]' \
        '. '"{{workspace}}"'/build/tools.sh && compress_swu {1} '$SWU_DIR'/update-{2}.swu' \
        ::: K3 K3M KS1 KS1M :::+ k2p-k3 k3m ks1 ks1m
    echo "Update SWU files built: $SWU_DIR"

# ─── Dev ──────────────────────────────────────────────────────────────────────

# Full dev build (buildroot → apps → packages → bundle "dev")
[group('dev')]
build: buildroot python-packages apps moonraker-packages bundle
    @echo "Build complete"

# Deploy dev build to printer via rclone/SSH (requires: swu-update)
[group('dev'), script]
dev-deploy ip: (require "swu-update" SWU_DIR / "update_swu/setup.tar.gz")
    docker run --rm \
        --mount type=bind,source={{workspace}}/build,target=/build \
        --mount type=bind,source=$SWU_DIR,target=/build/dist \
        -e KOBRA_IP={{ip}} \
        --entrypoint /bin/sh \
        rclone/rclone:1.69.1 /build/deploy-dev.sh
    echo "Development build deployed to {{ip}}"

# Remove build outputs (except Buildroot output and download cache)
[group('dev'), script]
clean:
    find "{{rinkhals_build_dir}}" -mindepth 1 -maxdepth 1 \
        ! -name buildroot-output ! -name buildroot-dl -exec rm -rf {} +
    echo "Clean complete"

# Remove all build outputs
[group('dev'), script]
clean-all:
    rm -rf "{{rinkhals_build_dir}}"
    echo "Clean all complete"


# Copy final SWU outputs to workspace build/dist
[group('dev'), script]
copy-dist:
    mkdir -p {{workspace}}/build/dist
    cp -a $SWU_DIR/. {{workspace}}/build/dist/
    echo "SWU outputs copied to {{workspace}}/build/dist"

# Register QEMU binfmt_misc for ARM emulation (needed for building ARM packages)
[group('dev'), script]
setup-qemu:
    if [ -f /proc/sys/fs/binfmt_misc/qemu-arm ]; then
        echo "QEMU ARM handler already registered"
    else
        echo "Registering QEMU binfmt_misc for ARM..."
        docker run --rm --privileged tonistiigi/binfmt --install all
        echo "QEMU ARM handler registered successfully"
    fi
