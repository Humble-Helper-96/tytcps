// SPDX-License-Identifier: BSD-3-Clause
// Copyright (C) 2026 TYTcps contributors.  BSD-3 as the rest of dmrconfig.
/*
 * The stock CPS's pages as config text, for the TYT MD-UV380/UV390.
 * See cpsfields.c and TYTcps's docs/dev/field-map.md.
 */
#ifndef CPSFIELDS_H
#define CPSFIELDS_H

#include <stdio.h>

// Include after radio.h (which has no include guard).

// Table ids for the new config tables (the old ones use D A Z S C G M).
#define CPS_T_MENU          'U'
#define CPS_T_BUTTONS       'B'
#define CPS_T_ONETOUCH      'O'
#define CPS_T_NUMKEY        'N'
#define CPS_T_SCANTIMING    'T'
#define CPS_T_CHANDIG       'X'
#define CPS_T_CHANANA       'Y'

// Image ranges of the records the diff names.
#define CPS_GENERAL_END     0x20f0      // general record 0x2040-0x20ef
#define CPS_MENU_START      0x20f0
#define CPS_MENU_SIZE       16
#define CPS_BUTTONS_START   0x2100
#define CPS_BUTTONS_SIZE    0x14
#define CPS_ONETOUCH_START  0x2114
#define CPS_NUMKEY_START    0x212c

// Phase 7.6 pages.
#define CPS_T_EMSYS         'E'
#define CPS_T_DTMFSYS       'F'
#define CPS_T_DTMFENC       'H'
#define CPS_T_DTMFDEC       'I'

#define CPS_EMERG_START     0x5a70      // Digit Emergency System settings
#define CPS_EMERG_SIZE      0x10
#define CPS_EMS_START       0x5a80      // emergency systems 1-32
#define CPS_EMS_SIZE        0x28
#define CPS_NEMS            32
#define CPS_DS_START        0x30000     // DTMF systems DTMF-1..4
#define CPS_DS_SIZE         0x30
#define CPS_NDS             4
#define CPS_DE_START        0x300c0     // DTMF encode list 1-32
#define CPS_DE_SIZE         0x10
#define CPS_NDE             32
#define CPS_DD_START        0x302c0     // DTMF decode 1-8
#define CPS_DD_SIZE         0x18
#define CPS_NDD             8
#define CPS_VFO_START       0x2ef00     // VFO A, VFO B
#define CPS_VFO_SIZE        0x40
#define CPS_NVFO            2

typedef void (*cps_field_event_t)(const char *name, const char *oldv, const char *newv,
    char *human, int hsize);

int  cps_fields_enabled(radio_device_t *radio);
void cps_note_contacts(void);
void cps_note_messages(void);
void cps_check_channels(const unsigned char *before);
void cps_note_buttons(void);
void cps_check_refs(void);
void cps_print(FILE *out, int verbose);
void cps_parse_begin(void);
int  cps_parse_parameter(const char *param, const char *value);
int  cps_parse_header(const char *line);
int  cps_parse_row(int table_id, char *line);
void cps_parse_finish(void);
int  cps_verify(void);

void cps_diff_general(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered, unsigned clen, cps_field_event_t ev, char *human, int hsize);
int  cps_diff_record(const char *kind, const unsigned char *a, const unsigned char *b,
    unsigned rec_start, unsigned rec_len, unsigned char *covered, cps_field_event_t ev,
    char *human, int hsize);
void cps_diff_channel(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered, cps_field_event_t ev, char *human, int hsize);
void cps_record_name(const unsigned char *mem, const char *kind, int index, char *buf, int size);
void cps_diff_scanlist(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered, cps_field_event_t ev, char *human, int hsize);

#endif
