FROM debian:12.10
ENV DEBIAN_FRONTEND=noninteractive

# Install Buildroot dependencies (same as root Dockerfile)
# https://buildroot.org/downloads/manual/manual.html#requirement
RUN --mount=type=cache,sharing=locked,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        which sed make binutils build-essential diffutils gcc g++ bash patch gzip bzip2 perl tar cpio unzip rsync file bc findutils wget \
        texinfo \
        python3 libncurses5 git mercurial ca-certificates \
        locales whois vim bison flex \
        libncurses5-dev libdevmapper-dev libsystemd-dev libssl-dev libfdt-dev libvncserver-dev libdrm-dev \
        zip curl jq parallel && \
    rm -rf /var/lib/apt/lists/*

# Sometimes Buildroot needs proper locale, e.g. when using a toolchain based on glibc
RUN locale-gen en_US.utf8

# Pre-create directories that will hold named volumes and symlinks
RUN mkdir -p /rinkhals-build/buildroot-output /rinkhals-build/buildroot-dl /rinkhals-build/files \
             /rinkhals-build/bundle /rinkhals-build/swu

# Install pinned version of Buildroot
ADD https://gitlab.com/buildroot.org/buildroot.git#2023.02.6 /buildroot

# Install just (task runner) and just-lsp (language server)
RUN JUST_VERSION="1.51.0" && \
    JUST_LSP_VERSION="0.4.4" && \
    ARCH="$(dpkg --print-architecture)" && \
    case "$ARCH" in \
        amd64)   ARCH="x86_64" ;; \
        arm64)   ARCH="aarch64" ;; \
        *)       echo "Unsupported arch: $ARCH" && exit 1 ;; \
    esac && \
    curl -sSL "https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-${ARCH}-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin just && \
    curl -sSL "https://github.com/terror/just-lsp/releases/download/${JUST_LSP_VERSION}/just-lsp-${JUST_LSP_VERSION}-${ARCH}-unknown-linux-musl.tar.gz" \
        | tar -xz -C /usr/local/bin ./just-lsp
