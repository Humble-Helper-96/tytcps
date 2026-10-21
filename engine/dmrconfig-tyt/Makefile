CC             ?= gcc
PKG_CONFIG     ?= pkg-config

# Upstream's numeric tags only: engine-* tags mark TYTcps baselines.
VERSION         = $(shell git describe --tags --abbrev=0 --match '[0-9]*')
GITCOUNT        = $(shell git rev-list HEAD --count)
GITCOMMIT       = $(shell git rev-parse --short HEAD)$(shell git diff --quiet HEAD -- . 2>/dev/null || echo -dirty)
GITBRANCH       = $(shell git rev-parse --abbrev-ref HEAD)
UNAME           = $(shell uname)

OBJS            = main.o util.o radio.o dfu-libusb.o privacy.o report.o state.o \
                  imgdiff.o uv380.o cpsfields.o md380.o rd5r.o \
                  gd77.o hid.o serial.o anytone_ht.o dm1801.o
CFLAGS         ?= -g -O -Wall -Werror 
CFLAGS         += -DVERSION='"$(VERSION).$(GITCOUNT)"' \
                  -DGITCOMMIT='"$(GITCOMMIT)"' -DGITBRANCH='"$(GITBRANCH)"' \
                  $(shell $(PKG_CONFIG) --cflags libusb-1.0)
LDFLAGS        ?= -g
LIBS            = $(shell $(PKG_CONFIG) --libs --static libusb-1.0)

#
# Make sure pkg-config is installed.
#
ifeq ($(shell $(PKG_CONFIG) --version),)
    $(error Fatal error: pkg-config is not installed)
endif

#
# Linux
#
# To install required libraries, use:
#   sudo apt-get install pkg-config libusb-1.0-0-dev libudev-dev
#
ifeq ($(UNAME),Linux)
    OBJS        += hid-libusb.o

    # Link libusb statically, when possible
    LIBUSB      = /usr/lib/x86_64-linux-gnu/libusb-1.0.a
    ifeq ($(wildcard $(LIBUSB)),$(LIBUSB))
        LIBS    = $(LIBUSB) -lpthread -ludev
    endif
endif

#
# Mac OS X
#
# To install required libraries, use:
#   brew install pkg-config libusb
#
ifeq ($(UNAME),Darwin)
    OBJS        += hid-macos.o
    LIBS        += -framework IOKit -framework CoreFoundation
endif

all:		dmrconfig

dmrconfig:	$(OBJS)
		$(CC) $(LDFLAGS) -o $@ $(OBJS) $(LIBS)

clean:
		rm -f *~ *.o core dmrconfig dmrconfig.exe dmrconfig-fakeusb tests/*.o

#
# Offline tests: the engine linked against tests/fakeusb.c, a stand-in for
# libusb that plays one MD-UV390 on the bus.  No radio is touched.
#
dmrconfig-fakeusb: $(OBJS) tests/fakeusb.o
		$(CC) $(LDFLAGS) -o $@ $(OBJS) tests/fakeusb.o -lpthread -ludev

test:		dmrconfig dmrconfig-fakeusb
		python3 tests/test_expect_unit.py ./dmrconfig-fakeusb ./dmrconfig

install:	dmrconfig
		install -c -s dmrconfig /usr/local/bin/dmrconfig

# The commit is compiled into main.o (--version), so rebuild it every time.
main.o:		FORCE
FORCE:

.PHONY:		test

###
tests/fakeusb.o: tests/fakeusb.c
anytone_ht.o: anytone_ht.c radio.h util.h anytone_ht-map.h
dfu-libusb.o: dfu-libusb.c util.h report.h state.h
report.o: report.c report.h
state.o: state.c state.h report.h util.h
imgdiff.o: imgdiff.c radio.h util.h report.h
dfu-windows.o: dfu-windows.c util.h
gd77.o: gd77.c radio.h util.h
hid.o: hid.c util.h
hid-libusb.o: hid-libusb.c util.h
hid-macos.o: hid-macos.c util.h
hid-windows.o: hid-windows.c util.h
main.o: main.c radio.h util.h report.h state.h
md380.o: md380.c radio.h util.h
radio.o: radio.c radio.h util.h report.h state.h
rd5r.o: rd5r.c radio.h util.h
serial.o: serial.c util.h
util.o: util.c util.h
uv380.o: uv380.c radio.h util.h report.h
privacy.o: privacy.c radio.h util.h report.h state.h
