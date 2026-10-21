# SPDX-License-Identifier: GPL-3.0-or-later
# Build machine for the AppImage: Ubuntu 22.04, the oldest
# system TYTcps supports (with Linux Mint 21). Programs built here run on
# every newer Ubuntu and Mint.
#
# Besides the build tools it has what a desktop has: the libraries Qt's X11
# and Wayland plugins and the GTK theme load, so the build can check that
# everything in the AppImage resolves.
FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential pkg-config libusb-1.0-0-dev libudev-dev \
        python3 curl ca-certificates file \
        libxcb-cursor0 libgtk-3-0 libegl1 libgl1 libfontconfig1 libfreetype6 libdbus-1-3 \
        libwayland-client0 libwayland-cursor0 libwayland-egl1 libx11-xcb1 libxkbcommon0 \
        libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 \
        libgssapi-krb5-2 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
