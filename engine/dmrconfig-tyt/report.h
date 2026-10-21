// SPDX-License-Identifier: BSD-3-Clause
/*
 * Machine-readable reporting for the tyt-plus fork: --json events on stdout,
 * one exit code per failure class.  See README-tyt-plus.md, "For programs".
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#ifndef REPORT_H
#define REPORT_H

#include <stdio.h>

//
// Exit codes.  Stable: TYTcps turns these into a
// result without reading any text.  The JSON "code" string of each is given
// in report.c.
//
enum {
    EXIT_OK                 = 0,
    EXIT_IO                 = 1,    // io_error: a file could not be read or written
    EXIT_USAGE              = 2,    // usage
    EXIT_NO_RADIO           = 3,    // no_radio: nothing on the bus
    EXIT_NO_PERMISSION      = 4,    // no_permission: libusb access denied
    EXIT_BUSY               = 5,    // busy: claimed by another process or a VM
    EXIT_UNSUPPORTED        = 6,    // unsupported_model
    EXIT_READS_DISAGREE     = 7,    // reads_disagree
    EXIT_WRITE_UNVERIFIED   = 8,    // write_unverified
    EXIT_TRANSFER           = 9,    // transfer_failed
    EXIT_KEYFILE            = 10,   // keyfile_invalid
    EXIT_CONF               = 11,   // conf_invalid
    EXIT_KEY_SLOT_EMPTY     = 12,   // key_slot_empty
    EXIT_LEDGER             = 13,   // ledger_failed
    EXIT_UNIT_UNREADABLE    = 14,   // unit_unreadable
    EXIT_MULTIPLE_RADIOS    = 15,   // multiple_radios
    EXIT_IMAGE              = 16,   // image_invalid
    EXIT_UNIT_MISMATCH      = 17,   // unit_mismatch: not the --expect-unit radio
    EXIT_KEYS_REFUSED       = 18,   // keys_refused: the radio refused the key table
    EXIT_UNCLASSIFIED       = 255,  // upstream code paths for other radio families
};

//
// What a failure did to the radio.  Every error event carries this, so the
// caller can say "nothing was written" or "the radio's contents are unknown"
// without guessing.
//
enum {
    RADIO_UNCHANGED = 0,            // nothing was written
    RADIO_CODEPLUG_INCOMPLETE,      // erase or write started and did not finish
    RADIO_CODEPLUG_DIFFERS,         // written, but read-back did not match
    RADIO_KEYS_UNKNOWN,             // key transfer started and did not finish
    RADIO_KEYS_WRITTEN,             // keys were written (ledger trouble after)
    RADIO_CODEPLUG_WRITTEN,         // codeplug written and verified
    RADIO_CODEPLUG_UNVERIFIED,      // written; the verify read did not finish
    RADIO_CONTACTS_INCOMPLETE,      // -u: contacts database write not finished
    RADIO_CONTACTS_WRITTEN,         // -u: contacts database written
};
extern int radio_state;

extern int json_mode;               // --json given

//
// Start JSON mode: stdout becomes the event stream, and everything the
// program would otherwise have printed to stdout goes to stderr instead.
//
void report_init(int json);

//
// Building one event.  Each is one line of JSON on stdout.  All of these are
// no-ops when --json was not given.
//
void ev_begin(const char *event);
void ev_str(const char *key, const char *value);   // null value -> JSON null
void ev_int(const char *key, long long value);
void ev_bool(const char *key, int value);
void ev_hex(const char *key, const unsigned char *data, int len);
void ev_obj(const char *key);       // key is null inside an array
void ev_obj_end(void);
void ev_arr(const char *key);
void ev_arr_end(void);
void ev_end(void);

//
// Common events.
//
void report_phase(const char *phase);
void report_progress(int done, int total);
void report_warning(const char *code, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
const char *report_current_phase(void);

//
// Print a progress mark on stderr and, every few percent, a progress event.
// Used by the codeplug and key transfers in place of their bare '#'.
//
void report_tick(int done, int total);

//
// Fail with an exit code.  die() prints the message on stderr, emits an
// error event, cleans up the radio session and exits.  For an error event
// with extra fields, call fail_begin(), add fields with ev_*(), then
// fail_end().
//
void die(int code, const char *fmt, ...)
    __attribute__((noreturn, format(printf, 2, 3)));
void fail_begin(int code);
void fail_end(const char *fmt, ...)
    __attribute__((noreturn, format(printf, 1, 2)));

//
// As fail_end(), for a caller that has printed its own human text: the
// message goes to the event only.
//
void fail_end_json(const char *msg) __attribute__((noreturn));

//
// Emit an error event without exiting, for checks that report every problem
// before giving up (conf validation).  The exit follows with fail_exit().
//
void error_event_end(const char *fmt, ...)
    __attribute__((format(printf, 1, 2)));
void fail_exit(int code) __attribute__((noreturn));

const char *exit_code_name(int code);

//
// Called on any die(): returns the radio to normal mode when nothing has been
// written, and releases the USB device.  Set by the radio layers.
//
void report_set_cleanup(void (*fn)(void));

//
// Fields added to every error event from here on, e.g. the unit and key set
// of a key write, so a failure part-way can still be recorded against them.
//
void report_context(const char *key, const char *value);

#endif
