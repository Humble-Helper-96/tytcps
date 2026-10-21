#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the AppImage inside Ubuntu 22.04 (make release), so it runs on
# Ubuntu 22.04 / Linux Mint 21 and everything newer. Needs docker; the
# AppImage lands in build/ as with make appimage.
set -eu
cd "$(dirname "$0")/.."
docker build -t tytcps-build:jammy -f packaging/docker/jammy.Dockerfile packaging/docker
# The engine is rebuilt in there: one built on a newer system needs a newer glibc.
rm -rf tytcps/libexec
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/src" -w /src \
    tytcps-build:jammy make appimage
