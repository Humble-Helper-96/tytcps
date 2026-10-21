// SPDX-License-Identifier: BSD-3-Clause
/*
 * The stock CPS's pages, as config text, for the TYT MD-UV380/UV390 (Plus).
 *
 * General Setting, Menu Item, Buttons Definitions (side buttons, One Touch
 * Access, Number Key quick contacts), scan-list timing and the channel
 * fields the Digital and Analog tables do not carry.  Every field is one
 * row of a table: where it is, how it is stored, and the word the CPS shows.
 * Print, parse and the diff's field names all come from these tables.
 *
 * The map is TYTcps's docs/dev/field-map.md: each offset was taken from
 * the CPS v2.41 binary's own getters and setters and cross-checked against
 * qdmr and md380tools.  It replaces the fork's general_settings_t bitfields
 * for these bytes, which are mirrored (bit n is really 7-n) in 0x2080-0x2082
 * and 0x2095.
 *
 * Rules (cps-field-map.md section 4.1):
 *  R1 Absent means untouched: a key, table or row the config does not carry
 *     leaves its bytes as they are.
 *  R2 Write only on change: a value is written only when it prints
 *     differently from what the image holds, so raw values that print the
 *     same (Keypad Lock 0x00 and 0xFF are both Manual) survive.
 *  R3 A value with no CPS word prints as raw:0xNN and parses back to it.
 *  R4 Checkboxes print + or - as the CPS box shows them; inversions are
 *     handled here.  Units are the CPS's (ms, s).
 *
 * The three passwords and Model Select A/B were settled by CPS-saved files:
 * BCD passwords most significant digit first,
 * the PC password ASCII then 0x00, Model Select A bit 2.
 *
 * Digit Emergency System, DTMF Signaling and VFO Mode come from
 * the CPS-saved files for those pages and, for the controls those files
 * could not reach (VFO B, DTMF systems 2-4, the encode and decode lists,
 * the emergency systems' own fields), from the CPS v2.41 binary's getters
 * and setters.
 *
 * Copyright (C) 2026 TYTcps contributors.  BSD-3 as the rest of dmrconfig.
 */
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>
#include <ctype.h>
#include <errno.h>
#include "radio.h"
#include "util.h"
#include "report.h"
#include "cpsfields.h"

#define CH_BASE     0x40000
#define CH_SIZE     64
#define NCH         3000
#define SL_BASE     0x18860
#define SL_SIZE     104
#define NSL         250
#define CT_BASE     0x70000
#define CT_SIZE     36
#define NCT         10000
#define MSG_BASE    0x02180
#define MSG_SIZE    288
#define NMSG        50

enum {
    K_BOOL,         // + / -
    K_ENUM,         // names[raw]
    K_NUM,          // raw * scale (+ base); zero_word for raw 0 if set
    K_ID32,         // uint32 LE Radio ID, FFFFFFFF = '-'
    K_KEYLOCK,      // 1/2/3 = 5/10/15 s, anything else Manual (written 0xFF)
    K_FREQMODE,     // 0 = Freq, any other = Channel (written 0x00 / 0xFF)
    K_TZ,           // index 0..24 = UTC -12..+12
    K_BCD8,         // 8 BCD digits, most significant first (read-only)
    K_ASCII8,       // ASCII password, 0x00 then 0xFF (read-only)
    K_U16,          // uint16 LE index, 0 = '-'
    K_DECODE,       // 8-bit mask as "12------"
    K_CODE,         // button function code
    K_FREQ,         // 8 BCD digits, little-endian, 10 Hz units: 467.55000
    K_TONE,         // CTCSS 67.0, DCS D023N/D023I, - = none (0xFFFF)
    K_TENTHS,       // raw / 10 with one decimal: 2.0
    K_DTMF,         // DTMF digits: length byte, then nibbles low first; - = none
    K_NAME16,       // 16 UTF-16 characters, zero-padded; - = none
    K_EREVERT,      // uint16 channel: 0 '-', 0xFFFE Selected
    K_DREVERT,      // uint16 channel: 0 Selected
    K_VPRIVNO,      // VFO Privacy No.: +0x02 low nibble, and for Universal the
                    // +0x1E high nibble too (an 8-bit key index)
};

#define F_INV   0x01        // stored inverted: bit 0 = box checked
#define F_RO    0x02        // printed, never parsed
#define F_ONE   0x04        // CPS-only (single source): the CPS writes it,
                            // what the firmware does with it is untested

typedef struct {
    const char *key;
    unsigned off;           // absolute, or within the record
    unsigned char mask;     // bits of the byte (0 = whole field, see width)
    unsigned char width;    // bytes, for K_NUM/K_U16/K_ID32/...
    unsigned char kind, flags;
    int scale, base;        // display = raw * scale + base
    int lo, hi;             // raw range accepted from the config
    const char *const *names;
    int nnames;
    const char *zero;       // display word for raw zraw (K_NUM)
    int zraw;               // the raw value that word stands for (usually 0)
} cfield_t;

// Fields whose value is bytes, not a number: set by cf_set_text().
#define BYTE_KIND(k)    ((k) == K_DTMF || (k) == K_NAME16)

static const char *const W_TALKPERMIT[] = { "None", "Digital", "Analog", "Analog & Digital" };
static const char *const W_MONITOR[]    = { "Silent", "Open Squelch" };
static const char *const W_VOICE[]      = { "English", "Chinese" };
static const char *const W_BACKLIGHT[]  = { "Always", "5", "10", "15" };
static const char *const W_MODEL[]      = { "VFO", "MR" };
static const char *const W_INTRO[]      = { "Char String", "Picture" };
static const char *const W_TXMODE[]     = { "Last Call CH", "Last Call CH + HandCH",
                                            "Designed CH", "Designed CH + HandCH" };
