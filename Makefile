# SPDX-License-Identifier: GPL-3.0-or-later
# TYTcps build.
#
#   make            build the bundled programming engine (dmrconfig-tyt)
#   make run        start TYTcps from this checkout
#   make test       offline tests (no radio)
#   make hooks      install the key-material pre-commit check
#   make desktop    install a desktop launcher for this checkout (per user)
#   make check-keys scan every tracked file for key material
#   make install    install into PREFIX (used by the Flatpak build)
#   make flatpak    build/TYTcps.flatpak
#   make appimage   build/TYTcps-<version>-x86_64.AppImage
#   make release    the AppImage built on Ubuntu 22.04 (docker)
#   make smoke      try it on clean Ubuntu 22.04, 24.04 and 26.04 (docker)
#
# The engine is built from the subtree in engine/dmrconfig-tyt and placed in
# tytcps/libexec/, where TYTcps looks for it. TYTcps never uses a system
# dmrconfig: upstream "dmrconfig -c" programs a single unverified read into
# the radio.

PYTHON     ?= python3
PREFIX     ?= /usr/local
DESTDIR    ?=
APPID      ?= io.github.Humble_Helper_96.TYTcps
VERSION     = $(shell $(PYTHON) -c "import re; print(re.search(r'__version__ = \"(.+)\"', open('tytcps/__init__.py').read()).group(1))")
PIN         = tytcps/engine_pin.json
ENGINE_SRC  = engine/dmrconfig-tyt
ENGINE_BIN  = tytcps/libexec/dmrconfig-tyt

# git inside the subtree would describe this repository, not the fork, so the
# version the engine reports comes from the pin. TYTcps checks it at startup.
pin         = $(shell $(PYTHON) -c "import json; print(json.load(open('$(PIN)'))['$(1)'])")
PIN_VERSION = $(call pin,version)
ENGINE_VARS = VERSION=$(basename $(PIN_VERSION)) GITCOUNT=$(subst .,,$(suffix $(PIN_VERSION))) \
              GITCOMMIT=$(call pin,commit) GITBRANCH=$(call pin,branch)

all: engine

engine: $(ENGINE_BIN)

$(ENGINE_BIN): $(wildcard $(ENGINE_SRC)/*.c $(ENGINE_SRC)/*.h) $(ENGINE_SRC)/Makefile $(PIN)
	$(MAKE) -C $(ENGINE_SRC) clean
	$(MAKE) -C $(ENGINE_SRC) $(ENGINE_VARS)
	mkdir -p $(dir $@)
	install -m 755 $(ENGINE_SRC)/dmrconfig $@
	$(MAKE) -C $(ENGINE_SRC) clean
	$@ --version

run: engine
	$(PYTHON) -m tytcps

test: engine
	$(PYTHON) -m unittest discover -s tests -t . -v

hooks:
	git config core.hooksPath .githooks
	@echo "Pre-commit key-material check installed."
	@echo "Point it at key files kept outside a fleet folder with:"
	@echo "  git config --add tytcps.keyfile '/path/to/keys/*.dec'"

check-keys:
	$(PYTHON) tools/check-key-material.py --all

desktop: engine
	$(PYTHON) tools/install-desktop.py

# The package goes to PREFIX/share/tytcps with the engine inside it, as in a
# checkout; PREFIX/bin/tytcps starts it. The launcher, icon and AppStream
# file are named after APPID, as Flatpak requires. The udev rule is copied
# to PREFIX/share/tytcps for the install instructions: it has to be put in
# place on the host, by root, and no package can do that from inside.
SHARE = $(DESTDIR)$(PREFIX)/share

install: engine
	mkdir -p $(SHARE)/tytcps $(DESTDIR)$(PREFIX)/bin
	cp -r tytcps $(SHARE)/tytcps/
	find $(SHARE)/tytcps -name __pycache__ -prune -exec rm -rf {} +
	install -m 644 tytcps/data/70-tytcps.rules $(SHARE)/tytcps/70-tytcps.rules
	printf '#!/bin/sh\nPYTHONPATH="$(PREFIX)/share/tytcps$${PYTHONPATH:+:$$PYTHONPATH}" exec python3 -m tytcps "$$@"\n' \
		> $(DESTDIR)$(PREFIX)/bin/tytcps
	chmod 755 $(DESTDIR)$(PREFIX)/bin/tytcps
	install -Dm 644 packaging/tytcps.desktop $(SHARE)/applications/$(APPID).desktop
	sed -i 's/^Icon=.*/Icon=$(APPID)/' $(SHARE)/applications/$(APPID).desktop
	install -Dm 644 tytcps/data/tytcps.svg $(SHARE)/icons/hicolor/scalable/apps/$(APPID).svg
	sed 's/@APPID@/$(APPID)/g' packaging/tytcps.metainfo.xml > $(SHARE)/tytcps-metainfo.tmp
	install -Dm 644 $(SHARE)/tytcps-metainfo.tmp $(SHARE)/metainfo/$(APPID).metainfo.xml
	rm -f $(SHARE)/tytcps-metainfo.tmp

flatpak:
	flatpak run org.flatpak.Builder --user --force-clean --install-deps-from=flathub \
		--repo=build/flatpak-repo build/flatpak packaging/flatpak/$(APPID).yml
	flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
		build/flatpak-repo build/TYTcps-$(VERSION).flatpak $(APPID)

# The AppImage as released: built on Ubuntu 22.04 (needs docker).
release:
	packaging/build-release.sh

# Start the AppImage on clean Ubuntu 22.04, 24.04 and 26.04.
smoke:
	packaging/smoke-test.sh

appimage:
	packaging/appimage/build-appimage.sh

clean:
	rm -rf tytcps/libexec
	$(MAKE) -C $(ENGINE_SRC) clean

.PHONY: install flatpak appimage release smoke all engine run test hooks check-keys desktop clean
