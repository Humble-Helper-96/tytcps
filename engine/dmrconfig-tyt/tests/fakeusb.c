// SPDX-License-Identifier: BSD-3-Clause
/*
 * A stand-in for libusb-1.0 that plays one TYT MD-UV390 on the bus, for
 * testing the engine without a radio.  Linked in place of libusb
 * by "make test"; the normal build never sees it.
 *
 * The fake radio answers the DFU requests dfu-libusb.c makes: the 91 xx and
 * a2 xx commands, the a2 identify blocks, codeplug reads and writes (kept in
 * memory, so a write verifies), erase, and the da 01 / da 02 key table.
 * Every request that matters is appended to $FAKEUSB_LOG, one per line:
 *
 *   OPEN                       the radio was opened
 *   CMD 91 01                  a two-byte command (91 05 is the restart)
 *   IDENT a2 07                an identify block was read
 *   ERASE 00010000             an erase command
 *   READ <block>               a codeplug block read
 *   WRITE <block>              a codeplug block written
 *   KEYS <n>                   key table block n sent (after CMD da 02)
 *   KEYREAD <n>                key table block n read (after CMD da 01)
 *   FAIL <what>                an injected failure
 *
 * Environment:
 *   FAKEUSB_RADIOS   how many radios are on the bus (default 1)
 *   FAKEUSB_MODEL    the a2 01 model string (default MD-UV390)
 *   FAKEUSB_A207     the a2 07 unit block in hex (default a fixed one);
 *                    "zero" returns it all zero, "fail" refuses the read
 *   FAKEUSB_IMAGE    the radio's codeplug at the start (default all 0xff)
 *   FAKEUSB_FAIL     READ, WRITE, ERASE or KEYS: fail the first such request;
 *                    KEYCMD: refuse (stall) the da 02 key-table command, as
 *                    a radio that takes no key table might
 *   FAKEUSB_LOG      where the log goes (default: nowhere)
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <libusb.h>

struct libusb_context { int unused; };
struct libusb_device { int index; };
struct libusb_device_handle { int unused; };

static struct libusb_context the_context;
static struct libusb_device radios[4];
static struct libusb_device_handle the_handle;

#define MEMSZ (1024 * 1024 * 2)
static unsigned char mem[MEMSZ];
static int mem_loaded;

static int pending_ident = -1;      // a2 block the next UPLOAD returns
static int key_mode;                // 1 after da 01, 2 after da 02
static int key_block;
static int failed;                  // the injected failure has happened

static void logf_(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void logf_(const char *fmt, ...)
{
    const char *path = getenv("FAKEUSB_LOG");
    va_list ap;
    FILE *f;

    if (! path || ! *path)
        return;
    f = fopen(path, "a");
    if (! f)
        return;
    va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fputc('\n', f);
    fclose(f);
}

static int env_int(const char *name, int dflt)
{
    const char *v = getenv(name);

    return (v && *v) ? atoi(v) : dflt;
}

//
// Fail the first request of this kind, once, when FAKEUSB_FAIL names it.
//
static int inject(const char *what)
{
    const char *v = getenv("FAKEUSB_FAIL");

    if (failed || ! v || strcmp(v, what) != 0)
        return 0;
    failed = 1;
    logf_("FAIL %s", what);
    return 1;
}

static void load_mem(void)
{
    const char *path = getenv("FAKEUSB_IMAGE");
    FILE *f;

    if (mem_loaded)
        return;
    mem_loaded = 1;
    memset(mem, 0xff, sizeof(mem));
    if (! path || ! *path)
        return;
    f = fopen(path, "rb");
    if (! f) {
        fprintf(stderr, "fakeusb: %s: cannot open\n", path);
        exit(99);
    }
    if (fread(mem, 1, sizeof(mem), f) == 0) {
        fprintf(stderr, "fakeusb: %s: empty\n", path);
        exit(99);
    }
    fclose(f);
}

//
// The identify blocks, a2 01 to a2 07.
//
static int ident_block(int cmd, unsigned char *data, int len)
{
    unsigned char buf[64];
    const char *v;
    int i;

    memset(buf, 0, sizeof(buf));
    switch (cmd) {
    case 0x01:
        v = getenv("FAKEUSB_MODEL");
        snprintf((char*) buf, sizeof(buf), "%s", (v && *v) ? v : "MD-UV390");
        break;
    case 0x02:
        buf[0] = 'S'; buf[1] = 0x11; buf[2] = 0x90; buf[3] = 0x38;
        break;
    case 0x03:
        snprintf((char*) buf, sizeof(buf), "%s", "000042");
        break;
    case 0x04:
        memset(buf, 0xff, 8);
        break;
    case 0x07:
        v = getenv("FAKEUSB_A207");
        if (! v || ! *v)
            v = "0badcafe0badcafe0badcafe00001001";
        if (strcmp(v, "fail") == 0) {
            logf_("FAIL IDENT a2 07");
            return LIBUSB_ERROR_PIPE;
        }
        if (strcmp(v, "zero") != 0) {
            for (i=0; i<16 && v[2*i] && v[2*i+1]; i++) {
                unsigned x;

                sscanf(v + 2*i, "%2x", &x);
                buf[i] = x;
            }
        }
        break;
    }
    logf_("IDENT a2 %02x", cmd);
    if (len > (int) sizeof(buf))
        len = sizeof(buf);
    memcpy(data, buf, len);
    return len;
}

//
// dfu_read_block() and dfu_write_block() move blocks 256-2047 up by 832;
// this puts them back.
//
static int block_index(int wvalue)
{
    int bno = wvalue - 2;

    if (bno >= 256 + 832 && bno < 2048 + 832)
        bno -= 832;
    return bno;
}

int LIBUSB_CALL libusb_control_transfer(libusb_device_handle *h,
    uint8_t request_type, uint8_t request, uint16_t wvalue, uint16_t windex,
    unsigned char *data, uint16_t len, unsigned int timeout)
{
    int bno;

    (void) h; (void) windex; (void) timeout;
    if (request_type == 0xA1) {
        switch (request) {
        case 5:                                     // GETSTATE
            data[0] = 2;                            // dfuIDLE
            return 1;
        case 3:                                     // GETSTATUS
            memset(data, 0, len);
            if (len >= 5)
                data[4] = 2;
            return len;
        case 2:                                     // UPLOAD
            if (wvalue == 0 && pending_ident >= 0) {
                int cmd = pending_ident;

                pending_ident = -1;
                return ident_block(cmd, data, len);
            }
            if (wvalue == 0 && key_mode == 1) {
                logf_("KEYREAD %d", key_block++);
                memset(data, 0, len);
                return len;
            }
            if (wvalue >= 2) {
                if (inject("READ"))
                    return LIBUSB_ERROR_IO;
                load_mem();
                bno = block_index(wvalue);
                if (bno < 0 || (bno + 1) * 1024 > MEMSZ || len > 1024)
                    return LIBUSB_ERROR_INVALID_PARAM;
                logf_("READ %d", bno);
                memcpy(data, &mem[bno * 1024], len);
                return len;
            }
            return LIBUSB_ERROR_PIPE;
        }
        return LIBUSB_ERROR_NOT_SUPPORTED;
    }
    if (request_type == 0x21) {
        switch (request) {
        case 0:                                     // DETACH
        case 4:                                     // CLRSTATUS
        case 6:                                     // ABORT
            return 0;
        case 1:                                     // DNLOAD
            if (wvalue >= 2) {
                if (inject("WRITE"))
                    return LIBUSB_ERROR_IO;
                load_mem();
                bno = block_index(wvalue);
                if (bno < 0 || (bno + 1) * 1024 > MEMSZ || len > 1024)
                    return LIBUSB_ERROR_INVALID_PARAM;
                logf_("WRITE %d", bno);
                memcpy(&mem[bno * 1024], data, len);
                return len;
            }
            if (len == 2) {
                logf_("CMD %02x %02x", data[0], data[1]);
                if (data[0] == 0xa2)
                    pending_ident = data[1];
                if (data[0] == 0xda && data[1] == 0x02 && inject("KEYCMD"))
                    return LIBUSB_ERROR_PIPE;
                if (data[0] == 0xda) {
                    key_mode = data[1];
                    key_block = 0;
                }
                return len;
            }
            if (len == 5 && data[0] == 0x41) {
                if (inject("ERASE"))
                    return LIBUSB_ERROR_IO;
                logf_("ERASE %02x%02x%02x%02x", data[4], data[3], data[2], data[1]);
                return len;
            }
            if (len == 5 && data[0] == 0x21)
                return len;                         // set address
            if (len == 1024 && key_mode == 2) {
                if (inject("KEYS"))
                    return LIBUSB_ERROR_IO;
                logf_("KEYS %d", key_block++);
                return len;
            }
            return LIBUSB_ERROR_PIPE;
        }
    }
    return LIBUSB_ERROR_NOT_SUPPORTED;
}

int LIBUSB_CALL libusb_init(libusb_context **ctx)
{
    *ctx = &the_context;
    return 0;
}

void LIBUSB_CALL libusb_exit(libusb_context *ctx)
{
    (void) ctx;
}

const char * LIBUSB_CALL libusb_strerror(int errcode)
{
    (void) errcode;
    return "fake libusb error";
}

ssize_t LIBUSB_CALL libusb_get_device_list(libusb_context *ctx,
    libusb_device ***list)
{
    static libusb_device *ptrs[5];
    int i, n = env_int("FAKEUSB_RADIOS", 1);

    (void) ctx;
    if (n < 0)
        n = 0;
    if (n > 4)
        n = 4;
    for (i=0; i<n; i++) {
        radios[i].index = i;
        ptrs[i] = &radios[i];
    }
    ptrs[n] = 0;
    *list = ptrs;
    return n;
}

void LIBUSB_CALL libusb_free_device_list(libusb_device **list, int unref)
{
    (void) list; (void) unref;
}

int LIBUSB_CALL libusb_get_device_descriptor(libusb_device *dev,
    struct libusb_device_descriptor *desc)
{
    (void) dev;
    memset(desc, 0, sizeof(*desc));
    desc->idVendor = 0x0483;
    desc->idProduct = 0xdf11;
    return 0;
}

int LIBUSB_CALL libusb_open(libusb_device *dev, libusb_device_handle **h)
{
    (void) dev;
    logf_("OPEN");
    pending_ident = -1;
    key_mode = 0;
    *h = &the_handle;
    return 0;
}

void LIBUSB_CALL libusb_close(libusb_device_handle *h)
{
    (void) h;
}

libusb_device_handle * LIBUSB_CALL libusb_open_device_with_vid_pid(
    libusb_context *ctx, uint16_t vid, uint16_t pid)
{
    (void) ctx; (void) vid; (void) pid;
    return 0;                       // no HID or serial radios here
}

int LIBUSB_CALL libusb_claim_interface(libusb_device_handle *h, int n)
{
    (void) h; (void) n;
    return 0;
}

int LIBUSB_CALL libusb_release_interface(libusb_device_handle *h, int n)
{
    (void) h; (void) n;
    return 0;
}

int LIBUSB_CALL libusb_kernel_driver_active(libusb_device_handle *h, int n)
{
    (void) h; (void) n;
    return 0;
}

int LIBUSB_CALL libusb_detach_kernel_driver(libusb_device_handle *h, int n)
{
    (void) h; (void) n;
    return 0;
}

//
// The asynchronous calls hid-libusb.c links against.  Never reached: no HID
// radio is ever found.
//
struct libusb_transfer * LIBUSB_CALL libusb_alloc_transfer(int iso_packets)
{
    (void) iso_packets;
    return calloc(1, sizeof(struct libusb_transfer));
}

int LIBUSB_CALL libusb_submit_transfer(struct libusb_transfer *t)
{
    (void) t;
    return LIBUSB_ERROR_NOT_SUPPORTED;
}

int LIBUSB_CALL libusb_cancel_transfer(struct libusb_transfer *t)
{
    (void) t;
    return 0;
}

void LIBUSB_CALL libusb_free_transfer(struct libusb_transfer *t)
{
    free(t);
}

int LIBUSB_CALL libusb_handle_events(libusb_context *ctx)
{
    (void) ctx;
    return LIBUSB_ERROR_NOT_SUPPORTED;
}