static const char *const W_WIDTH[]      = { "12.5", "20", "25" };
static const char *const W_REF[]        = { "Low", "Medium", "High" };
static const char *const W_LEADER[]     = { "Leader", "MS" };
static const char *const W_INCALL[]     = { "Always", "Follow", "TxInt" };
static const char *const W_MSGFMT[]     = { "DMR", "M" };
static const char *const W_SIG[]        = { "Off", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4" };
static const char *const W_QTREV[]      = { "180", "120", "240", "Silent" };
static const char *const W_TURNOFF[]    = { "259.2", "55.2", "None", "None" };
static const char *const W_OTMODE[]     = { "None", "Digital", "Analog" };

#define E(names) names, (int) (sizeof(names)/sizeof(names[0]))
#define NOE 0, 0

//
// General Setting (0x2040-0x20EF), Menu Hang Time and Long Press Duration,
// in the CPS's screen order.  lo..hi are the CPS's own spin limits, so a
// value the CPS cannot show prints as raw:0xNN (R3) rather than as a number
// the CPS would never offer.  Radio Name, Radio ID and the intro lines keep
// the config's existing keys (Name:, ID:, Intro Line 1/2:).
//
static const cfield_t GENERAL[] = {
    { "Save Preamble",                  0x2081, 0x01, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Save Mode Receive",              0x2081, 0x02, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Disable All Tone",               0x2081, 0x04, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "CH Free Indication Tone",        0x2081, 0x10, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Talk Permit Tone",               0x2081, 0xC0, 1, K_ENUM, 0,     0, 0, 0, 3, E(W_TALKPERMIT), 0 },
    { "Call Alert Tone Duration[s]",    0x208F, 0x00, 1, K_NUM,  0,     5, 0, 0, 240, NOE, "Continue" },
    { "Scan Digital Hang Time[ms]",     0x2093, 0x00, 1, K_NUM,  0,   100, 0, 5, 100, NOE, 0 },
    { "Scan Analog Hang Time[ms]",      0x2094, 0x00, 1, K_NUM,  0,   100, 0, 0, 100, NOE, 0 },
    { "Lone Worker Response Time[min]", 0x2090, 0x00, 1, K_NUM,  0,     1, 0, 1, 255, NOE, 0 },
    { "Lone Worker Reminder Time[s]",   0x2091, 0x00, 1, K_NUM,  0,     1, 0, 1, 255, NOE, 0 },
    { "Password and Lock Enable",       0x2081, 0x20, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Power On Password",              0x2098, 0x00, 4, K_BCD8, 0,     0, 0, 0, 0, NOE, 0 },
    { "CH Voice Announcement",          0x2082, 0x02, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Voice Announcement",             0x2082, 0x04, 1, K_ENUM, F_ONE, 0, 0, 0, 1, E(W_VOICE), 0 },
    { "Monitor Type",                   0x2080, 0x10, 1, K_ENUM, 0,     0, 0, 0, 1, E(W_MONITOR), 0 },
    { "VOX Sensitivity",                0x208B, 0x00, 1, K_NUM,  0,     1, 0, 1, 10, NOE, 0 },
    { "TX Preamble Duration[ms]",       0x2088, 0x00, 1, K_NUM,  0,    60, 0, 0, 144, NOE, 0 },
    { "RX Low Battery Interval[s]",     0x208E, 0x00, 1, K_NUM,  0,     5, 0, 0, 127, NOE, 0 },
    { "Channels Hang Time[ms]",         0x20D0, 0x00, 1, K_NUM,  0,   100, 0, 0, 70, NOE, 0 },
    { "PC Programming Password",        0x20A0, 0x00, 8, K_ASCII8, 0,   0, 0, 0, 0, NOE, 0 },
    { "Radio Program Password",         0x209C, 0x00, 4, K_BCD8, 0,     0, 0, 0, 0, NOE, 0 },
    { "Back Light Time[s]",             0x2095, 0x00, 1, K_ENUM, 0,     0, 0, 0, 3, E(W_BACKLIGHT), 0 },
    { "Set Keypad Lock Time[s]",        0x2096, 0x00, 1, K_KEYLOCK, 0,  0, 0, 0, 0, NOE, 0 },
    { "Freq/Channel Mode",              0x2097, 0x00, 1, K_FREQMODE, 0, 0, 0, 0, 0, NOE, 0 },
    { "Model Select A",                 0x2083, 0x04, 1, K_ENUM, 0,     0, 0, 0, 1, E(W_MODEL), 0 },
    { "Model Select B",                 0x2083, 0x80, 1, K_ENUM, 0,     0, 0, 0, 1, E(W_MODEL), 0 },
    { "Time Zone",                      0x20AB, 0xF8, 1, K_TZ,   0,     0, 0, 0, 24, NOE, 0 },
    { "Disable All LEDs",               0x2080, 0x04, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Group Call Match",               0x20AB, 0x01, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Private Call Match",             0x20AB, 0x02, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Group Call Hang Time[ms]",       0x2089, 0x00, 1, K_NUM,  0,   100, 0, 0, 70, NOE, 0 },
    { "Private Call Hang Time[ms]",     0x208A, 0x00, 1, K_NUM,  0,   100, 0, 0, 70, NOE, 0 },
    { "Intro Screen",                   0x2082, 0x10, 1, K_ENUM, 0,     0, 0, 0, 1, E(W_INTRO), 0 },
    { "Radio ID 1",                     0x20D4, 0x00, 4, K_ID32, 0,     0, 0, 1, 16776415, NOE, 0 },
    { "Radio ID 2",                     0x20D8, 0x00, 4, K_ID32, 0,     0, 0, 1, 16776415, NOE, 0 },
    { "Radio ID 3",                     0x20DC, 0x00, 4, K_ID32, 0,     0, 0, 1, 16776415, NOE, 0 },
    { "MIC Level",                      0x20E0, 0x38, 1, K_NUM,  0,     1, 1, 0, 5, NOE, 0 },
    { "Tx Mode",                        0x2080, 0xC0, 1, K_ENUM, 0,     0, 0, 0, 3, E(W_TXMODE), 0 },
    { "Front Keyboard Lock",            0x20E2, 0x04, 1, K_BOOL, F_INV|F_ONE, 0, 0, 0, 1, NOE, 0 },
    { "Edit Radio ID",                  0x20E0, 0x40, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Public Zone",                    0x20D2, 0x04, 1, K_BOOL, 0,     0, 0, 0, 1, NOE, 0 },
    { "Power On Voice",                 0x20E2, 0x20, 1, K_BOOL, F_ONE, 0, 0, 0, 1, NOE, 0 },
    { "TX/RX LED",                      0x20EA, 0x01, 1, K_BOOL, F_ONE, 0, 0, 0, 1, NOE, 0 },
    { "Menu Hang Time[s]",              0x20F0, 0x00, 1, K_NUM,  0,     1, 0, 0, 30, NOE, "Hang" },
    { "Long Press Duration[ms]",        0x2111, 0x00, 1, K_NUM,  0,   250, 0, 4, 40, NOE, 0 },
};
#define NGENERAL ((int) (sizeof(GENERAL) / sizeof(GENERAL[0])))

//
// Menu Item (0x20F0-0x20F7), the visible boxes in the CPS's order.
// + = the item is in the radio's menu.
//
static const cfield_t MENU[] = {
    { "Text_Message",        0x20F1, 0x01, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Call_Alert",          0x20F1, 0x02, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Edit_Contact",        0x20F1, 0x04, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Manual_Dial",         0x20F1, 0x08, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "New_Contact",         0x20F7, 0x40, 1, K_BOOL, F_INV|F_ONE, 0,0,0,1, NOE, 0 },
    { "Remote_Monitor",      0x20F1, 0x20, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Group_Call",          0x20F7, 0x80, 1, K_BOOL, F_INV|F_ONE, 0,0,0,1, NOE, 0 },
    { "Radio_Enable",        0x20F1, 0x40, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Radio_Check",         0x20F1, 0x10, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Radio_Disable",       0x20F1, 0x80, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Program_Key",         0x20F2, 0x01, 1, K_BOOL, F_ONE, 0,0,0,1, NOE, 0 },
    { "Missed",              0x20F2, 0x08, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Answered",            0x20F2, 0x10, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Outgoing_Radio",      0x20F2, 0x20, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Delete_All_Records",  0x20F7, 0x08, 1, K_BOOL, F_ONE, 0,0,0,1, NOE, 0 },
    { "Zone",                0x20F5, 0x40, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Edit_Zone",           0x20F6, 0x01, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "New_Zone_List",       0x20F5, 0x80, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Talkaround",          0x20F2, 0x40, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Tone_or_Alert",       0x20F2, 0x80, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Power",               0x20F3, 0x01, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Backlight",           0x20F3, 0x02, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Intro_Screen",        0x20F3, 0x04, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Keyboard_Lock",       0x20F3, 0x08, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "LED_Indicator",       0x20F3, 0x10, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Squelch",             0x20F3, 0x20, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "VOX",                 0x20F3, 0x80, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Password_and_Lock",   0x20F4, 0x01, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Display_Mode",        0x20F4, 0x02, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Program_Radio",       0x20F4, 0x04, 1, K_BOOL, F_INV, 0,0,0,1, NOE, 0 },
    { "Group_Call_Match",    0x20F5, 0x04, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Record_Switch",       0x20F4, 0x20, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Private_Call_Match",  0x20F5, 0x08, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "TX_Mode",             0x20F5, 0x20, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Monitor",             0x20F6, 0x08, 1, K_BOOL, F_ONE, 0,0,0,1, NOE, 0 },
    { "Select_Radio_ID",     0x20F7, 0x04, 1, K_BOOL, F_ONE, 0,0,0,1, NOE, 0 },
    { "Menu_Hang_Time",      0x20F5, 0x10, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Power_On_Voice",      0x20F7, 0x10, 1, K_BOOL, F_ONE, 0,0,0,1, NOE, 0 },
    { "Scan",                0x20F2, 0x02, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "Edit_List",           0x20F2, 0x04, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
    { "New_Scan_List",       0x20F6, 0x02, 1, K_BOOL, 0,     0,0,0,1, NOE, 0 },
};
#define NMENU ((int) (sizeof(MENU) / sizeof(MENU[0])))

//
// Side buttons: KeyData function codes (the CPS's keydata.ini [MD-UV390]
// allowed set, the same for all four).  Any other code prints as raw:0xNN.
//
static const struct { int code; const char *name; } BUTTON_FN[] = {
    {  0, "Unassigned" }, {  1, "All_Alert_Tones_On/Off" }, {  2, "Emergency_On" },
    {  3, "Emergency_Off" }, {  4, "Power_Select" }, {  5, "Monitor" },
    {  7, "One_Touch_Access_1" }, {  8, "One_Touch_Access_2" },
    {  9, "One_Touch_Access_3" }, { 10, "One_Touch_Access_4" },
    { 11, "One_Touch_Access_5" }, { 12, "One_Touch_Access_6" },
    { 13, "Repeater/Talkaround" }, { 14, "Scan_On/Off" }, { 21, "Squelch_Level" },
    { 22, "Privacy_On/Off" }, { 23, "VOX_On/Off" }, { 24, "Zone_+" },
    { 26, "Battery_Indicator" }, { 31, "Lone_Work_On/Off" }, { 34, "Record_On/Off" },
    { 35, "Record_Playback" }, { 36, "Delete_All_Record" }, { 38, "1750Hz" },
    { 47, "Switch_Up/Down_Screen" }, { 48, "Right_Key" }, { 49, "Left_Key" },
    { 55, "Zone_-" },
};
#define NBUTTON_FN ((int) (sizeof(BUTTON_FN) / sizeof(BUTTON_FN[0])))

static const struct { const char *name; unsigned shrt, lng; } BUTTONS[] = {
    { "Side_Button1", 0x2102, 0x2103 },
    { "Side_Button2", 0x2104, 0x2105 },
};
#define NBUTTONS 2

#define OT_BASE     0x2114          // One Touch Access rows 1-6, 4 bytes each
#define NONETOUCH   6
#define NK_BASE     0x212C          // Number Key 0-9 quick contacts, uint16
#define NNUMKEY     10

//
// Channel fields beyond the Digital/Analog tables, keyed by channel.
// Offsets are within the 64-byte record.
//
static const cfield_t CHANDIG[] = {
    { "Width",  0x00, 0x0C, 1, K_ENUM, 0,     0,0, 0, 2, E(W_WIDTH), 0 },
    { "Sq",     0x0F, 0x00, 1, K_NUM,  0,     1,0, 0, 9, NOE, 0 },
    { "RxRef",  0x03, 0x03, 1, K_ENUM, 0,     0,0, 0, 2, E(W_REF), 0 },
    { "TxRef",  0x04, 0x03, 1, K_ENUM, 0,     0,0, 0, 2, E(W_REF), 0 },
    { "Rekey",  0x09, 0x00, 1, K_NUM,  0,     1,0, 0, 255, NOE, 0 },
    { "AS",     0x00, 0x10, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "LW",     0x00, 0x80, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "VOX",    0x04, 0x10, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "TA",     0x01, 0x01, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "PCC",    0x02, 0x40, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "EAA",    0x03, 0x08, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "DCC",    0x02, 0x80, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "AI",     0x1F, 0x04, 1, K_BOOL, F_INV, 0,0, 0, 1, NOE, 0 },
    { "DCDM",   0x1F, 0x08, 1, K_BOOL, F_INV, 0,0, 0, 1, NOE, 0 },
    { "Leader", 0x1F, 0x10, 1, K_ENUM, 0,     0,0, 0, 1, E(W_LEADER), 0 },
    { "EmSys",  0x0A, 0x00, 1, K_NUM,  0,     1,0, 0, 32, NOE, "-" },
    { "InCall", 0x05, 0x30, 1, K_ENUM, 0,     0,0, 0, 2, E(W_INCALL), 0 },
    { "MsgFmt", 0x1F, 0x40, 1, K_ENUM, F_ONE, 0,0, 0, 1, E(W_MSGFMT), 0 },
};
#define NCHANDIG ((int) (sizeof(CHANDIG) / sizeof(CHANDIG[0])))

static const cfield_t CHANANA[] = {
    { "RxRef",    0x03, 0x03, 1, K_ENUM, 0,     0,0, 0, 2, E(W_REF), 0 },
    { "TxRef",    0x04, 0x03, 1, K_ENUM, 0,     0,0, 0, 2, E(W_REF), 0 },
    { "Rekey",    0x09, 0x00, 1, K_NUM,  0,     1,0, 0, 255, NOE, 0 },
    { "AS",       0x00, 0x10, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "LW",       0x00, 0x80, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "VOX",      0x04, 0x10, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "TA",       0x01, 0x01, 1, K_BOOL, 0,     0,0, 0, 1, NOE, 0 },
    { "RxSig",    0x1C, 0x00, 1, K_ENUM, 0,     0,0, 0, 4, E(W_SIG), 0 },
    { "TxSig",    0x1D, 0x00, 1, K_ENUM, 0,     0,0, 0, 4, E(W_SIG), 0 },
    { "QTRev",    0x05, 0x03, 1, K_ENUM, F_ONE, 0,0, 0, 3, E(W_QTREV), 0 },
    { "TurnOff",  0x05, 0xC0, 1, K_ENUM, 0,     0,0, 0, 3, E(W_TURNOFF), 0 },
    { "PTTID",    0x03, 0x80, 1, K_BOOL, F_INV, 0,0, 0, 1, NOE, 0 },
    { "RevBurst", 0x04, 0x04, 1, K_BOOL, F_ONE, 0,0, 0, 1, NOE, 0 },
    { "Decode",   0x0E, 0x00, 1, K_DECODE, 0,   0,0, 0, 255, NOE, 0 },
};
#define NCHANANA ((int) (sizeof(CHANANA) / sizeof(CHANANA[0])))

static const cfield_t SCANTIMING[] = {
    { "Hold[ms]",   0x27, 0x00, 1, K_NUM, 0,  25, 0, 0, 255, NOE, 0 },
    { "Sample[ms]", 0x28, 0x00, 1, K_NUM, 0, 250, 0, 0, 255, NOE, 0 },
};
#define NSCANTIMING 2

//
// Digit Emergency System: the page's own settings (absolute offsets), then
// one table row per system (offsets within its 0x28-byte record).  Remote
// Monitor Duration and Hot Mic Duration are whole seconds in the image (the
// CPS's getters return the byte as it is; qdmr's x10 is wrong).
//
static const char *const W_ALARMTYPE[] = { "Disabled", "Regular", "Silent", "Silent_w/Voice" };
static const char *const W_ALARMMODE[] = { "Emergency_Alarm", "Emergency_Alarm_w/Call",
                                           "Emergency_Alarm_w/Voice_To_Follow" };

static const cfield_t EMERG[] = {
    { "Radio Disable Decode",            0x5A70, 0x01, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Remote Monitor Decode",           0x5A70, 0x02, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Emergency Remote Monitor Decode", 0x5A70, 0x04, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Remote Monitor Duration[s]",      0x5A71, 0x00, 1, K_NUM,  0, 1, 0, 10, 120, NOE, 0 },
    { "Tx Sync Wakeup TOT[ms]",          0x5A72, 0x00, 1, K_NUM,  0, 25, 0, 5, 15, NOE, 0 },
    { "Tx Wakeup Message Limit",         0x5A73, 0x00, 1, K_NUM,  0, 1, 0, 1, 4, NOE, 0 },
};
#define NEMERG ((int) (sizeof(EMERG) / sizeof(EMERG[0])))

// Bits 2, 3 and 6 of +0x20 are not the CPS's: a new system from erased
// (0xFF) bytes gets 0x4D there, exactly as the CPS's Add.
static const cfield_t EMSYS[] = {
    { "Name",      0x00, 0x00, 32, K_NAME16, 0, 0, 0, 0, 0, NOE, 0 },
    { "AlarmType", 0x20, 0x03, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_ALARMTYPE), 0 },
    { "AlarmMode", 0x20, 0x30, 1, K_ENUM, 0, 0, 0, 0, 2, E(W_ALARMMODE), 0 },
    { "TxInt",     0x20, 0x80, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Impolite",  0x21, 0x00, 1, K_NUM,  0, 1, 0, 1, 15, NOE, 0 },
    { "Polite",    0x22, 0x00, 1, K_NUM,  0, 1, 0, 0, 14, NOE, "Infinite", 15 },
    { "HotMic[s]", 0x23, 0x00, 1, K_NUM,  0, 1, 0, 10, 120, NOE, 0 },
    { "Revert",    0x24, 0x00, 2, K_EREVERT, 0, 0, 0, 1, NCH, NOE, 0 },
};
#define NEMSYS ((int) (sizeof(EMSYS) / sizeof(EMSYS[0])))

//
// DTMF Signaling: systems DTMF-1..4 (the CPS's tabs), the encode list and
// the decode entries.  Times are the CPS's (x10 ms, x50 ms, x0.1 s).  The
// CPS's spin for D Key Assignment starts at 1 ms, so its up-arrow from
// "D Key" stores 0 again (DTM_2318_up has no change).
//
static const char *const W_PTTID[]     = { "None", "Pre_Only", "Post_Only", "Pre_&_Post" };
static const char *const W_GROUPCODE[] = { "None", "A", "B", "C", "D", "*", "#" };
static const char *const W_RESPONSE[]  = { 0, "Kill", 0, "Active" };
static const char *const W_DECTYPE[]   = { "None", "Sel_Call" };

static const cfield_t DTMFSYS[] = {
    { "FirstDelay[ms]", 0x00, 0x00, 1, K_NUM, 0, 10, 0, 10, 255, NOE, 0 },
    { "FirstTime[ms]",  0x01, 0x00, 1, K_NUM, 0, 10, 0, 3, 255, NOE, 0 },
    { "Duration[ms]",   0x02, 0x00, 1, K_NUM, 0, 10, 0, 3, 255, NOE, 0 },
    { "Interval[ms]",   0x03, 0x00, 1, K_NUM, 0, 10, 0, 3, 255, NOE, 0 },
    { "StarHash[ms]",   0x04, 0x00, 1, K_NUM, 0, 10, 0, 0, 255, NOE, 0 },
    { "DKey[ms]",       0x05, 0x00, 1, K_NUM, 0, 10, 0, 1, 255, NOE, "D_Key" },
    { "NextSeq[s]",     0x06, 0x00, 1, K_TENTHS, 0, 0, 0, 2, 255, NOE, 0 },
    { "AutoReset[s]",   0x07, 0x00, 1, K_NUM, 0, 1, 0, 1, 255, NOE, 0 },
    { "SideTone",       0x08, 0x01, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "PTTID",          0x08, 0x0C, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_PTTID), 0 },
    { "GroupCode",      0x08, 0xF0, 1, K_ENUM, 0, 0, 0, 0, 6, E(W_GROUPCODE), 0 },
    { "KeyUp",          0x10, 0x00, 16, K_DTMF, 0, 0, 0, 0, 0, NOE, 0 },
    { "KeyDown",        0x20, 0x00, 16, K_DTMF, 0, 0, 0, 0, 0, NOE, 0 },
};
#define NDTMFSYS ((int) (sizeof(DTMFSYS) / sizeof(DTMFSYS[0])))

static const cfield_t DTMFENC[] = {
    { "Code",           0x00, 0x00, 16, K_DTMF, 0, 0, 0, 0, 0, NOE, 0 },
};
#define NDTMFENC 1

static const cfield_t DTMFDEC[] = {
    { "ID",             0x00, 0x00, 16, K_DTMF, 0, 0, 0, 0, 0, NOE, 0 },
    { "Response",       0x10, 0x00, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_RESPONSE), 0 },
    { "DecodeType",     0x11, 0x00, 1, K_ENUM, 0, 0, 0, 0, 1, E(W_DECTYPE), 0 },
    { "ACK",            0x12, 0x00, 1, K_NUM, 0, 1, 0, 1, CPS_NDE, NOE, "-" },
    { "ACKDelay[ms]",   0x13, 0x00, 1, K_NUM, 0, 50, 0, 1, 255, NOE, "Off" },
    { "Revert",         0x14, 0x00, 2, K_DREVERT, 0, 0, 0, 1, NCH, NOE, 0 },
};
#define NDTMFDEC ((int) (sizeof(DTMFDEC) / sizeof(DTMFDEC[0])))

//
// VFO Mode: VFO A and VFO B are channel records (CPS indexes 4029/4030) and
// the CPS edits them with the channel accessors, so every offset is the
// channel table's; Step is the VFO's own byte at +0x20.  The keys are the
// CPS's labels, after "VFO A " or "VFO B ".  Privacy None clears the type,
// the key and the switch at +0x05, as the CPS's Privacy Switch does (CHD_1811).
//
static const char *const W_CHMODE[]  = { 0, "Analog", "Digital" };
static const char *const W_POWER[]   = { "Low", 0, "Middle", "High" };
static const char *const W_STEP[]    = { "2.5", "5", "6.25", "8.33", "10", "12.5", "20", "25",
                                         "30", "50" };
static const char *const W_ADMIT[]   = { "Always", "Channel Free", "Correct CTCSS/CDCSS",
                                         "Color Code" };
static const char *const W_PRIVACY[] = { "None", "Basic", "Enhanced", "Universal" };

static const cfield_t VFOF[] = {
    { "Channel Mode",              0x00, 0x03, 1, K_ENUM, 0, 0, 0, 1, 2, E(W_CHMODE), 0 },
    { "Band Width",                0x00, 0x0C, 1, K_ENUM, 0, 0, 0, 0, 2, E(W_WIDTH), 0 },
    { "Squelch",                   0x0F, 0x00, 1, K_NUM,  0, 1, 0, 0, 9, NOE, 0 },
    { "RX Ref Frequency",          0x03, 0x03, 1, K_ENUM, 0, 0, 0, 0, 2, E(W_REF), 0 },
    { "TX Ref Frequency",          0x04, 0x03, 1, K_ENUM, 0, 0, 0, 0, 2, E(W_REF), 0 },
    { "TOT[s]",                    0x08, 0x3F, 1, K_NUM,  0, 15, 0, 1, 37, NOE, "Infinite" },
    { "TOT Rekey Delay[s]",        0x09, 0x00, 1, K_NUM,  0, 1, 0, 0, 255, NOE, 0 },
    { "Power",                     0x1E, 0x03, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_POWER), 0 },
    { "Step[kHz]",                 0x20, 0x00, 1, K_ENUM, 0, 0, 0, 0, 9, E(W_STEP), 0 },
    { "RX Frequency(MHz)",         0x10, 0x00, 4, K_FREQ, 0, 0, 0, 0, 0, NOE, 0 },
    { "TX Frequency(MHz)",         0x14, 0x00, 4, K_FREQ, 0, 0, 0, 0, 0, NOE, 0 },
    { "Admit Criteria",            0x04, 0xC0, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_ADMIT), 0 },
    { "Auto Scan",                 0x00, 0x10, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Rx Only",                   0x01, 0x02, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Lone Worker",               0x00, 0x80, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "VOX",                       0x04, 0x10, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Allow Talkaround",          0x01, 0x01, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Scan List",                 0x0B, 0x00, 1, K_NUM,  0, 1, 0, 1, NSL, NOE, "-" },
    { "CTCSS/DCS Dec",             0x18, 0x00, 2, K_TONE, 0, 0, 0, 0, 0, NOE, 0 },
    { "CTCSS/DCS Enc",             0x1A, 0x00, 2, K_TONE, 0, 0, 0, 0, 0, NOE, 0 },
    { "Rx Signaling System",       0x1C, 0x00, 1, K_ENUM, 0, 0, 0, 0, 4, E(W_SIG), 0 },
    { "Tx Signaling System",       0x1D, 0x00, 1, K_ENUM, 0, 0, 0, 0, 4, E(W_SIG), 0 },
    { "QT Reverse",                0x05, 0x03, 1, K_ENUM, F_ONE, 0, 0, 0, 3, E(W_QTREV), 0 },
    { "Reverse Burst/Turn-off Code", 0x04, 0x04, 1, K_BOOL, F_ONE, 0, 0, 0, 1, NOE, 0 },
    { "Non-QT/DQT Turn-off Freq",  0x05, 0xC0, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_TURNOFF), 0 },
    { "Display PTT ID",            0x03, 0x80, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Decode",                    0x0E, 0x00, 1, K_DECODE, 0, 0, 0, 0, 255, NOE, 0 },
    { "Color Code",                0x01, 0xF0, 1, K_NUM,  0, 1, 0, 0, 15, NOE, 0 },
    { "Repeater Slot",             0x01, 0x0C, 1, K_NUM,  0, 1, 0, 1, 2, NOE, 0 },
    { "Contact Name",              0x06, 0x00, 2, K_U16,  0, 0, 0, 1, NCT, NOE, 0 },
    { "Group List",                0x0C, 0x00, 1, K_NUM,  0, 1, 0, 1, 250, NOE, "-" },
    { "Emergency System",          0x0A, 0x00, 1, K_NUM,  0, 1, 0, 1, CPS_NEMS, NOE, "-" },
    { "Privacy",                   0x02, 0x30, 1, K_ENUM, 0, 0, 0, 0, 3, E(W_PRIVACY), 0 },
    { "Privacy No.",               0x02, 0x00, 1, K_VPRIVNO, 0, 0, 0, 0, 15, NOE, 0 },
    { "In Call Criteria",          0x05, 0x30, 1, K_ENUM, 0, 0, 0, 0, 2, E(W_INCALL), 0 },
    { "Private Call Confirmed",    0x02, 0x40, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Emergency Alarm Ack",       0x03, 0x08, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Data Call Confirmed",       0x02, 0x80, 1, K_BOOL, 0, 0, 0, 0, 1, NOE, 0 },
    { "Allow Interrupt",           0x1F, 0x04, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "DCDM Switch",               0x1F, 0x08, 1, K_BOOL, F_INV, 0, 0, 0, 1, NOE, 0 },
    { "Leader/MS",                 0x1F, 0x10, 1, K_ENUM, 0, 0, 0, 0, 1, E(W_LEADER), 0 },
    { "Message Format",            0x1F, 0x40, 1, K_ENUM, F_ONE, 0, 0, 0, 1, E(W_MSGFMT), 0 },
};
#define NVFOF ((int) (sizeof(VFOF) / sizeof(VFOF[0])))

// ---------------------------------------------------------------------------
// Decoding and encoding one field.
// ---------------------------------------------------------------------------

static int shift_of(unsigned char mask)
{
    int s = 0;

    if (! mask)
        return 0;
    while (! (mask & 1)) {
        mask >>= 1;
        s++;
    }
    return s;
}

static unsigned long get_le(const unsigned char *p, int n)
{
    unsigned long v = 0;
    int i;

    for (i=n-1; i>=0; i--)
        v = (v << 8) | p[i];
    return v;
}

static void put_le(unsigned char *p, int n, unsigned long v)
{
    int i;

    for (i=0; i<n; i++) {
        p[i] = v & 0xff;
        v >>= 8;
    }
}

// The stored value: masked bits shifted down, or a whole little-endian field.
static long cf_get(const unsigned char *rec, const cfield_t *f)
{
    if (BYTE_KIND(f->kind))
        return 0;
    if (f->kind == K_VPRIVNO)
        return (rec[0x02] & 0x0f) | (((rec[0x02] & 0x30) == 0x30) ? (rec[0x1E] & 0xf0) : 0);
    if (f->mask)
        return (rec[f->off] & f->mask) >> shift_of(f->mask);
    return (long) get_le(&rec[f->off], f->width);
}

static void cf_put(unsigned char *rec, const cfield_t *f, long raw)
{
    if (f->kind == K_VPRIVNO) {
        rec[0x02] = (rec[0x02] & 0xf0) | (raw & 0x0f);
        if ((rec[0x02] & 0x30) == 0x30)
            rec[0x1E] = (rec[0x1E] & 0x0f) | (raw & 0xf0);
        return;
    }
    if (f->mask) {
        int s = shift_of(f->mask);

        rec[f->off] = (rec[f->off] & ~f->mask) | (((unsigned long) raw << s) & f->mask);
    } else {
        put_le(&rec[f->off], f->width, (unsigned long) raw);
    }
}

// Each of the n low nibbles is a decimal digit.
static int bcd_valid(unsigned long v, int n)
{
    int i;

    for (i=0; i<n; i++, v >>= 4)
        if ((v & 0xf) > 9)
            return 0;
    return 1;
}

static unsigned long to_bcd(unsigned long v)
{
    unsigned long r = 0;
    int shift = 0;

    do {
        r |= (v % 10) << shift;
        v /= 10;
        shift += 4;
    } while (v);
    return r;
}

//
// CTCSS 0x0670 = 67.0, DCS 0x8023 = D023N and 0xC023 = D023I, 0xFFFF = none.
// A tone the radio's lists do not have prints as raw:0xNNNN (R3), so that
// it reads back as it is.
//
static void tone_format(long v, char *buf, int size)
{
    char tmp[40];

    tmp[0] = 0;
    if (v == 0xffff) {
        snprintf(buf, size, "-");
        return;
    }
    if ((v & 0x8000) && bcd_valid(v & 0x0fff, 3))
        snprintf(tmp, sizeof(tmp), "D%03lx%c", v & 0x0fff, (v & 0x4000) ? 'I' : 'N');
    else if (! (v & 0xc000) && bcd_valid(v, 4))
        snprintf(tmp, sizeof(tmp), "%lx.%lx", v >> 4, v & 0xf);
    if (tmp[0] && encode_tone(tmp) == v)
        snprintf(buf, size, "%s", tmp);
    else
        snprintf(buf, size, "raw:0x%04lX", v);
}

//
// DTMF digits as the CPS keeps them: a length byte, then the digits two to a
// byte, low nibble first: 0-9, A-D, * = 0xE, # = 0xF.  The CPS shows nothing
// for a length above 30, and so does this.
//
static const char DTMF_DIGITS[] = "0123456789ABCD*#";
#define DTMF_MAX    30

static void dtmf_format(const unsigned char *p, int width, char *buf, int size)
{
    int len = p[0], i, n = 0;

    if (len > DTMF_MAX || len > 2 * (width - 1))
        len = 0;
    for (i=0; i<len && n < size - 1; i++) {
        int nib = (i & 1) ? p[1 + i/2] >> 4 : p[1 + i/2] & 0x0f;

        buf[n++] = DTMF_DIGITS[nib];
    }
    buf[n] = 0;
    if (n == 0)
        snprintf(buf, size, "-");
}

static int dtmf_digit(int c)
{
    const char *d;

    if (c >= 'a' && c <= 'd')
        c += 'A' - 'a';
    d = c ? strchr(DTMF_DIGITS, c) : 0;
    return d ? (int) (d - DTMF_DIGITS) : -1;
}

static int dtmf_check(const char *text, char *err, int esize)
{
    int n = strlen(text), i;

    if (strcmp(text, "-") == 0)
        return 1;
    if (n > DTMF_MAX) {
        snprintf(err, esize, "'%s' is too long: at most %d DTMF digits.", text, DTMF_MAX);
        return 0;
    }
    for (i=0; i<n; i++) {
        if (dtmf_digit((unsigned char) text[i]) < 0) {
            snprintf(err, esize, "'%s': DTMF digits are 0-9, A-D, * and #, or - for none.", text);
            return 0;
        }
    }
    return 1;
}

//
// As the CPS's encoder (0x4443a0): the length byte and the new digits'
// nibbles; nibbles past the new length keep what they held.
//
static void dtmf_put(unsigned char *p, const char *text)
{
    int n, i;

    if (strcmp(text, "-") == 0)
        text = "";
    n = strlen(text);
    for (i=0; i<n; i++) {
        int d = dtmf_digit((unsigned char) text[i]);
        unsigned char *b = &p[1 + i/2];

        if (i & 1)
            *b = (*b & 0x0f) | (d << 4);
        else
            *b = (*b & 0xf0) | d;
    }
    p[0] = n;
}

//
// "467.55000" -> 0x46755000: MHz with up to five decimals, 10 Hz units.
// The same bands as the channel tables: 136-174 and 400-480 MHz.
//
static int freq_parse(const char *text, long *raw)
{
    long mhz, frac = 0;
    int nf = 0;
    char *e;

    if (! isdigit((unsigned char) text[0]))
        return 0;
    mhz = strtol(text, &e, 10);
    if (*e == '.') {
        for (e++; isdigit((unsigned char) *e) && nf < 5; e++, nf++)
            frac = frac * 10 + (*e - '0');
    }
    if (*e)
        return 0;
    while (nf++ < 5)
        frac *= 10;
    if (! ((mhz >= 136 && mhz <= 174) || (mhz >= 400 && mhz <= 480)))
        return 0;
    *raw = (long) ((to_bcd(mhz) << 20) | to_bcd(frac));
    return 1;
}

// Display text for a stored value.
static void cf_format(const unsigned char *rec, const cfield_t *f, char *buf, int size)
{
    long raw = cf_get(rec, f);
    int i;

    switch (f->kind) {
    case K_BOOL:
        snprintf(buf, size, "%s", ((f->flags & F_INV) ? ! raw : raw) ? "+" : "-");
        return;
    case K_ENUM:
        if (raw >= 0 && raw < f->nnames && f->names[raw])
            snprintf(buf, size, "%s", f->names[raw]);
        else
            snprintf(buf, size, "raw:0x%02lX", raw);
        return;
    case K_NUM:
        if (raw == f->zraw && f->zero)
            snprintf(buf, size, "%s", f->zero);
        else if (raw < f->lo || raw > f->hi)
            snprintf(buf, size, "raw:0x%02lX", raw);       // R3: kept as it is
        else
            snprintf(buf, size, "%ld", raw * f->scale + f->base);
        return;
    case K_ID32:
        if ((unsigned long) raw == 0xffffffffUL)
            snprintf(buf, size, "-");
        else if (raw < f->lo || raw > f->hi)
            snprintf(buf, size, "raw:0x%08lX", raw);
        else
            snprintf(buf, size, "%lu", (unsigned long) raw);
        return;
    case K_KEYLOCK:
        if (raw >= 1 && raw <= 3)
            snprintf(buf, size, "%ld", raw * 5);
        else
            snprintf(buf, size, "Manual");
        return;
    case K_FREQMODE:
        snprintf(buf, size, "%s", raw ? "Channel" : "Freq");
        return;
    case K_TZ:
        if (raw <= 24)
            snprintf(buf, size, "UTC %+ld:00", raw - 12);
        else
            snprintf(buf, size, "raw:0x%02lX", raw);
        return;
    case K_BCD8: {
        const unsigned char *p = &rec[f->off];
        int empty = 1, n = 0;

        for (i=0; i<4; i++)
            if (p[i] != 0xff)
                empty = 0;
        if (empty) {
            snprintf(buf, size, "-");
            return;
        }
        for (i=0; i<4 && n < size - 2; i++) {
            int hi = p[i] >> 4, lo = p[i] & 0xf;

            buf[n++] = '0' + (hi > 9 ? 9 : hi);
            buf[n++] = '0' + (lo > 9 ? 9 : lo);
        }
        buf[n] = 0;
        return;
    }
    case K_ASCII8: {
        const unsigned char *p = &rec[f->off];
        int n = 0;

        for (i=0; i<8 && p[i] != 0 && p[i] != 0xff && n < size - 1; i++)
            buf[n++] = (p[i] > ' ' && p[i] < 127) ? p[i] : '?';
        buf[n] = 0;
        if (n == 0)
            snprintf(buf, size, "-");
        return;
    }
    case K_U16:
        if (raw == 0)
            snprintf(buf, size, "-");
        else if (raw < f->lo || raw > f->hi)
            snprintf(buf, size, "raw:0x%04lX", raw);       // R3: erased 0xFFFF
        else
            snprintf(buf, size, "%ld", raw);
        return;
    case K_DECODE:
        for (i=0; i<8 && i < size - 1; i++)
            buf[i] = (raw & (1 << i)) ? '1' + i : '-';
        buf[i] = 0;
        return;
    case K_FREQ:
        if (! bcd_valid(raw, 8))
            snprintf(buf, size, "raw:0x%08lX", raw);
        else
            snprintf(buf, size, "%lx.%05lx", raw >> 20, raw & 0xfffff);
        return;
    case K_TONE:
        tone_format(raw, buf, size);
        return;
    case K_TENTHS:
        if (raw < f->lo || raw > f->hi)
            snprintf(buf, size, "raw:0x%02lX", raw);
        else
            snprintf(buf, size, "%ld.%ld", raw / 10, raw % 10);
        return;
    case K_DTMF:
        dtmf_format(&rec[f->off], f->width, buf, size);
        return;
    case K_NAME16: {
        unsigned short name[16];
        int n;

        memcpy(name, &rec[f->off], sizeof(name));
        utf16_to_utf8(name, 16, buf, size);
        for (n=0; buf[n]; n++)
            if (buf[n] == ' ')
                buf[n] = '_';
        if (n == 0)
            snprintf(buf, size, "-");
        return;
    }
    case K_EREVERT:
        if (raw == 0)
            snprintf(buf, size, "-");
        else if (raw == 0xfffe)
            snprintf(buf, size, "Selected");
        else if (raw <= f->hi)
            snprintf(buf, size, "%ld", raw);
        else
            snprintf(buf, size, "raw:0x%04lX", raw);
        return;
    case K_VPRIVNO:
        // Keys 1-16 as the CPS's list; a Universal index above that (the
        // +0x1E high nibble set) has no key: kept as raw.
        if (raw <= 15)
            snprintf(buf, size, "%ld", raw + 1);
        else
            snprintf(buf, size, "raw:0x%02lX", raw);
        return;
    case K_DREVERT:
        if (raw == 0)
            snprintf(buf, size, "Selected");
        else if (raw <= f->hi)
            snprintf(buf, size, "%ld", raw);
        else
            snprintf(buf, size, "raw:0x%04lX", raw);
        return;
    }
    snprintf(buf, size, "?");
}

//
// A raw: value is hexadecimal, as it prints (raw:0x1F; the 0x is optional).
// No sign, no octal, nothing after the digits.
//
static int parse_raw(const char *text, unsigned long *v)
{
    const char *p = text + 4;
    char *e;
    int n;

    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X'))
        p += 2;
    for (n=0; isxdigit((unsigned char) p[n]); n++)
        continue;
    if (n == 0 || p[n] != 0 || n > 8)
        return 0;
    *v = strtoul(p, &e, 16);
    return *e == 0;
}

// The largest raw value a field can hold.
static unsigned long raw_max(const cfield_t *f)
{
    if (f->mask)
        return (unsigned long) f->mask >> shift_of(f->mask);
    if (f->width >= 4)
        return 0xffffffffUL;
    return (1UL << (8 * f->width)) - 1;
}

// A raw: table cell: 1 when it is raw: and fits in max.
static int raw_cell(const char *tok, unsigned long max, long *v)
{
    unsigned long u;

    if (strncasecmp(tok, "raw:", 4) != 0 || ! parse_raw(tok, &u) || u > max)
        return 0;
    *v = (long) u;
    return 1;
}

static int parse_long(const char *s, long *v)
{
    char *e;

    if (! *s)
        return 0;
    errno = 0;
    *v = strtol(s, &e, 10);
    // No field holds more than 32 bits; anything larger is out of range,
    // and the scale arithmetic stays far from overflow.
    return *e == 0 && errno == 0 && *v > -4294967296L && *v < 4294967296L;
}

//
// Config text -> stored value.  Returns 1, or 0 with a message in err.
//
static int cf_parse(const cfield_t *f, const char *text, long *raw, char *err, int esize)
{
    long v;
    int i;

    if (strncasecmp(text, "raw:", 4) == 0) {
        unsigned long u, max = raw_max(f);
        // A password is never repeated back in a message, raw or not.
        int secret = (f->kind == K_BCD8 || f->kind == K_ASCII8);

        if (! parse_raw(text, &u)) {
            if (secret)
                snprintf(err, esize, "Not a raw value like raw:0x1f.");
            else
                snprintf(err, esize, "'%s' is not a raw value like raw:0x1f.", text);
            return 0;
        }
        if (u > max) {
            if (secret)
                snprintf(err, esize, "Too large for this field (raw:0x%lX at most).", max);
            else
                snprintf(err, esize, "'%s' does not fit this field (raw:0x%lX at most).", text, max);
            return 0;
        }
        *raw = (long) u;
        return 1;
    }
    switch (f->kind) {
    case K_BOOL:
        if (strcmp(text, "+") == 0 || strcasecmp(text, "on") == 0 || strcasecmp(text, "yes") == 0)
            v = 1;
        else if (strcmp(text, "-") == 0 || strcasecmp(text, "off") == 0 || strcasecmp(text, "no") == 0)
            v = 0;
        else {
            snprintf(err, esize, "'%s' must be + or -.", text);
            return 0;
        }
        *raw = (f->flags & F_INV) ? ! v : v;
        return 1;
    case K_ENUM:
        // The last name that matches: TurnOff writes None as 3, as the CPS.
        for (i=f->nnames-1; i>=0; i--) {
            if (f->names[i] && strcasecmp(text, f->names[i]) == 0) {
                *raw = i;
                return 1;
            }
        }
        {
            int n = snprintf(err, esize, "'%s' must be one of:", text), first = 1;

            for (i=0; i<f->nnames && n < esize; i++) {
                if (! f->names[i] || (i > 0 && f->names[i-1] &&
                        strcmp(f->names[i], f->names[i-1]) == 0))
                    continue;
                n += snprintf(err + n, esize - n, "%s %s", first ? "" : ",", f->names[i]);
                first = 0;
            }
            if (n < esize)
                snprintf(err + n, esize - n, ".");
        }
        return 0;
    case K_NUM:
        if (f->zero && strcasecmp(text, f->zero) == 0) {
            *raw = f->zraw;
            return 1;
        }
        if (! parse_long(text, &v)) {
            snprintf(err, esize, "'%s' is not a number%s%s.", text,
                f->zero ? " or " : "", f->zero ? f->zero : "");
            return 0;
        }
        v -= f->base;
        if (v % f->scale) {
            snprintf(err, esize, "%s must be a multiple of %d.", text, f->scale);
            return 0;
        }
        v /= f->scale;
        if (v < f->lo || v > f->hi) {
            snprintf(err, esize, "%s is out of range (%ld to %ld).", text,
                (long) f->lo * f->scale + f->base, (long) f->hi * f->scale + f->base);
            return 0;
        }
        *raw = v;
        return 1;
    case K_ID32:
        if (strcmp(text, "-") == 0) {
            *raw = 0xffffffffL;
            return 1;
        }
        if (! parse_long(text, &v) || ! isdigit((unsigned char) text[0]) || v < f->lo || v > f->hi) {
            snprintf(err, esize, "'%s' must be - or a Radio ID from %d to %d.", text, f->lo, f->hi);
            return 0;
        }
        *raw = v;
        return 1;
    case K_KEYLOCK:
        if (strcasecmp(text, "Manual") == 0) {
            *raw = 0xff;
            return 1;
        }
        if (parse_long(text, &v) && (v == 5 || v == 10 || v == 15)) {
            *raw = v / 5;
            return 1;
        }
        snprintf(err, esize, "'%s' must be Manual, 5, 10 or 15.", text);
        return 0;
    case K_FREQMODE:
        if (strcasecmp(text, "Channel") == 0) {
            *raw = 0xff;
            return 1;
        }
        if (strcasecmp(text, "Freq") == 0) {
            *raw = 0;
            return 1;
        }
        snprintf(err, esize, "'%s' must be Channel or Freq.", text);
        return 0;
    case K_TZ: {
        const char *p = text;
        long h;
        char *e;

        if (strncasecmp(p, "UTC", 3) == 0)
            p += 3;
        while (*p == ' ')
            p++;
        h = strtol(p, &e, 10);
        if (e == p || (*e && strcmp(e, ":00") != 0) || h < -12 || h > 12) {
            snprintf(err, esize, "'%s' must be a whole hour from UTC -12:00 to UTC +12:00.", text);
            return 0;
        }
        *raw = h + 12;
        return 1;
    }
    case K_BCD8: {
        // 8 digits, most significant first at the lowest address; - = empty
        // (FF FF FF FF).  The CPS takes exactly 8 digits.
        unsigned long u = 0;

        if (strcmp(text, "-") == 0) {
            *raw = 0xffffffffL;
            return 1;
        }
        if (strlen(text) != 8 || strspn(text, "0123456789") != 8) {
            snprintf(err, esize, "A password must be 8 digits, or - for none.");
            return 0;
        }
        for (i=0; i<4; i++)
            u |= (unsigned long) (((text[2*i] - '0') << 4) | (text[2*i+1] - '0')) << (8*i);
        *raw = (long) u;
        return 1;
    }
    case K_ASCII8: {
        // Up to 8 printable characters, then 0x00, then 0xFF to the end; - = empty.
        unsigned long u = ~0UL;
        int n = strlen(text);

        if (strcmp(text, "-") == 0) {
            *raw = (long) u;
            return 1;
        }
        if (n < 1 || n > 8) {
            snprintf(err, esize, "A password must be 1 to 8 characters, or - for none.");
            return 0;
        }
        for (i=0; i<n; i++) {
            if (text[i] <= ' ' || text[i] >= 127) {
                snprintf(err, esize, "A password takes printable characters only, no spaces.");
                return 0;
            }
        }
        for (i=0; i<8; i++) {
            unsigned long b = i < n ? (unsigned char) text[i] : (i == n ? 0 : 0xff);

            u = (u & ~(0xffUL << (8*i))) | (b << (8*i));
        }
        *raw = (long) u;
        return 1;
    }
    case K_U16:
        if (strcmp(text, "-") == 0) {
            *raw = 0;
            return 1;
        }
        if (! parse_long(text, &v) || v < f->lo || v > f->hi) {
            snprintf(err, esize, "'%s' must be - or a number from %d to %d.", text, f->lo, f->hi);
            return 0;
        }
        *raw = v;
        return 1;
    case K_DECODE:
        if (strlen(text) != 8) {
            snprintf(err, esize, "'%s' must be 8 characters, - or the decode number, e.g. 12------.", text);
            return 0;
        }
        v = 0;
        for (i=0; i<8; i++) {
            if (text[i] == '1' + i)
                v |= 1 << i;
            else if (text[i] != '-') {
                snprintf(err, esize, "'%s': position %d must be %c or -.", text, i+1, '1' + i);
                return 0;
            }
        }
        *raw = v;
        return 1;
    case K_FREQ:
        if (! freq_parse(text, raw)) {
            snprintf(err, esize, "'%s' is not a frequency the radio covers: 136-174 or "
                "400-480 MHz, up to 5 decimals.", text);
            return 0;
        }
        return 1;
    case K_TONE: {
        char tmp[16];
        int t;

        snprintf(tmp, sizeof(tmp), "%s", text);
        t = (strlen(text) < sizeof(tmp)) ? encode_tone(tmp) : -1;
        if (t < 0) {
            snprintf(err, esize, "'%s' is not a tone: - , a CTCSS frequency like 67.0, "
                "or DCS like D023N or D023I.", text);
            return 0;
        }
        *raw = t;
        return 1;
    }
    case K_TENTHS: {
        char *e;
        long w;

        if (! isdigit((unsigned char) text[0]))
            goto bad_tenths;
        w = strtol(text, &e, 10) * 10;
        if (*e == '.' && isdigit((unsigned char) e[1])) {
            w += e[1] - '0';
            e += 2;
        }
        if (*e || w < f->lo || w > f->hi) {
bad_tenths: snprintf(err, esize, "'%s' must be from %d.%d to %d.%d, in steps of 0.1.", text,
                f->lo / 10, f->lo % 10, f->hi / 10, f->hi % 10);
            return 0;
        }
        *raw = w;
        return 1;
    }
    case K_VPRIVNO:
        if (! parse_long(text, &v) || ! isdigit((unsigned char) text[0]) || v < 1 || v > 16) {
            snprintf(err, esize, "'%s' must be a key number from 1 to 16.", text);
            return 0;
        }
        *raw = v - 1;
        return 1;
    case K_EREVERT:
    case K_DREVERT:
        if (f->kind == K_EREVERT && strcmp(text, "-") == 0) {
            *raw = 0;
            return 1;
        }
        if (strcasecmp(text, "Selected") == 0) {
            *raw = (f->kind == K_EREVERT) ? 0xfffe : 0;
            return 1;
        }
        if (! parse_long(text, &v) || ! isdigit((unsigned char) text[0]) || v < f->lo || v > f->hi) {
            snprintf(err, esize, "'%s' must be %sSelected or a channel number from 1 to %d.", text,
                f->kind == K_EREVERT ? "-, " : "", f->hi);
            return 0;
        }
        *raw = v;
        return 1;
    }
    snprintf(err, esize, "This field can't be set from the config.");
    return 0;
}

//
// Config text -> the field's bytes in rec, for every kind: R2 as cf_apply().
// Returns 1 (*changed says whether rec changed), or 0 with a message in err
// and rec as it was.
//
static int cf_apply(unsigned char *rec, const cfield_t *f, long raw);

static int cf_set_text(unsigned char *rec, const cfield_t *f, const char *text,
    int *changed, char *err, int esize)
{
    unsigned char tmp[64];
    char was[64], now[64];
    long raw;

    *changed = 0;
    // What the image already holds, as printed, is kept without being
    // parsed: a value the config can't set (a VFO outside the bands) still
    // reads back (R2).
    cf_format(rec, f, was, sizeof(was));
    if (strcmp(text, was) == 0)
        return 1;
    if (! BYTE_KIND(f->kind)) {
        if (! cf_parse(f, text, &raw, err, esize))
            return 0;
        *changed = cf_apply(rec, f, raw);
        return 1;
    }
    if (f->kind == K_DTMF) {
        if (! dtmf_check(text, err, esize))
            return 0;
    } else {
        const char *p = text;
        int n = 0;

        if (strcmp(text, "-") != 0) {
            while (*p && utf8_to_unicode(&p))
                n++;
            if (n > 16) {
                snprintf(err, esize, "'%s' is too long: at most 16 characters.", text);
                return 0;
            }
        }
    }
    memcpy(tmp, &rec[f->off], f->width);
    cf_format(rec, f, was, sizeof(was));
    if (f->kind == K_DTMF) {
        dtmf_put(&rec[f->off], text);
    } else {
        unsigned short name[16];

        utf8_decode(name, text, 16);
        memcpy(&rec[f->off], name, sizeof(name));
    }
    cf_format(rec, f, now, sizeof(now));
    if (strcmp(was, now) == 0) {
        memcpy(&rec[f->off], tmp, f->width);
        return 1;
    }
    *changed = 1;
    return 1;
}

//
// R2: set a field only when the new value prints differently.  Returns 1 if
// the record changed.
//
static int cf_apply(unsigned char *rec, const cfield_t *f, long raw)
{
    unsigned char tmp[64], hi = rec[0x1E];
    char was[64], now[64];
    unsigned lo = f->off, n = f->mask ? 1 : f->width;

    // Format the new value in a copy of the field's bytes.
    memcpy(tmp, &rec[lo], n);
    cf_format(rec, f, was, sizeof(was));
    cf_put(rec, f, raw);
    cf_format(rec, f, now, sizeof(now));
    if (strcmp(was, now) == 0) {
        memcpy(&rec[lo], tmp, n);
        if (f->kind == K_VPRIVNO)
            rec[0x1E] = hi;             // its other byte
        return 0;
    }
    return 1;
}

// ---------------------------------------------------------------------------
// Which radios.
// ---------------------------------------------------------------------------

//
// An image file carries no model: radio_read_image() takes every 851968-byte
// file for an MD-UV380, and the MD-2017, MD-9600 and RT84 save images of the
// same size.  Offline print and apply therefore treat any such image as an
// MD-UV380/UV390.  TYTcps is for the MD-UV390 (Plus) fleet only, and checks
// the radio's model before it writes.
//
int cps_fields_enabled(radio_device_t *radio)
{
    return radio == &radio_uv380 || radio == &radio_uv390;
}

static int channel_record_valid(const unsigned char *r, int *mode)
{
    unsigned name0 = r[0x20] | (r[0x21] << 8);

    if (name0 == 0 || name0 == 0xffff)
        return 0;
    *mode = r[0] & 3;
    return 1;
}

static int channel_valid(int i, int *mode)
{
    return channel_record_valid(&radio_mem[CH_BASE + i * CH_SIZE], mode);
}

static int scanlist_valid(int i)
{
    const unsigned char *r = &radio_mem[SL_BASE + i * SL_SIZE];
    unsigned name0 = r[0] | (r[1] << 8);

    return name0 != 0 && name0 != 0xffff;
}

static int contact_valid(int i)
{
    const unsigned char *r = &radio_mem[CT_BASE + i * CT_SIZE];
    unsigned name0 = r[4] | (r[5] << 8);

    return (r[3] & 0x1f) != 0 && name0 != 0 && name0 != 0xffff;
}

static int message_valid(int i)
{
    const unsigned char *r = &radio_mem[MSG_BASE + i * MSG_SIZE];
    unsigned c0 = r[0] | (r[1] << 8);

    return c0 != 0 && c0 != 0xffff;
}

//
// Which contacts and messages the image had before the config rewrote those
// tables (uv380.c calls cps_note_* just before it erases them).  A One Touch
// or Number Key row the config leaves as it is may keep pointing at a record
// the image never had, but not at one the same config deletes.
//
static unsigned char *contact_before, *message_before;

void cps_note_contacts(void)
{
    int i;

    if (contact_before)
        return;
    contact_before = malloc(NCT);
    if (! contact_before)
        die(EXIT_IO, "Out of memory.");
    for (i=0; i<NCT; i++)
        contact_before[i] = contact_valid(i);
}

void cps_note_messages(void)
{
    int i;

    if (message_before)
        return;
    message_before = malloc(NMSG);
    if (! message_before)
        die(EXIT_IO, "Out of memory.");
    for (i=0; i<NMSG; i++)
        message_before[i] = message_valid(i);
}

static int contact_was_valid(int i)
{
    return contact_before ? contact_before[i] : contact_valid(i);
}

static int message_was_valid(int i)
{
    return message_before ? message_before[i] : message_valid(i);
}

// ---------------------------------------------------------------------------
// Printing.
// ---------------------------------------------------------------------------

static const char *button_name(int code, char *buf, int size)
{
    int i;

    for (i=0; i<NBUTTON_FN; i++)
        if (BUTTON_FN[i].code == code)
            return BUTTON_FN[i].name;
    snprintf(buf, size, "raw:0x%02X", code);
    return buf;
}

static void print_row_fields(FILE *out, const unsigned char *rec, const cfield_t *tab,
    int n, const int *width)
{
    char buf[64];
    int k;

    for (k=0; k<n; k++) {
        cf_format(rec, &tab[k], buf, sizeof(buf));
        if (k == n - 1)
            fprintf(out, " %s", buf);
        else
            fprintf(out, " %-*s", width[k], buf);
    }
}

static void table_header(FILE *out, const char *first, const cfield_t *tab, int n, int *width)
{
    int k;

    fprintf(out, "%-11s", first);
    for (k=0; k<n; k++) {
        width[k] = (int) strlen(tab[k].key);
        if (tab[k].kind == K_ENUM) {
            int i;

            for (i=0; i<tab[k].nnames; i++)
                if (tab[k].names[i] && (int) strlen(tab[k].names[i]) > width[k])
                    width[k] = strlen(tab[k].names[i]);
        } else if (BYTE_KIND(tab[k].kind) && width[k] < 16) {
            width[k] = 16;
        } else if (tab[k].kind == K_DECODE && width[k] < 8) {
            width[k] = 8;
        } else if (tab[k].kind == K_NUM && width[k] < 5) {
            width[k] = 5;
        }
        if (k == n - 1)
            fprintf(out, " %s", tab[k].key);
        else
            fprintf(out, " %-*s", width[k], tab[k].key);
    }
    fprintf(out, "\n");
}

static void print_76(FILE *out, int verbose);

void cps_print(FILE *out, int verbose)
{
    char buf[64];
    int i, k, mode, width[32];

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# The stock CPS's General Setting page, plus Menu Hang Time and\n");
        fprintf(out, "# Long Press Duration. Checkboxes are + or -, as the CPS shows them.\n");
        fprintf(out, "# Power On and Radio Program Password: 8 digits; PC Programming\n");
        fprintf(out, "# Password: up to 8 characters; - = none.\n");
        fprintf(out, "# A value with no CPS word prints as raw:0xNN and is kept as it is.\n");
    }
    for (i=0; i<NGENERAL; i++) {
        cf_format(radio_mem, &GENERAL[i], buf, sizeof(buf));
        fprintf(out, "%s: %s\n", GENERAL[i].key, buf);
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# Menu Item: + = the item is in the radio's menu.\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "Menu     Item                Shown\n");
    for (i=0; i<NMENU; i++) {
        cf_format(radio_mem, &MENU[i], buf, sizeof(buf));
        fprintf(out, "         %-19s %s\n", MENU[i].key, buf);
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# Buttons Definitions: side button functions.\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "Buttons  Key            Short                    Long\n");
    for (i=0; i<NBUTTONS; i++) {
        char b2[32];

        fprintf(out, "         %-14s %-24s", BUTTONS[i].name,
            button_name(radio_mem[BUTTONS[i].shrt], buf, sizeof(buf)));
        fprintf(out, " %s\n", button_name(radio_mem[BUTTONS[i].lng], b2, sizeof(b2)));
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# One Touch Access 1-6. Mode: None, Digital, Analog. Call: contact or -.\n");
        fprintf(out, "# CallType: Call or Text (digital), DTMF-1..DTMF-4 (analog).\n");
        fprintf(out, "# Message: text message (digital) or DTMF encode number (analog), or -.\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "OneTouch Mode    Call  CallType Message\n");
    for (i=0; i<NONETOUCH; i++) {
        const unsigned char *r = &radio_mem[OT_BASE + 4*i];
        int m = (r[0] >> 4) & 3, ct = r[0] & 0x0f, msg = r[1];
        unsigned call = r[2] | (r[3] << 8);
        char cs[16], cts[16], ms[16];

        if (call == 0)
            snprintf(cs, sizeof(cs), "-");
        else if (call <= NCT)
            snprintf(cs, sizeof(cs), "%u", call);
        else
            snprintf(cs, sizeof(cs), "raw:0x%04X", call);
        if (m == 1 && ct <= 1)
            snprintf(cts, sizeof(cts), "%s", ct ? "Text" : "Call");
        else if (m == 2 && ct >= 8 && ct <= 11)
            snprintf(cts, sizeof(cts), "DTMF-%d", ct - 7);
        else
            snprintf(cts, sizeof(cts), "raw:0x%X", ct);
        snprintf(ms, sizeof(ms), msg ? "%d" : "-", msg);
        fprintf(out, "%8d %-7s %-5s %-8s %s\n", i+1,
            m < 3 ? W_OTMODE[m] : "raw:0x3", cs, cts, ms);
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# Number Key quick contacts 0-9: contact number or -.\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "NumberKey Contact\n");
    for (k=0; k<NNUMKEY; k++) {
        unsigned c = radio_mem[NK_BASE + 2*k] | (radio_mem[NK_BASE + 2*k + 1] << 8);

        if (c == 0)
            fprintf(out, "%9d -\n", k);
        else if (c <= NCT)
            fprintf(out, "%9d %u\n", k, c);
        else
            fprintf(out, "%9d raw:0x%04X\n", k, c);
    }

    for (i=0, k=0; i<NSL; i++)
        if (scanlist_valid(i))
            k++;
    if (k) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Scan list timing: signalling hold and priority sample time.\n");
            fprintf(out, "#\n");
        }
        table_header(out, "ScanTiming", SCANTIMING, NSCANTIMING, width);
        for (i=0; i<NSL; i++) {
            if (! scanlist_valid(i))
                continue;
            fprintf(out, "%10d ", i+1);
            print_row_fields(out, &radio_mem[SL_BASE + i*SL_SIZE], SCANTIMING, NSCANTIMING, width);
            fprintf(out, "\n");
        }
    }

    for (mode=2; mode>=1; mode--) {
        const cfield_t *tab = (mode == 2) ? CHANDIG : CHANANA;
        int n = (mode == 2) ? NCHANDIG : NCHANANA, any = 0;

        for (i=0; i<NCH; i++) {
            int m;

            if (! channel_valid(i, &m) || m != mode)
                continue;
            if (! any) {
                fprintf(out, "\n");
                if (verbose && mode == 2) {
                    fprintf(out, "# Digital channel fields beyond the Digital table, by channel.\n");
                    fprintf(out, "# RxRef/TxRef reference frequency, Rekey TOT rekey delay [s],\n");
                    fprintf(out, "# AS auto scan, LW lone worker, TA allow talkaround, PCC/EAA/DCC\n");
                    fprintf(out, "# private call confirmed / emergency alarm ack / data call\n");
                    fprintf(out, "# confirmed, AI allow interrupt, EmSys emergency system,\n");
                    fprintf(out, "# InCall in-call criteria, MsgFmt message format.\n");
                    fprintf(out, "#\n");
                }
                if (verbose && mode == 1) {
                    fprintf(out, "# Analog channel fields beyond the Analog table, by channel.\n");
                    fprintf(out, "# RxSig/TxSig signalling system, QTRev QT reverse, TurnOff\n");
                    fprintf(out, "# non-QT/DQT turn-off frequency, PTTID display PTT ID, RevBurst\n");
                    fprintf(out, "# reverse burst/turn-off code, Decode 1-8.\n");
                    fprintf(out, "#\n");
                }
                table_header(out, mode == 2 ? "ChanDigital" : "ChanAnalog", tab, n, width);
                any = 1;
            }
            fprintf(out, "%11d", i+1);
            print_row_fields(out, &radio_mem[CH_BASE + i*CH_SIZE], tab, n, width);
            fprintf(out, "\n");
        }
    }
    print_76(out, verbose);
}

// ---------------------------------------------------------------------------
// Parsing.  Scalars apply at once; table rows are kept and applied when the
// whole file has been read (cps_parse_finish), so the channel tables' erase
// of the bank cannot undo them and table order does not matter.
// ---------------------------------------------------------------------------

#define UNSET   (-0x7fffffffL)

static long menu_val[64];
static long button_val[NBUTTONS][2];
static long onetouch_val[NONETOUCH][4];     // mode, call, calltype, message
static long numkey_val[NNUMKEY];
static long *scan_val;                      // NSL x NSCANTIMING
static long *chan_val;                      // NCH x 32
static char chan_mode_given[NCH];           // 2 ChanDigital, 1 ChanAnalog
static int pending, begun;

// Problems found when applying, reported by cps_verify().
typedef struct { int table, code; char id[16]; const char *section, *column; char msg[160]; } cproblem_t;
static cproblem_t problems[64];
static int nproblems;

void cps_parse_begin(void)
{
    int i, k;

    if (! scan_val)
        scan_val = malloc(sizeof(long) * NSL * NSCANTIMING);
    if (! chan_val)
        chan_val = malloc(sizeof(long) * NCH * 32);
    if (! scan_val || ! chan_val)
        die(EXIT_IO, "Out of memory.");
    for (i=0; i<64; i++)
        menu_val[i] = UNSET;
    for (i=0; i<NBUTTONS; i++)
        button_val[i][0] = button_val[i][1] = UNSET;
    for (i=0; i<NONETOUCH; i++)
        for (k=0; k<4; k++)
            onetouch_val[i][k] = UNSET;
    for (i=0; i<NNUMKEY; i++)
        numkey_val[i] = UNSET;
    for (i=0; i<NSL * NSCANTIMING; i++)
        scan_val[i] = UNSET;
    for (i=0; i<NCH * 32; i++)
        chan_val[i] = UNSET;
    memset(chan_mode_given, 0, sizeof(chan_mode_given));
    nproblems = 0;
    pending = 0;
    begun = 1;
}

static void problem(int table, const char *id, const char *section, const char *column,
    const char *fmt, ...) __attribute__((format(printf, 5, 6)));
static void problem(int table, const char *id, const char *section, const char *column,
    const char *fmt, ...)
{
    va_list ap;
    cproblem_t *p;

    if (nproblems >= (int) (sizeof(problems) / sizeof(problems[0])))
        return;
    p = &problems[nproblems++];
    p->table = table;
    p->code = EXIT_CONF;
    snprintf(p->id, sizeof(p->id), "%s", id);
    p->section = section;
    p->column = column;
    va_start(ap, fmt);
    vsnprintf(p->msg, sizeof(p->msg), fmt, ap);
    va_end(ap);
}

static int parse_param_76(const char *param, const char *value);

int cps_parse_parameter(const char *param, const char *value)
{
    char err[256];
    long raw;
    int i;

    if (parse_param_76(param, value))
        return 1;

    for (i=0; i<NGENERAL; i++) {
        const cfield_t *f = &GENERAL[i];

        if (strcasecmp(param, f->key) != 0)
            continue;
        if (f->flags & F_RO) {
            // Printed for information; whatever the config says, the radio
            // keeps its own value (a wrong password would lock it).
            return 1;
        }
        if (! cf_parse(f, value, &raw, err, sizeof(err)))
            conf_fail(f->key, "%s: %s", f->key, err);
        cf_apply(radio_mem, f, raw);
        return 1;
    }
    return 0;
}

int cps_parse_header(const char *line)
{
    if (strncasecmp(line, "Menu", 4) == 0)        return CPS_T_MENU;
    if (strncasecmp(line, "Buttons", 7) == 0)     return CPS_T_BUTTONS;
    if (strncasecmp(line, "OneTouch", 8) == 0)    return CPS_T_ONETOUCH;
    if (strncasecmp(line, "NumberKey", 9) == 0)   return CPS_T_NUMKEY;
    if (strncasecmp(line, "ScanTiming", 10) == 0) return CPS_T_SCANTIMING;
    if (strncasecmp(line, "ChanDigital", 11) == 0) return CPS_T_CHANDIG;
    if (strncasecmp(line, "ChanAnalog", 10) == 0) return CPS_T_CHANANA;
    if (strncasecmp(line, "EmergencySystem", 15) == 0) return CPS_T_EMSYS;
    if (strncasecmp(line, "DTMFSystem", 10) == 0) return CPS_T_DTMFSYS;
    if (strncasecmp(line, "DTMFEncode", 10) == 0) return CPS_T_DTMFENC;
    if (strncasecmp(line, "DTMFDecode", 10) == 0) return CPS_T_DTMFDEC;
    return 0;
}

#define MAXTOK 40

static int split(char *line, char **tok, int max)
{
    int n = 0;
    char *p = line;

    while (*p && n < max) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')
            p++;
        if (! *p)
            break;
        tok[n++] = p;
        while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n')
            p++;
        if (*p)
            *p++ = 0;
    }
    return n;
}

static int parse_fields(const cfield_t *tab, int n, char **tok, long *out)
{
    char err[256];
    int k;

    for (k=0; k<n; k++) {
        if (! cf_parse(&tab[k], tok[k], &out[k], err, sizeof(err))) {
            conf_error(tab[k].key, "%s", err);
            return 0;
        }
    }
    return 1;
}

static int button_code(const char *s, long *code)
{
    int i;

    for (i=0; i<NBUTTON_FN; i++) {
        if (strcasecmp(s, BUTTON_FN[i].name) == 0) {
            *code = BUTTON_FN[i].code;
            return 1;
        }
    }
    return raw_cell(s, 0xff, code);
}

static int parse_row_76(int table_id, char **tok, int n);

int cps_parse_row(int table_id, char *line)
{
    char *tok[MAXTOK];
    int n = split(line, tok, MAXTOK);
    long v;
    int i;

    if (! begun)
        cps_parse_begin();
    i = parse_row_76(table_id, tok, n);
    if (i >= 0)
        return i;
    pending = 1;
    switch (table_id) {
    case CPS_T_MENU:
        if (n != 2) {
            conf_error(0, "A Menu row has 2 columns: item and + or -.");
            return 0;
        }
        for (i=0; i<NMENU; i++) {
            char err[128];

            if (strcasecmp(tok[0], MENU[i].key) != 0)
                continue;
            if (! cf_parse(&MENU[i], tok[1], &v, err, sizeof(err))) {
                conf_error("Shown", "%s", err);
                return 0;
            }
            menu_val[i] = v;
            return 1;
        }
        conf_error("Item", "Unknown menu item '%s'.", tok[0]);
        return 0;

    case CPS_T_BUTTONS:
        if (n != 3) {
            conf_error(0, "A Buttons row has 3 columns: key, short press, long press.");
            return 0;
        }
        for (i=0; i<NBUTTONS; i++) {
            if (strcasecmp(tok[0], BUTTONS[i].name) != 0)
                continue;
            if (! button_code(tok[1], &button_val[i][0])) {
                conf_error("Short", "Unknown button function '%s'.", tok[1]);
                return 0;
            }
            if (! button_code(tok[2], &button_val[i][1])) {
                conf_error("Long", "Unknown button function '%s'.", tok[2]);
                return 0;
            }
            return 1;
        }
        conf_error("Key", "Unknown key '%s': Side_Button1 or Side_Button2.", tok[0]);
        return 0;

    case CPS_T_ONETOUCH: {
        long row, mode, call, ct, msg;

        if (n != 5) {
            conf_error(0, "A OneTouch row has 5 columns: number, mode, call, call type, message.");
            return 0;
        }
        if (! parse_long(tok[0], &row) || row < 1 || row > NONETOUCH) {
            conf_error("#", "One Touch Access number must be 1-6.");
            return 0;
        }
        for (mode=0; mode<3; mode++)
            if (strcasecmp(tok[1], W_OTMODE[mode]) == 0)
                break;
        if (mode == 3 && ! raw_cell(tok[1], 3, &mode)) {
            conf_error("Mode", "Mode '%s' must be None, Digital or Analog.", tok[1]);
            return 0;
        }
        if (strcmp(tok[2], "-") == 0)
            call = 0;
        else if (raw_cell(tok[2], 0xffff, &call))
            ;
        else if (! parse_long(tok[2], &call) || call < 1 || call > NCT) {
            conf_error("Call", "Call '%s' must be - or a contact number.", tok[2]);
            return 0;
        }
        // The words are the ones the CPS shows for the row's mode, so the
        // row prints back the same: Call/Text on a Digital row, DTMF-n on
        // an Analog row, raw:0xN for anything else.
        if (strcasecmp(tok[3], "Call") == 0 || strcasecmp(tok[3], "Text") == 0) {
            if (mode != 1) {
                conf_error("CallType", "Call type %s is for a Digital row; this row is %s.",
                    tok[3], mode < 3 ? W_OTMODE[mode] : "raw:0x3");
                return 0;
            }
            ct = strcasecmp(tok[3], "Text") == 0;
        } else if (strncasecmp(tok[3], "DTMF-", 5) == 0 && tok[3][5] >= '1' && tok[3][5] <= '4' && ! tok[3][6]) {
            if (mode != 2) {
                conf_error("CallType", "Call type %s is for an Analog row; this row is %s.",
                    tok[3], mode < 3 ? W_OTMODE[mode] : "raw:0x3");
                return 0;
            }
            ct = tok[3][5] - '1' + 8;
        } else if (! raw_cell(tok[3], 0x0f, &ct)) {
            conf_error("CallType", "Call type '%s' must be Call, Text or DTMF-1..DTMF-4.", tok[3]);
            return 0;
        }
        if (strcmp(tok[4], "-") == 0)
            msg = 0;
        else if (! parse_long(tok[4], &msg) || msg < 1 || msg > 255) {
            conf_error("Message", "Message '%s' must be - or a number.", tok[4]);
            return 0;
        }
        onetouch_val[row-1][0] = mode;
        onetouch_val[row-1][1] = call;
        onetouch_val[row-1][2] = ct;
        onetouch_val[row-1][3] = msg;
        return 1;
    }

    case CPS_T_NUMKEY: {
        long key, c;

        if (n != 2) {
            conf_error(0, "A NumberKey row has 2 columns: key 0-9 and contact or -.");
            return 0;
        }
        if (! parse_long(tok[0], &key) || key < 0 || key > 9) {
            conf_error("#", "Number key must be 0-9.");
            return 0;
        }
        if (strcmp(tok[1], "-") == 0)
            c = 0;
        else if (raw_cell(tok[1], 0xffff, &c))
            ;
        else if (! parse_long(tok[1], &c) || c < 1 || c > NCT) {
            conf_error("Contact", "Contact '%s' must be - or a contact number.", tok[1]);
            return 0;
        }
        numkey_val[key] = c;
        return 1;
    }

    case CPS_T_SCANTIMING: {
        long sl;

        if (n != 1 + NSCANTIMING) {
            conf_error(0, "A ScanTiming row has %d columns.", 1 + NSCANTIMING);
            return 0;
        }
        if (! parse_long(tok[0], &sl) || sl < 1 || sl > NSL) {
            conf_error("#", "Scan list number must be 1-%d.", NSL);
            return 0;
        }
        return parse_fields(SCANTIMING, NSCANTIMING, tok + 1, &scan_val[(sl-1) * NSCANTIMING]);
    }

    case CPS_T_CHANDIG:
    case CPS_T_CHANANA: {
        const cfield_t *tab = (table_id == CPS_T_CHANDIG) ? CHANDIG : CHANANA;
        int nf = (table_id == CPS_T_CHANDIG) ? NCHANDIG : NCHANANA;
        long ch;

        if (n != 1 + nf) {
            conf_error(0, "A %s row has %d columns; this one has %d.",
                table_id == CPS_T_CHANDIG ? "ChanDigital" : "ChanAnalog", 1 + nf, n);
            return 0;
        }
        if (! parse_long(tok[0], &ch) || ch < 1 || ch > NCH) {
            conf_error("#", "Channel number must be 1-%d.", NCH);
            return 0;
        }
        if (chan_mode_given[ch-1] && chan_mode_given[ch-1] != (table_id == CPS_T_CHANDIG ? 2 : 1)) {
            conf_error("#", "Channel %ld already has a row in %s; a channel is digital or "
                "analog, not both.", ch, chan_mode_given[ch-1] == 2 ? "ChanDigital" : "ChanAnalog");
            return 0;
        }
        if (! parse_fields(tab, nf, tok + 1, &chan_val[(ch-1) * 32]))
            return 0;
        chan_mode_given[ch-1] = (table_id == CPS_T_CHANDIG) ? 2 : 1;
        return 1;
    }
    }
    return 0;
}

// Whether a One Touch row in the config differs from the image: references
// are checked only on rows the config changes (an unchanged row from the
// radio is kept as it is, whatever it points at).
static int onetouch_changed(int i, const long *v)
{
    const unsigned char *r = &radio_mem[OT_BASE + 4*i];

    return ((r[0] >> 4) & 3) != v[0] || (r[0] & 0x0f) != v[2] || r[1] != v[3] ||
        (r[2] | (r[3] << 8)) != v[1];
}

// ---------------------------------------------------------------------------
// Digit Emergency System, DTMF Signaling and VFO Mode.  These
// regions are not touched by the channel tables' erase, so their rows and
// scalars apply at once; the checks run in cps_parse_finish().
// ---------------------------------------------------------------------------

#define R76_EM_LEN  (CPS_EMS_START + CPS_NEMS * CPS_EMS_SIZE - CPS_EMERG_START)

#define GL_BASE     0x0ec20         // group lists 1-250, 96 bytes each
#define GL_SIZE     96
#define NGL         250

// A record with a name (UTF-16, first character not 0 or 0xFFFF).
static int named_at(const unsigned char *r)
{
    unsigned c = r[0] | (r[1] << 8);

    return c != 0 && c != 0xffff;
}

// Contacts, group lists, scan lists and channels in an image (mem is
// radio_mem, or conf_mem_before for the image as the config found it).
static int contact_in(const unsigned char *mem, int i)
{
    const unsigned char *r = &mem[CT_BASE + i * CT_SIZE];

    return (r[3] & 0x1f) != 0 && named_at(&r[4]);
}

static int grouplist_in(const unsigned char *mem, int i)
{
    return named_at(&mem[GL_BASE + i * GL_SIZE]);
}

static int scanlist_in(const unsigned char *mem, int i)
{
    return named_at(&mem[SL_BASE + i * SL_SIZE]);
}

static int channel_in(const unsigned char *mem, int i)
{
    int mode;

    return channel_record_valid(&mem[CH_BASE + i * CH_SIZE], &mode);
}

static unsigned char *emsys_rec(unsigned char *mem, int i)
{
    return &mem[CPS_EMS_START + i * CPS_EMS_SIZE];
}

static int emsys_named(const unsigned char *r)
{
    unsigned c = r[0] | (r[1] << 8);

    return c != 0 && c != 0xffff;
}

// How many systems the CPS sees: it counts up to the first one with no name.
static int emsys_count(const unsigned char *mem)
{
    int i;

    for (i=0; i<CPS_NEMS; i++)
        if (! emsys_named(&mem[CPS_EMS_START + i * CPS_EMS_SIZE]))
            break;
    return i;
}

static void print_scalars(FILE *out, const unsigned char *rec, const cfield_t *tab, int n,
    const char *prefix)
{
    char buf[64];
    int k;

    for (k=0; k<n; k++) {
        cf_format(rec, &tab[k], buf, sizeof(buf));
        fprintf(out, "%s%s: %s\n", prefix, tab[k].key, buf);
    }
}

static void print_76(FILE *out, int verbose)
{
    int i, width[32];

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# Digit Emergency System. Durations as the CPS shows them.\n");
        fprintf(out, "#\n");
    }
    print_scalars(out, radio_mem, EMERG, NEMERG, "");

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# Emergency systems: one row per system. A row for the next free number\n");
        fprintf(out, "# adds a system; Name - deletes one (from the last). Polite: 0-14 or\n");
        fprintf(out, "# Infinite. Revert: -, Selected or a channel number.\n");
        fprintf(out, "#\n");
    }
    table_header(out, "EmergencySystem", EMSYS, NEMSYS, width);
    for (i=0; i<CPS_NEMS; i++) {
        const unsigned char *r = emsys_rec(radio_mem, i);

        if (! emsys_named(r))
            continue;
        fprintf(out, "%15d", i+1);
        print_row_fields(out, r, EMSYS, NEMSYS, width);
        fprintf(out, "\n");
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# DTMF systems DTMF-1..DTMF-4. Times in ms or s as the CPS shows them;\n");
        fprintf(out, "# KeyUp/KeyDown: DTMF digits 0-9 A-D * #, or - for none.\n");
        fprintf(out, "#\n");
    }
    table_header(out, "DTMFSystem", DTMFSYS, NDTMFSYS, width);
    for (i=0; i<CPS_NDS; i++) {
        fprintf(out, "%10d ", i+1);
        print_row_fields(out, &radio_mem[CPS_DS_START + i * CPS_DS_SIZE], DTMFSYS, NDTMFSYS, width);
        fprintf(out, "\n");
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# DTMF encode list: DTMF digits, or - for none (1 is never empty).\n");
        fprintf(out, "#\n");
    }
    table_header(out, "DTMFEncode", DTMFENC, NDTMFENC, width);
    for (i=0; i<CPS_NDE; i++) {
        fprintf(out, "%10d ", i+1);
        print_row_fields(out, &radio_mem[CPS_DE_START + i * CPS_DE_SIZE], DTMFENC, NDTMFENC, width);
        fprintf(out, "\n");
    }

    fprintf(out, "\n");
    if (verbose) {
        fprintf(out, "# DTMF decode 1-8. ACK: - or an encode number. Revert: Selected or a\n");
        fprintf(out, "# channel number.\n");
        fprintf(out, "#\n");
    }
    table_header(out, "DTMFDecode", DTMFDEC, NDTMFDEC, width);
    for (i=0; i<CPS_NDD; i++) {
        fprintf(out, "%10d ", i+1);
        print_row_fields(out, &radio_mem[CPS_DD_START + i * CPS_DD_SIZE], DTMFDEC, NDTMFDEC, width);
        fprintf(out, "\n");
    }

    for (i=0; i<CPS_NVFO; i++) {
        char prefix[8];

        fprintf(out, "\n");
        if (verbose && i == 0) {
            fprintf(out, "# VFO Mode: VFO A and VFO B, with the CPS's labels. Digital and analog\n");
            fprintf(out, "# fields are all kept; the radio uses the ones for the VFO's mode.\n");
            fprintf(out, "#\n");
        }
        snprintf(prefix, sizeof(prefix), "VFO %c ", 'A' + i);
        print_scalars(out, &radio_mem[CPS_VFO_START + i * CPS_VFO_SIZE], VFOF, NVFOF, prefix);
    }
}

//
// A VFO scalar.  Privacy None clears the type, the key and the switch bit;
// any other type sets the switch bit, as the CPS's Privacy Switch.
//
static long vfo_key[CPS_NVFO] = { -1, -1 };

static void vfo_set(int v, const cfield_t *f, const char *value)
{
    unsigned char *r = &radio_mem[CPS_VFO_START + v * CPS_VFO_SIZE];
    int was = (r[2] >> 4) & 3, changed;
    char err[256], key[64];

    snprintf(key, sizeof(key), "VFO %c %s", 'A' + v, f->key);
    if (strcmp(f->key, "Privacy No.") == 0) {
        // Greyed in the CPS while Privacy is None: written at the end, and
        // only if the VFO then has a privacy type (check_76).
        if (! cf_parse(f, value, &vfo_key[v], err, sizeof(err)))
            conf_fail(key, "%s: %s", key, err);
        return;
    }
    if (! cf_set_text(r, f, value, &changed, err, sizeof(err)))
        conf_fail(key, "%s: %s", key, err);
    if (changed && strcmp(f->key, "Privacy") == 0) {
        int now = (r[2] >> 4) & 3;

        if (now == 0) {
            r[2] &= 0xc0;
            r[5] &= ~0x04;
        } else if (was == 0) {
            r[5] |= 0x04;
        }
        // A Universal key is 8 bits, the high nibble at +0x1E (CPS setter
        // 0x41c820); the CPS writes 0 there for keys 1-16, as the channel
        // tables do (uv380.c setup_channel).
        if (now == 3)
            r[0x1E] &= 0x0f;
    }
}

// 1 when the parameter is one of this page's scalars (and has been applied).
static int parse_param_76(const char *param, const char *value)
{
    char err[256];
    int i, v, changed;

    for (i=0; i<NEMERG; i++) {
        if (strcasecmp(param, EMERG[i].key) != 0)
            continue;
        if (! cf_set_text(radio_mem, &EMERG[i], value, &changed, err, sizeof(err)))
            conf_fail(EMERG[i].key, "%s: %s", EMERG[i].key, err);
        return 1;
    }
    for (v=0; v<CPS_NVFO; v++) {
        char prefix[8];

        snprintf(prefix, sizeof(prefix), "VFO %c ", 'A' + v);
        if (strncasecmp(param, prefix, 6) != 0)
            continue;
        for (i=0; i<NVFOF; i++) {
            if (strcasecmp(param + 6, VFOF[i].key) != 0)
                continue;
            vfo_set(v, &VFOF[i], value);
            return 1;
        }
    }
    return 0;
}

//
// One row of a record table: number, then one cell per field.  The cells
// are checked on a copy of the record, which replaces it only when all are
// good.
//
static int parse_record_row(const char *section, char **tok, int n, const cfield_t *tab,
    int nf, unsigned base, unsigned size, int count, long *idx)
{
    unsigned char tmp[64];
    char err[256];
    int k, changed;

    if (n != 1 + nf) {
        conf_error(0, "A %s row has %d columns; this one has %d.", section, 1 + nf, n);
        return 0;
    }
    if (! parse_long(tok[0], idx) || *idx < 1 || *idx > count) {
        conf_error("#", "%s number must be 1-%d.", section, count);
        return 0;
    }
    memcpy(tmp, &radio_mem[base + (*idx - 1) * size], size);
    for (k=0; k<nf; k++) {
        if (! cf_set_text(tmp, &tab[k], tok[1 + k], &changed, err, sizeof(err))) {
            conf_error(tab[k].key, "%s", err);
            return 0;
        }
    }
    memcpy(&radio_mem[base + (*idx - 1) * size], tmp, size);
    return 1;
}

static int parse_row_76(int table_id, char **tok, int n)
{
    long idx;

    switch (table_id) {
    case CPS_T_EMSYS:
        if (n == 1 + NEMSYS && strcmp(tok[1], "-") == 0) {
            unsigned char *r;
            int k;

            if (! parse_long(tok[0], &idx) || idx < 1 || idx > CPS_NEMS) {
                conf_error("#", "Emergency system number must be 1-%d.", CPS_NEMS);
                return 0;
            }
            // A system is deleted by a row of - only: a name of - alone
            // is a mistake, not a delete.
            for (k=2; k<n; k++) {
                if (strcmp(tok[k], "-") != 0) {
                    conf_error("Name", "An emergency system needs a name. To delete one, "
                        "put - in every column.");
                    return 0;
                }
            }
            // Name - deletes the system: an empty one has a zero name and
            // 0xFF in +0x20..+0x27 (as in every radio examined).
            r = emsys_rec(radio_mem, idx - 1);
            if (emsys_named(r)) {
                memset(r, 0, 32);
                memset(r + 0x20, 0xff, 8);
            }
            return 1;
        }
        return parse_record_row("EmergencySystem", tok, n, EMSYS, NEMSYS,
            CPS_EMS_START, CPS_EMS_SIZE, CPS_NEMS, &idx);

    case CPS_T_DTMFSYS:
        return parse_record_row("DTMFSystem", tok, n, DTMFSYS, NDTMFSYS,
            CPS_DS_START, CPS_DS_SIZE, CPS_NDS, &idx);

    case CPS_T_DTMFENC:
        if (n == 2 && strcmp(tok[0], "1") == 0 && strcmp(tok[1], "-") == 0) {
            char was[64];

            // Only emptying it is refused: an image that has no code there
            // (an erased one) prints - and reads back as it is (R2).
            cf_format(&radio_mem[CPS_DE_START], &DTMFENC[0], was, sizeof(was));
            if (strcmp(was, "-") != 0) {
                conf_error("Code", "Encode 1 can't be empty: the CPS always keeps a code there.");
                return 0;
            }
        }
        return parse_record_row("DTMFEncode", tok, n, DTMFENC, NDTMFENC,
            CPS_DE_START, CPS_DE_SIZE, CPS_NDE, &idx);

    case CPS_T_DTMFDEC:
        return parse_record_row("DTMFDecode", tok, n, DTMFDEC, NDTMFDEC,
            CPS_DD_START, CPS_DD_SIZE, CPS_NDD, &idx);
    }
    return -1;
}

//
// After the whole config: what the CPS would never leave behind.  Checked on
// the records this config changed, and on references this config broke (a
// record it deleted or emptied); a record the config leaves alone is kept as
// it is.  conf_mem_before is the image as the config found it.
//
static void problem_76(int table, const char *id, const char *section, const char *column,
    int code, const char *fmt, ...) __attribute__((format(printf, 6, 7)));
static void problem_76(int table, const char *id, const char *section, const char *column,
    int code, const char *fmt, ...)
{
    char msg[160];
    va_list ap;
    int n = nproblems;

    va_start(ap, fmt);
    vsnprintf(msg, sizeof(msg), fmt, ap);
    va_end(ap);
    problem(table, id, section, column, "%s", msg);
    if (nproblems > n)
        problems[nproblems - 1].code = code;
}

static void check_76(void)
{
    const unsigned char *B = conf_mem_before;
    const cfield_t *pk;
    char id[16], col[48];
    int i, count, mode;

    // A VFO's Privacy No., now that its Privacy is known.
    for (pk = VFOF; strcmp(pk->key, "Privacy No.") != 0; pk++)
        continue;
    for (i=0; i<CPS_NVFO; i++) {
        unsigned char *r = &radio_mem[CPS_VFO_START + i * CPS_VFO_SIZE];

        if (vfo_key[i] < 0)
            continue;
        if ((r[2] >> 4) & 3)
            cf_apply(r, pk, vfo_key[i]);
        vfo_key[i] = -1;
    }

    // Emergency systems: no gaps, when this config changed the page (an
    // image that came with a gap can still be written).
    count = emsys_count(radio_mem);
    if (memcmp(&radio_mem[CPS_EMERG_START], &B[CPS_EMERG_START], R76_EM_LEN) != 0) {
        for (i=count; i<CPS_NEMS; i++) {
            if (emsys_named(emsys_rec(radio_mem, i))) {
                snprintf(id, sizeof(id), "%d", i+1);
                problem(CPS_T_EMSYS, id, "EmergencySystem", "#",
                    "Emergency system %d comes after an empty system %d: systems are "
                    "numbered without gaps, so delete from the last one.", i+1, count+1);
                break;
            }
        }
    }
    // Nothing left using a system this config deletes.
    for (i=0; i<NCH; i++) {
        const unsigned char *r = &radio_mem[CH_BASE + i * CH_SIZE];
        int e = r[0x0A];

        if (! channel_valid(i, &mode) || mode != 2 || e <= count || e > CPS_NEMS ||
                ! emsys_named(emsys_rec((unsigned char *) B, e - 1)))
            continue;
        snprintf(id, sizeof(id), "%d", e);
        problem(CPS_T_EMSYS, id, "EmergencySystem", "Name",
            "Channel %d uses emergency system %d, which this config deletes.", i+1, e);
    }
    for (i=0; i<CPS_NVFO; i++) {
        const unsigned char *r = &radio_mem[CPS_VFO_START + i * CPS_VFO_SIZE];
        int e = r[0x0A];

        if (e <= count || e > CPS_NEMS || ! emsys_named(emsys_rec((unsigned char *) B, e - 1)))
            continue;
        snprintf(id, sizeof(id), "%d", e);
        problem(CPS_T_EMSYS, id, "EmergencySystem", "Name",
            "VFO %c uses emergency system %d, which this config deletes.", 'A' + i, e);
    }
    // Revert channels: on a system this config changed, or to a channel it
    // deleted.
    for (i=0; i<count; i++) {
        const unsigned char *r = emsys_rec(radio_mem, i);
        unsigned rv = r[0x24] | (r[0x25] << 8);

        if (rv < 1 || rv > NCH || channel_in(radio_mem, rv - 1))
            continue;
        if (memcmp(r, &B[CPS_EMS_START + i * CPS_EMS_SIZE], CPS_EMS_SIZE) == 0 &&
                ! channel_in(B, rv - 1))
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        problem(CPS_T_EMSYS, id, "EmergencySystem", "Revert",
            "Emergency system %d: revert channel %u is not in the codeplug.", i+1, rv);
    }

    // DTMF decode: ACK names an encode entry with a code; revert a channel.
    for (i=0; i<CPS_NDD; i++) {
        const unsigned char *r = &radio_mem[CPS_DD_START + i * CPS_DD_SIZE];
        const unsigned char *o = &B[CPS_DD_START + i * CPS_DD_SIZE];
        unsigned rv = r[0x14] | (r[0x15] << 8);
        int ack = r[0x12], changed = memcmp(r, o, CPS_DD_SIZE) != 0;

        snprintf(id, sizeof(id), "%d", i+1);
        if (ack >= 1 && ack <= CPS_NDE) {
            const unsigned char *e = &radio_mem[CPS_DE_START + (ack - 1) * CPS_DE_SIZE];
            const unsigned char *eo = &B[CPS_DE_START + (ack - 1) * CPS_DE_SIZE];

            if ((e[0] == 0 || e[0] > DTMF_MAX) && (changed || memcmp(e, eo, CPS_DE_SIZE) != 0))
                problem(CPS_T_DTMFDEC, id, "DTMFDecode", "ACK",
                    "Decode %d answers with encode %d, which has no code.", i+1, ack);
        }
        if (rv >= 1 && rv <= NCH && ! channel_in(radio_mem, rv - 1) &&
                (changed || channel_in(B, rv - 1)))
            problem(CPS_T_DTMFDEC, id, "DTMFDecode", "Revert",
                "Decode %d: revert channel %u is not in the codeplug.", i+1, rv);
    }

    // VFOs: what the CPS's VFO page would allow, and records that exist.
    for (i=0; i<CPS_NVFO; i++) {
        const unsigned char *r = &radio_mem[CPS_VFO_START + i * CPS_VFO_SIZE];
        const unsigned char *o = &B[CPS_VFO_START + i * CPS_VFO_SIZE];
        int changed = memcmp(r, o, CPS_VFO_SIZE) != 0, chmode = r[0] & 3;
        int type = (r[2] >> 4) & 3, key = (r[2] & 0x0f) + 1;
        int admit = r[4] >> 6, tot = r[8] & 0x3f;
        unsigned c = r[6] | (r[7] << 8), oc = o[6] | (o[7] << 8);
        int g = r[0x0C], sl = r[0x0B], e = r[0x0A];
        char v = 'A' + i;

        if (type == 3)
            key += r[0x1E] & 0xf0;
        if (changed && type == 2 && key > 8) {
            snprintf(col, sizeof(col), "VFO %c Privacy No.", v);
            problem(0, "", "General", strdup(col), "VFO %c: Enhanced privacy has only 8 keys.", v);
        }
        // The CPS's lists: Correct CTCSS/CDCSS for analog, Color Code for
        // digital; and with DCDM on, a TOT of 15-60 s (as the channels).
        if (changed && ((chmode == 1 && admit == 3) || (chmode == 2 && admit == 2))) {
            snprintf(col, sizeof(col), "VFO %c Admit Criteria", v);
            problem(0, "", "General", strdup(col), "VFO %c: Admit Criteria %s is for %s VFO.", v,
                admit == 3 ? "Color Code" : "Correct CTCSS/CDCSS",
                admit == 3 ? "a digital" : "an analog");
        }
        if (changed && chmode == 2 && ! (r[0x1F] & 0x08) && (tot < 1 || tot > 4)) {
            snprintf(col, sizeof(col), "VFO %c TOT[s]", v);
            problem(0, "", "General", strdup(col),
                "VFO %c has DCDM on, so its TOT must be 15, 30, 45 or 60 s.", v);
        }
        if (c >= 1 && c <= NCT && ! contact_in(radio_mem, c - 1) &&
                (c != oc || contact_in(B, c - 1))) {
            snprintf(col, sizeof(col), "VFO %c Contact Name", v);
            problem(0, "", "General", strdup(col), "VFO %c: contact %u is not in the codeplug.", v, c);
        }
        if (g >= 1 && g <= NGL && ! grouplist_in(radio_mem, g - 1) &&
                (g != o[0x0C] || grouplist_in(B, g - 1))) {
            snprintf(col, sizeof(col), "VFO %c Group List", v);
            problem(0, "", "General", strdup(col), "VFO %c: group list %d is not in the codeplug.", v, g);
        }
        if (sl >= 1 && sl <= NSL && ! scanlist_in(radio_mem, sl - 1) &&
                (sl != o[0x0B] || scanlist_in(B, sl - 1))) {
            snprintf(col, sizeof(col), "VFO %c Scan List", v);
            problem(0, "", "General", strdup(col), "VFO %c: scan list %d is not in the codeplug.", v, sl);
        }
        if (e >= 1 && e <= CPS_NEMS && e > count && e != o[0x0A] &&
                ! emsys_named(emsys_rec((unsigned char *) B, e - 1))) {
            snprintf(col, sizeof(col), "VFO %c Emergency System", v);
            problem(0, "", "General", strdup(col),
                "VFO %c: emergency system %d is not in the codeplug.", v, e);
        }
        // As the channels with -F: a Universal key the fleet file leaves
        // empty means scrambled audio on a VFO that looks right.
        if (chmode == 2 && type == 3 && radio_fleet_keys &&
                (key > 16 || ! privacy_slot_available(radio_fleet_keys, key))) {
            snprintf(col, sizeof(col), "VFO %c Privacy No.", v);
            problem_76(0, "", "General", strdup(col), EXIT_KEY_SLOT_EMPTY,
                "VFO %c: Universal key %d is empty in the fleet key table.", v, key);
        }
    }
}

void cps_parse_finish(void)
{
    int i, k, mode;
    char id[16];

    begun = 0;
    if (! pending) {
        check_76();
        return;
    }
    for (i=0; i<NMENU; i++)
        if (menu_val[i] != UNSET)
            cf_apply(radio_mem, &MENU[i], menu_val[i]);
    for (i=0; i<NBUTTONS; i++) {
        if (button_val[i][0] != UNSET)
            radio_mem[BUTTONS[i].shrt] = button_val[i][0];
        if (button_val[i][1] != UNSET)
            radio_mem[BUTTONS[i].lng] = button_val[i][1];
    }
    for (i=0; i<NONETOUCH; i++) {
        unsigned char *r = &radio_mem[OT_BASE + 4*i];
        long *v = onetouch_val[i];

        if (v[0] == UNSET)
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        // Rows the config changes are checked here; the rest in
        // cps_check_refs(), whether or not the config carries them.
        if (v[1] && v[1] <= NCT && ! contact_valid(v[1] - 1) && onetouch_changed(i, v))
            problem(CPS_T_ONETOUCH, id, "OneTouch", "Call",
                "One Touch Access %d: contact %ld is not in the codeplug.", i+1, v[1]);
        if (v[0] == 1 && v[2] == 1 && v[3] && (v[3] > NMSG || ! message_valid(v[3] - 1)) &&
                onetouch_changed(i, v))
            problem(CPS_T_ONETOUCH, id, "OneTouch", "Message",
                "One Touch Access %d: message %ld is not in the codeplug.", i+1, v[3]);
        // Bits 7-6 of the first byte are the CPS's and are kept.
        r[0] = (r[0] & 0xc0) | ((v[0] & 3) << 4) | (v[2] & 0x0f);
        r[1] = v[3];
        r[2] = v[1] & 0xff;
        r[3] = v[1] >> 8;
    }
    for (k=0; k<NNUMKEY; k++) {
        if (numkey_val[k] == UNSET)
            continue;
        snprintf(id, sizeof(id), "%d", k);
        if (numkey_val[k] && numkey_val[k] <= NCT && ! contact_valid(numkey_val[k] - 1) &&
                (radio_mem[NK_BASE + 2*k] | (radio_mem[NK_BASE + 2*k + 1] << 8)) != numkey_val[k])
            problem(CPS_T_NUMKEY, id, "NumberKey", "Contact",
                "Number key %d: contact %ld is not in the codeplug.", k, numkey_val[k]);
        radio_mem[NK_BASE + 2*k] = numkey_val[k] & 0xff;
        radio_mem[NK_BASE + 2*k + 1] = numkey_val[k] >> 8;
    }
    for (i=0; i<NSL; i++) {
        long *v = &scan_val[i * NSCANTIMING];

        if (v[0] == UNSET)
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        if (! scanlist_valid(i)) {
            problem(CPS_T_SCANTIMING, id, "ScanTiming", "#",
                "Scan list %d is not in the codeplug.", i+1);
            continue;
        }
        for (k=0; k<NSCANTIMING; k++)
            cf_apply(&radio_mem[SL_BASE + i*SL_SIZE], &SCANTIMING[k], v[k]);
    }
    for (i=0; i<NCH; i++) {
        const cfield_t *tab;
        long *v = &chan_val[i * 32];
        int nf;

        if (! chan_mode_given[i])
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        tab = chan_mode_given[i] == 2 ? CHANDIG : CHANANA;
        nf = chan_mode_given[i] == 2 ? NCHANDIG : NCHANANA;
        if (! channel_valid(i, &mode) || mode != chan_mode_given[i]) {
            problem(chan_mode_given[i] == 2 ? CPS_T_CHANDIG : CPS_T_CHANANA, id,
                chan_mode_given[i] == 2 ? "ChanDigital" : "ChanAnalog", "#",
                "Channel %d is not %s channel in this codeplug.", i+1,
                chan_mode_given[i] == 2 ? "a digital" : "an analog");
            continue;
        }
        for (k=0; k<nf; k++)
            cf_apply(&radio_mem[CH_BASE + i*CH_SIZE], &tab[k], v[k]);
    }
    pending = 0;
    check_76();
}

//
// With DCDM on the CPS offers only TOT 15-60 s (map 2.12, 4.3).  Checked
// after the whole config, on every digital channel, whichever table changed
// it; before is the channel bank as it was before the config, and a channel
// that already had this DCDM and TOT is kept as it is (R2).
//
//
// One Touch and Number Key bytes as the image had them, before the config.
//
static unsigned char ot_before[4 * NONETOUCH], nk_before[2 * NNUMKEY];

void cps_note_buttons(void)
{
    memcpy(ot_before, &radio_mem[OT_BASE], sizeof(ot_before));
    memcpy(nk_before, &radio_mem[NK_BASE], sizeof(nk_before));
}

//
// A One Touch or Number Key row the config leaves as it is - unchanged, or
// not in the config at all (R1) - may keep pointing at a record the image
// never had, but not at one the same config deletes: the CPS never leaves
// such a row (map 2.4, 4.4).  Rows the config changes are checked when they
// are applied.
//
void cps_check_refs(void)
{
    char id[16];
    int i;

    for (i=0; i<NONETOUCH; i++) {
        const unsigned char *r = &radio_mem[OT_BASE + 4*i];
        int mode = (r[0] >> 4) & 3, ct = r[0] & 0x0f, msg = r[1];
        unsigned call = r[2] | (r[3] << 8);

        if (memcmp(r, &ot_before[4*i], 4) != 0)
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        if (call && call <= NCT && ! contact_valid(call - 1) && contact_was_valid(call - 1))
            problem(CPS_T_ONETOUCH, id, "OneTouch", "Call",
                "One Touch Access %d calls contact %u, which this config deletes.", i+1, call);
        if (mode == 1 && ct == 1 && msg && msg <= NMSG && ! message_valid(msg - 1) &&
                message_was_valid(msg - 1))
            problem(CPS_T_ONETOUCH, id, "OneTouch", "Message",
                "One Touch Access %d sends message %d, which this config deletes.", i+1, msg);
    }
    for (i=0; i<NNUMKEY; i++) {
        const unsigned char *r = &radio_mem[NK_BASE + 2*i];
        unsigned c = r[0] | (r[1] << 8);

        if (memcmp(r, &nk_before[2*i], 2) != 0)
            continue;
        snprintf(id, sizeof(id), "%d", i);
        if (c && c <= NCT && ! contact_valid(c - 1) && contact_was_valid(c - 1))
            problem(CPS_T_NUMKEY, id, "NumberKey", "Contact",
                "Number key %d calls contact %u, which this config deletes.", i, c);
    }
}

void cps_check_channels(const unsigned char *before)
{
    char id[16];
    int i, mode, omode;

    for (i=0; i<NCH; i++) {
        const unsigned char *r = &radio_mem[CH_BASE + i*CH_SIZE], *o = &before[i*CH_SIZE];
        int tot = r[0x08] & 0x3f, was_dcdm;

        if (! channel_valid(i, &mode) || mode != 2 || (r[0x1F] & 0x08) || (tot >= 1 && tot <= 4))
            continue;
        was_dcdm = channel_record_valid(o, &omode) && omode == 2 && ! (o[0x1F] & 0x08);
        if (was_dcdm && (o[0x08] & 0x3f) == tot)
            continue;
        snprintf(id, sizeof(id), "%d", i+1);
        if (was_dcdm)
            problem('D', id, "Digital", "TOT",
                "Channel %d has DCDM on, so its TOT must be 15, 30, 45 or 60 s.", i+1);
        else
            problem(CPS_T_CHANDIG, id, "ChanDigital", "DCDM",
                "Channel %d: with DCDM on, its TOT must be 15, 30, 45 or 60 s.", i+1);
    }

    // Emergency System: a system that exists (the CPS lists only those).
    // A channel whose number this config leaves as it was is kept; one that
    // uses a system the config deletes is reported by check_76().
    {
        int count = emsys_count(radio_mem), e;

        for (i=0; i<NCH; i++) {
            const unsigned char *r = &radio_mem[CH_BASE + i*CH_SIZE], *o = &before[i*CH_SIZE];

            e = r[0x0A];
            if (! channel_valid(i, &mode) || mode != 2 || e < 1 || e > CPS_NEMS || e <= count)
                continue;
            if (channel_record_valid(o, &omode) && omode == 2 && o[0x0A] == e)
                continue;
            if (emsys_named(emsys_rec(conf_mem_before, e - 1)))
                continue;
            snprintf(id, sizeof(id), "%d", i+1);
            problem(CPS_T_CHANDIG, id, "ChanDigital", "EmSys",
                "Channel %d: emergency system %d is not in the codeplug.", i+1, e);
        }
    }
}

int cps_verify(void)
{
    int i;

    for (i=0; i<nproblems; i++) {
        conf_problem_begin(problems[i].code, problems[i].table, problems[i].id,
            problems[i].section, problems[i].column);
        error_event_end("%s", problems[i].msg);
    }
    return nproblems == 0;
}

// ---------------------------------------------------------------------------
// diff: field names for the General, Menu, Buttons, OneTouch, NumberKey and
// scan-list timing records.
// ---------------------------------------------------------------------------

static void diff_tab(const unsigned char *a, const unsigned char *b, const cfield_t *tab,
    int n, unsigned base, unsigned char *covered, unsigned clen,
    cps_field_event_t field_event,
    char *human, int hsize)
{
    char ov[64], nv[64];
    int k;

    for (k=0; k<n; k++) {
        const cfield_t *f = &tab[k];
        unsigned off = f->off - base, w = f->mask ? 1 : f->width, j;

        for (j=0; j<w; j++)
            if (off + j < clen)
                covered[off + j] |= f->mask ? f->mask : 0xff;
        cf_format(a, f, ov, sizeof(ov));
        cf_format(b, f, nv, sizeof(nv));
        if (strcmp(ov, nv) != 0)
            field_event(f->key, ov, nv, human, hsize);
    }
}

void cps_diff_general(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered, unsigned clen,
    cps_field_event_t field_event,
    char *human, int hsize)
{
    // Menu Hang Time and Long Press Duration live in the menu and button
    // records; the rest is the general record.
    int k;

    for (k=0; k<NGENERAL; k++) {
        if (GENERAL[k].off < start || GENERAL[k].off >= start + clen)
            continue;
        diff_tab(a, b, &GENERAL[k], 1, start, covered, clen, field_event, human, hsize);
    }
}

int cps_diff_record(const char *kind, const unsigned char *a, const unsigned char *b,
    unsigned rec_start, unsigned rec_len, unsigned char *covered,
    cps_field_event_t field_event,
    char *human, int hsize)
{
    char ov[64], nv[64];
    int k;

    if (strcmp(kind, "menu") == 0) {
        diff_tab(a, b, MENU, NMENU, rec_start, covered, rec_len, field_event, human, hsize);
        diff_tab(a, b, &GENERAL[NGENERAL-2], 1, rec_start, covered, rec_len, field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "buttons") == 0) {
        for (k=0; k<NBUTTONS; k++) {
            unsigned o[2] = { BUTTONS[k].shrt, BUTTONS[k].lng };
            const char *col[2] = { "Short", "Long" };
            int s;

            for (s=0; s<2; s++) {
                char fname[48];

                const char *was, *now;

                covered[o[s] - rec_start] = 0xff;
                was = button_name(a[o[s]], ov, sizeof(ov));
                now = button_name(b[o[s]], nv, sizeof(nv));
                if (strcmp(was, now) != 0) {
                    snprintf(fname, sizeof(fname), "%s %s", BUTTONS[k].name, col[s]);
                    field_event(fname, was, now, human, hsize);
                }
            }
        }
        diff_tab(a, b, &GENERAL[NGENERAL-1], 1, rec_start, covered, rec_len, field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "onetouch") == 0) {
        const unsigned char *ra = &a[rec_start], *rb = &b[rec_start];

        int ma = (ra[0] >> 4) & 3, mb = (rb[0] >> 4) & 3;

        memset(covered, 0xff, 4);
        covered[0] = 0x3f;              // bits 7-6 are the CPS's own
        if (ma != mb)
            field_event("Mode", ma < 3 ? W_OTMODE[ma] : "raw:0x3",
                mb < 3 ? W_OTMODE[mb] : "raw:0x3", human, hsize);
        if (((ra[0] ^ rb[0]) & 0x0f)) {
            snprintf(ov, sizeof(ov), "%d", ra[0] & 0x0f);
            snprintf(nv, sizeof(nv), "%d", rb[0] & 0x0f);
            field_event("CallType", ov, nv, human, hsize);
        }
        if (ra[1] != rb[1]) {
            snprintf(ov, sizeof(ov), "%d", ra[1]);
            snprintf(nv, sizeof(nv), "%d", rb[1]);
            field_event("Message", ov, nv, human, hsize);
        }
        if (ra[2] != rb[2] || ra[3] != rb[3]) {
            snprintf(ov, sizeof(ov), "%d", ra[2] | (ra[3] << 8));
            snprintf(nv, sizeof(nv), "%d", rb[2] | (rb[3] << 8));
            field_event("Call", ov, nv, human, hsize);
        }
        return 1;
    }
    if (strcmp(kind, "emergency") == 0) {
        diff_tab(a, b, EMERG, NEMERG, rec_start, covered, rec_len, field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "emsystem") == 0) {
        diff_tab(a + rec_start, b + rec_start, EMSYS, NEMSYS, 0, covered, rec_len,
            field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "dtmfsystem") == 0) {
        diff_tab(a + rec_start, b + rec_start, DTMFSYS, NDTMFSYS, 0, covered, rec_len,
            field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "dtmfencode") == 0) {
        diff_tab(a + rec_start, b + rec_start, DTMFENC, NDTMFENC, 0, covered, rec_len,
            field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "dtmfdecode") == 0) {
        diff_tab(a + rec_start, b + rec_start, DTMFDEC, NDTMFDEC, 0, covered, rec_len,
            field_event, human, hsize);
        return 1;
    }
    if (strcmp(kind, "vfo") == 0) {
        diff_tab(a + rec_start, b + rec_start, VFOF, NVFOF, 0, covered, rec_len,
            field_event, human, hsize);
        covered[0x1E] |= 0xf0;          // Privacy No.'s high nibble (Universal)
        return 1;
    }
    if (strcmp(kind, "numberkey") == 0) {
        memset(covered, 0xff, 2);
        snprintf(ov, sizeof(ov), "%d", a[rec_start] | (a[rec_start+1] << 8));
        snprintf(nv, sizeof(nv), "%d", b[rec_start] | (b[rec_start+1] << 8));
        if (strcmp(ov, nv) != 0)
            field_event("Contact", ov, nv, human, hsize);
        return 1;
    }
    return 0;
}

//
// The name the preview gives a record of these pages (index from 0), or ""
// for an empty emergency system.
//
void cps_record_name(const unsigned char *mem, const char *kind, int index, char *buf, int size)
{
    buf[0] = 0;
    if (strcmp(kind, "emsystem") == 0) {
        const unsigned char *r = &mem[CPS_EMS_START + index * CPS_EMS_SIZE];
        unsigned short name[16];

        if (emsys_named(r)) {
            memcpy(name, r, sizeof(name));
            utf16_to_utf8(name, 16, buf, size);
        }
    } else if (strcmp(kind, "dtmfsystem") == 0) {
        snprintf(buf, size, "DTMF-%d", index + 1);
    } else if (strcmp(kind, "dtmfencode") == 0) {
        snprintf(buf, size, "Encode %d", index + 1);
    } else if (strcmp(kind, "dtmfdecode") == 0) {
        snprintf(buf, size, "Decode %d", index + 1);
    } else if (strcmp(kind, "vfo") == 0) {
        snprintf(buf, size, "VFO %c", 'A' + index);
    }
}

void cps_diff_scanlist(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered,
    cps_field_event_t field_event,
    char *human, int hsize)
{
    diff_tab(a + start, b + start, SCANTIMING, NSCANTIMING, 0, covered, SL_SIZE,
        field_event, human, hsize);
}

//
// Channel fields for the diff: names for bits CHAN_FIELD_TAB leaves as +0xNN.
//
void cps_diff_channel(const unsigned char *a, const unsigned char *b, unsigned start,
    unsigned char *covered,
    cps_field_event_t field_event,
    char *human, int hsize)
{
    const cfield_t *tabs[2] = { CHANDIG, CHANANA };
    int ns[2] = { NCHANDIG, NCHANANA }, t, k;
    char ov[64], nv[64];

    for (t=0; t<2; t++) {
        for (k=0; k<ns[t]; k++) {
            const cfield_t *f = &tabs[t][k];
            unsigned char m = f->mask ? f->mask : 0xff;

            if ((covered[f->off] & m) == m)
                continue;               // named already (CHAN_FIELD_TAB or the other table)
            covered[f->off] |= m;
            cf_format(&a[start], f, ov, sizeof(ov));
            cf_format(&b[start], f, nv, sizeof(nv));
            if (strcmp(ov, nv) != 0)
                field_event(f->key, ov, nv, human, hsize);
        }
    }
}
