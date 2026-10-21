/*
 * Configuration Utility for DMR radios.
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
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <stdarg.h>
#include <errno.h>
#include <sys/stat.h>
#include "radio.h"
#include "util.h"
#include "report.h"
#include "state.h"

static struct {
    char *ident;
    radio_device_t *device;
} radio_tab[] = {
    { "DR780",      &radio_md380 },     // TYT MD-380, Retevis RT3, RT8
    { "MD390",      &radio_md390 },     // TYT MD-390
    { "MD-UV380",   &radio_uv380 },     // TYT MD-UV380
    { "MD-UV390",   &radio_uv390 },     // TYT MD-UV390, Retevis RT3S
    { "2017",       &radio_md2017 },    // TYT MD-2017, Retevis RT82
    { "MD9600",     &radio_md9600 },    // TYT MD-9600
    { "BF-5R",      &radio_rd5r },      // Baofeng RD-5R, TD-5R
    { "1801",       &radio_dm1801 },    // Baofeng DM-1801
    { "DM-1701",    &radio_rt84 },      // Baofeng DM-1701, Retevis RT84
    { "MD-760P",    &radio_gd77 },      // Radioddity GD-77, version 3.1.1 and later
    { "D868UVE",    &radio_d868uv },    // Anytone AT-D868UV
    { "D878UV2",    &radio_d878uv2 },   // Anytone AT-D878UV2
    { "D878UV",     &radio_d878uv },    // Anytone AT-D878UV
    { "D6X2UV",     &radio_dmr6x2 },    // BTECH DMR-6x2
    { "ZD3688",     &radio_d900 },      // Zastone D900
    { "TP660",      &radio_dp880 },     // Zastone DP880
    { "ZN><:",      &radio_rt27d },     // Radtel RT-27D
    { 0, 0 }
};

unsigned char radio_mem [1024*1024*2];  // Radio memory contents, up to 2 Mbytes
unsigned char conf_mem_before [1024*1024*2]; // radio_mem as it was before the config
int radio_progress;                     // Read/write progress counter

static radio_device_t *device;          // Device-dependent interface

//
// What the attached radio identified as.  'device' can change after the
// connect: -w loads an image file, which picks a device by file size, and an
// 851968-byte file always comes back as the MD-UV380.  Anything that depends
// on the radio actually attached - the volatile-byte exemption in the verify
// - must use this instead.
//
static radio_device_t *connected;
static int dfu_session;                 // the radio was opened via DFU

const unsigned char *radio_fleet_keys;  // Fleet .dec from -F, or null

int radio_verify_volatile;              // volatile bytes ignored by the verify
unsigned radio_verify_ndiff;            // bytes that failed the verify
unsigned radio_verify_first;            // first of them

//
// Close the serial port.
//
void radio_disconnect()
{
    fprintf(stderr, "Close device.\n");

    // Restore the normal radio mode.
    dfu_reboot();
    dfu_close();
    hid_close();
    serial_close();
}

//
// Close after a write that has landed, or a read that has completed.  The
// restart (91 05) failing then must not turn a written and verified radio,
// or two agreeing reads, into a transfer failure: it is a warning, and the
// operator power-cycles.
//
void radio_disconnect_after_write()
{
    int error;

    fprintf(stderr, "Close device.\n");
    error = dfu_try_reboot();
    if (error < 0)
        report_warning("reboot_failed", "The radio did not take the restart "
            "command (%d). What was written is in place; switch the radio off "
            "and on to leave programming mode.", error);
    dfu_close();
    hid_close();
    serial_close();
}

//
// Print a generic information about the device.
//
void radio_print_version(FILE *out)
{
    device->print_version(device, out);
}

//
// Connect to the radio and identify the type of device.
//
void radio_connect()
{
    const char *ident;
    int i;

    report_phase("connect");

    // Try TYT MD family.
    ident = dfu_init(0x0483, 0xdf11);
    dfu_session = (ident != 0);
    if (! ident) {
        // Try RD-5R, DM-1801 and GD-77.
        if (hid_init(0x15a2, 0x0073) >= 0)
            ident = hid_identify();
    }
    if (! ident) {
        // Try Anytone family.
        if (serial_init(0x28e9, 0x018a) >= 0)
            ident = serial_identify();
    }
    if (! ident)
        die(EXIT_NO_RADIO, "No radio detected. Check your USB cable, and that "
            "the radio is switched on.");

    // An image file loaded earlier may have set a device; the radio decides.
    device = 0;
    for (i=0; radio_tab[i].ident; i++) {
        if (strcasecmp(ident, radio_tab[i].ident) == 0) {
            device = radio_tab[i].device;
            break;
        }
    }
    if (! device)
        die(EXIT_UNSUPPORTED, "Unrecognized radio '%s'.", ident);
    connected = device;
    fprintf(stderr, "Connect to %s.\n", device->name);
    radio_report_unit(ident);
}

//
// The "unit" event: which physical radio this session is talking to.
//
void radio_report_unit(const char *ident)
{
    const char *a207 = dfu_session ? unit_a207() : "";
    const char *serial = dfu_session ? unit_serial() : "";
    const char *fw = dfu_session ? unit_firmware() : "";

    if (dfu_session)
        fprintf(stderr, "Unit: a207=%s serial=%s firmware=%s\n",
            *a207 ? a207 : "(unreadable)", *serial ? serial : "-",
            *fw ? fw : "-");
    ev_begin("unit");
    ev_str("model", ident);
    ev_str("device", device ? device->name : 0);
    ev_str("a207", *a207 ? a207 : 0);
    ev_str("serial", *serial ? serial : 0);
    ev_str("firmware", *fw ? fw : 0);
    ev_bool("privacy_capable", radio_is_privacy_capable(ident));
    ev_end();
    if (dfu_session && ! *a207 && radio_is_privacy_capable(ident))
        report_warning("unit_unreadable", "The radio's a2 07 unit block came "
            "back empty, so the roster cannot be updated for this session.");
}

//
// Record this session in the roster: the unit, and the Radio ID that was
// read from it or written to it (null when not known).
//
void radio_roster_seen(long radio_id, int wrote_codeplug)
{
    char id[32];
    const char *a207 = dfu_session ? unit_a207() : "";

    if (! *a207)
        return;
    if (radio_id >= 0)
        snprintf(id, sizeof(id), "%ld", radio_id);
    roster_seen(a207, radio_id >= 0 ? id : 0, wrote_codeplug);
}

//
// --expect-unit.  A program that identified a radio and then
// writes to it cannot tell, from outside, that the radio on the cable is
// still that one: the radio leaves the bus after every session and comes
// back 2.7 s later, and another radio plugged in during that gap looks the
// same.  So it names the unit it means, and the write refuses any other,
// right after connecting and before anything is read, erased or sent.
//
const char *radio_expect_unit;

void radio_require_unit(const char *a207)
{
    if (! radio_expect_unit)
        return;
    if (! a207 || ! *a207)
        die(EXIT_UNIT_UNREADABLE, "Cannot read the a2 07 unit block, so this "
            "radio cannot be confirmed as unit %s. Nothing was written. "
            "Reconnect and try again.", radio_expect_unit);
    if (strcasecmp(a207, radio_expect_unit) != 0) {
        fail_begin(EXIT_UNIT_MISMATCH);
        ev_str("expected", radio_expect_unit);
        ev_str("a207", a207);
        fail_end("This is unit %s, not unit %s that the write was meant "
            "for. Nothing was written.", a207, radio_expect_unit);
    }
}

void radio_check_unit(void)
{
    radio_require_unit(dfu_session ? unit_a207() : "");
}

//
// -w: the image file must be for the kind of radio attached.  The file picks
// its device by size, so an MD-380 image would otherwise be written to an
// MD-UV390 with the MD-380's block map.
//
void radio_check_image_fits(void)
{
    if (connected && device &&
        uv380_is_family(connected) != uv380_is_family(device))
        die(EXIT_IMAGE, "This codeplug file is for a %s, but the radio is a "
            "%s. Nothing was written.", device->name, connected->name);
}

//
// Warnings about the codeplug in memory that a read or open should show.
//
void radio_privacy_warnings(void)
{
    if (device && uv380_is_family(device))
        uv380_report_privacy_warnings();
}

//
// Radio ID and name stored in the image in memory, for the layouts this fork
// knows (-1 / empty otherwise).
//
long radio_image_id(void)
{
    if (! device || ! uv380_is_family(device))
        return -1;
    return uv380_radio_id(radio_mem);
}

void radio_image_name(char *buf, int size)
{
    buf[0] = 0;
    if (device && uv380_is_family(device))
        uv380_radio_name(radio_mem, buf, size);
}

int radio_image_size(void)
{
    if (device && uv380_is_family(device))
        return uv380_image_size();
    return 0;
}

//
// List all supported radios.
//
void radio_list()
{
    int i;

    printf("Supported radios:\n");
    for (i=0; radio_tab[i].ident; i++) {
        printf("    %s\n", radio_tab[i].device->name);
    }
}

//
// Read the device twice and require the two reads to agree.
//
// A dmrconfig read can SILENTLY return corrupt data: whole 1024-byte DFU
// transfers come back wrong and the tool still exits 0 (seen on the bench;
// "Read reliability").  The project rule is to read twice and compare, but an
// operator can only do that for -r.  The -c config path reads the radio
// INTERNALLY, applies the config to whatever came back, and writes the result
// to flash - so a corrupt read becomes a corrupt codeplug, with no chance to
// intervene.
//
// Observed on a test radio: one upstream -c run read block 0
// as 0x03 x 1024 and part of the settings region as 0xff, differing from the
// radio's true contents by 4922 bytes, and wrote 1135 bytes of that back.
// The image the config path had built was provably correct; the read was not.
//
// Hence: any read that is going to be written back gets verified here.
//
int radio_download_twice(unsigned *pndiff, unsigned *pfirst)
{
    // Whole-array compare, so this needs no per-device image size. The tail
    // beyond the device's image is untouched by both reads and compares equal.
    static unsigned char first_read[sizeof(radio_mem)];
    unsigned i, ndiff = 0, firstdiff = 0;

    report_phase("read1");
    radio_download();
    memcpy(first_read, radio_mem, sizeof(radio_mem));

    report_phase("read2");
    if (! trace_flag) {
        fprintf(stderr, "Verify read: ");
        fflush(stderr);
    }
    radio_progress = 0;
    device->download(device);
    if (! trace_flag)
        fprintf(stderr, " done.\n");

    report_phase("compare");
    if (memcmp(first_read, radio_mem, sizeof(radio_mem)) != 0) {
        for (i=0; i<sizeof(radio_mem); i++) {
            if (first_read[i] != radio_mem[i]) {
                if (! ndiff)
                    firstdiff = i;
                ndiff++;
            }
        }
    }
    if (pndiff)
        *pndiff = ndiff;
    if (pfirst)
        *pfirst = firstdiff;
    return ndiff == 0;
}

void radio_download_verified()
{
    unsigned ndiff, firstdiff;

    if (! radio_download_twice(&ndiff, &firstdiff)) {
        fprintf(stderr, "\nTWO READS OF THIS RADIO DISAGREE: %u bytes, "
            "first at 0x%05x.\n", ndiff, firstdiff);
        fprintf(stderr, "One of them is corrupt, and writing it back would "
            "corrupt the codeplug.\n");
        fail_begin(EXIT_READS_DISAGREE);
        ev_int("bytes", ndiff);
        ev_int("first", firstdiff);
        fail_end("Two reads of this radio disagree (%u bytes, first at "
            "0x%05x). Nothing has been written. Unplug the radio, plug it "
            "back in and try again.", ndiff, firstdiff);
    }
}

//
// Read back what we just wrote and check it landed.
//
// Returns 1 on success.  A single disagreeing read is retried once, because a
// corrupt READ is at least as likely as a corrupt write and must not be
// reported as a bad write.
//
int radio_verify_upload()
{
    static unsigned char written[sizeof(radio_mem)];
    int attempt;

    memcpy(written, radio_mem, sizeof(radio_mem));

    for (attempt=1; attempt<=2; attempt++) {
        unsigned i, ndiff = 0, nvol = 0, firstdiff = 0;

        report_phase(attempt == 1 ? "verify" : "verify_retry");
        if (! trace_flag) {
            fprintf(stderr, "Verify write: ");
            fflush(stderr);
        }
        radio_progress = 0;
        device->download(device);
        if (! trace_flag)
            fprintf(stderr, " done.\n");

        for (i=0; i<sizeof(radio_mem); i++) {
            if (written[i] == radio_mem[i])
                continue;
            // 0x2F004 and 0x2F006 change by themselves through normal radio
            // use. They did not move across any write
            // observed in this project, so they are counted and named rather
            // than ignored. Only on the MD-UV390: on other radios this address
            // is ordinary codeplug data and a difference there is a real one.
            if (connected == &radio_uv390 && (i == 0x2F004 || i == 0x2F006)) {
                nvol++;
                continue;
            }
            if (! ndiff)
                firstdiff = i;
            ndiff++;
        }
        memcpy(radio_mem, written, sizeof(radio_mem));

        if (! ndiff) {
            radio_state = RADIO_CODEPLUG_WRITTEN;
            radio_verify_volatile = nvol;
            if (nvol)
                fprintf(stderr, "Write verified (%u volatile byte%s at "
                    "0x2F004/0x2F006 differ, which is normal).\n",
                    nvol, nvol == 1 ? "" : "s");
            else
                fprintf(stderr, "Write verified: the radio matches the image "
                    "byte for byte.\n");
            return 1;
        }
        if (attempt == 1) {
            fprintf(stderr, "Read-back differs in %u bytes, first at 0x%05x. "
                "Re-reading before\njudging, since a corrupt read looks the "
                "same as a bad write.\n", ndiff, firstdiff);
            continue;
        }
        radio_state = RADIO_CODEPLUG_DIFFERS;
        radio_verify_ndiff = ndiff;
        radio_verify_first = firstdiff;
        fprintf(stderr, "\nWRITE DID NOT VERIFY: %u bytes differ, first at "
            "0x%05x, on two reads.\n", ndiff, firstdiff);
        fprintf(stderr, "The radio does NOT hold the image you asked for. "
            "Do not put it in service.\n");
        fprintf(stderr, "Write it again, and if that fails, restore a known "
            "good image with -w.\n");
        return 0;
    }
    return 0;
}

//
// Read firmware image from the device.
//
void radio_download()
{
    radio_progress = 0;
    if (! trace_flag) {
        fprintf(stderr, "Read device: ");
        fflush(stderr);
    }

    device->download(device);

    if (! trace_flag)
        fprintf(stderr, " done.\n");
}

//
// Write firmware image to the device.
//
void radio_upload(int cont_flag)
{
    // Check for compatibility.
    if (! device->is_compatible(device))
        die(EXIT_IMAGE, "Incompatible image - cannot upload.");
    radio_progress = 0;
    if (! trace_flag) {
        fprintf(stderr, "Write device: ");
        fflush(stderr);
    }
    device->upload(device, cont_flag);

    if (! trace_flag)
        fprintf(stderr, " done.\n");

    // Written, not yet verified: if the verify read fails, the radio's
    // contents are unknown, not "incomplete".
    radio_state = RADIO_CODEPLUG_UNVERIFIED;
}

//
// Read firmware image from the binary file.
//
void radio_read_image(const char *filename)
{
    FILE *img;
    struct stat st;
    char ident[8];

    fprintf(stderr, "Read codeplug from file '%s'.\n", filename);
    img = fopen(filename, "rb");
    if (! img)
        die(EXIT_IO, "%s: %s", filename, strerror(errno));

    // Guess device type by file size.
    if (fstat(fileno(img), &st) < 0)
        die(EXIT_IO, "%s: %s", filename, strerror(errno));
    switch (st.st_size) {
    case 851968:
    case 852533:
        device = &radio_uv380;
        break;
    case 262144:
    case 262709:
        device = &radio_md380;
        break;
    case 1606528:
        if (fread(ident, 1, 8, img) != 8)
            die(EXIT_IO, "%s: Cannot read header.", filename);
        fseek(img, 0, SEEK_SET);
        if (memcmp(ident, "D868UVE", 7) == 0) {
            device = &radio_d868uv;
        } else if (memcmp(ident, "D878UV2", 7) == 0) {
            device = &radio_d878uv2;
        } else if (memcmp(ident, "D878UV", 6) == 0) {
            device = &radio_d878uv;
        } else if (memcmp(ident, "D6X2UV", 6) == 0) {
            device = &radio_dmr6x2;
        } else {
            die(EXIT_IMAGE, "%s: Unrecognized header '%.6s'",
                filename, ident);
        }
        break;
    case 131072:
        if (fread(ident, 1, 8, img) != 8)
            die(EXIT_IO, "%s: Cannot read header.", filename);
        if (memcmp(ident, "BF-5R", 5) == 0) {
            device = &radio_rd5r;
        } else if (memcmp(ident, "MD-760P", 7) == 0) {
            device = &radio_gd77;
        } else if (memcmp(ident, "1801", 4) == 0) {
            device = &radio_dm1801;
        } else if (memcmp(ident, "MD-760", 6) == 0) {
            die(EXIT_IMAGE, "Old Radioddity GD-77 v2.6 image not supported!");
        } else {
            die(EXIT_IMAGE, "%s: Unrecognized header '%.6s'",
                filename, ident);
        }
        fseek(img, 0, SEEK_SET);
        break;
    default:
        die(EXIT_IMAGE, "%s: Unrecognized file size %u bytes. This is not a "
            "codeplug image.", filename, (int) st.st_size);
    }

    device->read_image(device, img);
    fclose(img);
}

//
// Save firmware image to the binary file.
//
void radio_save_image(const char *filename)
{
    FILE *img;

    fprintf(stderr, "Write codeplug to file '%s'.\n", filename);
    img = fopen(filename, "wb");
    if (! img)
        die(EXIT_IO, "%s: %s", filename, strerror(errno));
    device->save_image(device, img);
    if (ferror(img) | fclose(img))
        die(EXIT_IO, "%s: write failed: %s", filename, strerror(errno));
}


//
// -------------------------------------------------------------------------
// Where a configuration problem is.
// -------------------------------------------------------------------------
//
// radio_parse_config() keeps the current line, table and row; the device
// parsers say which column was bad with conf_error().  The error event
// carries all of it, so TYTcps can put the message on the exact cell.
//
static const char *conf_file;
static int conf_lineno;                 // 1-based line in the file
static int conf_row;                    // 1-based data row within the table
static char conf_section[32];           // "Digital", "Zone"... or "General"
static char conf_rowid[32];             // first token of the row: "7", "1a"
static char conf_text[256];             // the line as read
static char conf_col[48];               // column named by the parser
static char conf_msg[512];              // message from the parser
static int conf_err_set;

void conf_error(const char *column, const char *fmt, ...)
{
    va_list ap;

    if (conf_err_set)
        return;
    conf_err_set = 1;
    snprintf(conf_col, sizeof(conf_col), "%.47s", column ? column : "");
    va_start(ap, fmt);
    vsnprintf(conf_msg, sizeof(conf_msg), fmt, ap);
    va_end(ap);
}

//
// The line as error messages and the "text" field show it.  A password line
// is never repeated back: a near-miss of a real password would end up in
// logs and in diagnostics people send with bug reports.
//
static void conf_text_set(const char *line)
{
    static const char *secret[] = { "Power On Password", "Radio Program Password",
                                    "PC Programming Password", 0 };
    int i, n;

    for (i=0; secret[i]; i++) {
        n = strlen(secret[i]);
        if (strncasecmp(line, secret[i], n) == 0 &&
                line[n + strspn(line + n, " \t")] == ':') {
            snprintf(conf_text, sizeof(conf_text), "%s: (not shown)", secret[i]);
            return;
        }
    }
    snprintf(conf_text, sizeof(conf_text), "%s", line);
}

static void conf_fail_here(void) __attribute__((noreturn));
static void conf_fail_here(void)
{
    char where[1200];
    int n = 0;
    const char *msg = conf_err_set ? conf_msg : "Invalid line.";

#define WHERE_ADD(...) do { if (n < (int) sizeof(where)) \
        n += snprintf(where + n, sizeof(where) - n, __VA_ARGS__); } while (0)
    WHERE_ADD("%s line %d", conf_file, conf_lineno);
    if (conf_section[0])
        WHERE_ADD(", %s", conf_section);
    if (conf_rowid[0])
        WHERE_ADD(" %s", conf_rowid);
    if (conf_col[0])
        WHERE_ADD("%s%s", conf_rowid[0] ? ", " : " ", conf_col);
#undef WHERE_ADD

    fail_begin(EXIT_CONF);
    ev_str("file", conf_file);
    ev_int("line", conf_lineno);
    ev_str("section", conf_section[0] ? conf_section : 0);
    if (conf_row > 0)
        ev_int("row", conf_row);
    ev_str("id", conf_rowid[0] ? conf_rowid : 0);
    ev_str("column", conf_col[0] ? conf_col : 0);
    ev_str("text", conf_text);
    fprintf(stderr, "%s: %s\n    '%s'\n", where, msg, conf_text);
    fail_end_json(msg);
}

//
// A parser that cannot return a failure (the scalar parameters) stops here.
//
void conf_fail(const char *column, const char *fmt, ...)
{
    va_list ap;

    if (! conf_err_set) {
        conf_err_set = 1;
        snprintf(conf_col, sizeof(conf_col), "%.47s", column ? column : "");
        va_start(ap, fmt);
        vsnprintf(conf_msg, sizeof(conf_msg), fmt, ap);
        va_end(ap);
    }
    conf_fail_here();
}

//
// Where each parsed row came from, so that problems found after parsing -
// a channel naming a missing scan list, an empty key slot - can be placed
// on the row too.  Keyed by table id and the row's id as written ("7",
// "1a"); a later row with the same id replaces an earlier one, as it does
// in the codeplug.
//
typedef struct {
    int  table_id, line, row;
    char id[32];
    char section[32];
} conf_where_t;
static conf_where_t *conf_where;
static int conf_nwhere, conf_maxwhere;

static void conf_remember(int table_id, const char *rowid)
{
    conf_where_t *w;

    if (conf_nwhere == conf_maxwhere) {
        int max = conf_maxwhere ? conf_maxwhere * 2 : 256;
        conf_where_t *p = realloc(conf_where, max * sizeof(conf_where_t));

        if (! p)
            return;
        conf_where = p;
        conf_maxwhere = max;
    }
    w = &conf_where[conf_nwhere++];
    w->table_id = table_id;
    w->line = conf_lineno;
    w->row = conf_row;
    snprintf(w->id, sizeof(w->id), "%s", rowid);
    snprintf(w->section, sizeof(w->section), "%s", conf_section);
}

static const conf_where_t *conf_lookup(int table_id, const char *id)
{
    int i;

    for (i=conf_nwhere-1; i>=0; i--)
        if (conf_where[i].table_id == table_id &&
            strcasecmp(conf_where[i].id, id) == 0)
            return &conf_where[i];
    return 0;
}

static int conf_nproblems, conf_nkeyproblems;

//
// Start an error event for a problem found after parsing.  The caller adds
// any fields of its own and finishes with error_event_end().  id is the row
// id as the config writes it; section is the table name to report when the
// row was not in the config (an image checked without one).
//
void conf_problem_begin(int code, int table_id, const char *id,
    const char *section, const char *column)
{
    const conf_where_t *w = conf_lookup(table_id, id);

    conf_nproblems++;
    if (code == EXIT_KEY_SLOT_EMPTY)
        conf_nkeyproblems++;

    fail_begin(code);
    if (conf_file)
        ev_str("file", conf_file);
    if (w) {
        ev_int("line", w->line);
        ev_str("section", w->section);
        ev_int("row", w->row);
    } else {
        ev_str("section", section);
    }
    ev_str("id", id);
    ev_str("column", column);
}

//
// Loop over all known radios and see if the config file can be parsed.
//
void radio_validate_config(const char *filename) {
  int i = 0;
  FILE *conf;
  char line[256];

  conf = fopen(filename, "r");
  if (! conf)
    die(EXIT_IO, "%s: %s", filename, strerror(errno));

  // First, find out which radio it is.
  while (fgets(line, sizeof(line), conf)) {
    if (strstr(line, "Radio:")) {
      for (i = 0; radio_tab[i].ident; i++) {
        if (strstr(line, radio_tab[i].ident)) goto found;
      }
    }
  }
  fclose(conf);
  die(EXIT_CONF, "Couldn't identify radio type from config file");

 found:

  fprintf(stderr, "Identified radio from config file as: %s\n", radio_tab[i].ident);
  fclose(conf);
  device = radio_tab[i].device;
  radio_parse_config(filename);
  fprintf(stderr, "Configuration validated successfully for %s\n", radio_tab[i].ident);
  ev_begin("result");
  ev_str("command", "validate");
  ev_bool("ok", 1);
  ev_str("radio", radio_tab[i].device->name);
  ev_end();
  exit(0);
}

//
// Read the configuration from text file, and modify the firmware.
//
void radio_parse_config(const char *filename)
{
    FILE *conf;
    char line [256], *p, *v;
    int table_id = 0, table_dirty = 0;

    fprintf(stderr, "Read configuration from file '%s'.\n", filename);
    report_phase("parse");
    conf = fopen(filename, "r");
    if (! conf)
        die(EXIT_IO, "%s: %s", filename, strerror(errno));
    conf_file = filename;
    conf_lineno = 0;
    memcpy(conf_mem_before, radio_mem, sizeof(radio_mem));

    device->channel_count = 0;
    while (fgets(line, sizeof(line), conf)) {
        line[sizeof(line)-1] = 0;
        conf_lineno++;

        // Strip comments.
        v = strchr(line, '#');
        if (v == line)
            *v = 0;

        // Strip trailing spaces and newline.
        v = line + strlen(line) - 1;
        while (v >= line && (*v=='\n' || *v=='\r' || *v==' ' || *v=='\t'))
            *v-- = 0;

        // Ignore comments and empty lines.
        p = line;
        if (*p == 0)
            continue;
        conf_text_set(line);
        conf_err_set = 0;
        conf_col[0] = 0;
        conf_rowid[0] = 0;

        if (*p != ' ') {
            // Table finished.
            table_id = 0;
            conf_row = 0;

            // Find the value.
            v = strchr(p, ':');
            if (! v) {
                // Table header: get table type.
                snprintf(conf_section, sizeof(conf_section), "%.*s",
                    (int) strcspn(p, " \t"), p);
                table_id = device->parse_header(device, p);
                if (! table_id) {
                    conf_error(0, "Unknown table '%s'.", conf_section);
badline:            conf_fail_here();
                }
                table_dirty = 0;
                continue;
            }

            // Parameter.
            *v++ = 0;

            // Skip spaces.
            while (*v == ' ' || *v == '\t')
                v++;

            snprintf(conf_section, sizeof(conf_section), "General");
            snprintf(conf_col, sizeof(conf_col), "%.47s", p);
            device->parse_parameter(device, p, v);

        } else {
            // Table row or comment.
            // Skip spaces.
            // Ignore comments and empty lines.
            while (*p == ' ' || *p == '\t')
                p++;
            if (*p == '#' || *p == 0)
                continue;
            if (! table_id) {
                conf_error(0, "A table row outside any table.");
                goto badline;
            }
            conf_row++;
            snprintf(conf_rowid, sizeof(conf_rowid), "%.*s",
                (int) strcspn(p, " \t"), p);

            if (! device->parse_row(device, table_id, ! table_dirty, p)) {
                goto badline;
            }
            conf_remember(table_id, conf_rowid);
            table_dirty = 1;
        }
    }
    fclose(conf);
    if (device->parse_finish)
        device->parse_finish(device);
    device->update_timestamp(device);
}

//
// Print full information about the device configuration.
//
void radio_print_config(FILE *out, int verbose)
{
    if (verbose) {
        char buf [40];
        time_t t;
        struct tm *tmp;

        t = time(NULL);
        tmp = localtime(&t);
        if (! tmp || ! strftime(buf, sizeof(buf), "%Y/%m/%d ", tmp))
            buf[0] = 0;
        fprintf(out, "#\n");
        fprintf(out, "# Configuration generated %sby dmrconfig, version %s\n",
            buf, version);
        fprintf(out, "#\n");
    }
    device->print_config(device, out, verbose);
}

//
// Check the configuration is correct.
//
void radio_verify_config()
{
    report_phase("check");
    conf_nproblems = conf_nkeyproblems = 0;
    if (!device->verify_config(device)) {
        // Each problem has had its own error event already.  The exit code
        // says key_slot_empty only when that is all that is wrong.
        if (conf_nproblems == 0)
            die(EXIT_CONF, "The configuration has errors.");
        fail_exit(conf_nkeyproblems == conf_nproblems ?
            EXIT_KEY_SLOT_EMPTY : EXIT_CONF);
    }
}

//
// Update contacts database on the device.
//
void radio_write_csv(const char *filename)
{
    FILE *csv;

    if (!device->write_csv)
        die(EXIT_UNSUPPORTED, "%s does not support CSV database.", device->name);

    csv = fopen(filename, "r");
    if (! csv)
        die(EXIT_IO, "%s: %s", filename, strerror(errno));
    fprintf(stderr, "Read file '%s'.\n", filename);

    device->write_csv(device, csv);
    fclose(csv);
    if (radio_state == RADIO_CONTACTS_INCOMPLETE)
        radio_state = RADIO_CONTACTS_WRITTEN;
}

//
// Does this radio use the privacy key table mapped in Phase 2?
//
// Verified on the 5W MD-UV390 Plus, whose DFU identify string is the plain
// "MD-UV390".  The MD-UV380 shares the codeplug layout and
// is very likely the same, but has not been on the bench; the 10W Plus is
// Phase 5.  Anything else is refused rather than guessed at, because a key
// write cannot be read back or undone.
//
int radio_is_privacy_capable(const char *ident)
{
    return strcasecmp(ident, "MD-UV390") == 0 ||
           strcasecmp(ident, "MD-UV380") == 0;
}

//
// Check for compatible radio model.
//
int radio_is_compatible(const char *name)
{
    int i;

    for (i=0; radio_tab[i].ident; i++) {
        // Radio is compatible when it has the same parse routine.
        if (device->parse_parameter == radio_tab[i].device->parse_parameter &&
            strcasecmp(name, radio_tab[i].device->name) == 0) {
            return 1;
        }
    }
    return 0;
}
