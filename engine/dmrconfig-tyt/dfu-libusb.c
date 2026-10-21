/*
 * DFU routines for Linux and MacOS, via libusb-1.0.
 *
 * Copyright (C) 2018 Serge Vakulenko, KK6ABQ
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 *   1. Redistributions of source code must retain the above copyright notice,
 *      this list of conditions and the following disclaimer.
 *   2. Redistributions in binary form must reproduce the above copyright
 *      notice, this list of conditions and the following disclaimer in the
 *      documentation and/or other materials provided with the distribution.
 *   3. The name of the author may not be used to endorse or promote products
 *      derived from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR IMPLIED
 * WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO
 * EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
 * ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <libusb.h>
#include "util.h"
#include "radio.h"
#include "report.h"
#include "state.h"

//
// USB request types.
//
#define REQUEST_TYPE_TO_HOST    0xA1
#define REQUEST_TYPE_TO_DEVICE  0x21

enum {
    REQUEST_DETACH      = 0,
    REQUEST_DNLOAD      = 1,
    REQUEST_UPLOAD      = 2,
    REQUEST_GETSTATUS   = 3,
    REQUEST_CLRSTATUS   = 4,
    REQUEST_GETSTATE    = 5,
    REQUEST_ABORT       = 6,
};

enum {
    appIDLE                 = 0,
    appDETACH               = 1,
    dfuIDLE                 = 2,
    dfuDNLOAD_SYNC          = 3,
    dfuDNBUSY               = 4,
    dfuDNLOAD_IDLE          = 5,
    dfuMANIFEST_SYNC        = 6,
    dfuMANIFEST             = 7,
    dfuMANIFEST_WAIT_RESET  = 8,
    dfuUPLOAD_IDLE          = 9,
    dfuERROR                = 10,
};

typedef struct {
    unsigned    status       : 8;
    unsigned    poll_timeout : 24;
    unsigned    state        : 8;
    unsigned    string_index : 8;
} status_t;

static libusb_context *ctx = NULL;
static libusb_device_handle *dev;
static status_t status;

static int detach(int timeout)
{
    if (trace_flag) {
        printf("--- Send DETACH\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DETACH, timeout, 0, NULL, 0, 0);
    return error;
}

static int get_status()
{
    if (trace_flag) {
        printf("--- Send GETSTATUS [6]\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_GETSTATUS, 0, 0, (unsigned char*)&status, 6, 0);
    if (trace_flag && error >= 0) {
        printf("--- Recv ");
        print_hex((unsigned char*)&status, 6);
        printf("\n");
    }
    return error;
}

static int clear_status()
{
    if (trace_flag) {
        printf("--- Send CLRSTATUS\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_CLRSTATUS, 0, 0, NULL, 0, 0);
    return error;
}

static int get_state(int *pstate)
{
    unsigned char state;

    if (trace_flag) {
        printf("--- Send GETSTATE [1]\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_GETSTATE, 0, 0, &state, 1, 0);
    *pstate = state;
    if (trace_flag && error >= 0) {
        printf("--- Recv ");
        print_hex(&state, 1);
        printf("\n");
    }
    return error;
}

static int dfu_abort()
{
    if (trace_flag) {
        printf("--- Send ABORT\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_ABORT, 0, 0, NULL, 0, 0);
    return error;
}

//
// Bring the device to dfuIDLE.  Returns 0, or a libusb error with the state
// it happened in, for the callers that must not exit on a failure.
//
static int wait_idle_state;

static int try_wait_dfu_idle(void)
{
    int state, error;

    for (;;) {
        error = get_state(&state);
        wait_idle_state = -1;
        if (error < 0)
            return error;

        switch (state) {
        case dfuIDLE:
            return 0;

        case appIDLE:
            error = detach(1000);
            break;

        case dfuERROR:
            error = clear_status();
            break;

        case appDETACH:
        case dfuDNBUSY:
        case dfuMANIFEST_WAIT_RESET:
            usleep(100000);
            continue;

        default:
            error = dfu_abort();
            break;
        }

        if (error < 0) {
            wait_idle_state = state;
            return error;
        }
    }
}

static void wait_dfu_idle()
{
    int error = try_wait_dfu_idle();

    if (error == 0)
        return;
    if (wait_idle_state < 0)
        die(EXIT_TRANSFER, "%s: cannot get state: %d: %s",
            __func__, error, libusb_strerror(error));
    die(EXIT_TRANSFER, "%s: unexpected usb error in state=%d: %d: %s",
        __func__, wait_idle_state, error, libusb_strerror(error));
}

//
// A two-byte TYT command.  The _soft form returns the libusb error of the
// DNLOAD instead of exiting, for the unit identify blocks; on success both
// send exactly the same requests.
//
static int md380_command_soft(uint8_t a, uint8_t b)
{
    unsigned char cmd[2] = { a, b };

    if (trace_flag) {
        printf("--- Send DNLOAD [2] ");
        print_hex(cmd, 2);
        printf("\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, cmd, 2, 0);
    if (error < 0)
        return error;
    get_status();
    usleep(100000);
    wait_dfu_idle();
    return 0;
}

static void md380_command(uint8_t a, uint8_t b)
{
    int error = md380_command_soft(a, b);

    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot send command %02x %02x: %d: %s",
            __func__, a, b, error, libusb_strerror(error));
}

static void set_address(uint32_t address)
{
    unsigned char cmd[5] = { 0x21,
        (uint8_t)address,
        (uint8_t)(address >> 8),
        (uint8_t)(address >> 16),
        (uint8_t)(address >> 24),
    };

    if (trace_flag) {
        printf("--- Send DNLOAD [5] ");
        print_hex(cmd, 5);
        printf("\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, cmd, 5, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot send command: %d: %s",
            __func__, error, libusb_strerror(error));
    get_status();
    wait_dfu_idle();
}

static void erase_block(uint32_t address, int progress_flag)
{
    unsigned char cmd[5] = { 0x41,
        (uint8_t)address,
        (uint8_t)(address >> 8),
        (uint8_t)(address >> 16),
        (uint8_t)(address >> 24),
    };

    if (trace_flag) {
        printf("--- Send DNLOAD [5] ");
        print_hex(cmd, 5);
        printf("\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, cmd, 5, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot send command: %d: %s",
            __func__, error, libusb_strerror(error));
    get_status();
    wait_dfu_idle();

    if (progress_flag) {
        fprintf(stderr, "#");
        fflush(stderr);
    }
}

static const char *identify()
{
    static uint8_t data[64];

    md380_command(0xa2, 0x01);

    if (trace_flag) {
        printf("--- Send UPLOAD [64]\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_UPLOAD, 0, 0, data, 64, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot read data: %d: %s",
            __func__, error, libusb_strerror(error));
    if (trace_flag) {
        printf("--- Recv ");
        print_hex(data, 64);
        printf("\n");
    }
    get_status();
    return (const char*) data;
}

//
// Return the radio to normal mode and release it, unless a transfer to it
// broke off part-way: then the radio is left exactly as upstream leaves it,
// since restarting a half-written codeplug or key table is not a decision
// to take on the operator's behalf.  Runs on any die().  The reboot here
// never exits by itself; this is already the way out.
//
static void dfu_cleanup(void)
{
    if (! ctx)
        return;
    if (radio_state != RADIO_CODEPLUG_INCOMPLETE &&
        radio_state != RADIO_CODEPLUG_UNVERIFIED &&
        radio_state != RADIO_CONTACTS_INCOMPLETE &&
        radio_state != RADIO_KEYS_UNKNOWN &&
        dfu_try_reboot() < 0)
        report_warning("reboot_failed", "The radio did not take the restart "
            "command; it is still in programming mode. Switch it off and on.");
    dfu_close();
}

static void open_failed(int code, const char *what, int error)
{
    libusb_exit(ctx);
    ctx = 0;
    die(code, "%s: %d: %s", what, error, libusb_strerror(error));
}

//
// Open the USB device and claim the DFU interface.
// Return 0 when no such device is present.
//
// libusb_open_device_with_vid_pid() reports "not found" for a radio that is
// present but cannot be opened, which sends an operator looking for a cable
// fault when the fix is a udev rule.  So enumerate, and tell the three cases
// apart: nothing on the bus, no permission, or claimed by
// another program - typically a VM with USB passthrough.  Two radios at once
// are refused: these units share one USB serial number, so there is no way
// to say which of them a command would reach.
//
static int open_device(unsigned vid, unsigned pid)
{
    libusb_device **list, *found = 0;
    ssize_t n, i;
    int error, count = 0;

    error = libusb_init(&ctx);
    if (error < 0) {
        ctx = 0;
        die(EXIT_NO_RADIO, "libusb init failed: %d: %s",
            error, libusb_strerror(error));
    }

    n = libusb_get_device_list(ctx, &list);
    if (n < 0)
        open_failed(EXIT_NO_RADIO, "Cannot list USB devices", (int) n);
    for (i=0; i<n; i++) {
        struct libusb_device_descriptor desc;

        if (libusb_get_device_descriptor(list[i], &desc) < 0)
            continue;
        if (desc.idVendor == vid && desc.idProduct == pid) {
            if (! found)
                found = list[i];
            count++;
        }
    }
    if (count == 0) {
        libusb_free_device_list(list, 1);
        if (trace_flag) {
            fprintf(stderr, "Cannot find USB device %04x:%04x\n",
                vid, pid);
        }
        libusb_exit(ctx);
        ctx = 0;
        return 0;
    }
    if (count > 1) {
        libusb_free_device_list(list, 1);
        libusb_exit(ctx);
        ctx = 0;
        die(EXIT_MULTIPLE_RADIOS, "%d radios (%04x:%04x) are connected. "
            "Connect one at a time: they share a USB serial number, so "
            "there is no telling which one a command would reach.",
            count, vid, pid);
    }

    error = libusb_open(found, &dev);
    libusb_free_device_list(list, 1);
    if (error == LIBUSB_ERROR_ACCESS)
        open_failed(EXIT_NO_PERMISSION, "Radio found, but this user cannot "
            "open it (udev rule or group membership)", error);
    if (error == LIBUSB_ERROR_BUSY)
        open_failed(EXIT_BUSY, "Radio is in use by another program", error);
    if (error < 0)
        open_failed(EXIT_NO_RADIO, "Cannot open the radio", error);

    if (libusb_kernel_driver_active(dev, 0) == 1) {
        libusb_detach_kernel_driver(dev, 0);
    }

    error = libusb_claim_interface(dev, 0);
    if (error < 0) {
        int code = (error == LIBUSB_ERROR_ACCESS) ? EXIT_NO_PERMISSION :
                   (error == LIBUSB_ERROR_NO_DEVICE) ? EXIT_NO_RADIO :
                   EXIT_BUSY;

        libusb_close(dev);
        open_failed(code, (code == EXIT_BUSY) ?
            "Radio is in use by another program (a VM with USB passthrough "
            "holds it even when paused; shut the VM down)" :
            "Failed to claim USB interface", error);
    }
    report_set_cleanup(dfu_cleanup);
    return 1;
}

static void read_unit_ident(const uint8_t *a201, int a201len);
static void clear_unit_ident(void);

const char *dfu_init(unsigned vid, unsigned pid)
{
    if (! open_device(vid, pid))
        return 0;

    // Enter Programming Mode.
    wait_dfu_idle();
    md380_command(0x91, 0x01);

    // Get device identifier in a static buffer.
    const char *ident = identify();

    // The unit blocks, a2 02 to a2 07, so a codeplug session knows which
    // physical radio it is talking to (UI-SPEC F6: the roster maps a2 07 to
    // the Radio ID it read or wrote).  The CPS sends exactly this sequence
    // at the start of every codeplug read and write (USB captures of the stock CPS,
    // cap2), so the radio sees nothing it has not seen from the CPS.  Only
    // for the models with the Plus key table (captured on the MD-UV390; the
    // MD-UV380 is assumed to share it): other TYT radios get upstream's
    // session unchanged.  A block the radio will not give is not fatal.
    if (radio_is_privacy_capable(ident))
        read_unit_ident((const uint8_t*) ident, 64);
    else
        clear_unit_ident();

    // Zero address.
    set_address(0x00000000);

    return ident;
}

void dfu_close()
{
    if (ctx) {
        libusb_release_interface(dev, 0);
        libusb_close(dev);
        libusb_exit(ctx);
        ctx = 0;
    }
}

void dfu_erase(unsigned start, unsigned finish)
{
    report_phase("erase");

    // Enter Programming Mode.
    get_status();
    wait_dfu_idle();
    md380_command(0x91, 0x01);
    usleep(100000);

    // From the first erase command, the codeplug (or, from 0x200000, the
    // contacts database) is incomplete until the write finishes.
    radio_state = (start == 0) ? RADIO_CODEPLUG_INCOMPLETE :
                                 RADIO_CONTACTS_INCOMPLETE;

    if (start == 0) {
        // Erase 256kbytes of configuration memory, and for the larger
        // radios 768kbytes of extended configuration memory.  Same sectors
        // in the same order as upstream; only the progress report is new.
        static const uint32_t sector[] = {
            0x00000000, 0x00010000, 0x00020000, 0x00030000,
            0x00110000, 0x00120000, 0x00130000, 0x00140000,
            0x00150000, 0x00160000, 0x00170000, 0x00180000,
            0x00190000, 0x001a0000, 0x001b0000, 0x001c0000,
            0x001d0000,
        };
        int i, nsect = (finish > 256*1024) ? 17 : 4;

        for (i=0; i<nsect; i++) {
            erase_block(sector[i], 1);
            report_tick(i + 1, nsect);
        }
    } else {
        // Erase callsign database.
        int addr;

        for (addr=start; addr<finish; addr+=0x00010000) {
            erase_block(addr, (addr & 0x00070000) == 0x00070000);
        }
    }

    // Zero address.
    set_address(0x00000000);
}

void dfu_read_block(int bno, uint8_t *data, int nbytes)
{
    if (bno >= 256 && bno < 2048)
        bno += 832;

    if (trace_flag) {
        printf("--- Send UPLOAD [%d]\n", nbytes);
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_UPLOAD, bno+2, 0, data, nbytes, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot read block %d, nbytes = %d: %d: %s",
            __func__, bno, nbytes, error, libusb_strerror(error));
    if (error != nbytes)
        die(EXIT_TRANSFER, "%s: short read of block %d: asked %d, got %d",
            __func__, bno, nbytes, error);
    if (trace_flag > 1) {
        printf("--- Recv ");
        print_hex(data, nbytes);
        printf("\n");
    }
    get_status();
}

void dfu_write_block(int bno, uint8_t *data, int nbytes)
{
    if (bno >= 256 && bno < 2048)
        bno += 832;

    if (trace_flag) {
        printf("--- Send DNLOAD [%d] ", nbytes);
        if (trace_flag > 1)
            print_hex(data, nbytes);
        printf("\n");
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, bno+2, 0, data, nbytes, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot write block %d, nbytes = %d: %d: %s",
            __func__, bno, nbytes, error, libusb_strerror(error));

    get_status();
    wait_dfu_idle();
}

//
// The closing 91 05, without exiting on a failure: returns 0 or a libusb
// error.  Used after a write that has already landed, where a failed
// restart must not hide the result (or the ledger line), and in the cleanup.
//
int dfu_try_reboot(void)
{
    unsigned char cmd[2] = { 0x91, 0x05 };
    int error;

    if (! ctx)
        return 0;
    if (trace_flag) {
        printf("--- Send DNLOAD [2] ");
        print_hex(cmd, 2);
        printf("\n");
    }
    error = try_wait_dfu_idle();
    if (error < 0)
        return error;
    error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, cmd, 2, 0);
    if (error < 0)
        return error;
    get_status();
    return 0;
}

void dfu_reboot()
{
    unsigned char cmd[2] = { 0x91, 0x05 };

    if (! ctx)
        return;
    if (trace_flag) {
        printf("--- Send DNLOAD [2] ");
        print_hex(cmd, 2);
        printf("\n");
    }
    wait_dfu_idle();
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, cmd, 2, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot send command: %d: %s",
            __func__, error, libusb_strerror(error));
    get_status();
}

//
// ---------------------------------------------------------------------------
// Privacy / AES key table session.  TYT MD-UV390 Plus, Phase 4.1.
// ---------------------------------------------------------------------------
//
// Replays the CPS v2.41 "Write privacy" and "Read privacy" operations as
// captured from the stock CPS; see TYTcps's docs/dev/protocol.md.  Everything
// below is taken from USB captures of its key write and key read, not guessed.
//
// How this differs from the codeplug path:
//   - There is no erase (0x41) and no set-address (0x21).  At all.
//   - The vendor selector 0xda 0x01 / 0xda 0x02 chooses the privacy table.
//   - Every data DNLOAD carries wValue = 0, so the blocks are positional and
//     must be sent strictly in file order.  dfu_write_block() cannot be used:
//     it puts a block number in wValue.
//   - Each UPLOAD is followed by a DFU_ABORT.
//
// The radio answers dfuDNBUSY and then errors to state 10 (dfuERROR, status
// 0x0e) after most requests.  That is normal.  wait_dfu_idle() clears it,
// which is exactly what the CPS does; a replay must never abort on it.
//
#define PRIV_NBLOCKS    20
#define PRIV_BLOCK      1024
#define PRIV_TABLE_SIZE (PRIV_NBLOCKS * PRIV_BLOCK)     // 20480 = a .dec file

//
// Vendor identify blocks, with the UPLOAD lengths the CPS asks for.
// a2 03 and a2 07 differ between units; a2 01 and the USB iSerial do not.
//
static const struct {
    uint8_t cmd;
    int     len;
} priv_ident_req[] = {
    { 0x01, 32 },       // model string, "MD-UV390" on the 5W Plus
    { 0x02,  4 },       // firmware version
    { 0x03, 24 },       // ASCII serial number - PER UNIT
    { 0x04,  8 },       // unidentified, all 0xff on the 5W Plus
    { 0x07, 16 },       // unidentified - PER UNIT, used as the unit guard
};
#define PRIV_NIDENT ((int) (sizeof(priv_ident_req) / sizeof(priv_ident_req[0])))

static uint8_t priv_ident[PRIV_NIDENT][32];
static int priv_ident_len[PRIV_NIDENT];

//
// UPLOAD with wValue = 0, then the CPS's trailing ABORT.
//
//
// The _soft form returns -1 for a failed or short UPLOAD, after bringing the
// device back to idle, instead of exiting.  On success both send exactly
// the same requests: UPLOAD, GETSTATUS, back to idle, ABORT.
//
static int priv_upload_soft(uint8_t *data, int nbytes, int *got)
{
    if (trace_flag) {
        printf("--- Send UPLOAD [%d]\n", nbytes);
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_UPLOAD, 0, 0, data, nbytes, 0);
    *got = error;
    if (error != nbytes) {
        wait_dfu_idle();
        return -1;
    }
    if (trace_flag > 1) {
        printf("--- Recv ");
        print_hex(data, nbytes);
        printf("\n");
    }
    get_status();
    wait_dfu_idle();
    dfu_abort();
    return 0;
}

static void priv_upload(uint8_t *data, int nbytes)
{
    if (trace_flag) {
        printf("--- Send UPLOAD [%d]\n", nbytes);
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_HOST,
        REQUEST_UPLOAD, 0, 0, data, nbytes, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot read %d bytes: %d: %s",
            __func__, nbytes, error, libusb_strerror(error));
    if (error != nbytes)
        die(EXIT_TRANSFER, "%s: short read: asked %d, got %d",
            __func__, nbytes, error);
    if (trace_flag > 1) {
        printf("--- Recv ");
        print_hex(data, nbytes);
        printf("\n");
    }
    get_status();
    wait_dfu_idle();
    dfu_abort();
}

//
// DNLOAD a data block with wValue = 0.  Positional: order is the only
// addressing this path has.
//
static void priv_dnload(const uint8_t *data, int nbytes)
{
    // This path only ever carries the key table: never print the payload,
    // at any trace level.  A trace is something people paste into a bug
    // report.
    if (trace_flag) {
        printf("--- Send DNLOAD [%d] (key data not shown)\n", nbytes);
    }
    int error = libusb_control_transfer(dev, REQUEST_TYPE_TO_DEVICE,
        REQUEST_DNLOAD, 0, 0, (unsigned char*) data, nbytes, 0);
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot write %d bytes: %d: %s",
            __func__, nbytes, error, libusb_strerror(error));
    get_status();
    wait_dfu_idle();
}

//
// One unit identify block, a2 02 to a2 07.  A block the radio will not give
// (command refused, UPLOAD failed or short) is left empty rather than ending
// the session: the unit is then "unreadable", which a key write refuses and
// a codeplug session reports as a warning.  A device that cannot even get
// back to idle afterwards still ends the session, as transfer_failed.
//
static void read_ident_block(int i)
{
    int error, got = 0;

    memset(priv_ident[i], 0, sizeof(priv_ident[i]));
    priv_ident_len[i] = 0;
    error = md380_command_soft(0xa2, priv_ident_req[i].cmd);
    if (error < 0) {
        report_warning("unit_block_unreadable", "Unit block a2 %02x: command "
            "refused: %d: %s", priv_ident_req[i].cmd, error,
            libusb_strerror(error));
        wait_dfu_idle();
        return;
    }
    if (priv_upload_soft(priv_ident[i], priv_ident_req[i].len, &got) < 0) {
        report_warning("unit_block_unreadable", "Unit block a2 %02x: read %d "
            "of %d bytes", priv_ident_req[i].cmd, got < 0 ? 0 : got,
            priv_ident_req[i].len);
        memset(priv_ident[i], 0, sizeof(priv_ident[i]));
        return;
    }
    priv_ident_len[i] = priv_ident_req[i].len;
}

//
// Open a privacy session: 0x91 0x01 then the five a2 identify blocks, in the
// CPS's order and with the CPS's lengths.  Returns the model string, or 0
// when no radio is present.  Note there is deliberately no set_address()
// here: the capture has none, and this session never touches the codeplug.
//
const char *dfu_privacy_init(unsigned vid, unsigned pid)
{
    int i;

    if (! open_device(vid, pid))
        return 0;

    wait_dfu_idle();
    md380_command(0x91, 0x01);

    // a2 01, the model, is required.  The unit blocks after it are read
    // with read_ident_block(): one the radio will not give leaves that
    // block empty, and the caller decides (a key write refuses, exit 14).
    memset(priv_ident[0], 0, sizeof(priv_ident[0]));
    md380_command(0xa2, priv_ident_req[0].cmd);
    priv_upload(priv_ident[0], priv_ident_req[0].len);
    priv_ident_len[0] = priv_ident_req[0].len;
    for (i=1; i<PRIV_NIDENT; i++)
        read_ident_block(i);

    // a2 01 is a NUL-terminated model string in a buffer we zeroed.
    return (const char*) priv_ident[0];
}

//
// Codeplug session: a2 01 was already read by identify(), with upstream's
// 64-byte UPLOAD, and is copied here; then a2 02, 03, 04 and 07 exactly as
// dfu_privacy_init() reads them.
//
static void clear_unit_ident(void)
{
    memset(priv_ident, 0, sizeof(priv_ident));
    memset(priv_ident_len, 0, sizeof(priv_ident_len));
}

static void read_unit_ident(const uint8_t *a201, int a201len)
{
    int i;

    memset(priv_ident[0], 0, sizeof(priv_ident[0]));
    memcpy(priv_ident[0], a201,
        a201len < (int) sizeof(priv_ident[0]) ? a201len : (int) sizeof(priv_ident[0]));
    priv_ident_len[0] = priv_ident_req[0].len;

    for (i=1; i<PRIV_NIDENT; i++)
        read_ident_block(i);
}

//
// The unit's a2 07 block as hex, and its a2 03 serial as text, from the
// identify blocks of the current session.  Empty when not read, or when the
// block is all 0x00 or all 0xff, which would be no identity at all.
//
const char *unit_a207(void)
{
    static char buf[2 * sizeof(priv_ident[0]) + 1];
    int len = 0, i, n00 = 0, nff = 0;
    const unsigned char *p = dfu_privacy_ident(0x07, &len);

    buf[0] = 0;
    if (! p || len <= 0)
        return buf;
    for (i=0; i<len; i++) {
        if (p[i] == 0x00) n00++;
        if (p[i] == 0xff) nff++;
    }
    if (n00 == len || nff == len)
        return buf;
    for (i=0; i<len; i++)
        sprintf(buf + i*2, "%02x", p[i]);
    return buf;
}

const char *unit_serial(void)
{
    static char buf[sizeof(priv_ident[0]) + 1];
    int len = 0, i, n = 0;
    const unsigned char *p = dfu_privacy_ident(0x03, &len);

    buf[0] = 0;
    if (! p)
        return buf;
    for (i=0; i<len && n < (int) sizeof(buf) - 1; i++) {
        if (p[i] >= 32 && p[i] < 127)
            buf[n++] = p[i];
        else if (p[i] == 0)
            break;
    }
    buf[n] = 0;
    return buf;
}

//
// Firmware version from a2 02.  Four bytes: a letter, then six BCD digits,
// e.g. 53 11 90 38 = S119.038 (the 5W Plus) or 53 21 90 43 = S219.043 (the
// 10W).  Anything else is shown as hex.
//
const char *unit_firmware(void)
{
    static char buf[2 * sizeof(priv_ident[0]) + 1];
    int len = 0, i, bcd = 1;
    const unsigned char *p = dfu_privacy_ident(0x02, &len);

    buf[0] = 0;
    if (! p || len != 4)
        return buf;
    for (i=1; i<4; i++)
        if ((p[i] >> 4) > 9 || (p[i] & 15) > 9)
            bcd = 0;
    if (p[0] >= 'A' && p[0] <= 'Z' && bcd) {
        snprintf(buf, sizeof(buf), "%c%x%x%x.%x%x%x", p[0],
            p[1] >> 4, p[1] & 15, p[2] >> 4, p[2] & 15, p[3] >> 4, p[3] & 15);
        return buf;
    }
    for (i=0; i<len; i++)
        sprintf(buf + i*2, "%02x", p[i]);
    return buf;
}

//
// Return the a2 <acmd> identify block read by dfu_privacy_init().
// Returns 0 for a command this session does not read.
//
const unsigned char *dfu_privacy_ident(int acmd, int *len)
{
    int i;

    for (i=0; i<PRIV_NIDENT; i++) {
        if (priv_ident_req[i].cmd == acmd) {
            if (len)
                *len = priv_ident_len[i];
            return priv_ident[i];
        }
    }
    if (len)
        *len = 0;
    return 0;
}

//
// Read the privacy table: da 01, then 20 UPLOADs of 1024 bytes.
// The key fields come back all zero by design - see
// (protocol.md, "No readback").  Types and names do read back.
//
void dfu_privacy_read_table(unsigned char *data, int nbytes)
{
    int i;

    if (nbytes != PRIV_TABLE_SIZE)
        die(EXIT_KEYFILE, "%s: table is %d bytes, not %d.",
            __func__, nbytes, PRIV_TABLE_SIZE);
    md380_command(0xda, 0x01);

    for (i=0; i<PRIV_NBLOCKS; i++) {
        priv_upload(&data[i * PRIV_BLOCK], PRIV_BLOCK);

        if (! trace_flag) {
            fprintf(stderr, "#");
            fflush(stderr);
        }
        report_tick(i + 1, PRIV_NBLOCKS);
    }
}

//
// Write the privacy table: da 02, then 20 DNLOADs of 1024 bytes in file
// order.  The whole 20480-byte table goes every time - there is no way to
// write one slot, and the radio will not give key bytes back, so the caller
// must supply a complete table.
//
void dfu_privacy_write_table(const unsigned char *data, int nbytes)
{
    int i, error, was;

    if (nbytes != PRIV_TABLE_SIZE)
        die(EXIT_KEYFILE, "%s: table is %d bytes, not %d.",
            __func__, nbytes, PRIV_TABLE_SIZE);
    // From the moment the radio is told a key table is coming, its keys
    // are in an unknown state until the last block lands.
    was = radio_state;
    radio_state = RADIO_KEYS_UNKNOWN;
    error = md380_command_soft(0xda, 0x02);
    if (error == LIBUSB_ERROR_PIPE) {
        // The radio refused the command itself (a stall), before any key
        // byte was sent: its keys are as they were.  Only the MD-UV390
        // Plus takes a key table; a non-Plus model that identifies the
        // same way may refuse it here.
        radio_state = was;
        die(EXIT_KEYS_REFUSED, "The radio did not accept the key table: it refused "
            "the command before any key was sent, so its keys are as they were. "
            "It may not be an MD-UV390 Plus: only the Plus takes AES keys.");
    }
    if (error < 0)
        die(EXIT_TRANSFER, "%s: cannot send command da 02: %d: %s",
            __func__, error, libusb_strerror(error));

    for (i=0; i<PRIV_NBLOCKS; i++) {
        priv_dnload(&data[i * PRIV_BLOCK], PRIV_BLOCK);

        if (! trace_flag) {
            fprintf(stderr, "#");
            fflush(stderr);
        }
        report_tick(i + 1, PRIV_NBLOCKS);
    }
    radio_state = RADIO_KEYS_WRITTEN;
}
