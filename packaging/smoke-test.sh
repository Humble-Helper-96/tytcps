#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Try the AppImage on clean Ubuntu 22.04, 24.04 and 26.04 (make smoke,
# after make release). Linux Mint 21 and 22 are built on Ubuntu 22.04 and
# 24.04, so these cover them. Each system gets the libraries any desktop has
# (GTK, Mesa, X11, Wayland), then: every library in the AppImage must
# resolve, the engine must run, and TYTcps must start on Qt's offscreen
# screen and keep running. No radio, no display.
set -eu
cd "$(dirname "$0")/.."
img=$(ls build/TYTcps-*-x86_64.AppImage 2>/dev/null | tail -1)
[ -n "$img" ] || { echo "no AppImage in build/: make release first" >&2; exit 1; }
desktop="libgtk-3-0 libegl1 libgl1 libfontconfig1 libdbus-1-3 libx11-xcb1 libxkbcommon-x11-0
         libwayland-client0 libwayland-cursor0 libwayland-egl1 libxcb-icccm4 libxcb-image0
         libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1"
fail=0
for base in ${SMOKE_SYSTEMS:-ubuntu:22.04 ubuntu:24.04 ubuntu:26.04}; do
    echo "== $base"
    if docker run --rm -v "$PWD/build:/b:ro" -e DEBIAN_FRONTEND=noninteractive "$base" sh -c '
        set -e
        apt-get update -qq >/dev/null
        apt-get install -y -qq --no-install-recommends $2 >/dev/null
        cd /tmp && "/b/$1" --appimage-extract >/dev/null
        bad=$(find /tmp/squashfs-root -name "*.so*" -type f -exec ldd {} \; 2>/dev/null | grep "not found" | sort -u || true)
        [ -z "$bad" ] || { echo "missing libraries:"; echo "$bad"; exit 1; }
        /tmp/squashfs-root/usr/share/tytcps/tytcps/libexec/dmrconfig-tyt --version
        "/b/$1" --appimage-extract-and-run --version
        rc=0; QT_QPA_PLATFORM=offscreen timeout 15 "/b/$1" --appimage-extract-and-run >/tmp/out 2>&1 || rc=$?
        if [ $rc -ne 124 ]; then echo "TYTcps stopped by itself (exit $rc):"; tail -20 /tmp/out; exit 1; fi
        echo "TYTcps: running after 15 s"
    ' sh "$(basename "$img")" "$desktop"; then echo "== $base: OK"; else echo "== $base: FAILED"; fail=1; fi
done
exit $fail
