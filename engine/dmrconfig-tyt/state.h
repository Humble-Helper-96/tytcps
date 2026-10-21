// SPDX-License-Identifier: BSD-3-Clause
/*
 * The fleet folder: key-set ledger, radio roster and pre-write images.
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#ifndef STATE_H
#define STATE_H

//
// The fleet folder.  TYT_STATE_DIR when set (TYTcps always sets it);
// otherwise $XDG_DATA_HOME/tytcps, or ~/.local/share/tytcps.  Never a
// hard-coded path.
//
const char *state_dir(void);
void state_path(char *buf, int size, const char *name);

//
// Create the fleet folder (mode 0700) if it does not exist.
// Returns 0 on success, -1 with errno set.
//
int state_dir_ensure(void);

//
// SHA-256 of a buffer, as 64 hex digits.
//
void sha256_hex(const unsigned char *data, int len, char out[65]);

//
// Local time as 2026-10-11T18:56:59-0800.
//
void iso_now(char *buf, int size);

//
// The radio roster, radios.tsv.  One line per unit, keyed on the a2 07 block:
//
//      a207  radio_id  label  last_seen  last_write  flags
//
// The fork fills in radio_id, last_seen and last_write.  label and flags
// belong to the operator (TYTcps's Fleet tab) and are carried through
// verbatim.  There is no allow/refuse policy: the roster is for display, and
// to give a key write's ledger line a Radio ID.
//
typedef struct {
    char a207[80];
    char radio_id[32];
    char label[256];
    char last_seen[40];
    char last_write[40];
    char flags[64];
} roster_entry_t;

//
// Returns 1 and fills *e when the unit is listed; 0 otherwise, with *e set
// to "-" placeholders.
//
int roster_lookup(const char *a207, roster_entry_t *e);

//
// Record that this unit was seen now.  radio_id, when not null, replaces the
// recorded Radio ID; wrote_codeplug also stamps last_write.  A unit not yet
// listed is added.  Returns 0, or -1 after a warning event (the roster is a
// convenience: failing to update it never fails a radio operation).  A
// missing fleet folder is not created for this; the update is skipped.
//
int roster_seen(const char *a207, const char *radio_id, int wrote_codeplug);

//
// The ledger, ledger.tsv:
//
//      when  a207  serial  dmr_id  label  dec_sha256  dec_file  tool  note
//
// Lines written before the note column existed have eight fields.
//
// ledger_preflight() checks the ledger can be appended to before a key write
// starts; returns 0, or -1 with errno set.  ledger_append() returns 0, or -1
// with errno set; the line it wrote (or meant to write) is left in 'line'.
//
int ledger_preflight(char *path, int size);
int ledger_append(const char *a207, const char *serial, const char *dmrid,
    const char *label, const char *sha, const char *decfile,
    const char *tool, const char *note, char *line, int linesize);

//
// The pre-write image: the codeplug as the radio held it just before a -c or
// -w, saved as prewrite/<a207>-<YYYYMMDDTHHMMSSZ>-NN.img (UTC) in the fleet
// folder.
// The last PREWRITE_KEEP per unit are kept, and an image identical to the
// newest one kept is not saved again (*reused = 1, path names that one).
// Returns 0 and the path, or -1 with errno; ENOENT means there is no fleet
// folder, which the fork does not create for this, and ENODEV that the unit
// is unknown (a2 07 unreadable), when no image is kept.
//
#define PREWRITE_KEEP 5
int prewrite_save(const char *a207, const unsigned char *img, int len,
    char *path, int size, int *reused);

//
// Unit identity as read by the most recent DFU session, or "" when it was
// not read.  Set by dfu-libusb.c.
//
const char *unit_a207(void);
const char *unit_serial(void);
const char *unit_firmware(void);

#endif
