// SPDX-License-Identifier: BSD-3-Clause
/*
 * AES / privacy key table support for the TYT MD-UV390 Plus.
 *
 * The key table is NOT part of the 851968-byte codeplug image.  It lives in a
 * region reachable only through the vendor command 0xda, it is written as one
 * 20480-byte blob, and the radio returns all-zero key fields when it is read
 * back.  See TYTcps's docs/dev/protocol.md.
 *
 * Two consequences shape everything here:
 *
 *   1. Keys cannot be verified by reading the radio.  The only record of what
 *      a radio holds is the ledger this file appends to, plus an over-the-air
 *      test.
 *   2. Phase 3 proved the key id travels over the air: the transmitter tags
 *      the slot number and the receiver looks that id up in its OWN table.
 *      The key table is therefore a FLEET-WIDE CONTRACT, slot for slot.  One
 *      .dec file is the single source of truth and every radio gets the
 *      identical blob.  This tool never edits keys per radio.
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "radio.h"
#include "util.h"
#include "report.h"
#include "state.h"

#define NSLOTS          16
#define SLOT_STRIDE     100             // 0x64
#define OFF_TYPE        0x00            // uint32 LE
#define OFF_NAME        0x04            // UTF-16LE, 32 bytes
#define OFF_KEY         0x24
#define NAME_CHARS      16

#define TYPE_ARC4       1
#define TYPE_AES128     3
#define TYPE_AES256     4

#define CURRENT_KEYSET  "current-keyset"

static const struct {
    int         type;
    int         keylen;
    const char *name;
} TYPE_TAB[] = {
    { TYPE_ARC4,    5,  "ARC4"   },
    { TYPE_AES128, 16,  "AES128" },
    { TYPE_AES256, 32,  "AES256" },
};
#define NTYPES ((int) (sizeof(TYPE_TAB) / sizeof(TYPE_TAB[0])))

//
// Length of the key field for a slot type, or 0 for an unknown type.
//
static int type_keylen(int type)
{
    int i;

    for (i=0; i<NTYPES; i++)
        if (TYPE_TAB[i].type == type)
            return TYPE_TAB[i].keylen;
    return 0;
}

static const char *type_name(int type)
{
    int i;

    for (i=0; i<NTYPES; i++)
        if (TYPE_TAB[i].type == type)
            return TYPE_TAB[i].name;
    return "?";
}

//
// Parse a type given as a name or as a number.  Returns 0 when invalid.
//
static int parse_type(const char *s)
{
    int i, n;

    for (i=0; i<NTYPES; i++)
        if (strcasecmp(s, TYPE_TAB[i].name) == 0)
            return TYPE_TAB[i].type;
    n = atoi(s);
    if (type_keylen(n))
        return n;
    return 0;
}

static const unsigned char *slot_rec(const unsigned char *blob, int slot)
{
    return &blob[(slot - 1) * SLOT_STRIDE];
}

static int slot_type(const unsigned char *blob, int slot)
{
    const unsigned char *r = slot_rec(blob, slot);

    return r[0] | (r[1] << 8) | (r[2] << 16) | (r[3] << 24);
}

//
// A slot is "in use" when its type is known AND its key field is not the
// unused default.  The fleet file ships slots 4-16 as type 4 with the key
// field 01 00 00 ... 00, which is the CPS's empty-slot filler, not a key;
// the CPS's own stock file has the key field all zero.
//
static int slot_in_use(const unsigned char *blob, int slot)
{
    const unsigned char *r = slot_rec(blob, slot);
    int len = type_keylen(slot_type(blob, slot));
    int i, nonzero = 0;

    if (! len)
        return 0;
    for (i=0; i<len; i++)
        if (r[OFF_KEY + i])
            nonzero++;
    if (! nonzero)
        return 0;
    // Unused default: a single 0x01 in the first byte and nothing else.
    if (nonzero == 1 && r[OFF_KEY] == 0x01)
        return 0;
    return 1;
}

static void slot_name(const unsigned char *blob, int slot, char *buf, int size)
{
    uint16_t name[NAME_CHARS];

    memcpy(name, &slot_rec(blob, slot)[OFF_NAME], sizeof(name));
    utf16_to_utf8(name, NAME_CHARS, buf, size);
}

//
// Is slot N usable as a channel's Universal key?  Used by verify_config.
//
int privacy_slot_available(const unsigned char *blob, int slot)
{
    if (slot < 1 || slot > NSLOTS)
        return 0;
    return slot_in_use(blob, slot);
}

const char *privacy_slot_type_name(const unsigned char *blob, int slot)
{
    if (slot < 1 || slot > NSLOTS)
        return "?";
    return type_name(slot_type(blob, slot));
}

//
// Load a .dec file into a caller-supplied PRIVACY_TABLE_SIZE buffer.
// Exits on any problem: a short or padded file would be written to a radio.
//
void privacy_load_dec(const char *filename, unsigned char *blob)
{
    FILE *f;
    struct stat st;

    if (stat(filename, &st) < 0)
        die(EXIT_KEYFILE, "%s: %s", filename, strerror(errno));
    if (st.st_size != PRIVACY_TABLE_SIZE) {
        fail_begin(EXIT_KEYFILE);
        ev_int("size", st.st_size);
        ev_int("expected", PRIVACY_TABLE_SIZE);
        fail_end("%s: key file is %u bytes, expected %d. This is not a CPS "
            ".dec file.", filename, (unsigned) st.st_size, PRIVACY_TABLE_SIZE);
    }
    f = fopen(filename, "rb");
    if (! f)
        die(EXIT_KEYFILE, "%s: %s", filename, strerror(errno));
    if (fread(blob, 1, PRIVACY_TABLE_SIZE, f) != PRIVACY_TABLE_SIZE)
        die(EXIT_KEYFILE, "%s: cannot read key file.", filename);
    fclose(f);
}

//
// Print the slot table.  With show_keys, key bytes are printed in CPS grid
// order, i.e. reversed from how they sit in the file (see protocol.md,
// "The .dec key file").
//
void privacy_print_table(FILE *out, const unsigned char *blob, int show_keys)
{
    uint16_t name[NAME_CHARS];
    int slot, i, len;

    fprintf(out, "%4s  %-8s  %-16s  %6s  %s\n",
        "Slot", "Type", "Name", "KeyLen", show_keys ? "Key (CPS grid order)"
                                                    : "Key field");
    for (slot=1; slot<=NSLOTS; slot++) {
        const unsigned char *r = slot_rec(blob, slot);
        int type = slot_type(blob, slot);

        len = type_keylen(type);
        fprintf(out, "%4d  %-8s  ", slot, type_name(type));

        memcpy(name, &r[OFF_NAME], sizeof(name));
        print_unicode(out, name, NAME_CHARS, 1);
        fprintf(out, "  %6d  ", len);

        if (! slot_in_use(blob, slot)) {
            fprintf(out, "-\n");
            continue;
        }
        if (show_keys) {
            // Reverse: file order -> grid order.
            for (i=len-1; i>=0; i--)
                fprintf(out, "%02x", r[OFF_KEY + i]);
            fprintf(out, "\n");
        } else {
            int nonzero = 0;
            for (i=0; i<len; i++)
                if (r[OFF_KEY + i])
                    nonzero++;
            fprintf(out, "set, %d non-zero byte%s\n",
                nonzero, nonzero == 1 ? "" : "s");
        }
    }
}

//
// The slot table as a JSON array.  Key hex only with show_keys, and then in
// CPS grid order: this is what TYTcps shows, masked, in its Keys tab.  It
// never logs it.
//
static void slots_event(const unsigned char *blob, int show_keys)
{
    int slot, i;

    ev_arr("slots");
    for (slot=1; slot<=NSLOTS; slot++) {
        const unsigned char *r = slot_rec(blob, slot);
        int type = slot_type(blob, slot), len = type_keylen(type);
        int used = slot_in_use(blob, slot);
        char name[3 * NAME_CHARS + 1];

        slot_name(blob, slot, name, sizeof(name));
        ev_obj(0);
        ev_int("slot", slot);
        ev_str("type", used ? type_name(type) : "empty");
        ev_int("type_code", type);
        ev_str("name", name);
        ev_int("length", len);
        ev_bool("in_use", used);
        if (show_keys) {
            if (used) {
                unsigned char grid[64];

                for (i=0; i<len; i++)
                    grid[i] = r[OFF_KEY + len - 1 - i];
                ev_hex("key", grid, len);
                memset(grid, 0, sizeof(grid));
            } else {
                ev_str("key", 0);
            }
        }
        ev_obj_end();
    }
    ev_arr_end();
}

//
// -------------------------------------------------------------------------
// Sessions.
// -------------------------------------------------------------------------
//
typedef struct {
    const char    *model;
    char           a207[80];
    char           serial[64];
    char           firmware[64];
    int            known;           // in the roster
    roster_entry_t roster;
} unit_t;

//
// Open a privacy session: the CPS's preamble (91 01, a2 01-07), then who is
// this.  require_unit: refuse when a2 07 cannot be read, because a ledger
// line without it would be meaningless.
//
static void privacy_connect(unit_t *u, int require_model, int require_unit)
{
    const char *ident;

    memset(u, 0, sizeof(*u));
    report_phase("connect");
    ident = dfu_privacy_init(0x0483, 0xdf11);
    if (! ident)
        die(EXIT_NO_RADIO, "No radio detected. Check your USB cable, that the "
            "radio is on, and that no VM has grabbed 0483:df11.");
    u->model = ident;
    snprintf(u->a207, sizeof(u->a207), "%s", unit_a207());
    snprintf(u->serial, sizeof(u->serial), "%s", unit_serial());
    snprintf(u->firmware, sizeof(u->firmware), "%s", unit_firmware());
    u->known = roster_lookup(u->a207, &u->roster);

    fprintf(stderr, "Connect to %s (privacy table).\n", ident);
    fprintf(stderr, "Unit: a207=%s serial=%s firmware=%s",
        u->a207[0] ? u->a207 : "(unreadable)", u->serial[0] ? u->serial : "-",
        u->firmware[0] ? u->firmware : "-");
    if (u->known)
        fprintf(stderr, " -> last seen as Radio ID %s (%s)",
            u->roster.radio_id, u->roster.label);
    fprintf(stderr, "\n");

    ev_begin("unit");
    ev_str("model", ident);
    ev_str("a207", u->a207[0] ? u->a207 : 0);
    ev_str("serial", u->serial[0] ? u->serial : 0);
    ev_str("firmware", u->firmware[0] ? u->firmware : 0);
    ev_bool("privacy_capable", radio_is_privacy_capable(ident));
    ev_bool("known", u->known);
    ev_str("radio_id", u->known && strcmp(u->roster.radio_id, "-") != 0 ?
        u->roster.radio_id : 0);
    ev_str("label", u->known && strcmp(u->roster.label, "-") != 0 ?
        u->roster.label : 0);
    ev_end();

    if (require_model && ! radio_is_privacy_capable(ident))
        die(EXIT_UNSUPPORTED, "Radio identifies as '%s'. The privacy key "
            "table is only known for the MD-UV390 family; nothing was "
            "written.", ident);
    if (require_unit && ! u->a207[0])
        die(EXIT_UNIT_UNREADABLE, "Cannot read the a2 07 unit block, so a "
            "key write could not be recorded against this radio. Nothing was "
            "written. Reconnect and try again.");
}

//
// Close the session.  identify and -k have their answer by now, so a
// restart the radio does not take is a warning, not a failure.
//
static void privacy_disconnect(void)
{
    fprintf(stderr, "Close device.\n");
    if (dfu_try_reboot() < 0)
        report_warning("reboot_failed", "The radio did not take the restart "
            "command; switch it off and on to leave programming mode.");
    dfu_close();
}

//
// identify: who is on the cable.  No codeplug read, no key table read.
// Adds a new unit to the roster, or refreshes last_seen of a known one.
//
void privacy_identify(void)
{
    unit_t u;

    privacy_connect(&u, 0, 0);
    privacy_disconnect();
    if (u.a207[0])
        roster_seen(u.a207, 0, 0);

    printf("Model:    %s\n", u.model);
    printf("Firmware: %s\n", u.firmware[0] ? u.firmware : "-");
    printf("Serial:   %s\n", u.serial[0] ? u.serial : "-");
    printf("Unit:     %s\n", u.a207[0] ? u.a207 : "(unreadable)");
    if (u.known)
        printf("Roster:   last seen as Radio ID %s, label %s\n",
            u.roster.radio_id, u.roster.label);
    else
        printf("Roster:   new radio\n");

    ev_begin("result");
    ev_str("command", "identify");
    ev_bool("ok", 1);
    ev_str("model", u.model);
    ev_str("firmware", u.firmware[0] ? u.firmware : 0);
    ev_str("serial", u.serial[0] ? u.serial : 0);
    ev_str("a207", u.a207[0] ? u.a207 : 0);
    ev_bool("privacy_capable", radio_is_privacy_capable(u.model));
    ev_bool("known", u.known);
    ev_str("radio_id", u.known && strcmp(u.roster.radio_id, "-") != 0 ?
        u.roster.radio_id : 0);
    ev_str("label", u.known && strcmp(u.roster.label, "-") != 0 ?
        u.roster.label : 0);
    ev_str("last_seen", u.known && strcmp(u.roster.last_seen, "-") != 0 ?
        u.roster.last_seen : 0);
    ev_end();
    if (! u.a207[0])
        report_warning("unit_unreadable", "The a2 07 unit block came back "
            "empty; this radio cannot be tracked in the roster.");
}

//
// -K <file.dec>: write the fleet key table to the radio.
//
// Any radio can be written; the roster only supplies the Radio
// ID and label for the ledger line, and "-" when it does not know the unit.
//
void privacy_write_keys(const char *filename)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    char sha[65], path[1024], line[8192];
    const char *radio_id, *label;
    unit_t u;

    // The file name goes into the ledger line: a tab or newline in it would
    // break the record, so refuse it while nothing has been written.
    if (strpbrk(filename, "\t\r\n") || strlen(filename) > 2048)
        die(EXIT_USAGE, "The key file's name has a tab or newline in it, or "
            "is too long, and could not be recorded in the ledger. Rename it.");
    privacy_load_dec(filename, blob);
    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);

    fprintf(stderr, "Key table '%s'\n", filename);
    fprintf(stderr, "SHA256 %s\n", sha);
    privacy_print_table(stderr, blob, 0);

    // The ledger is the only record of what this write does.  Make sure it
    // can be written before the radio is touched, not after.  This is an
    // io_error, not ledger_failed: exit 13 always means the keys WERE
    // written and the record of it is what is missing (E-K5).
    if (ledger_preflight(path, sizeof(path)) < 0)
        die(EXIT_IO, "Cannot write the ledger %s: %s. Nothing was "
            "written to the radio.", path, strerror(errno));

    privacy_connect(&u, 1, 1);

    // --expect-unit: a radio swapped onto the cable since the caller
    // identified it is refused here, before da 02.
    radio_require_unit(u.a207);
    radio_id = (u.known && strcmp(u.roster.radio_id, "-") != 0) ?
        u.roster.radio_id : "-";

    // From here, any error event names the unit and the key set, so a
    // transfer that breaks off can still be recorded as "keys unknown"
    // against this radio.
    report_context("a207", u.a207);
    report_context("sha256", sha);
    report_context("file", filename);
    label = (u.known && strcmp(u.roster.label, "-") != 0) ?
        u.roster.label : "-";

    report_phase("keys");
    if (! trace_flag) {
        fprintf(stderr, "Write privacy: ");
        fflush(stderr);
    }
    dfu_privacy_write_table(blob, PRIVACY_TABLE_SIZE);
    if (! trace_flag)
        fprintf(stderr, " done.\n");

    // Record it the moment the last block is in, before anything else can
    // fail - including the restart below.  A failure here still restarts
    // the radio on the way out: the table is complete.
    if (ledger_append(u.a207, u.serial, radio_id, label, sha, filename,
            version, "-", line, sizeof(line)) < 0) {
        int err = errno;

        fprintf(stderr, "Add this line to %s by hand:\n%s\n", path, line);
        fail_begin(EXIT_LEDGER);
        ev_str("a207", u.a207);
        ev_str("sha256", sha);
        ev_str("ledger", path);
        ev_str("line", line);
        fail_end("The keys WERE written, but the ledger %s could not be "
            "updated: %s. Do not write the keys again; record the line "
            "instead.", path, strerror(err));
    }

    fprintf(stderr, "Close device.\n");
    if (dfu_try_reboot() < 0)
        report_warning("reboot_failed", "The radio did not take the restart "
            "command. The keys are written and recorded; switch the radio off "
            "and on to leave programming mode.");
    dfu_close();
    roster_seen(u.a207, 0, 0);

    fprintf(stderr, "\nThe radio does NOT return key material, so this write "
                    "cannot be verified\nby reading it back. Verify over the "
                    "air.\n");

    ev_begin("result");
    ev_str("command", "write_keys");
    ev_bool("ok", 1);
    ev_str("file", filename);
    ev_str("sha256", sha);
    ev_str("a207", u.a207);
    ev_str("serial", u.serial[0] ? u.serial : 0);
    ev_str("radio_id", strcmp(radio_id, "-") ? radio_id : 0);
    ev_str("label", strcmp(label, "-") ? label : 0);
    ev_str("ledger", path);
    ev_str("line", line);
    ev_str("verify", "on_air_only");
    slots_event(blob, 0);
    ev_end();
}

//
// -k: read the slot types and names back.  Key fields come back all zero by
// design; this is a liveness and type/name check only.
//
void privacy_read_keys(void)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    unit_t u;
    int slot;

    privacy_connect(&u, 1, 0);

    report_phase("keys_read");
    if (! trace_flag) {
        fprintf(stderr, "Read privacy: ");
        fflush(stderr);
    }
    memset(blob, 0, sizeof(blob));
    dfu_privacy_read_table(blob, PRIVACY_TABLE_SIZE);
    if (! trace_flag)
        fprintf(stderr, " done.\n");

    privacy_disconnect();
    if (u.a207[0])
        roster_seen(u.a207, 0, 0);

    printf("\n");
    privacy_print_table(stdout, blob, 0);
    printf("\nNOTE: key fields read back all zero by design - the radio does "
           "not return key\nmaterial. Types "
           "and names are real.\n");

    // A slot read back has an all-zero key field, so "in use" means nothing
    // here: report the type the radio holds for each slot as it is.
    ev_begin("result");
    ev_str("command", "read_keys");
    ev_bool("ok", 1);
    ev_str("a207", u.a207[0] ? u.a207 : 0);
    ev_arr("slots");
    for (slot=1; slot<=NSLOTS; slot++) {
        char name[3 * NAME_CHARS + 1];
        int type = slot_type(blob, slot);

        slot_name(blob, slot, name, sizeof(name));
        ev_obj(0);
        ev_int("slot", slot);
        ev_str("type", type_name(type));
        ev_int("type_code", type);
        ev_str("name", name);
        ev_int("length", type_keylen(type));
        ev_obj_end();
    }
    ev_arr_end();
    ev_str("note", "Radios never return the key itself; types and names are "
        "real, keys read back as zero.");
    ev_end();
}

//
// -------------------------------------------------------------------------
// Key files.
// -------------------------------------------------------------------------
//

//
// The empty key set, as the CPS makes it: 16 slots of type AES256 named
// "1" to "16" with no key, and the CPS's padding.  That padding is not all
// zero: every 1024-byte block of the file from the third on repeats the
// first 8 bytes of the slot 12-16 records (type 4, names "12" to "16") at
// block offset 0x4c, which is where those records fall in the second block.
// It is identical in every CPS-made file seen (stock and fleet sets with
// different keys), and the radio is sent all 20480 bytes, so it is
// reproduced exactly rather than zeroed.
//
static void empty_slot(unsigned char *blob, int slot)
{
    unsigned char *r = &blob[(slot - 1) * SLOT_STRIDE];
    char digits[4];
    int i;

    memset(r, 0, SLOT_STRIDE);
    r[OFF_TYPE] = TYPE_AES256;
    snprintf(digits, sizeof(digits), "%d", slot);
    for (i=0; digits[i]; i++)
        r[OFF_NAME + 2*i] = digits[i];
}

static void empty_table(unsigned char *blob)
{
    int slot, block, j;

    memset(blob, 0, PRIVACY_TABLE_SIZE);
    for (slot=1; slot<=NSLOTS; slot++)
        empty_slot(blob, slot);
    for (block=2; block<PRIVACY_TABLE_SIZE/1024; block++) {
        for (j=0; j<5; j++) {
            unsigned char *p = &blob[block*1024 + 0x4c + j*SLOT_STRIDE];

            p[0] = TYPE_AES256;
            p[4] = '1';
            p[6] = '2' + j;
        }
    }
}

//
// Write a key file: mode 0600.  'exclusive' creates it and refuses to
// replace anything; otherwise it is written to a temp file in the same
// folder and renamed over the original, so a crash never leaves half a key
// set.
//
static void save_dec(const char *filename, const unsigned char *blob,
    int exclusive)
{
    char tmp[4200], real[4096];
    int fd;

    if (exclusive) {
        fd = open(filename, O_WRONLY | O_CREAT | O_EXCL, 0600);
        if (fd < 0) {
            int err = errno;

            die(err == EEXIST ? EXIT_USAGE : EXIT_IO, "%s: %s%s", filename,
                strerror(err), err == EEXIST ?
                " - keys new never replaces a file" : "");
        }
        if (write(fd, blob, PRIVACY_TABLE_SIZE) != PRIVACY_TABLE_SIZE ||
            fsync(fd) != 0) {
            close(fd);
            unlink(filename);
            die(EXIT_IO, "%s: write failed.", filename);
        }
        close(fd);
        return;
    }
    // Edit what a symlink points at, as an in-place write would, rather
    // than replacing the link with a file.
    if (realpath(filename, real))
        filename = real;
    snprintf(tmp, sizeof(tmp), "%s.tmp.%d", filename, (int) getpid());
    fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0)
        die(EXIT_IO, "%s: %s", tmp, strerror(errno));
    if (write(fd, blob, PRIVACY_TABLE_SIZE) != PRIVACY_TABLE_SIZE ||
        fsync(fd) != 0) {
        close(fd);
        unlink(tmp);
        die(EXIT_IO, "%s: write failed.", tmp);
    }
    close(fd);
    if (rename(tmp, filename) < 0) {
        int err = errno;

        unlink(tmp);
        die(EXIT_IO, "%s: %s", filename, strerror(err));
    }
}

//
// keys show <file.dec>
//
static void keys_show(const char *filename)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    char sha[65];

    privacy_load_dec(filename, blob);
    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);
    if (! json_mode) {
        printf("File:   %s\n", filename);
        printf("SHA256: %s\n\n", sha);
        privacy_print_table(stdout, blob, 1);
        return;
    }
    // With --json the keys go to the event stream only, never to the log.
    fprintf(stderr, "Key file '%s', SHA256 %s (keys in the JSON result only)\n",
        filename, sha);
    ev_begin("result");
    ev_str("command", "keys_show");
    ev_bool("ok", 1);
    ev_str("file", filename);
    ev_str("sha256", sha);
    slots_event(blob, 1);
    ev_end();
}

//
// keys new <out.dec>: an empty key set.  Never replaces a file.
//
static void keys_new(const char *filename)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    char sha[65];

    empty_table(blob);
    save_dec(filename, blob, 1);
    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);
    printf("New empty key set: %s\nSHA256: %s\n", filename, sha);
    ev_begin("result");
    ev_str("command", "keys_new");
    ev_bool("ok", 1);
    ev_str("file", filename);
    ev_str("sha256", sha);
    ev_end();
}

//
// One hex digit, or -1.
//
static int hexdigit(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

//
// Has this key set been given to any radio, or is it the current set?
// Either makes it a file whose old contents matter, so it is never edited
// without a backup.  Returns the reason, or null.
//
static const char *keyset_in_service(const char *filename,
    const unsigned char *blob)
{
    char path[1024], line[1024], sha[65], cur[1024];
    const char *base;
    FILE *f;

    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);
    state_path(path, sizeof(path), "ledger.tsv");
    f = fopen(path, "r");
    if (f) {
        while (fgets(line, sizeof(line), f)) {
            if (line[0] != '#' && strstr(line, sha)) {
                fclose(f);
                return "it has been written to a radio (it is in the ledger)";
            }
        }
        fclose(f);
    }
    state_path(path, sizeof(path), CURRENT_KEYSET);
    f = fopen(path, "r");
    if (f) {
        if (fgets(cur, sizeof(cur), f)) {
            cur[strcspn(cur, "\r\n")] = 0;
            base = strrchr(filename, '/');
            base = base ? base + 1 : filename;
            if (cur[0] && strcmp(cur, base) == 0) {
                fclose(f);
                return "it is the current key set";
            }
        }
        fclose(f);
    }
    return 0;
}

//
// Keep a timestamped copy of a key file before it is edited.
//
static void backup_dec(const char *filename, const unsigned char *blob)
{
    char bak[1100], stamp[32];
    time_t t = time(0);
    struct tm *tm = localtime(&t);
    int fd = -1, i;

    if (! tm || ! strftime(stamp, sizeof(stamp), "%Y%m%d-%H%M%S", tm))
        snprintf(stamp, sizeof(stamp), "%ld", (long) t);
    // Never clobber an existing backup: two edits in the same second must
    // not leave only one of them recoverable.
    for (i=0; i<100; i++) {
        if (i == 0)
            snprintf(bak, sizeof(bak), "%s.%s.bak", filename, stamp);
        else
            snprintf(bak, sizeof(bak), "%s.%s-%d.bak", filename, stamp, i);
        fd = open(bak, O_WRONLY | O_CREAT | O_EXCL, 0600);
        if (fd >= 0 || errno != EEXIST)
            break;
    }
    if (fd < 0)
        die(EXIT_IO, "%s: %s. Refusing to edit %s without a backup.",
            bak, strerror(errno), filename);
    if (write(fd, blob, PRIVACY_TABLE_SIZE) != PRIVACY_TABLE_SIZE ||
        fsync(fd) != 0) {
        close(fd);
        die(EXIT_IO, "%s: short write. Refusing to edit %s without a backup.",
            bak, filename);
    }
    close(fd);
    fprintf(stderr, "Backup: %s\n", bak);
}

//
// Read one line of hex from stdin, so a key never has to appear on a command
// line (where /proc/<pid>/cmdline shows it to the same user).
//
static void read_stdin_line(char *buf, int size)
{
    int n;

    if (! fgets(buf, size, stdin))
        die(EXIT_USAGE, "Expected the key in hex on standard input.");
    n = strlen(buf);
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r'))
        buf[--n] = 0;
}

static void keys_edited_result(const char *command, const char *filename,
    const unsigned char *blob, int slot)
{
    char sha[65];

    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);
    printf("File:   %s\n", filename);
    printf("SHA256: %s\n", sha);
    ev_begin("result");
    ev_str("command", command);
    ev_bool("ok", 1);
    ev_str("file", filename);
    ev_int("slot", slot);
    ev_str("sha256", sha);
    ev_end();
}

//
// A slot name: UTF-8 in, up to 16 UTF-16 units out, zero-filled.  Strict:
// malformed UTF-8 and characters outside the Basic Multilingual Plane (which
// would need two units, and which the radio cannot show) are refused rather
// than guessed at.
//
static void decode_slot_name(const char *src, uint16_t name[NAME_CHARS])
{
    const unsigned char *s = (const unsigned char*) src;
    int n = 0;

    memset(name, 0, NAME_CHARS * sizeof(uint16_t));
    while (*s) {
        unsigned c = *s, cp;
        int more, k;

        if (c < 0x80)       { cp = c;        more = 0; }
        else if (c >= 0xc2 && c < 0xe0) { cp = c & 0x1f; more = 1; }
        else if (c >= 0xe0 && c < 0xf0) { cp = c & 0x0f; more = 2; }
        else if (c >= 0xf0 && c < 0xf5)
            die(EXIT_KEYFILE, "Slot names can only use characters the radio "
                "can show (no emoji or other characters beyond U+FFFF).");
        else
            die(EXIT_KEYFILE, "Slot name is not valid UTF-8.");
        for (k=1; k<=more; k++) {
            if ((s[k] & 0xc0) != 0x80)
                die(EXIT_KEYFILE, "Slot name is not valid UTF-8.");
            cp = (cp << 6) | (s[k] & 0x3f);
        }
        if ((more == 2 && cp < 0x800) || (cp >= 0xd800 && cp < 0xe000))
            die(EXIT_KEYFILE, "Slot name is not valid UTF-8.");
        if (n == NAME_CHARS)
            die(EXIT_KEYFILE, "Slot name is longer than %d characters.",
                NAME_CHARS);
        name[n++] = cp;
        s += more + 1;
    }
}

//
// keys set [--no-backup] [--name NAME] <file.dec> <slot> <type> <hex|->
//
// The key is given in CPS grid order and reversed into file order here.
// The file is a fleet key set, so a timestamped copy is kept first, unless
// --no-backup says the file is one being built from scratch - allowed only
// for a file that is not in service (keyset_in_service()).
//
static void keys_set(int nobackup, const char *newname, const char *filename,
    const char *slot_str, const char *type_str, const char *hex_arg)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    unsigned char key[64];
    char hexbuf[512];
    const char *hex = hex_arg, *p, *why;
    int slot, type, want, nhex = 0, i;
    char *end;

    slot = strtol(slot_str, &end, 10);
    if (*end || slot < 1 || slot > NSLOTS)
        die(EXIT_KEYFILE, "Slot must be 1..%d.", NSLOTS);
    type = parse_type(type_str);
    if (! type)
        die(EXIT_KEYFILE, "Type must be ARC4, AES128 or AES256.");
    want = type_keylen(type);

    if (strcmp(hex_arg, "-") == 0) {
        read_stdin_line(hexbuf, sizeof(hexbuf));
        hex = hexbuf;
    }

    // Parse the hex key, ignoring spaces, colons and dashes.
    for (p=hex; *p; p++) {
        int hi, lo;

        if (*p == ' ' || *p == ':' || *p == '-')
            continue;
        hi = hexdigit(*p);
        lo = p[1] ? hexdigit(p[1]) : -1;
        if (hi < 0 || lo < 0)
            die(EXIT_KEYFILE, "Key must be whole hex digit pairs.");
        if (nhex >= (int) sizeof(key))
            die(EXIT_KEYFILE, "Key is too long.");
        key[nhex++] = (hi << 4) | lo;
        p++;
    }
    memset(hexbuf, 0, sizeof(hexbuf));
    if (nhex != want)
        die(EXIT_KEYFILE, "%s needs %d key bytes, got %d.",
            type_name(type), want, nhex);

    privacy_load_dec(filename, blob);

    // --no-backup never destroys a key: it is for filling the empty slots
    // of a set being built (keys new, then one set per slot).  Replacing a
    // key, or editing a set that is in service, keeps a copy first.
    why = keyset_in_service(filename, blob);
    if (! why && slot_in_use(blob, slot))
        why = "slot already holds a key, which would be lost";
    if (nobackup && why)
        die(EXIT_USAGE, "--no-backup is only for a key set being built, and "
            "for %s: %s. Save the edit as a new key set instead.",
            filename, why);
    if (! nobackup)
        backup_dec(filename, blob);

    {
        unsigned char *r = &blob[(slot - 1) * SLOT_STRIDE];

        r[OFF_TYPE + 0] = type;
        r[OFF_TYPE + 1] = type >> 8;
        r[OFF_TYPE + 2] = type >> 16;
        r[OFF_TYPE + 3] = type >> 24;

        // Clear the whole key field first: records are fixed width, and a
        // shorter key must not leave the tail of the old one behind.
        memset(&r[OFF_KEY], 0, SLOT_STRIDE - OFF_KEY);

        // Reverse: grid order -> file order.
        for (i=0; i<nhex; i++)
            r[OFF_KEY + i] = key[nhex - 1 - i];

        if (newname) {
            uint16_t name[NAME_CHARS];

            decode_slot_name(newname, name);
            memcpy(&r[OFF_NAME], name, sizeof(name));
        }
    }
    memset(key, 0, sizeof(key));

    save_dec(filename, blob, 0);

    printf("Slot %d set to %s, %d key bytes (reversed into file order).\n",
        slot, type_name(type), nhex);
    printf("\nThis changed the FLEET key table. Every radio must be given "
           "this file with\n-K, or the slot will not interoperate: the key's slot "
           "number travels over\nthe air and the receiver looks it up in its "
           "own table.\n");
    keys_edited_result("keys_set", filename, blob, slot);
}

//
// keys clear [--no-backup] <file.dec> <slot>: back to the CPS's empty slot.
//
static void keys_clear(int nobackup, const char *filename, const char *slot_str)
{
    unsigned char blob[PRIVACY_TABLE_SIZE];
    const char *why;
    char *end;
    int slot;

    slot = strtol(slot_str, &end, 10);
    if (*end || slot < 1 || slot > NSLOTS)
        die(EXIT_KEYFILE, "Slot must be 1..%d.", NSLOTS);
    privacy_load_dec(filename, blob);
    why = keyset_in_service(filename, blob);
    if (! why && slot_in_use(blob, slot))
        why = "clearing a slot that holds a key would lose it";
    if (nobackup && why)
        die(EXIT_USAGE, "--no-backup is only for a key set being built, and "
            "%s: %s.", filename, why);
    if (! nobackup)
        backup_dec(filename, blob);
    empty_slot(blob, slot);
    save_dec(filename, blob, 0);
    printf("Slot %d cleared.\n", slot);
    keys_edited_result("keys_clear", filename, blob, slot);
}

static void keys_usage(void) __attribute__((noreturn));
static void keys_usage(void)
{
    fprintf(stderr, "Usage:\n");
    fprintf(stderr, "    dmrconfig keys show <file.dec>\n");
    fprintf(stderr, "    dmrconfig keys new <file.dec>\n");
    fprintf(stderr, "    dmrconfig keys set [--no-backup] [--name NAME] "
                    "<file.dec> <slot> <type> <hex|->\n");
    fprintf(stderr, "        slot 1..%d, type ARC4|AES128|AES256,\n", NSLOTS);
    fprintf(stderr, "        hex in CPS grid order (the tool reverses it),\n");
    fprintf(stderr, "        - reads the hex from standard input\n");
    fprintf(stderr, "    dmrconfig keys clear [--no-backup] <file.dec> <slot>\n");
    die(EXIT_USAGE, "Bad 'keys' command.");
}

//
// The 'keys' subcommand.
//
void privacy_keys_command(int argc, char **argv)
{
    int nobackup = 0;
    const char *newname = 0;
    const char *cmd;

    if (argc < 1)
        keys_usage();
    cmd = argv[0];
    argc--;
    argv++;
    while (argc > 0 && argv[0][0] == '-' && argv[0][1] == '-') {
        if (strcmp(argv[0], "--no-backup") == 0) {
            nobackup = 1;
        } else if (strcmp(argv[0], "--name") == 0 && argc > 1) {
            newname = argv[1];
            argc--;
            argv++;
        } else {
            keys_usage();
        }
        argc--;
        argv++;
    }
    if (strcasecmp(cmd, "show") == 0 && argc == 1 && ! nobackup && ! newname)
        keys_show(argv[0]);
    else if (strcasecmp(cmd, "new") == 0 && argc == 1 && ! nobackup && ! newname)
        keys_new(argv[0]);
    else if (strcasecmp(cmd, "set") == 0 && argc == 4)
        keys_set(nobackup, newname, argv[0], argv[1], argv[2], argv[3]);
    else if (strcasecmp(cmd, "clear") == 0 && argc == 2 && ! newname)
        keys_clear(nobackup, argv[0], argv[1]);
    else
        keys_usage();
}

//
// -------------------------------------------------------------------------
// The ledger subcommand.
// -------------------------------------------------------------------------
//

//
// Tabs and newlines would break the TSV.
//
static void tsv_clean(char *s)
{
    for (; *s; s++)
        if (*s == '\t' || *s == '\n' || *s == '\r')
            *s = ' ';
}

//
// ledger add-existing --unit <a207> --keyset <file.dec> [--note <text>]
//                     [--tool manual|recovered]
//
// For keys a radio already holds that this tool did not record: written by
// the CPS, or by a -K whose ledger append failed.
// Nothing touches a radio; the operator vouches for it.
//
static void ledger_add_existing(int argc, char **argv)
{
    const char *unit = 0, *keyset = 0, *tool = "manual";
    char note[512] = "-", a207[80], line[8192], sha[65], path[1024];
    unsigned char blob[PRIVACY_TABLE_SIZE];
    roster_entry_t r;
    int i, n;

    for (i=0; i<argc; i++) {
        if (strcmp(argv[i], "--unit") == 0 && i+1 < argc)
            unit = argv[++i];
        else if (strcmp(argv[i], "--keyset") == 0 && i+1 < argc)
            keyset = argv[++i];
        else if (strcmp(argv[i], "--note") == 0 && i+1 < argc)
            snprintf(note, sizeof(note), "%s", argv[++i]);
        else if (strcmp(argv[i], "--tool") == 0 && i+1 < argc)
            tool = argv[++i];
        else
            die(EXIT_USAGE, "Usage: dmrconfig ledger add-existing --unit "
                "<a207> --keyset <file.dec> [--note <text>] "
                "[--tool manual|recovered]");
    }
    if (! unit || ! keyset)
        die(EXIT_USAGE, "ledger add-existing needs --unit and --keyset.");
    if (strpbrk(keyset, "\t\r\n") || strlen(keyset) > 2048)
        die(EXIT_USAGE, "The key file's name has a tab or newline in it, or "
            "is too long, and could not be recorded in the ledger.");
    if (strcmp(tool, "manual") != 0 && strcmp(tool, "recovered") != 0)
        die(EXIT_USAGE, "--tool is manual or recovered.");

    // The unit is the full a2 07 block in hex, as identify prints it.
    n = strlen(unit);
    if (n < 8 || n > 64 || (n & 1))
        die(EXIT_USAGE, "--unit must be the a2 07 block in hex, as "
            "'dmrconfig identify' shows it.");
    for (i=0; i<n; i++) {
        if (hexdigit(unit[i]) < 0)
            die(EXIT_USAGE, "--unit must be hex digits only.");
        a207[i] = (unit[i] >= 'A' && unit[i] <= 'F') ? unit[i] + 32 : unit[i];
    }
    a207[n] = 0;
    if (! note[0])
        strcpy(note, "-");
    tsv_clean(note);

    privacy_load_dec(keyset, blob);
    sha256_hex(blob, PRIVACY_TABLE_SIZE, sha);
    roster_lookup(a207, &r);

    state_path(path, sizeof(path), "ledger.tsv");
    if (ledger_append(a207, "-", r.radio_id, r.label, sha, keyset, tool,
            note, line, sizeof(line)) < 0)
        die(EXIT_LEDGER, "Cannot append to the ledger %s: %s.", path,
            strerror(errno));
    printf("%s\n", line);
    ev_begin("result");
    ev_str("command", "ledger_add_existing");
    ev_bool("ok", 1);
    ev_str("ledger", path);
    ev_str("line", line);
    ev_str("sha256", sha);
    ev_end();
}

void privacy_ledger_command(int argc, char **argv)
{
    if (argc >= 1 && strcmp(argv[0], "add-existing") == 0) {
        ledger_add_existing(argc - 1, argv + 1);
        return;
    }
    die(EXIT_USAGE, "Usage: dmrconfig ledger add-existing --unit <a207> "
        "--keyset <file.dec> [--note <text>] [--tool manual|recovered]");
}
