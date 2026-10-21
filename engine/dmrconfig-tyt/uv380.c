/*
 * Interface to TYT MD-UV380 and MD-2017.
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
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <stdint.h>
#include <sys/stat.h>
#include "radio.h"
#include "util.h"
#include "report.h"
#include "cpsfields.h"

//#define PRINT_EXTENDED_PARAMS

#define NCHAN           3000
#define NCONTACTS       10000
#define NZONES          250
#define NGLISTS         250
#define NSCANL          250
#define NMESSAGES       50

#define MEMSZ           0xd0000
#define OFFSET_TIMESTMP 0x02001
#define OFFSET_SETTINGS 0x02040
#define OFFSET_MSG      0x02180
#define OFFSET_GLISTS   0x0ec20
#define OFFSET_ZONES    0x149e0
#define OFFSET_SCANL    0x18860
#define OFFSET_ZONEXT   0x31000
#define OFFSET_CHANNELS 0x40000
#define OFFSET_CONTACTS 0x70000

#define CALLSIGN_START  0x00200000  // Start of callsign database
#define CALLSIGN_FINISH 0x01000000  // End of callsign database
#define CALLSIGN_OFFSET 0x4003

#define GET_TIMESTAMP()     (&radio_mem[OFFSET_TIMESTMP])
#define GET_SETTINGS()      ((general_settings_t*) &radio_mem[OFFSET_SETTINGS])
#define GET_CHANNEL(i)      ((channel_t*) &radio_mem[OFFSET_CHANNELS + (i)*64])
#define GET_ZONE(i)         ((zone_t*) &radio_mem[OFFSET_ZONES + (i)*64])
#define GET_ZONEXT(i)       ((zone_ext_t*) &radio_mem[OFFSET_ZONEXT + (i)*224])
#define GET_SCANLIST(i)     ((scanlist_t*) &radio_mem[OFFSET_SCANL + (i)*104])
#define GET_CONTACT(i)      ((contact_t*) &radio_mem[OFFSET_CONTACTS + (i)*36])
#define GET_GROUPLIST(i)    ((grouplist_t*) &radio_mem[OFFSET_GLISTS + (i)*96])
#define GET_MESSAGE(i)      ((uint16_t*) &radio_mem[OFFSET_MSG + (i)*288])
#define GET_CALLSIGN(m,i)   ((callsign_t*) ((m) + CALLSIGN_OFFSET + (i)*120))

#define VALID_TEXT(txt)     (*(txt) != 0 && *(txt) != 0xffff)
#define VALID_CHANNEL(ch)   VALID_TEXT((ch)->name)
#define VALID_ZONE(z)       VALID_TEXT((z)->name)
#define VALID_SCANLIST(sl)  VALID_TEXT((sl)->name)
#define VALID_GROUPLIST(gl) VALID_TEXT((gl)->name)
#define VALID_CONTACT(ct)   ((ct)->type != 0 && VALID_TEXT((ct)->name))

//
// Channel data.
//
typedef struct {
    // Byte 0
    uint8_t channel_mode        : 2,    // Mode: Analog or Digital
#define MODE_ANALOG     1
#define MODE_DIGITAL    2

            bandwidth           : 2,    // Bandwidth: 12.5 or 20 or 25 kHz
#define BW_12_5_KHZ     0
#define BW_20_KHZ       1
#define BW_25_KHZ       2

            autoscan            : 1,    // Autoscan Enable
            _unused1            : 2,    // 0b11
            lone_worker         : 1;    // Lone Worker

    // Byte 1
    uint8_t _unused2            : 1,    // 0
            rx_only             : 1,    // RX Only Enable
            repeater_slot       : 2,    // Repeater Slot: 1 or 2
            colorcode           : 4;    // Color Code: 0...15

    // Byte 2
    uint8_t privacy_no          : 4,    // Privacy No. (+1): 1...16
            privacy             : 2,    // Privacy: None, Basic, Enhanced
                                        // or Universal
#define PRIV_NONE       0
#define PRIV_BASIC      1
#define PRIV_ENHANCED   2
#define PRIV_UNIVERSAL  3               // MD-UV390 Plus AES, Phase 1

            private_call_conf   : 1,    // Private Call Confirmed
            data_call_conf      : 1;    // Data Call Confirmed

    // Byte 3
    uint8_t rx_ref_frequency    : 2,    // RX Ref Frequency: Low, Medium or High
#define REF_LOW         0
#define REF_MEDIUM      1
#define REF_HIGH        2

            _unused3            : 1,    // 0
            emergency_alarm_ack : 1,    // Emergency Alarm Ack
            _unused4            : 3,    // 0b110
            display_pttid_dis   : 1;    // Display PTT ID (inverted)

    // Byte 4
    uint8_t tx_ref_frequency    : 2,    // RX Ref Frequency: Low, Medium or High
            _unused5            : 2,    // 0b01
            vox                 : 1,    // VOX Enable
            _unused6            : 1,    // 1
            admit_criteria      : 2;    // Admit Criteria: Always, Channel Free or Correct CTS/DCS
#define ADMIT_ALWAYS    0
#define ADMIT_CH_FREE   1
#define ADMIT_TONE      2
#define ADMIT_COLOR     3

    // Byte 5
    uint8_t _unused7a           : 2,    // 0

            privacy_enable      : 1,    // Privacy enabled, ANY type.
                                        // Upstream calls this bit unused; the
                                        // Plus CPS sets it for Basic,
                                        // Enhanced and Universal alike and
                                        // clears it for None.  Mapped in
                                        // Phase 1, settled by variant H in
                                        // (USB captures of the stock CPS).

            _unused7b           : 1,    // 0
            in_call_criteria    : 2,    // In Call Criteria: Always, Follow Admit Criteria or TX Interrupt
#define INCALL_ALWAYS   0
#define INCALL_ADMIT    1
#define INCALL_TXINT    2

            turn_off_freq       : 2;    // Non-QT/DQT Turn-off Freq.: None, 259.2Hz or 55.2Hz
#define TURNOFF_NONE    3
#define TURNOFF_259_2HZ 0
#define TURNOFF_55_2HZ  1

    // Bytes 6-7
    uint16_t contact_name_index;        // Contact Name: Contact1...

    // Bytes 8-9
    uint8_t tot                 : 6,    // TOT x 15sec: 0-Infinite, 1=15s... 37=555s
            _unused13           : 2;    // 0
    uint8_t tot_rekey_delay;            // TOT Rekey Delay: 0s...255s

    // Bytes 10-11
    uint8_t emergency_system_index;     // Emergency System: None, System1...32
    uint8_t scan_list_index;            // Scan List: None, ScanList1...250

    // Bytes 12-13
    uint8_t group_list_index;           // Group List: None, GroupList1...250
    uint8_t _unused8;                   // 0

    // Bytes 14-15
    uint8_t _unused9;                   // 0
    uint8_t squelch;                    // Squelch: 0...9

    // Bytes 16-23
    uint32_t rx_frequency;              // RX Frequency: 8 digits BCD
    uint32_t tx_frequency;              // TX Frequency: 8 digits BCD

    // Bytes 24-27
    uint16_t ctcss_dcs_receive;         // CTCSS/DCS Dec: 4 digits BCD
    uint16_t ctcss_dcs_transmit;        // CTCSS/DCS Enc: 4 digits BCD

    // Bytes 28-29
    uint8_t rx_signaling_syst;          // Rx Signaling System: Off, DTMF-1...4
    uint8_t tx_signaling_syst;          // Tx Signaling System: Off, DTMF-1...4

    // Byte 30
    uint8_t power               : 2,    // Power: Low, Middle, High
#define POWER_HIGH      3
#define POWER_LOW       0
#define POWER_MIDDLE    2

            _unused10           : 6;    // 0b111111

    // Byte 31
    uint8_t _unused11           : 3,    // 0b111
            dcdm_switch_dis     : 1,    // DCDM switch (inverted)
            leader_ms           : 1,    // Leader/MS: Leader or MS
#define DCDM_LEADER     0
#define DCDM_MS         1

            _unused12           : 3;    // 0b111

    // Bytes 32-63
    uint16_t name[16];                  // Channel Name (Unicode)
} channel_t;

//
// Contact data.
//
typedef struct {
    // Bytes 0-2
    uint8_t id[3];                      // Call ID: 1...16777215
#define CONTACT_ID(ct) ((ct)->id[0] | ((ct)->id[1] << 8) | ((ct)->id[2] << 16))

    // Byte 3
    uint8_t type                : 5,    // Call Type: Group Call, Private Call or All Call
#define CALL_GROUP      1
#define CALL_PRIVATE    2
#define CALL_ALL        3

            receive_tone        : 1,    // Call Receive Tone: No or yes
            _unused2            : 2;    // 0b11

    // Bytes 4-35
    uint16_t name[16];                  // Contact Name (Unicode)
} contact_t;

//
// Zone data.
//
typedef struct {
    // Bytes 0-31
    uint16_t name[16];                  // Zone Name (Unicode)

    // Bytes 32-63
    uint16_t member_a[16];              // Member A: channels 1...16
} zone_t;

typedef struct {
    // Bytes 0-95
    uint16_t ext_a[48];                 // Member A: channels 17...64

    // Bytes 96-223
    uint16_t member_b[64];              // Member B: channels 1...64
} zone_ext_t;

//
// Group list data.
//
typedef struct {
    // Bytes 0-31
    uint16_t name[16];                  // Group List Name (Unicode)

    // Bytes 32-95
    uint16_t member[32];                // Contacts
} grouplist_t;

//
// Scan list data.
//
typedef struct {
    // Bytes 0-31
    uint16_t name[16];                  // Scan List Name (Unicode)

    // Bytes 32-37
    uint16_t priority_ch1;              // Priority Channel 1 or ffff
    uint16_t priority_ch2;              // Priority Channel 2 or ffff
    uint16_t tx_designated_ch;          // Tx Designated Channel or ffff

    // Bytes 38-41
    uint8_t _unused1;                   // 0xf1
    uint8_t sign_hold_time;             // Signaling Hold Time (x25 = msec)
    uint8_t prio_sample_time;           // Priority Sample Time (x250 = msec)
    uint8_t _unused2;                   // 0xff

    // Bytes 42-103
    uint16_t member[31];                // Channels
} scanlist_t;

//
// General settings.
// TODO: verify the general settings with official CPS
//
typedef struct {

    // Bytes 0-19
    uint16_t intro_line1[10];

    // Bytes 20-39
    uint16_t intro_line2[10];

    // Bytes 40-63
    uint8_t  _unused40[24];

    // Byte 64
    uint8_t  _unused64_0                : 3,
             monitor_type               : 1,
             _unused64_4                : 1,
             disable_all_leds           : 1,
             _unused64_6                : 2;

    // Byte 65
    uint8_t  talk_permit_tone           : 2,
             pw_and_lock_enable         : 1,
             ch_free_indication_tone    : 1,
             _unused65_4                : 1,
             disable_all_tones          : 1,
             save_mode_receive          : 1,
             save_preamble              : 1;

    // Byte 66
    uint8_t  _unused66_0                : 2,
             keypad_tones               : 1,
             intro_picture              : 1,
             _unused66_4                : 4;

    // Byte 67
    uint8_t  _unused67;

    // Bytes 68-71
    uint8_t  radio_id[3];
    uint8_t  _unused71;

    // Bytes 72-84
    uint8_t  tx_preamble_duration;
    uint8_t  group_call_hang_time;
    uint8_t  private_call_hang_time;
    uint8_t  vox_sensitivity;
    uint8_t  _unused76[2];
    uint8_t  rx_low_battery_interval;
    uint8_t  call_alert_tone_duration;
    uint8_t  lone_worker_response_time;
    uint8_t  lone_worker_reminder_time;
    uint8_t  _unused82;
    uint8_t  scan_digital_hang_time;
    uint8_t  scan_analog_hang_time;

    // Byte 85
    uint8_t  _unused85_0                : 6,
             backlight_time             : 2;

    // Bytes 86-87
    uint8_t  set_keypad_lock_time;
    uint8_t  mode;

    // Bytes 88-95
    uint32_t power_on_password;
    uint32_t radio_prog_password;

    // Bytes 96-103
    uint8_t  pc_prog_password[8];

    // Bytes 104-111
    uint8_t  _unused104[8];

    // Bytes 112-143
    uint16_t radio_name[16];
} general_settings_t;

//
// Callsign database (CSV).
//
typedef struct {
    unsigned dmrid   : 24;      // DMR id
    unsigned _unused : 8;       // 0xff
    char     callsign[16];      // ascii zero terminated
    char     name[100];         // name, nickname, city, state, country
} callsign_t;

static const char *POWER_NAME[] = { "Low", "Low", "Mid", "High" };
static const char *BANDWIDTH[] = { "12.5", "20", "25", "25" };
static const char *CONTACT_TYPE[] = { "-", "Group", "Private", "All" };
static const char *ADMIT_NAME[] = { "-", "Free", "Tone", "Color" };

// Privacy type names, indexed by channel_t.privacy. Index 3 is the Plus
// "Universal" (AES) type, which neither upstream dmrconfig nor qdmr knows.
static const char *PRIVACY_NAME[] = { "None", "Basic", "Enhanced", "Universal" };
#define NPRIVACY ((int) (sizeof(PRIVACY_NAME) / sizeof(PRIVACY_NAME[0])))

#ifdef PRINT_EXTENDED_PARAMS
static const char *INCALL_NAME[] = { "-", "Admit", "TXInt", "Admit" };
static const char *REF_FREQUENCY[] = { "Low", "Med", "High" };
static const char *SIGNALING_SYSTEM[] = { "-", "DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4" };
static const char *TURNOFF_FREQ[] = { "259.2", "55.2", "-", "-" };
#endif

//
// Print a generic information about the device.
//
static void uv380_print_version(radio_device_t *radio, FILE *out)
{
    unsigned char *timestamp = GET_TIMESTAMP();
    static const char charmap[16] = "0123456789:;<=>?";

    if (*timestamp != 0xff) {
        fprintf(out, "Last Programmed Date: %d%d%d%d-%d%d-%d%d",
            timestamp[0] >> 4, timestamp[0] & 15, timestamp[1] >> 4, timestamp[1] & 15,
            timestamp[2] >> 4, timestamp[2] & 15, timestamp[3] >> 4, timestamp[3] & 15);
        fprintf(out, " %d%d:%d%d:%d%d\n",
            timestamp[4] >> 4, timestamp[4] & 15, timestamp[5] >> 4, timestamp[5] & 15,
            timestamp[6] >> 4, timestamp[6] & 15);
        fprintf(out, "CPS Software Version: V%c%c.%c%c\n",
            charmap[timestamp[7] & 15], charmap[timestamp[8] & 15],
            charmap[timestamp[9] & 15], charmap[timestamp[10] & 15]);
    }
}

//
// Read memory image from the device.
//
static void uv380_download(radio_device_t *radio)
{
    int bno;

    for (bno=0; bno<MEMSZ/1024; bno++) {
        dfu_read_block(bno, &radio_mem[bno*1024], 1024);

        ++radio_progress;
        if (radio_progress % 32 == 0) {
            fprintf(stderr, "#");
            fflush(stderr);
        }
        report_tick(bno + 1, MEMSZ/1024);
    }
}

//
// Write memory image to the device.
//
static void uv380_upload(radio_device_t *radio, int cont_flag)
{
    int bno;

    dfu_erase(0, MEMSZ);

    report_phase("write");
    for (bno=0; bno<MEMSZ/1024; bno++) {
        dfu_write_block(bno, &radio_mem[bno*1024], 1024);

        ++radio_progress;
        if (radio_progress % 32 == 0) {
            fprintf(stderr, "#");
            fflush(stderr);
        }
        report_tick(bno + 1, MEMSZ/1024);
    }
}

//
// Check whether the memory image is compatible with this device.
//
static int uv380_is_compatible(radio_device_t *radio)
{
    return 1;
}

//
// Set name for a given zone.
//
static void setup_zone(int index, const char *name)
{
    zone_t *z = GET_ZONE(index);

    utf8_decode(z->name, name, 16);
}

//
// Add channel to a zone.
// Return 0 on failure.
//
static int zone_append(int index, int b_flag, int cnum)
{
    zone_t     *z    = GET_ZONE(index);
    zone_ext_t *zext = GET_ZONEXT(index);
    int i;

    if (b_flag) {
        for (i=0; i<64; i++) {
            if (zext->member_b[i] == cnum)
                return 1;
            if (zext->member_b[i] == 0) {
                zext->member_b[i] = cnum;
                return 1;
            }
        }
    } else {
        for (i=0; i<16; i++) {
            if (z->member_a[i] == cnum)
                return 1;
            if (z->member_a[i] == 0) {
                z->member_a[i] = cnum;
                return 1;
            }
        }
        for (i=0; i<48; i++) {
            if (zext->ext_a[i] == cnum)
                return 1;
            if (zext->ext_a[i] == 0) {
                zext->ext_a[i] = cnum;
                return 1;
            }
        }
    }
    return 0;
}

static void erase_zone(int index)
{
    zone_t     *z    = GET_ZONE(index);
    zone_ext_t *zext = GET_ZONEXT(index);

    memset(z, 0, 64);
    memset(zext, 0, 224);
}

// The scan-list bank as it was before the config erased it (erase_scanlists).
static unsigned char scan_snapshot[NSCANL * 104];
static int scan_snapshot_valid;

//
// Set parameters for a given scan list.
//
static void setup_scanlist(int index, const char *name,
    int prio1, int prio2, int txchan)
{
    scanlist_t *sl = GET_SCANLIST(index);
    scanlist_t *old = (scanlist_t*) &scan_snapshot[index * 104];

    if (scan_snapshot_valid && VALID_SCANLIST(old)) {
        memcpy(sl, old, 104);
        memset(sl->member, 0, sizeof(sl->member));     // the config lists them
    }

    // Bytes 0-31
    utf8_decode(sl->name, name, 16);

    // Bytes 32-37
    sl->priority_ch1     = prio1;
    sl->priority_ch2     = prio2;
    sl->tx_designated_ch = txchan;
}

static void erase_scanlist(int index)
{
    scanlist_t *sl = GET_SCANLIST(index);

    memset(sl, 0, 104);

    // Bytes 32-37
    sl->priority_ch1     = 0xffff;
    sl->priority_ch2     = 0xffff;
    sl->tx_designated_ch = 0xffff;

    // Bytes 38-41
    sl->_unused1         = 0xf1;
    sl->sign_hold_time   = 500 / 25;    // 500 msec
    sl->prio_sample_time = 2000 / 250;  // 2 sec
    sl->_unused2         = 0xff;
}

//
// Add channel to a zone.
// Return 0 on failure.
//
static int scanlist_append(int index, int cnum)
{
    scanlist_t *sl = GET_SCANLIST(index);
    int i;

    for (i=0; i<31; i++) {
        if (sl->member[i] == cnum)
            return 1;
        if (sl->member[i] == 0) {
            sl->member[i] = cnum;
            return 1;
        }
    }
    return 0;
}

static void erase_contact(int index)
{
    contact_t *ct = GET_CONTACT(index);

    memset(ct, 0, 36);

    // An empty contact is id 0xffffff with byte 3 = 0xc0, i.e. type 0 and
    // the two documented _unused bits set.  Upstream writes 0xff there,
    // which decodes as type 31 with receive_tone set - harmless, since
    // VALID_CONTACT also needs a name, but it differs from every byte the
    // CPS writes and so moves 9990 bytes of an untouched codeplug.
    ct->id[0] = 0xff;
    ct->id[1] = 0xff;
    ct->id[2] = 0xff;
    ct->type         = 0;
    ct->receive_tone = 0;
    ct->_unused2     = 3;
}

static void setup_contact(int index, const char *name, int type, int id, int rxtone)
{
    contact_t *ct = GET_CONTACT(index);

    ct->id[0]        = id;
    ct->id[1]        = id >> 8;
    ct->id[2]        = id >> 16;
    ct->type         = type;
    ct->receive_tone = rxtone;

    utf8_decode(ct->name, name, 16);
}

static void setup_grouplist(int index, const char *name)
{
    grouplist_t *gl = GET_GROUPLIST(index);

    utf8_decode(gl->name, name, 16);
}

//
// Add contact to a grouplist.
// Return 0 on failure.
//
static int grouplist_append(int index, int cnum)
{
    grouplist_t *gl = GET_GROUPLIST(index);
    int i;

    for (i=0; i<32; i++) {
        if (gl->member[i] == cnum)
            return 1;
        if (gl->member[i] == 0) {
            gl->member[i] = cnum;
            return 1;
        }
    }
    return 0;
}

//
// Set text for a given message.
//
static void setup_message(int index, const char *text)
{
    uint16_t *msg = GET_MESSAGE(index);

    // Skip spaces and tabs.
    while (*text == ' ' || *text == '\t')
        text++;
    utf8_decode(msg, text, 144);
}

//
// Check that the radio does support this frequency.
//
static int is_valid_frequency(int mhz)
{
    if (mhz >= 136 && mhz <= 174)
        return 1;
    if (mhz >= 400 && mhz <= 480)
        return 1;
    return 0;
}

//
// Snapshot of the channel bank as it was before the config erased it.
//
// A text config is a lossy projection of the codeplug: it names about a third
// of the fields in a channel record, and parse_digital_channel() erases the
// whole bank before rebuilding it.  Upstream therefore resets every field the
// config does not mention to a built-in default, which silently rewrites real
// settings - including the two privacy bytes mapped in Phase 1.
//
// This fork keeps the original 64-byte record for any channel the config
// mentions, and applies the config fields on top.  Everything the config does
// not name round-trips unchanged, which is the property that made dmrconfig
// the chosen vehicle in the first place.
//
// The snapshot is used only when the old record was a valid channel of the
// same mode: a record that was empty, or that was analog and is becoming
// digital, gets the clean erase defaults instead.
//
static unsigned char chan_snapshot[NCHAN * 64];
static int chan_snapshot_valid;

//
// Warn once when a config has no Privacy column.
//
static void warn_no_privacy_column(void)
{
    static int warned;

    if (warned)
        return;
    warned = 1;
    report_warning("no_privacy_columns",
        "NOTE: this config has no Privacy/Key columns, so it cannot set or\n"
        "      clear channel privacy. Existing privacy settings in the\n"
        "      codeplug are left untouched. Re-read the radio to get a\n"
        "      config with the columns.");
}

static void snapshot_channels(void)
{
    memcpy(chan_snapshot, &radio_mem[OFFSET_CHANNELS], sizeof(chan_snapshot));
    chan_snapshot_valid = 1;
}

//
// Put back the pre-erase bytes of channel i, if they are usable.
//
static int restore_channel(int i, int mode)
{
    channel_t *old = (channel_t*) &chan_snapshot[i * 64];

    if (! chan_snapshot_valid)
        return 0;
    if (! VALID_CHANNEL(old))
        return 0;
    if (old->channel_mode != mode)
        return 0;
    memcpy(GET_CHANNEL(i), old, 64);
    return 1;
}

//
// Which channel table each channel came from in this config.  A channel is
// digital or analog, not both: a second row in the other table would build
// on the first row's record and keep its digital-only (or analog-only)
// fields, where a real mode change gets erase_channel's defaults.
//
static unsigned char chan_table_seen[NCHAN];

static int channel_in_other_table(int num, int mode)
{
    if (chan_table_seen[num-1] && chan_table_seen[num-1] != mode) {
        conf_error("#", "Channel %d is already in the %s table; a channel is "
            "digital or analog, not both.", num,
            mode == MODE_DIGITAL ? "Analog" : "Digital");
        return 1;
    }
    chan_table_seen[num-1] = mode;
    return 0;
}

//
// Set the parameters for a given memory channel.
//
// privacy is PRIV_NONE/BASIC/ENHANCED/UNIVERSAL, or -1 to leave the channel's
// existing privacy bytes alone (an old config with no Privacy column).
// width, colorcode, timeslot, grouplist, contact, rxtone and txtone are -1 for
// a field the row's table does not carry: the restored record keeps its
// value (the CPS edits Width on digital channels), and a new one keeps
// erase_channel's default.
//
static void setup_channel(int i, int mode, char *name, double rx_mhz, double tx_mhz,
    int power, int scanlist, int squelch, int tot, int rxonly,
    int admit, int colorcode, int timeslot, int grouplist, int contact,
    int rxtone, int txtone, int width, int privacy, int key)
{
    channel_t *ch = GET_CHANNEL(i);
    int restored = restore_channel(i, mode);
    int was_universal = restored && ch->privacy == PRIV_UNIVERSAL;
    int was_key = ch->privacy_no;

    ch->channel_mode        = mode;
    if (! restored && mode == MODE_DIGITAL) {
        // The CPS's new digital channel has Message Format DMR (+0x1F bit
        // 6 clear); erase_channel's 0b111 there is M Format (map R8c).
        ch->_unused12 &= ~2;
    }
    if (width >= 0)
        ch->bandwidth       = width;
    ch->rx_only             = rxonly;
    if (timeslot >= 0)
        ch->repeater_slot   = timeslot;
    if (colorcode >= 0)
        ch->colorcode       = colorcode;
    ch->admit_criteria      = admit;
    if (contact >= 0)
        ch->contact_name_index = contact;
    ch->tot                 = tot;
    ch->scan_list_index     = scanlist;
    if (grouplist >= 0)
        ch->group_list_index = grouplist;
    if (squelch >= 0) {
        // Only the analog table has a Squelch column. The CPS stores a
        // squelch value on digital channels too, so forcing one here would
        // rewrite it on every config pass.
        ch->squelch = squelch;
    }
    ch->rx_frequency        = mhz_to_abcdefgh(rx_mhz);
    ch->tx_frequency        = mhz_to_abcdefgh(tx_mhz);
    if (rxtone >= 0)
        ch->ctcss_dcs_receive  = rxtone;
    if (txtone >= 0)
        ch->ctcss_dcs_transmit = txtone;
    ch->power               = power;

    if (privacy >= 0) {
        ch->privacy = privacy;
        if (privacy == PRIV_NONE) {
            // Variant A in Phase 1: the CPS zeroes both fields and clears
            // the enable bit.
            ch->privacy_no     = 0;
            ch->privacy_enable = 0;
        } else {
            ch->privacy_no     = key - 1;
            ch->privacy_enable = 1;
        }
        // A Universal key number is 8 bits: +0x02 low nibble and +0x1E high
        // nibble (CPS setter 0x41c820).  erase_channel leaves 0xF there, which
        // the CPS reads as Privacy No. 241 or more, so a channel made
        // Universal here gets the CPS's 0 for keys 1-16.  A channel that was
        // already Universal on the same key keeps what the radio has.
        if (privacy == PRIV_UNIVERSAL && ! (was_universal && was_key == key - 1))
            ch->_unused10 = (ch->_unused10 & 0x03) | ((((key - 1) >> 4) & 0x0f) << 2);
    }

    utf8_decode(ch->name, name, 16);
}

//
// Erase the channel record.
//
static void erase_channel(int i)
{
    channel_t *ch = GET_CHANNEL(i);

    // Byte 0
    ch->channel_mode = MODE_ANALOG;
    ch->bandwidth    = BW_12_5_KHZ;
    ch->autoscan     = 0;
    ch->_unused1     = 3;
    ch->lone_worker  = 0;

    // Byte 1
    ch->_unused2      = 0;
    ch->rx_only       = 0;
    ch->repeater_slot = 1;
    ch->colorcode     = 1;

    // Byte 2
    ch->privacy_no        = 0;
    ch->privacy           = PRIV_NONE;
    ch->private_call_conf = 0;
    ch->data_call_conf    = 0;

    // Byte 3
    ch->rx_ref_frequency    = REF_LOW;
    ch->_unused3            = 0;
    ch->emergency_alarm_ack = 0;
    ch->_unused4            = 6;
    ch->display_pttid_dis   = 1;

    // Byte 4
    ch->tx_ref_frequency = REF_LOW;
    ch->_unused5         = 1;
    ch->vox              = 0;
    ch->_unused6         = 1;
    ch->admit_criteria   = ADMIT_ALWAYS;

    // Byte 5
    ch->_unused7a        = 0;
    ch->privacy_enable   = 0;
    ch->_unused7b        = 0;
    ch->in_call_criteria = INCALL_ALWAYS;
    ch->turn_off_freq    = TURNOFF_NONE;

    // Bytes 6-7
    ch->contact_name_index = 0;

    // Bytes 8-9
    ch->tot             = 60/15;
    ch->_unused13       = 0;
    ch->tot_rekey_delay = 0;

    // Bytes 10-11
    ch->emergency_system_index = 0;
    ch->scan_list_index        = 0;

    // Bytes 12-13
    ch->group_list_index = 0;
    ch->_unused8         = 0;

    // Bytes 14-15
    ch->_unused9 = 0;
    ch->squelch  = 1;

    // Bytes 16-23
    ch->rx_frequency = 0x40000000;
    ch->tx_frequency = 0x40000000;

    // Bytes 24-27
    ch->ctcss_dcs_receive = 0xffff;
    ch->ctcss_dcs_transmit = 0xffff;

    // Bytes 28-29
    ch->rx_signaling_syst = 0;
    ch->tx_signaling_syst = 0;

    // Byte 30
    ch->power     = POWER_HIGH;
    ch->_unused10 = 0x3f;

    // Byte 31
    ch->_unused11       = 7;
    ch->dcdm_switch_dis = 1;
    ch->leader_ms       = DCDM_MS;
    ch->_unused12       = 7;

    // Bytes 32-63
    utf8_decode(ch->name, "", 16);
}

//
// Print a zone or scanlist channel list.
//
// Upstream sorted the list before printing it.  That loses the stored order,
// which is the order the radio steps through the zone in, so a read-modify-
// write through the config silently reshuffles every zone.  This fork prints
// the list as stored; consecutive runs still collapse to N-M.
//
static void print_chanlist(FILE *out, uint16_t *data, int nchan)
{
    int last  = -1;
    int range = 0;
    int n;

    for (n=0; n<nchan; n++) {
        int cnum = data[n];

        if (cnum == 0)
            break;

        if (cnum == last+1) {
            range = 1;
        } else {
            if (range) {
                fprintf(out, "-%d", last);
                range = 0;
            }
            if (n > 0)
                fprintf(out, ",");
            fprintf(out, "%d", cnum);
        }
        last = cnum;
    }
    if (range)
        fprintf(out, "-%d", last);
}

static void print_id(FILE *out, int verbose)
{
    general_settings_t *gs = GET_SETTINGS();
    unsigned id = gs->radio_id[0] | (gs->radio_id[1] << 8) | (gs->radio_id[2] << 16);

    if (verbose)
        fprintf(out, "\n# Unique DMR ID and name of this radio.");
    fprintf(out, "\nID: %u\nName: ", id);
    if (VALID_TEXT(gs->radio_name)) {
        print_unicode(out, gs->radio_name, 16, 0);
    } else {
        fprintf(out, "-");
    }
    fprintf(out, "\n");
}

static void print_intro(FILE *out, int verbose)
{
    general_settings_t *gs = GET_SETTINGS();

    if (verbose)
        fprintf(out, "\n# Text displayed when the radio powers up.\n");
    fprintf(out, "Intro Line 1: ");
    if (VALID_TEXT(gs->intro_line1)) {
        print_unicode(out, gs->intro_line1, 10, 0);
    } else {
        fprintf(out, "-");
    }
    fprintf(out, "\nIntro Line 2: ");
    if (VALID_TEXT(gs->intro_line2)) {
        print_unicode(out, gs->intro_line2, 10, 0);
    } else {
        fprintf(out, "-");
    }
    fprintf(out, "\n");
}

//
// Do we have any channels of given mode?
//
static int have_channels(int mode)
{
    int i;

    for (i=0; i<NCHAN; i++) {
        channel_t *ch = GET_CHANNEL(i);

        if (VALID_CHANNEL(ch) && ch->channel_mode == mode)
            return 1;
    }
    return 0;
}

//
// Print base parameters of the channel:
//      Name
//      RX Frequency
//      TX Frequency
//      Power
//      Scan List
//      TOT
//      RX Only
//      Admit Criteria
//
static void print_chan_base(FILE *out, channel_t *ch, int cnum)
{
    fprintf(out, "%5d   ", cnum);
    print_unicode(out, ch->name, 16, 1);
    fprintf(out, " ");
    print_freq(out, ch->rx_frequency);
    fprintf(out, " ");
    print_offset(out, ch->rx_frequency, ch->tx_frequency);

    fprintf(out, "%-4s  ", POWER_NAME[ch->power]);

    if (ch->scan_list_index == 0)
        fprintf(out, "-    ");
    else
        fprintf(out, "%-4d ", ch->scan_list_index);

    if (ch->tot == 0)
        fprintf(out, "-   ");
    else
        fprintf(out, "%-3d ", ch->tot * 15);

    fprintf(out, "%c  ", "-+"[ch->rx_only]);

    fprintf(out, "%-6s ", ADMIT_NAME[ch->admit_criteria]);
}

#ifdef PRINT_EXTENDED_PARAMS
//
// Print extended parameters of the channel:
//      TOT Rekey Delay
//      RX Ref Frequency
//      RX Ref Frequency
//      Lone Worker
//      VOX
//
static void print_chan_ext(FILE *out, channel_t *ch)
{
    fprintf(out, "%-3d ", ch->tot_rekey_delay);
    fprintf(out, "%-5s ", REF_FREQUENCY[ch->rx_ref_frequency]);
    fprintf(out, "%-5s ", REF_FREQUENCY[ch->tx_ref_frequency]);
    fprintf(out, "%c  ", "-+"[ch->lone_worker]);
    fprintf(out, "%c   ", "-+"[ch->vox]);
}
#endif

static void print_digital_channels(FILE *out, int verbose)
{
    int i;

    if (verbose) {
        fprintf(out, "# Table of digital channels.\n");
        fprintf(out, "# 1) Channel number: 1-%d\n", NCHAN);
        fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
        fprintf(out, "# 3) Receive frequency in MHz\n");
        fprintf(out, "# 4) Transmit frequency or +/- offset in MHz\n");
        fprintf(out, "# 5) Transmit power: High, Mid, Low\n");
        fprintf(out, "# 6) Scan list: - or index in Scanlist table\n");
        fprintf(out, "# 7) Transmit timeout timer in seconds: 0, 15, 30, 45... 555\n");
        fprintf(out, "# 8) Receive only: -, +\n");
        fprintf(out, "# 9) Admit criteria: -, Free, Color\n");
        fprintf(out, "# 10) Color code: 0, 1, 2, 3... 15\n");
        fprintf(out, "# 11) Time slot: 1 or 2\n");
        fprintf(out, "# 12) Receive group list: - or index in Grouplist table\n");
        fprintf(out, "# 13) Contact for transmit: - or index in Contacts table\n");
        fprintf(out, "# 14) Privacy: None, Basic, Enhanced, Universal\n");
        fprintf(out, "#     Universal is the MD-UV390 Plus AES type; its key is a slot\n");
        fprintf(out, "#     in the fleet .dec key table, written separately with -K.\n");
        fprintf(out, "# 15) Privacy key: - or 1-16 (Basic 1-16, Enhanced 1-8, Universal 1-16)\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "Digital Name             Receive   Transmit Power Scan TOT RO Admit  Color Slot RxGL TxContact Privacy   Key");
#ifdef PRINT_EXTENDED_PARAMS
    fprintf(out, " AS InCall Sq Dly RxRef TxRef LW VOX EmSys Privacy  PN PCC EAA DCC DCDM");
#endif
    fprintf(out, "\n");
    for (i=0; i<NCHAN; i++) {
        channel_t *ch = GET_CHANNEL(i);

        if (!VALID_CHANNEL(ch) || ch->channel_mode != MODE_DIGITAL) {
            // Select digital channels
            continue;
        }
        print_chan_base(out, ch, i+1);

        // Print digital parameters of the channel:
        //      Color Code
        //      Repeater Slot
        //      Group List
        //      Contact Name
        fprintf(out, "%-5d %-3d  ", ch->colorcode, ch->repeater_slot);

        if (ch->group_list_index == 0)
            fprintf(out, "-    ");
        else
            fprintf(out, "%-4d ", ch->group_list_index);

        // TxContact is no longer the last column, so it has to be padded.
        if (ch->contact_name_index == 0)
            fprintf(out, "%-9s ", "-");
        else
            fprintf(out, "%-9d ", ch->contact_name_index);

        // Privacy and key slot. Phase 1 mapped these to record +0x02
        // (bits 0-3 key index, bits 4-5 type) and +0x05 bit 0x04.
        fprintf(out, "%-9s ", PRIVACY_NAME[ch->privacy]);
        if (ch->privacy == PRIV_NONE)
            fprintf(out, "%-3s", "-");
        else
            fprintf(out, "%-3d", ch->privacy_no + 1);

#ifdef PRINT_EXTENDED_PARAMS
        fprintf(out, "     "):

        print_chan_ext(out, ch);

        // Extended digital parameters of the channel:
        //      Autoscan
        //      In Call Criteria
        //      Squelch
        //      Emergency System
        //      Privacy
        //      Privacy No. (+1)
        //      Private Call Confirmed
        //      Emergency Alarm Ack
        //      Data Call Confirmed
        //      DCDM switch (inverted)
        //      Leader/MS
        fprintf(out, "%c  ", "-+"[ch->autoscan]);
        fprintf(out, "%-6s ", INCALL_NAME[ch->in_call_criteria]);

        if (ch->squelch <= 9)
            fprintf(out, "%1d  ", ch->squelch);
        else
            fprintf(out, "1  ");

        if (ch->emergency_system_index == 0)
            fprintf(out, "-     ");
        else
            fprintf(out, "%-5d ", ch->emergency_system_index);

        fprintf(out, "%-8s ", PRIVACY_NAME[ch->privacy]);

        if (ch->privacy == PRIV_NONE)
            fprintf(out, "-  ");
        else
            fprintf(out, "%-2d ", ch->privacy_no + 1);

        fprintf(out, "%c   ", "-+"[ch->private_call_conf]);
        fprintf(out, "%c   ", "-+"[ch->emergency_alarm_ack]);
        fprintf(out, "%c   ", "-+"[ch->data_call_conf]);

        if (ch->dcdm_switch_dis)
            fprintf(out, "-     ");
        else
            fprintf(out, "%-6s", ch->leader_ms ? "MS" : "Leader");
#endif
        // Print contact name as a comment.
        if (ch->contact_name_index > 0) {
            contact_t *ct = GET_CONTACT(ch->contact_name_index - 1);
            if (VALID_CONTACT(ct)) {
                fprintf(out, " # ");
                print_unicode(out, ct->name, 16, 0);
            }
        }
        fprintf(out, "\n");
    }
}

static void print_analog_channels(FILE *out, int verbose)
{
    int i;

    if (verbose) {
        fprintf(out, "# Table of analog channels.\n");
        fprintf(out, "# 1) Channel number: 1-%d\n", NCHAN);
        fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
        fprintf(out, "# 3) Receive frequency in MHz\n");
        fprintf(out, "# 4) Transmit frequency or +/- offset in MHz\n");
        fprintf(out, "# 5) Transmit power: High, Mid, Low\n");
        fprintf(out, "# 6) Scan list: - or index\n");
        fprintf(out, "# 7) Transmit timeout timer in seconds: 0, 15, 30, 45... 555\n");
        fprintf(out, "# 8) Receive only: -, +\n");
        fprintf(out, "# 9) Admit criteria: -, Free, Tone\n");
        fprintf(out, "# 10) Squelch level: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9\n");
        fprintf(out, "# 11) Guard tone for receive, or '-' to disable\n");
        fprintf(out, "# 12) Guard tone for transmit, or '-' to disable\n");
        fprintf(out, "# 13) Bandwidth in kHz: 12.5, 20, 25\n");
        fprintf(out, "#\n");
    }
    fprintf(out, "Analog  Name             Receive   Transmit Power Scan TOT RO Admit  Sq RxTone TxTone Width");
#ifdef PRINT_EXTENDED_PARAMS
    fprintf(out, " AS Dly RxRef TxRef LW VOX RxSign TxSign ID TOFreq");
#endif
    fprintf(out, "\n");
    for (i=0; i<NCHAN; i++) {
        channel_t *ch = GET_CHANNEL(i);

        if (!VALID_CHANNEL(ch) || ch->channel_mode != MODE_ANALOG) {
            // Select analog channels
            continue;
        }
        print_chan_base(out, ch, i+1);

        // Print analog parameters of the channel:
        //      Squelch
        //      CTCSS/DCS Dec
        //      CTCSS/DCS Enc
        //      Bandwidth
        if (ch->squelch <= 9)
            fprintf(out, "%1d  ", ch->squelch);
        else
            fprintf(out, "1  ");

        print_tone(out, ch->ctcss_dcs_receive);
        fprintf(out, "  ");
        print_tone(out, ch->ctcss_dcs_transmit);
        fprintf(out, "  %s", BANDWIDTH[ch->bandwidth]);

#ifdef PRINT_EXTENDED_PARAMS
        print_chan_ext(out, ch);

        // Extended analog parameters of the channel:
        //      Rx Signaling System
        //      Tx Signaling System
        //      Display PTT ID (inverted)
        //      Non-QT/DQT Turn-off Freq.
        fprintf(out, "%-6s ", SIGNALING_SYSTEM[ch->rx_signaling_syst]);
        fprintf(out, "%-6s ", SIGNALING_SYSTEM[ch->tx_signaling_syst]);
        fprintf(out, "%c  ", "+-"[ch->display_pttid_dis]);
        fprintf(out, "%s", TURNOFF_FREQ[ch->turn_off_freq]);
#endif
        fprintf(out, "\n");
    }
}

static int have_zones()
{
    int i;

    for (i=0; i<NZONES; i++) {
        zone_t *z = GET_ZONE(i);
        if (VALID_ZONE(z))
            return 1;
    }
    return 0;
}

static int have_scanlists()
{
    int i;

    for (i=0; i<NSCANL; i++) {
        scanlist_t *sl = GET_SCANLIST(i);

        if (VALID_SCANLIST(sl))
            return 1;
    }
    return 0;
}

static int have_contacts()
{
    int i;

    for (i=0; i<NCONTACTS; i++) {
        contact_t *ct = GET_CONTACT(i);

        if (VALID_CONTACT(ct))
            return 1;
    }
    return 0;
}

static int have_grouplists()
{
    int i;

    for (i=0; i<NGLISTS; i++) {
        grouplist_t *gl = GET_GROUPLIST(i);

        if (VALID_GROUPLIST(gl))
            return 1;
    }
    return 0;
}

static int have_messages()
{
    int i;

    for (i=0; i<NMESSAGES; i++) {
        uint16_t *msg = GET_MESSAGE(i);

        if (VALID_TEXT(msg))
            return 1;
    }
    return 0;
}

//
// Print full information about the device configuration.
//
static void uv380_print_config(radio_device_t *radio, FILE *out, int verbose)
{
    int i;

    fprintf(out, "Radio: %s\n", radio->name);
    if (verbose)
        uv380_print_version(radio, out);

    //
    // Channels.
    //
    if (have_channels(MODE_DIGITAL)) {
        fprintf(out, "\n");
        print_digital_channels(out, verbose);
    }
    if (have_channels(MODE_ANALOG)) {
        fprintf(out, "\n");
        print_analog_channels(out, verbose);
    }

    //
    // Zones.
    //
    if (have_zones()) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Table of channel zones.\n");
            fprintf(out, "# 1) Zone number: 1-%d\n", NZONES);
            fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
            fprintf(out, "# 3) List of channels: numbers and ranges (N-M) separated by comma\n");
            fprintf(out, "#\n");
        }
        fprintf(out, "Zone    Name             Channels\n");
        for (i=0; i<NZONES; i++) {
            zone_t     *z    = GET_ZONE(i);
            zone_ext_t *zext = GET_ZONEXT(i);

            if (!VALID_ZONE(z)) {
                // Zone is disabled.
                continue;
            }

            fprintf(out, "%4da   ", i + 1);
            print_unicode(out, z->name, 16, 1);
            fprintf(out, " ");
            if (z->member_a[0]) {
                print_chanlist(out, z->member_a, 16);
                if (zext->ext_a[0]) {
                    fprintf(out, ",");
                    print_chanlist(out, zext->ext_a, 48);
                }
            } else {
                fprintf(out, "-");
            }
            fprintf(out, "\n");

            fprintf(out, "%4db   -                ", i + 1);
            if (zext->member_b[0]) {
                print_chanlist(out, zext->member_b, 64);
            } else {
                fprintf(out, "-");
            }
            fprintf(out, "\n");
        }
    }

    //
    // Scan lists.
    //
    if (have_scanlists()) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Table of scan lists.\n");
            fprintf(out, "# 1) Scan list number: 1-%d\n", NSCANL);
            fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
            fprintf(out, "# 3) Priority channel 1 (50%% of scans): -, Sel or index\n");
            fprintf(out, "# 4) Priority channel 2 (25%% of scans): -, Sel or index\n");
            fprintf(out, "# 5) Designated transmit channel: Last, Sel or index\n");
            fprintf(out, "# 6) List of channels: numbers and ranges (N-M) separated by comma\n");
            fprintf(out, "#\n");
        }
        fprintf(out, "Scanlist Name             PCh1 PCh2 TxCh ");
#ifdef PRINT_EXTENDED_PARAMS
        fprintf(out, "Hold Smpl ");
#endif
        fprintf(out, "Channels\n");
        for (i=0; i<NSCANL; i++) {
            scanlist_t *sl = GET_SCANLIST(i);

            if (!VALID_SCANLIST(sl)) {
                // Scan list is disabled.
                continue;
            }

            fprintf(out, "%5d    ", i + 1);
            print_unicode(out, sl->name, 16, 1);
            if (sl->priority_ch1 == 0xffff) {
                fprintf(out, " -    ");
            } else if (sl->priority_ch1 == 0) {
                fprintf(out, " Sel  ");
            } else {
                fprintf(out, " %-4d ", sl->priority_ch1);
            }
            if (sl->priority_ch2 == 0xffff) {
                fprintf(out, "-    ");
            } else if (sl->priority_ch2 == 0) {
                fprintf(out, "Sel  ");
            } else {
                fprintf(out, "%-4d ", sl->priority_ch2);
            }
            if (sl->tx_designated_ch == 0xffff) {
                fprintf(out, "Last ");
            } else if (sl->tx_designated_ch == 0) {
                fprintf(out, "Sel  ");
            } else {
                fprintf(out, "%-4d ", sl->tx_designated_ch);
            }
#ifdef PRINT_EXTENDED_PARAMS
            fprintf(out, "%-4d %-4d ",
                sl->sign_hold_time * 25, sl->prio_sample_time * 250);
#endif
            if (sl->member[0]) {
                print_chanlist(out, sl->member, 31);
            } else {
                fprintf(out, "-");
            }
            fprintf(out, "\n");
        }
    }

    //
    // Contacts.
    //
    if (have_contacts()) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Table of contacts.\n");
            fprintf(out, "# 1) Contact number: 1-%d\n", NCONTACTS);
            fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
            fprintf(out, "# 3) Call type: Group, Private, All\n");
            fprintf(out, "# 4) Call ID: 1...16777215\n");
            fprintf(out, "# 5) Call receive tone: -, +\n");
            fprintf(out, "#\n");
        }
        fprintf(out, "Contact Name             Type    ID       RxTone\n");
        for (i=0; i<NCONTACTS; i++) {
            contact_t *ct = GET_CONTACT(i);

            if (!VALID_CONTACT(ct)) {
                // Contact is disabled
                continue;
            }

            fprintf(out, "%5d   ", i+1);
            print_unicode(out, ct->name, 16, 1);
            fprintf(out, " %-7s %-8d %s\n",
                CONTACT_TYPE[ct->type & 3], CONTACT_ID(ct), ct->receive_tone ? "+" : "-");
        }
    }

    //
    // Group lists.
    //
    if (have_grouplists()) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Table of group lists.\n");
            fprintf(out, "# 1) Group list number: 1-%d\n", NGLISTS);
            fprintf(out, "# 2) Name: up to 16 characters, use '_' instead of space\n");
            fprintf(out, "# 3) List of contacts: numbers and ranges (N-M) separated by comma\n");
            fprintf(out, "#\n");
        }
        fprintf(out, "Grouplist Name             Contacts\n");
        for (i=0; i<NGLISTS; i++) {
            grouplist_t *gl = GET_GROUPLIST(i);

            if (!VALID_GROUPLIST(gl)) {
                // Group list is disabled.
                continue;
            }

            fprintf(out, "%5d     ", i + 1);
            print_unicode(out, gl->name, 16, 1);
            fprintf(out, " ");
            if (gl->member[0]) {
                print_chanlist(out, gl->member, 32);
            } else {
                fprintf(out, "-");
            }
            fprintf(out, "\n");
        }
    }

    //
    // Text messages.
    //
    if (have_messages()) {
        fprintf(out, "\n");
        if (verbose) {
            fprintf(out, "# Table of text messages.\n");
            fprintf(out, "# 1) Message number: 1-%d\n", NMESSAGES);
            fprintf(out, "# 2) Text: up to 144 characters\n");
            fprintf(out, "#\n");
        }
        fprintf(out, "Message Text\n");
        for (i=0; i<NMESSAGES; i++) {
            uint16_t *msg = GET_MESSAGE(i);

            if (!VALID_TEXT(msg)) {
                // Message is disabled
                continue;
            }

            fprintf(out, "%5d   ", i+1);
            print_unicode(out, msg, 144, 0);
            fprintf(out, "\n");
        }
    }

    // General settings.
    print_id(out, verbose);
    print_intro(out, verbose);

    // The stock CPS's other pages (cpsfields.c).
    if (cps_fields_enabled(radio))
        cps_print(out, verbose);
}

//
// Read memory image from the binary file.
//
static void uv380_read_image(radio_device_t *radio, FILE *img)
{
    struct stat st;

    // Guess device type by file size.
    if (fstat(fileno(img), &st) < 0)
        die(EXIT_IO, "Cannot get file size.");
    switch (st.st_size) {
    case MEMSZ:
        // IMG file.
        if (fread(&radio_mem[0], 1, MEMSZ, img) != MEMSZ)
            die(EXIT_IO, "Error reading image data.");
        break;
    case MEMSZ + 0x225 + 0x10:
        // RTD file.
        // Header 0x225 bytes and footer 0x10 bytes at 0x40225.
        fseek(img, 0x225, SEEK_SET);
        if (fread(&radio_mem[0], 1, 0x40000, img) != 0x40000)
            die(EXIT_IO, "Error reading image data.");
        fseek(img, 0x10, SEEK_CUR);
        if (fread(&radio_mem[0x40000], 1, MEMSZ - 0x40000, img) != MEMSZ - 0x40000)
            die(EXIT_IO, "Error reading image data.");
        break;
    default:
        die(EXIT_IMAGE, "Unrecognized file size %u bytes.", (int) st.st_size);
    }
}

//
// Save memory image to the binary file.
//
static void uv380_save_image(radio_device_t *radio, FILE *img)
{
    fwrite(&radio_mem[0], 1, MEMSZ, img);
}

//
// Erase all channels.
//
static void erase_channels()
{
    int i;

    for (i=0; i<NCHAN; i++) {
        erase_channel(i);
    }
}

//
// Erase all zones.
//
static void erase_zones()
{
    int i;

    for (i=0; i<NZONES; i++) {
        erase_zone(i);
    }
}

//
// Erase all scanlists.
//
static void erase_scanlists()
{
    int i;

    // Snapshot the bank before the first erase, so a list the config names
    // keeps what the config does not carry: signalling hold and priority
    // sample time (cps-field-map.md R8e).  The first Digital row erases the
    // lists too, before the Scanlist table is read.
    if (! scan_snapshot_valid) {
        memcpy(scan_snapshot, &radio_mem[OFFSET_SCANL], sizeof(scan_snapshot));
        scan_snapshot_valid = 1;
    }
    for (i=0; i<NSCANL; i++) {
        erase_scanlist(i);
    }
}

//
// Erase all contacts.
//
static void erase_contacts()
{
    int i;

    cps_note_contacts();
    for (i=0; i<NCONTACTS; i++) {
        erase_contact(i);
    }
}

//
// Parse the scalar parameter.
//
static void uv380_parse_parameter(radio_device_t *radio, char *param, char *value)
{
    general_settings_t *gs = GET_SETTINGS();

    if (strcasecmp("Radio", param) == 0) {
        if (!radio_is_compatible(value))
            conf_fail("Radio", "This config is for '%s', which this radio "
                "cannot take.", value);
        return;
    }
    if (strcasecmp ("Name", param) == 0) {
        utf8_decode(gs->radio_name, value, 16);
        return;
    }
    if (strcasecmp ("ID", param) == 0) {
        // Decimal only.  strtoul(..., 0) read '02102' as octal 1090.
        // The CPS takes 0-16776415 and stores 4 bytes, 0x2087 = 0x00
        // (cps-field-map.md R8b).  The ID the image already holds is kept
        // as it is, whatever it is, so a printed config always applies (R2).
        char *e;
        unsigned long id = strtoul(value, &e, 10);
        unsigned cur = gs->radio_id[0] | (gs->radio_id[1] << 8) | (gs->radio_id[2] << 16);

        if (*e || ! isdigit((unsigned char) value[0]) || (id != cur && id > 16776415))
            conf_fail("ID", "Radio ID '%s' must be a whole number from 0 to 16776415.", value);
        if (id == cur)
            return;
        gs->radio_id[0] = id;
        gs->radio_id[1] = id >> 8;
        gs->radio_id[2] = id >> 16;
        gs->_unused71   = 0;
        return;
    }
    if (strcasecmp ("Last Programmed Date", param) == 0) {
        // Ignore.
        return;
    }
    if (strcasecmp ("CPS Software Version", param) == 0) {
        // Ignore.
        return;
    }
    if (strcasecmp ("Intro Line 1", param) == 0) {
        utf8_decode(gs->intro_line1, value, 10);
        return;
    }
    if (strcasecmp ("Intro Line 2", param) == 0) {
        utf8_decode(gs->intro_line2, value, 10);
        return;
    }
    if (cps_fields_enabled(radio) && cps_parse_parameter(param, value))
        return;
    conf_fail(param, "Unknown parameter: %s = %s", param, value);
}

//
// Parse one line of Digital channel table.
// Start_flag is 1 for the first table row.
// Return 0 on failure.
//
static int parse_digital_channel(radio_device_t *radio, int first_row, char *line)
{
    char num_str[256], name_str[256], rxfreq_str[256], offset_str[256];
    char power_str[256], scanlist_str[256];
    char tot_str[256], rxonly_str[256], admit_str[256], colorcode_str[256];
    char slot_str[256], grouplist_str[256], contact_str[256];
    char privacy_str[256], key_str[256];
    int num, power, scanlist, tot, rxonly, admit;
    int colorcode, timeslot, grouplist, contact;
    int privacy = -1, key = 0, nfields;
    double rx_mhz, tx_mhz;
    char *p;

    // Cut a trailing comment first.  print_digital_channels() appends the
    // contact name as "# Contact_1", and radio_parse_config() only strips a
    // comment that starts in column one.  Upstream got away with that
    // because it read exactly 13 fields and sscanf simply stopped; this
    // table reads 15, so the comment would land in the Privacy column.
    // Only a '#' that starts a whitespace-delimited token is a comment:
    // a channel name may legitimately contain one.
    for (p = line; *p; p++) {
        if (*p == '#' && p > line && (p[-1] == ' ' || p[-1] == '\t')) {
            *p = 0;
            break;
        }
    }

    nfields = sscanf(line, "%s %s %s %s %s %s %s %s %s %s %s %s %s %s %s",
        num_str, name_str, rxfreq_str, offset_str,
        power_str, scanlist_str,
        tot_str, rxonly_str, admit_str, colorcode_str,
        slot_str, grouplist_str, contact_str,
        privacy_str, key_str);

    // 15 fields is this fork's table, with the Privacy and Key columns added
    // in Phase 4.3.  13 is an upstream config: accept it, but leave the
    // channel's existing privacy bytes alone rather than clearing them, since
    // clearing them would put an encrypted fleet on the air in the clear.
    if (nfields != 13 && nfields != 15) {
        conf_error(0, "A digital channel row has 15 columns (13 in an "
            "upstream config); this one has %d.", nfields < 0 ? 0 : nfields);
        return 0;
    }

    num = atoi(num_str);
    if (num < 1 || num > NCHAN) {
        conf_error("#", "Channel number must be 1-%d.", NCHAN);
        return 0;
    }

    if (sscanf(rxfreq_str, "%lf", &rx_mhz) != 1 ||
        !is_valid_frequency(rx_mhz)) {
        conf_error("Receive", "Receive frequency '%s' is not valid: the radio covers 136-174 and 400-480 MHz.", rxfreq_str);
        return 0;
    }
    if (sscanf(offset_str, "%lf", &tx_mhz) != 1) {
badtx:  conf_error("Transmit", "Transmit frequency '%s' is not valid: the radio covers 136-174 and 400-480 MHz.", offset_str);
        return 0;
    }
    if (offset_str[0] == '-' || offset_str[0] == '+')
        tx_mhz += rx_mhz;
    if (! is_valid_frequency(tx_mhz))
        goto badtx;

    if (strcasecmp("High", power_str) == 0) {
        power = POWER_HIGH;
    } else if (strcasecmp("Mid", power_str) == 0) {
        power = POWER_MIDDLE;
    } else if (strcasecmp("Low", power_str) == 0) {
        power = POWER_LOW;
    } else {
        conf_error("Power", "Power '%s' is not one of High, Mid, Low.", power_str);
        return 0;
    }

    if (*scanlist_str == '-') {
        scanlist = 0;
    } else {
        scanlist = atoi(scanlist_str);
        if (scanlist == 0 || scanlist > NSCANL) {
            conf_error("Scan", "Scan list '%s' must be - or 1-%d.", scanlist_str, NSCANL);
            return 0;
        }
    }

    tot = atoi(tot_str);
    if (tot > 555 || tot % 15 != 0) {
        conf_error("TOT", "TOT '%s' must be a multiple of 15 seconds, up to 555.", tot_str);
        return 0;
    }
    tot /= 15;

    if (*rxonly_str == '-') {
        rxonly = 0;
    } else if (*rxonly_str == '+') {
        rxonly = 1;
    } else {
        conf_error("RO", "RO '%s' must be - or +.", rxonly_str);
        return 0;
    }

    if (*admit_str == '-' || strcasecmp("Always", admit_str) == 0) {
        admit = ADMIT_ALWAYS;
    } else if (strcasecmp("Free", admit_str) == 0) {
        admit = ADMIT_CH_FREE;
    } else if (strcasecmp("Color", admit_str) == 0) {
        admit = ADMIT_COLOR;
    } else {
        conf_error("Admit", "Admit '%s' must be -, Free or Color (Tone on analog).", admit_str);
        return 0;
    }

    colorcode = atoi(colorcode_str);
    if (colorcode < 0 || colorcode > 15) {
        conf_error("Color", "Color code '%s' must be 0-15.", colorcode_str);
        return 0;
    }

    timeslot = atoi(slot_str);
    if (timeslot < 1 || timeslot > 2) {
        conf_error("Slot", "Slot '%s' must be 1 or 2.", slot_str);
        return 0;
    }

    if (*grouplist_str == '-') {
        grouplist = 0;
    } else {
        grouplist = atoi(grouplist_str);
        if (grouplist == 0 || grouplist > NGLISTS) {
            conf_error("RxGL", "Receive group list '%s' must be - or 1-%d.", grouplist_str, NGLISTS);
            return 0;
        }
    }

    if (*contact_str == '-') {
        contact = 0;
    } else {
        contact = atoi(contact_str);
        if (contact == 0 || contact > NCONTACTS) {
            conf_error("TxContact", "Transmit contact '%s' must be - or 1-%d.", contact_str, NCONTACTS);
            return 0;
        }
    }

    if (nfields == 15) {
        privacy = string_in_table(privacy_str, PRIVACY_NAME, NPRIVACY);
        if (privacy < 0) {
            conf_error("Privacy", "Privacy '%s' must be None, Basic, "
                "Enhanced or Universal.", privacy_str);
            return 0;
        }
        if (privacy == PRIV_NONE) {
            if (strcmp(key_str, "-") != 0) {
                conf_error("Key", "Privacy None cannot have a key: use -.");
                return 0;
            }
            key = 0;
        } else {
            key = atoi(key_str);
            if (key < 1 || key > 16) {
                conf_error("Key", "Key '%s' must be 1-16.", key_str);
                return 0;
            }
            if (privacy == PRIV_ENHANCED && key > 8) {
                conf_error("Key", "Enhanced privacy has only 8 keys.");
                return 0;
            }
        }
    } else {
        warn_no_privacy_column();
    }

    if (first_row && radio->channel_count == 0) {
        // On first entry, erase all channels, zones and scanlists.
        // Snapshot the channel bank first so that fields this config does
        // not name survive the rebuild - see restore_channel().
        snapshot_channels();
        erase_channels();
        erase_zones();
        erase_scanlists();
        memset(chan_table_seen, 0, sizeof(chan_table_seen));
    }

    if (channel_in_other_table(num, MODE_DIGITAL))
        return 0;
    setup_channel(num-1, MODE_DIGITAL, name_str, rx_mhz, tx_mhz,
        power, scanlist, -1, tot, rxonly, admit, colorcode,
        timeslot, grouplist, contact, -1, -1, -1, privacy, key);

    radio->channel_count++;
    return 1;
}

//
// Parse one line of Analog channel table.
// Start_flag is 1 for the first table row.
// Return 0 on failure.
//
static int parse_analog_channel(radio_device_t *radio, int first_row, char *line)
{
    char num_str[256], name_str[256], rxfreq_str[256], offset_str[256];
    char power_str[256], scanlist_str[256], squelch_str[256];
    char tot_str[256], rxonly_str[256], admit_str[256];
    char rxtone_str[256], txtone_str[256], width_str[256];
    int num, power, scanlist, squelch, tot, rxonly, admit;
    int rxtone, txtone, width, nfields;
    double rx_mhz, tx_mhz;

    nfields = sscanf(line, "%s %s %s %s %s %s %s %s %s %s %s %s %s",
        num_str, name_str, rxfreq_str, offset_str,
        power_str, scanlist_str,
        tot_str, rxonly_str, admit_str, squelch_str,
        rxtone_str, txtone_str, width_str);
    if (nfields != 13) {
        conf_error(0, "An analog channel row has 13 columns; this one has %d.",
            nfields < 0 ? 0 : nfields);
        return 0;
    }

    num = atoi(num_str);
    if (num < 1 || num > NCHAN) {
        conf_error("#", "Channel number must be 1-%d.", NCHAN);
        return 0;
    }

    if (sscanf(rxfreq_str, "%lf", &rx_mhz) != 1 ||
        !is_valid_frequency(rx_mhz)) {
        conf_error("Receive", "Receive frequency '%s' is not valid: the radio covers 136-174 and 400-480 MHz.", rxfreq_str);
        return 0;
    }
    if (sscanf(offset_str, "%lf", &tx_mhz) != 1) {
badtx:  conf_error("Transmit", "Transmit frequency '%s' is not valid: the radio covers 136-174 and 400-480 MHz.", offset_str);
        return 0;
    }
    if (offset_str[0] == '-' || offset_str[0] == '+')
        tx_mhz += rx_mhz;
    if (! is_valid_frequency(tx_mhz))
        goto badtx;

    if (strcasecmp("High", power_str) == 0) {
        power = POWER_HIGH;
    } else if (strcasecmp("Mid", power_str) == 0) {
        power = POWER_MIDDLE;
    } else if (strcasecmp("Low", power_str) == 0) {
        power = POWER_LOW;
    } else {
        conf_error("Power", "Power '%s' is not one of High, Mid, Low.", power_str);
        return 0;
    }

    if (*scanlist_str == '-') {
        scanlist = 0;
    } else {
        scanlist = atoi(scanlist_str);
        if (scanlist == 0 || scanlist > NSCANL) {
            conf_error("Scan", "Scan list '%s' must be - or 1-%d.", scanlist_str, NSCANL);
            return 0;
        }
    }

    squelch = atoi(squelch_str);
    if (squelch > 9) {
        conf_error("Sq", "Squelch '%s' must be 0-9.", squelch_str);
        return 0;
    }

    tot = atoi(tot_str);
    if (tot > 555 || tot % 15 != 0) {
        conf_error("TOT", "TOT '%s' must be a multiple of 15 seconds, up to 555.", tot_str);
        return 0;
    }
    tot /= 15;

    if (*rxonly_str == '-') {
        rxonly = 0;
    } else if (*rxonly_str == '+') {
        rxonly = 1;
    } else {
        conf_error("RO", "RO '%s' must be - or +.", rxonly_str);
        return 0;
    }

    if (*admit_str == '-' || strcasecmp("Always", admit_str) == 0) {
        admit = ADMIT_ALWAYS;
    } else if (strcasecmp("Free", admit_str) == 0) {
        admit = ADMIT_CH_FREE;
    } else if (strcasecmp("Tone", admit_str) == 0) {
        admit = ADMIT_TONE;
    } else {
        conf_error("Admit", "Admit '%s' must be -, Free or Color (Tone on analog).", admit_str);
        return 0;
    }

    rxtone = encode_tone(rxtone_str);
    if (rxtone < 0) {
        conf_error("RxTone", "Receive tone '%s' is not valid.", rxtone_str);
        return 0;
    }
    txtone = encode_tone(txtone_str);
    if (txtone < 0) {
        conf_error("TxTone", "Transmit tone '%s' is not valid.", txtone_str);
        return 0;
    }

    if (strcasecmp ("12.5", width_str) == 0) {
        width = BW_12_5_KHZ;
    } else if (strcasecmp ("20", width_str) == 0) {
        width = BW_20_KHZ;
    } else if (strcasecmp ("25", width_str) == 0) {
        width = BW_25_KHZ;
    } else {
        conf_error("Width", "Width '%s' must be 12.5, 20 or 25.", width_str);
        return 0;
    }

    if (first_row && radio->channel_count == 0) {
        // On first entry, erase all channels, zones and scanlists.
        snapshot_channels();
        erase_channels();
        memset(chan_table_seen, 0, sizeof(chan_table_seen));
    }

    if (channel_in_other_table(num, MODE_ANALOG))
        return 0;
    // Privacy is a digital feature; -1 leaves an analog channel's bytes be.
    setup_channel(num-1, MODE_ANALOG, name_str, rx_mhz, tx_mhz,
        power, scanlist, squelch, tot, rxonly, admit,
        -1, -1, -1, -1, rxtone, txtone, width, -1, 0);

    radio->channel_count++;
    return 1;
}

//
// Parse one line of Zones table.
// Return 0 on failure.
//
static int parse_zones(int first_row, char *line)
{
    char num_str[256], name_str[256], chan_str[256], *eptr;
    int znum, b_flag;

    if (sscanf(line, "%s %s %s", num_str, name_str, chan_str) != 3) {
        conf_error(0, "A zone row has 3 columns: number, name, channels.");
        return 0;
    }

    znum = strtoul(num_str, &eptr, 10);
    if (znum < 1 || znum > NZONES || strchr("aAbB", *eptr) == 0) {
        conf_error("#", "Zone number must be 1a-%da or 1b-%db.", NZONES, NZONES);
        return 0;
    }
    b_flag = (*eptr == 'b' || *eptr == 'B');

    if (first_row) {
        // On first entry, erase the Zones table.
        erase_zones();
    }

    if (b_flag == 0)
        setup_zone(znum-1, name_str);

    if (*chan_str != '-') {
        char *str   = chan_str;
        int   range = 0;
        int   last  = 0;

        // Parse channel list.
        for (;;) {
            char *eptr;
            int cnum = strtoul(str, &eptr, 10);

            if (eptr == str) {
                conf_error("Channels", "Zone %d: wrong channel list '%s'.", znum, str);
                return 0;
            }
            if (cnum < 1 || cnum > NCHAN) {
                conf_error("Channels", "Zone %d: wrong channel number %d.", znum, cnum);
                return 0;
            }

            if (range) {
                // Add range.
                int c;
                for (c=last+1; c<=cnum; c++) {
                    if (!zone_append(znum-1, b_flag, c)) {
                        conf_error("Channels", "Zone %d: too many channels.", znum);
                        return 0;
                    }
                }
            } else {
                // Add single channel.
                if (!zone_append(znum-1, b_flag, cnum)) {
                    conf_error("Channels", "Zone %d: too many channels.", znum);
                    return 0;
                }
            }

            if (*eptr == 0)
                break;

            if (*eptr != ',' && *eptr != '-') {
                conf_error("Channels", "Zone %d: wrong channel list '%s'.", znum, eptr);
                return 0;
            }
            range = (*eptr == '-');
            last = cnum;
            str = eptr + 1;
        }
    }
    return 1;
}

//
// Parse one line of Scanlist table.
// Return 0 on failure.
//
static int parse_scanlist(int first_row, char *line)
{
    char num_str[256], name_str[256], prio1_str[256], prio2_str[256];
    char tx_str[256], chan_str[256];
    int snum, prio1, prio2, txchan;

    if (sscanf(line, "%s %s %s %s %s %s",
        num_str, name_str, prio1_str, prio2_str, tx_str, chan_str) != 6) {
        conf_error(0, "A scan list row has 6 columns: number, name, PCh1, "
            "PCh2, TxCh, channels.");
        return 0;
    }

    snum = atoi(num_str);
    if (snum < 1 || snum > NSCANL) {
        conf_error("#", "Scan list number must be 1-%d.", NSCANL);
        return 0;
    }

    if (first_row) {
        // On first entry, erase the Scanlists table.
        erase_scanlists();
    }

    if (*prio1_str == '-') {
        prio1 = 0xffff;
    } else if (strcasecmp("Sel", prio1_str) == 0) {
        prio1 = 0;
    } else {
        prio1 = atoi(prio1_str);
        if (prio1 < 1 || prio1 > NCHAN) {
            conf_error("PCh1", "Priority channel 1 '%s' must be -, Sel or 1-%d.", prio1_str, NCHAN);
            return 0;
        }
    }

    if (*prio2_str == '-') {
        prio2 = 0xffff;
    } else if (strcasecmp("Sel", prio2_str) == 0) {
        prio2 = 0;
    } else {
        prio2 = atoi(prio2_str);
        if (prio2 < 1 || prio2 > NCHAN) {
            conf_error("PCh2", "Priority channel 2 '%s' must be -, Sel or 1-%d.", prio2_str, NCHAN);
            return 0;
        }
    }

    if (strcasecmp("Last", tx_str) == 0) {
        txchan = 0xffff;
    } else if (strcasecmp("Sel", tx_str) == 0) {
        txchan = 0;
    } else {
        txchan = atoi(tx_str);
        if (txchan < 1 || txchan > NCHAN) {
            conf_error("TxCh", "Transmit channel '%s' must be Last, Sel or 1-%d.", tx_str, NCHAN);
            return 0;
        }
    }

    setup_scanlist(snum-1, name_str, prio1, prio2, txchan);

    if (*chan_str != '-') {
        char *str   = chan_str;
        int   range = 0;
        int   last  = 0;

        // Parse channel list.
        for (;;) {
            char *eptr;
            int cnum = strtoul(str, &eptr, 10);

            if (eptr == str) {
                conf_error("Channels", "Scan list %d: wrong channel list '%s'.", snum, str);
                return 0;
            }
            if (cnum < 1 || cnum > NCHAN) {
                conf_error("Channels", "Scan list %d: wrong channel number %d.", snum, cnum);
                return 0;
            }

            if (range) {
                // Add range.
                int c;
                for (c=last+1; c<=cnum; c++) {
                    if (!scanlist_append(snum-1, c)) {
                        conf_error("Channels", "Scan list %d: too many channels.", snum);
                        return 0;
                    }
                }
            } else {
                // Add single channel.
                if (!scanlist_append(snum-1, cnum)) {
                    conf_error("Channels", "Scan list %d: too many channels.", snum);
                    return 0;
                }
            }

            if (*eptr == 0)
                break;

            if (*eptr != ',' && *eptr != '-') {
                conf_error("Channels", "Scan list %d: wrong channel list '%s'.", snum, eptr);
                return 0;
            }
            range = (*eptr == '-');
            last = cnum;
            str = eptr + 1;
        }
    }
    return 1;
}

//
// Parse one line of Contacts table.
// Return 0 on failure.
//
static int parse_contact(int first_row, char *line)
{
    char num_str[256], name_str[256], type_str[256], id_str[256], rxtone_str[256];
    int cnum, type, id, rxtone;

    if (sscanf(line, "%s %s %s %s %s",
        num_str, name_str, type_str, id_str, rxtone_str) != 5) {
        conf_error(0, "A contact row has 5 columns: number, name, type, ID, "
            "RxTone.");
        return 0;
    }

    cnum = atoi(num_str);
    if (cnum < 1 || cnum > NCONTACTS) {
        conf_error("#", "Contact number must be 1-%d.", NCONTACTS);
        return 0;
    }

    if (first_row) {
        // On first entry, erase the Contacts table.
        erase_contacts();
    }

    if (strcasecmp("Group", type_str) == 0) {
        type = CALL_GROUP;
    } else if (strcasecmp("Private", type_str) == 0) {
        type = CALL_PRIVATE;
    } else if (strcasecmp("All", type_str) == 0) {
        type = CALL_ALL;
    } else {
        conf_error("Type", "Call type '%s' must be Group, Private or All.", type_str);
        return 0;
    }

    id = atoi(id_str);
    if (id < 1 || id > 0xffffff) {
        conf_error("ID", "Call ID '%s' must be 1-16777215.", id_str);
        return 0;
    }

    if (*rxtone_str == '-' || strcasecmp("No", rxtone_str) == 0) {
        rxtone = 0;
    } else if (*rxtone_str == '+' || strcasecmp("Yes", rxtone_str) == 0) {
        rxtone = 1;
    } else {
        conf_error("RxTone", "Receive tone '%s' must be -, +, No or Yes.", rxtone_str);
        return 0;
    }

    setup_contact(cnum-1, name_str, type, id, rxtone);
    return 1;
}

//
// Parse one line of Grouplist table.
// Return 0 on failure.
//
static int parse_grouplist(int first_row, char *line)
{
    char num_str[256], name_str[256], list_str[256];
    int glnum;

    if (sscanf(line, "%s %s %s", num_str, name_str, list_str) != 3) {
        conf_error(0, "A group list row has 3 columns: number, name, "
            "contacts.");
        return 0;
    }

    glnum = strtoul(num_str, 0, 10);
    if (glnum < 1 || glnum > NGLISTS) {
        conf_error("#", "Group list number must be 1-%d.", NGLISTS);
        return 0;
    }

    if (first_row) {
        // On first entry, erase the Grouplists table.
        memset(&radio_mem[OFFSET_GLISTS], 0, NGLISTS*96);
    }

    setup_grouplist(glnum-1, name_str);

    if (*list_str != '-') {
        char *str   = list_str;
        int   range = 0;
        int   last  = 0;

        // Parse contact list.
        for (;;) {
            char *eptr;
            int cnum = strtoul(str, &eptr, 10);

            if (eptr == str) {
                conf_error("Contacts", "Group list %d: wrong contact list '%s'.", glnum, str);
                return 0;
            }
            if (cnum < 1 || cnum > NCONTACTS) {
                conf_error("Contacts", "Group list %d: wrong contact number %d.", glnum, cnum);
                return 0;
            }

            if (range) {
                // Add range.
                int c;
                for (c=last+1; c<=cnum; c++) {
                    if (!grouplist_append(glnum-1, c)) {
                        conf_error("Contacts", "Group list %d: too many contacts.", glnum);
                        return 0;
                    }
                }
            } else {
                // Add single contact.
                if (!grouplist_append(glnum-1, cnum)) {
                    conf_error("Contacts", "Group list %d: too many contacts.", glnum);
                    return 0;
                }
            }

            if (*eptr == 0)
                break;

            if (*eptr != ',' && *eptr != '-') {
                conf_error("Contacts", "Group list %d: wrong contact list '%s'.", glnum, eptr);
                return 0;
            }
            range = (*eptr == '-');
            last = cnum;
            str = eptr + 1;
        }
    }
    return 1;
}

//
// Parse one line of Messages table.
// Return 0 on failure.
//
static int parse_messages(int first_row, char *line)
{
    char *text;
    int mnum;

    mnum = strtoul(line, &text, 10);
    if (text == line || mnum < 1 || mnum > NMESSAGES) {
        conf_error("#", "Message number must be 1-%d.", NMESSAGES);
        return 0;
    }

    if (first_row) {
        // On first entry, erase the Messages table.
        cps_note_messages();
        memset(&radio_mem[OFFSET_MSG], 0, NMESSAGES*288);
    }

    setup_message(mnum-1, text);
    return 1;
}

//
// Parse table header.
// Return table id, or 0 in case of error.
//
static int uv380_parse_header(radio_device_t *radio, char *line)
{
    if (cps_fields_enabled(radio)) {
        int t = cps_parse_header(line);

        if (t)
            return t;
    }
    if (strncasecmp(line, "Digital", 7) == 0)
        return 'D';
    if (strncasecmp(line, "Analog", 6) == 0)
        return 'A';
    if (strncasecmp(line, "Zone", 4) == 0)
        return 'Z';
    if (strncasecmp(line, "Scanlist", 8) == 0)
        return 'S';
    if (strncasecmp(line, "Contact", 7) == 0)
        return 'C';
    if (strncasecmp(line, "Grouplist", 9) == 0)
        return 'G';
    if (strncasecmp(line, "Message", 7) == 0)
        return 'M';
    return 0;
}

//
// Parse one line of table data.
// Return 0 on failure.
//
static int uv380_parse_row(radio_device_t *radio, int table_id, int first_row, char *line)
{
    switch (table_id) {
    case 'D': return parse_digital_channel(radio, first_row, line);
    case 'A': return parse_analog_channel(radio, first_row, line);
    case 'Z': return parse_zones(first_row, line);
    case 'S': return parse_scanlist(first_row, line);
    case 'C': return parse_contact(first_row, line);
    case 'G': return parse_grouplist(first_row, line);
    case 'M': return parse_messages(first_row, line);
    }
    if (cps_fields_enabled(radio))
        return cps_parse_row(table_id, line);
    return 0;
}

//
// After the whole config: the CPS tables' rows, kept until now so that the
// channel tables' erase cannot undo them (cpsfields.c).
//
static void uv380_parse_finish(radio_device_t *radio)
{
    if (! cps_fields_enabled(radio))
        return;
    // A config with no channel table leaves the bank as the image had it.
    if (! chan_snapshot_valid)
        snapshot_channels();
    cps_note_buttons();
    cps_parse_finish();
    cps_check_channels(chan_snapshot);
    cps_check_refs();
}

//
// Update timestamp.
//
static void uv380_update_timestamp(radio_device_t *radio)
{
    unsigned char *timestamp = GET_TIMESTAMP();
    char p[16];

    // Last Programmed Date
    get_timestamp(p);
    timestamp[0] = ((p[0]  & 0xf) << 4) | (p[1]  & 0xf); // year upper
    timestamp[1] = ((p[2]  & 0xf) << 4) | (p[3]  & 0xf); // year lower
    timestamp[2] = ((p[4]  & 0xf) << 4) | (p[5]  & 0xf); // month
    timestamp[3] = ((p[6]  & 0xf) << 4) | (p[7]  & 0xf); // day
    timestamp[4] = ((p[8]  & 0xf) << 4) | (p[9]  & 0xf); // hour
    timestamp[5] = ((p[10] & 0xf) << 4) | (p[11] & 0xf); // minute
    timestamp[6] = ((p[12] & 0xf) << 4) | (p[13] & 0xf); // second

    // CPS Software Version: Vdx.xx
    const char *dot = strchr(VERSION, '.');
    if (dot) {
        timestamp[7] = 0x0d; // Prints as '='
        timestamp[8] = dot[-1] & 0x0f;
        if (dot[2] == '.') {
            timestamp[9] = 0;
            timestamp[10] = dot[1] & 0x0f;
        } else {
            timestamp[9] = dot[1] & 0x0f;
            timestamp[10] = dot[2] & 0x0f;
        }
    }
}

//
// UTF-16 name from the codeplug as UTF-8, for messages and events.
// Stops at the first 0x0000 or 0xffff.
//
static void name_utf8(const uint16_t *text, int nchars, char *buf, int size)
{
    char *p;

    utf16_to_utf8(text, nchars, buf, size);

    // As the config prints a name: a space is '_' in any field of up to 16
    // characters (print_unicode()), so names here match the config's text.
    if (nchars <= 16)
        for (p = buf; *p; p++)
            if (*p == ' ')
                *p = '_';
}

//
// A problem with channel i, placed on its row in the config.
//
static void chan_problem(int code, int i, const char *column)
{
    channel_t *ch = GET_CHANNEL(i);
    int digital = (ch->channel_mode == MODE_DIGITAL);
    char name[64], id[16];

    name_utf8(ch->name, 16, name, sizeof(name));
    snprintf(id, sizeof(id), "%d", i+1);
    conf_problem_begin(code, digital ? 'D' : 'A', id,
        digital ? "Digital" : "Analog", column);
    ev_str("name", name);
}

//
// Check that configuration is correct.
// Return 0 on error.
//
// Every problem is reported, each with its own error event placed on the
// record it concerns, before giving up.
//
static int uv380_verify_config(radio_device_t *radio)
{
    int i, k, nchannels = 0, nzones = 0, nscanlists = 0, ngrouplists = 0;
    int ncontacts = 0, nerrors = 0, nuniversal = 0;
    char name[64];

    // Channels: check references to scanlists, contacts and grouplists.
    for (i=0; i<NCHAN; i++) {
        channel_t *ch = GET_CHANNEL(i);

        if (!VALID_CHANNEL(ch))
            continue;

        nchannels++;
        name_utf8(ch->name, 16, name, sizeof(name));

        // A Universal channel points at a slot in the fleet key table.  The
        // radio will not tell us what it holds, and Phase 3 showed the slot
        // number is signalled over the air and looked up in the receiver's
        // own table: a channel on a slot the fleet file leaves empty is a
        // channel that will hear scrambled audio while looking correctly
        // configured.  Check it when a fleet file was given with -F.
        if (ch->privacy == PRIV_UNIVERSAL)
            nuniversal++;
        if (ch->privacy == PRIV_UNIVERSAL && radio_fleet_keys) {
            int slot = ch->privacy_no + 1;

            if (! privacy_slot_available(radio_fleet_keys, slot)) {
                chan_problem(EXIT_KEY_SLOT_EMPTY, i, "Key");
                ev_int("slot", slot);
                error_event_end("Channel %d '%s': Universal key %d is empty "
                    "in the fleet key table.", i+1, name, slot);
                nerrors++;
            }
        }
        if (ch->privacy != PRIV_NONE && ! ch->privacy_enable) {
            chan_problem(EXIT_CONF, i, "Privacy");
            error_event_end("Channel %d '%s': privacy type %s but the enable "
                "bit at +0x05 is clear.", i+1, name,
                PRIVACY_NAME[ch->privacy]);
            nerrors++;
        }
        if (ch->scan_list_index != 0) {
            scanlist_t *sl = GET_SCANLIST(ch->scan_list_index - 1);

            if (!VALID_SCANLIST(sl)) {
                chan_problem(EXIT_CONF, i, "Scan");
                error_event_end("Channel %d '%s': scanlist %d not found.",
                    i+1, name, ch->scan_list_index);
                nerrors++;
            }
        }
        if (ch->contact_name_index != 0) {
            contact_t *ct = GET_CONTACT(ch->contact_name_index - 1);

            if (!VALID_CONTACT(ct)) {
                chan_problem(EXIT_CONF, i, "TxContact");
                error_event_end("Channel %d '%s': contact %d not found.",
                    i+1, name, ch->contact_name_index);
                nerrors++;
            }
        }
        if (ch->group_list_index != 0) {
            grouplist_t *gl = GET_GROUPLIST(ch->group_list_index - 1);

            if (!VALID_GROUPLIST(gl)) {
                chan_problem(EXIT_CONF, i, "RxGL");
                error_event_end("Channel %d '%s': grouplist %d not found.",
                    i+1, name, ch->group_list_index);
                nerrors++;
            }
        }
    }

    // Zones: check references to channels.
    for (i=0; i<NZONES; i++) {
        zone_t     *z    = GET_ZONE(i);
        zone_ext_t *zext = GET_ZONEXT(i);
        int         cnum;

        if (!VALID_ZONE(z))
            continue;

        nzones++;
        name_utf8(z->name, 16, name, sizeof(name));

        // Zone A: 16 members in the zone record, 48 more in the extension.
        // Zone B: 64 members in the extension.
        for (k=0; k<16+48+64; k++) {
            int b_flag = (k >= 64);

            cnum = (k < 16) ? z->member_a[k] :
                   (k < 64) ? zext->ext_a[k-16] : zext->member_b[k-64];
            if (cnum != 0 && !VALID_CHANNEL(GET_CHANNEL(cnum - 1))) {
                char id[16];

                snprintf(id, sizeof(id), "%d%c", i+1, b_flag ? 'b' : 'a');
                conf_problem_begin(EXIT_CONF, 'Z', id, "Zone", "Channels");
                ev_str("name", name);
                error_event_end("Zone %d%c '%s': channel %d not found.",
                    i+1, b_flag ? 'b' : 'a', name, cnum);
                nerrors++;
            }
        }
    }

    // Scanlists: check references to channels.
    for (i=0; i<NSCANL; i++) {
        scanlist_t *sl = GET_SCANLIST(i);

        if (!VALID_SCANLIST(sl))
            continue;

        nscanlists++;
        name_utf8(sl->name, 16, name, sizeof(name));
        for (k=0; k<31; k++) {
            int cnum = sl->member[k];

            if (cnum != 0) {
                channel_t *ch = GET_CHANNEL(cnum - 1);

                if (!VALID_CHANNEL(ch)) {
                    char id[16];

                    snprintf(id, sizeof(id), "%d", i+1);
                    conf_problem_begin(EXIT_CONF, 'S', id, "Scanlist",
                        "Channels");
                    ev_str("name", name);
                    error_event_end("Scanlist %d '%s': channel %d not found.",
                        i+1, name, cnum);
                    nerrors++;
                }
            }
        }
    }

    // Grouplists: check references to contacts.
    for (i=0; i<NGLISTS; i++) {
        grouplist_t *gl = GET_GROUPLIST(i);

        if (!VALID_GROUPLIST(gl))
            continue;

        ngrouplists++;
        name_utf8(gl->name, 16, name, sizeof(name));
        for (k=0; k<32; k++) {
            int cnum = gl->member[k];

            if (cnum != 0) {
                contact_t *ct = GET_CONTACT(cnum - 1);

                if (!VALID_CONTACT(ct)) {
                    char id[16];

                    snprintf(id, sizeof(id), "%d", i+1);
                    conf_problem_begin(EXIT_CONF, 'G', id, "Grouplist",
                        "Contacts");
                    ev_str("name", name);
                    error_event_end("Grouplist %d '%s': contact %d not found.",
                        i+1, name, cnum);
                    nerrors++;
                }
            }
        }
    }

    // Count contacts.
    for (i=0; i<NCONTACTS; i++) {
        contact_t *ct = GET_CONTACT(i);

        if (VALID_CONTACT(ct))
            ncontacts++;
    }

    if (cps_fields_enabled(radio) && ! cps_verify())
        nerrors++;
    if (nerrors > 0) {
        fprintf(stderr, "Total %d errors.\n", nerrors);
        return 0;
    }
    fprintf(stderr, "Total %d channels, %d zones, %d scanlists, %d contacts, %d grouplists.\n",
        nchannels, nzones, nscanlists, ncontacts, ngrouplists);
    if (nuniversal > 0) {
        fprintf(stderr, "%d channel%s use Universal (AES) privacy.\n",
            nuniversal, nuniversal == 1 ? "" : "s");
        if (! radio_fleet_keys)
            report_warning("no_key_check", "NOTE: no fleet key table given "
                "with -F, so the key slots were not checked.");
    }
    return 1;
}

//
// Build search index of callsign table.
// Callsigns are supposed to be sorted by id.
//
// Region 0x200003-0x204002 of configuration memory contains a search helper
// for the ContactsCSV table. The helper is organized as a list
// of pairs <idbase, index>:
//      idbase - high bits 23:12 of DMR ID
//      index - number in ContactsCSV table, starting from 1 (20 bits)
//
// For example:
//               id[23:12]
//        Ncontacts  |   index[19:0]
//         vvvvvvvv //\  /||\\.
// 200000  00 40 00 5a d0 00 01 5a e0 10 00 5a f0 20 00 5b  .@.Z...Z...Z. .[
// 200010  00 30 00 5b 10 40 00 ff ff ff ff ff ff ff ff ff  .0.[.@..........
// 200020  ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff  ................
// *
// 204000  ff ff ff
//
static void build_callsign_index(uint8_t *mem, int nrecords)
{
    uint8_t *p;
    int index;

    // Number of contacts.
    mem[0] = nrecords >> 16;
    mem[1] = nrecords >> 8;
    mem[2] = nrecords;

    // Callsign index starting from 1.
    index = 1;

    p = &mem[3];
    for (;;) {
        int id = GET_CALLSIGN(mem, index-1)->dmrid;

        // Add index item.
        *p++ = id >> 16;
        *p++ = ((id >> 8) & 0xf0) | (index >> 16);
        *p++ = index >> 8;
        *p++ = index;

        // Skip callsigns with the same id[23:12].
        do {
            index++;
            if (index > nrecords)
                return;
        } while ((GET_CALLSIGN(mem, index-1)->dmrid >> 12) == (id >> 12));
    }
}

//
// Write CSV file to contacts database.
//
static void uv380_write_csv(radio_device_t *radio, FILE *csv)
{
    uint8_t *mem;
    char line[256];
    char *radioid, *callsign, *name, *city, *state, *country, *remarks;
    int id, bno, nbytes, nrecords = 0;
    unsigned finish;
    callsign_t *cs;

    // Allocate 14Mbytes of memory.
    nbytes = CALLSIGN_FINISH - CALLSIGN_START;
    mem = malloc(nbytes);
    if (!mem) {
        fprintf(stderr, "Out of memory!\n");
        return;
    }
    memset(mem, 0xff, nbytes);

    //
    // Parse CSV file.
    //
    if (csv_init(csv) < 0) {
        free(mem);
        return;
    }
    while (csv_read(csv, &radioid, &callsign, &name, &city, &state, &country, &remarks)) {
        //printf("%s,%s,%s,%s,%s,%s,%s\n", radioid, callsign, name, city, state, country, remarks);

        id = strtoul(radioid, 0, 10);
        if (id < 1 || id > 0xffffff) {
            fprintf(stderr, "Bad id: %d\n", id);
            fprintf(stderr, "Line: '%s,%s,%s,%s,%s,%s,%s'\n",
                radioid, callsign, name, city, state, country, remarks);
            return;
        }

        cs = GET_CALLSIGN(mem, nrecords);
        if ((uint8_t*) (cs + 1) > &mem[nbytes]) {
            fprintf(stderr, "WARNING: Too many callsigns!\n");
            fprintf(stderr, "Skipping the rest.\n");
            break;
        }
        nrecords++;

        // Fill callsign structure.
        cs->dmrid = id;
        strncpy(cs->callsign, callsign, sizeof(cs->callsign));
        snprintf(line, sizeof(line), "%s,%s,%s,%s,%s",
            name, city, state, country, remarks);
        strncpy(cs->name, line, sizeof(cs->name));
    }
    fprintf(stderr, "Total %d contacts.\n", nrecords);

    build_callsign_index(mem, nrecords);
#if 0
    print_hex(mem, 0x4003);
    exit(0);
#endif

    // Align to 1kbyte.
    finish = CALLSIGN_START + (CALLSIGN_OFFSET + nrecords*120 + 1023) / 1024 * 1024;
    if (finish > CALLSIGN_FINISH) {
        // Limit is 122197 contacts.
        fprintf(stderr, "Too many contacts!\n");
        return;
    }

    //
    // Erase whole region.
    // Align finish to 64kbytes.
    //
    radio_progress = 0;
    if (! trace_flag) {
        fprintf(stderr, "Erase: ");
        fflush(stderr);
    }
    dfu_erase(CALLSIGN_START, (finish + 0xffff) / 0x10000 * 0x10000);
    if (! trace_flag) {
        fprintf(stderr, "# done.\n");
        fprintf(stderr, "Write: ");
        fflush(stderr);
    }

    //
    // Write callsigns.
    //
    for (bno = CALLSIGN_START/1024; bno < finish/1024; bno++) {
        dfu_write_block(bno, &mem[bno*1024 - CALLSIGN_START], 1024);

        ++radio_progress;
        if (radio_progress % 512 == 0) {
            fprintf(stderr, "#");
            fflush(stderr);
        }
    }
    if (! trace_flag)
        fprintf(stderr, "# done.\n");
    free(mem);
}

//
// -------------------------------------------------------------------------
// tyt-plus: the layout as data, for the roster, the warnings and 'diff'.
// -------------------------------------------------------------------------
//
int uv380_is_family(const radio_device_t *dev)
{
    return dev == &radio_uv380 || dev == &radio_uv390 ||
           dev == &radio_md2017 || dev == &radio_md9600 || dev == &radio_rt84;
}

int uv380_image_size(void)
{
    return MEMSZ;
}

long uv380_radio_id(const unsigned char *mem)
{
    const general_settings_t *gs = (const general_settings_t*) &mem[OFFSET_SETTINGS];

    return gs->radio_id[0] | (gs->radio_id[1] << 8) | (gs->radio_id[2] << 16);
}

void uv380_radio_name(const unsigned char *mem, char *buf, int size)
{
    const general_settings_t *gs = (const general_settings_t*) &mem[OFFSET_SETTINGS];

    name_utf8(gs->radio_name, 16, buf, size);
}

//
// E-C3 in UI-SPEC: a channel whose privacy type is set while the enable bit
// is clear.  The CPS does not produce that; reported when a codeplug is read
// or opened, so the operator can make the two agree.
//
void uv380_report_privacy_warnings(void)
{
    int i;
    char name[64];

    for (i=0; i<NCHAN; i++) {
        channel_t *ch = GET_CHANNEL(i);

        if (!VALID_CHANNEL(ch) || ch->privacy == PRIV_NONE || ch->privacy_enable)
            continue;
        name_utf8(ch->name, 16, name, sizeof(name));
        fprintf(stderr, "Channel %d '%s': privacy type %s but the enable bit "
            "at +0x05 is clear.\n", i+1, name, PRIVACY_NAME[ch->privacy]);
        ev_begin("warning");
        ev_str("code", "privacy_inconsistent");
        ev_int("channel", i+1);
        ev_str("name", name);
        ev_str("privacy", PRIVACY_NAME[ch->privacy]);
        ev_str("message", "Encryption is set but switched off in the radio's data.");
        ev_end();
    }
}

//
// Record tables of the layout: where each kind of record lives.
//
static const struct {
    const char *kind;
    unsigned    start, size, count;
} REGION_TAB[] = {
    { "general",   OFFSET_SETTINGS, CPS_GENERAL_END - OFFSET_SETTINGS, 1 },
    { "menu",      CPS_MENU_START,  CPS_MENU_SIZE, 1 },
    { "buttons",   CPS_BUTTONS_START, CPS_BUTTONS_SIZE, 1 },
    { "onetouch",  CPS_ONETOUCH_START, 4, 6 },
    { "numberkey", CPS_NUMKEY_START, 2, 10 },
    { "emergency", CPS_EMERG_START, CPS_EMERG_SIZE, 1 },
    { "emsystem",  CPS_EMS_START,   CPS_EMS_SIZE, CPS_NEMS },
    { "dtmfsystem", CPS_DS_START,   CPS_DS_SIZE, CPS_NDS },
    { "dtmfencode", CPS_DE_START,   CPS_DE_SIZE, CPS_NDE },
    { "dtmfdecode", CPS_DD_START,   CPS_DD_SIZE, CPS_NDD },
    { "vfo",       CPS_VFO_START,   CPS_VFO_SIZE, CPS_NVFO },
    { "message",   OFFSET_MSG,      288, NMESSAGES  },
    { "privacy_legacy", 0x059c0,    0xb0, 1          },
    { "grouplist", OFFSET_GLISTS,   96,  NGLISTS    },
    { "zone",      OFFSET_ZONES,    64,  NZONES     },
    { "scanlist",  OFFSET_SCANL,    104, NSCANL     },
    { "zone",      OFFSET_ZONEXT,   224, NZONES     },  // members 17+ and B
    { "channel",   OFFSET_CHANNELS, 64,  NCHAN      },
    { "contact",   OFFSET_CONTACTS, 36,  NCONTACTS  },
};
#define NREGIONS ((int) (sizeof(REGION_TAB) / sizeof(REGION_TAB[0])))

//
// Name of record 'index' (0-based) of a kind, from one image, or "" when the
// record is empty there.
//
static void record_name(const unsigned char *mem, const char *kind, int index,
    char *buf, int size)
{
    buf[0] = 0;
    if (strcmp(kind, "channel") == 0) {
        const channel_t *ch = (const channel_t*) &mem[OFFSET_CHANNELS + index*64];
        if (VALID_CHANNEL(ch))
            name_utf8(ch->name, 16, buf, size);
    } else if (strcmp(kind, "zone") == 0) {
        const zone_t *z = (const zone_t*) &mem[OFFSET_ZONES + index*64];
        if (VALID_ZONE(z))
            name_utf8(z->name, 16, buf, size);
    } else if (strcmp(kind, "scanlist") == 0) {
        const scanlist_t *sl = (const scanlist_t*) &mem[OFFSET_SCANL + index*104];
        if (VALID_SCANLIST(sl))
            name_utf8(sl->name, 16, buf, size);
    } else if (strcmp(kind, "grouplist") == 0) {
        const grouplist_t *gl = (const grouplist_t*) &mem[OFFSET_GLISTS + index*96];
        if (VALID_GROUPLIST(gl))
            name_utf8(gl->name, 16, buf, size);
    } else if (strcmp(kind, "contact") == 0) {
        const contact_t *ct = (const contact_t*) &mem[OFFSET_CONTACTS + index*36];
        if (VALID_CONTACT(ct))
            name_utf8(ct->name, 16, buf, size);
    } else if (strcmp(kind, "message") == 0) {
        const uint16_t *m = (const uint16_t*) &mem[OFFSET_MSG + index*288];
        if (VALID_TEXT(m))
            name_utf8(m, 16, buf, size);
    } else {
        cps_record_name(mem, kind, index, buf, size);
    }
}

//
// Which record holds 'offset'?  Fills rec and the record's byte range and
// returns 1, or returns 0 for a byte outside every known record.  The name
// comes from the new image, or from the old one when the record was
// deleted.
//
int uv380_diff_record(const unsigned char *a, const unsigned char *b,
    unsigned offset, diff_record_t *rec, unsigned *rec_start, unsigned *rec_len)
{
    int r;

    for (r=0; r<NREGIONS; r++) {
        unsigned start = REGION_TAB[r].start;
        unsigned end = start + REGION_TAB[r].size * REGION_TAB[r].count;
        int index;

        if (offset < start || offset >= end)
            continue;
        index = (offset - start) / REGION_TAB[r].size;
        rec->kind = REGION_TAB[r].kind;
        rec->index = (REGION_TAB[r].count > 1) ? index + 1 : 0;
        record_name(b, rec->kind, index, rec->name, sizeof(rec->name));
        if (! rec->name[0])
            record_name(a, rec->kind, index, rec->name, sizeof(rec->name));
        *rec_start = start + index * REGION_TAB[r].size;
        *rec_len = REGION_TAB[r].size;
        return 1;
    }
    rec->kind = 0;
    rec->index = 0;
    rec->name[0] = 0;
    return 0;
}

//
// Field-level description of a changed record.
//
// Values are formatted as the config prints them, so the preview can say
// "Key 2 -> 1".  Bytes the config does not name are reported by offset
// within the record, so nothing that changed is ever left out.
//
static void fmt_trim(char *buf)
{
    int n = strlen(buf);

    while (n > 0 && buf[n-1] == ' ')
        buf[--n] = 0;
}

static void fmt_freq(char *buf, int size, unsigned bcd)
{
    FILE *f = fmemopen(buf, size, "w");

    buf[0] = 0;
    if (! f)
        return;
    print_freq(f, bcd);
    fclose(f);
    fmt_trim(buf);
}

static void fmt_tone(char *buf, int size, unsigned tone)
{
    FILE *f = fmemopen(buf, size, "w");

    buf[0] = 0;
    if (! f)
        return;
    print_tone(f, tone);
    fclose(f);
    fmt_trim(buf);
}

static void fmt_index(char *buf, int size, unsigned v)
{
    if (v == 0)
        snprintf(buf, size, "-");
    else
        snprintf(buf, size, "%u", v);
}

static void fmt_chanlist(char *buf, int size, const uint16_t *list, int n)
{
    FILE *f = fmemopen(buf, size, "w");

    buf[0] = 0;
    if (! f)
        return;
    if (n == 0 || list[0] == 0)
        fputs("-", f);
    else
        print_chanlist(f, (uint16_t*) list, n);
    fclose(f);
}

//
// One channel field as the config prints it.
//
static void chan_field(const channel_t *ch, const char *field, char *buf, int size)
{
    if (strcmp(field, "Name") == 0)
        name_utf8(ch->name, 16, buf, size);
    else if (strcmp(field, "Mode") == 0)
        snprintf(buf, size, "%s", ch->channel_mode == MODE_DIGITAL ? "Digital" :
            ch->channel_mode == MODE_ANALOG ? "Analog" : "?");
    else if (strcmp(field, "Width") == 0)
        snprintf(buf, size, "%s", BANDWIDTH[ch->bandwidth]);
    else if (strcmp(field, "RO") == 0)
        snprintf(buf, size, "%c", "-+"[ch->rx_only]);
    else if (strcmp(field, "Slot") == 0)
        snprintf(buf, size, "%d", ch->repeater_slot);
    else if (strcmp(field, "Color") == 0)
        snprintf(buf, size, "%d", ch->colorcode);
    else if (strcmp(field, "Privacy") == 0)
        snprintf(buf, size, "%s", PRIVACY_NAME[ch->privacy]);
    else if (strcmp(field, "Key") == 0) {
        if (ch->privacy == PRIV_NONE)
            snprintf(buf, size, "-");
        else
            snprintf(buf, size, "%d", ch->privacy_no + 1);
    } else if (strcmp(field, "Privacy enable") == 0)
        snprintf(buf, size, "%s", ch->privacy_enable ? "on" : "off");
    else if (strcmp(field, "Admit") == 0)
        snprintf(buf, size, "%s", ADMIT_NAME[ch->admit_criteria]);
    else if (strcmp(field, "TxContact") == 0)
        fmt_index(buf, size, ch->contact_name_index);
    else if (strcmp(field, "TOT") == 0) {
        if (ch->tot == 0)
            snprintf(buf, size, "-");
        else
            snprintf(buf, size, "%d", ch->tot * 15);
    } else if (strcmp(field, "Scan") == 0)
        fmt_index(buf, size, ch->scan_list_index);
    else if (strcmp(field, "RxGL") == 0)
        fmt_index(buf, size, ch->group_list_index);
    else if (strcmp(field, "Sq") == 0)
        snprintf(buf, size, "%d", ch->squelch);
    else if (strcmp(field, "Receive") == 0)
        fmt_freq(buf, size, ch->rx_frequency);
    else if (strcmp(field, "Transmit") == 0)
        fmt_freq(buf, size, ch->tx_frequency);
    else if (strcmp(field, "RxTone") == 0)
        fmt_tone(buf, size, ch->ctcss_dcs_receive);
    else if (strcmp(field, "TxTone") == 0)
        fmt_tone(buf, size, ch->ctcss_dcs_transmit);
    else if (strcmp(field, "Power") == 0)
        snprintf(buf, size, "%s", POWER_NAME[ch->power]);
    else
        buf[0] = 0;
}

//
// Channel record fields: byte offset, bit mask within it, and the name used
// in the config (or a descriptive name for fields the config does not have).
//
static const struct {
    int         byte, nbytes;
    unsigned    mask;           // within the first byte; 0xff for whole bytes
    const char *name;
    int         formatted;      // chan_field() knows it
} CHAN_FIELD_TAB[] = {
    { 0,  1, 0x03, "Mode",           1 },
    { 0,  1, 0x0c, "Width",          1 },
    { 0,  1, 0x10, "Autoscan",       0 },
    { 0,  1, 0x80, "Lone Worker",    0 },
    { 1,  1, 0x02, "RO",             1 },
    { 1,  1, 0x0c, "Slot",           1 },
    { 1,  1, 0xf0, "Color",          1 },
    { 2,  1, 0x0f, "Key",            1 },
    { 2,  1, 0x30, "Privacy",        1 },
    { 2,  1, 0x40, "Private Call Confirmed", 0 },
    { 2,  1, 0x80, "Data Call Confirmed",    0 },
    { 3,  1, 0x03, "RX Ref Frequency",       0 },
    { 3,  1, 0x08, "Emergency Alarm Ack",    0 },
    { 3,  1, 0x80, "Display PTT ID",         0 },
    { 4,  1, 0x03, "TX Ref Frequency",       0 },
    { 4,  1, 0x10, "VOX",            0 },
    { 4,  1, 0xc0, "Admit",          1 },
    { 5,  1, 0x04, "Privacy enable", 1 },
    { 5,  1, 0x30, "In Call Criteria",       0 },
    { 5,  1, 0xc0, "Turn-off Freq",  0 },
    { 6,  2, 0xff, "TxContact",      1 },
    { 8,  1, 0x3f, "TOT",            1 },
    { 9,  1, 0xff, "TOT Rekey Delay",        0 },
    { 10, 1, 0xff, "Emergency System",       0 },
    { 11, 1, 0xff, "Scan",           1 },
    { 12, 1, 0xff, "RxGL",           1 },
    { 15, 1, 0xff, "Sq",             1 },
    { 16, 4, 0xff, "Receive",        1 },
    { 20, 4, 0xff, "Transmit",       1 },
    { 24, 2, 0xff, "RxTone",         1 },
    { 26, 2, 0xff, "TxTone",         1 },
    { 28, 1, 0xff, "Rx Signaling",   0 },
    { 29, 1, 0xff, "Tx Signaling",   0 },
    { 30, 1, 0x03, "Power",          1 },
    { 31, 1, 0x08, "DCDM Switch",    0 },
    { 31, 1, 0x10, "Leader/MS",      0 },
    { 32, 32, 0xff, "Name",          1 },
};
#define NCHANFIELDS ((int) (sizeof(CHAN_FIELD_TAB) / sizeof(CHAN_FIELD_TAB[0])))

static void field_event(const char *name, const char *oldv, const char *newv,
    char *human, int hsize)
{
    int n = strlen(human);

    ev_obj(0);
    ev_str("field", name);
    if (oldv)
        ev_str("old", oldv);
    if (newv)
        ev_str("new", newv);
    ev_obj_end();

    if (n < hsize - 1) {
        if (oldv && newv)
            snprintf(human + n, hsize - n, "%s%s %s -> %s", n ? ", " : "",
                name, oldv, newv);
        else
            snprintf(human + n, hsize - n, "%s%s", n ? ", " : "", name);
    }
}

//
// Bytes of a record that changed but no field above accounts for.
//
static void other_bytes_event(const unsigned char *a, const unsigned char *b,
    unsigned start, const unsigned char *covered, unsigned len,
    char *human, int hsize)
{
    unsigned i;

    for (i=0; i<len; i++) {
        char name[32], ov[8], nv[8];

        if (covered[i] == 0xff || a[start+i] == b[start+i])
            continue;
        if ((a[start+i] & ~covered[i]) == (b[start+i] & ~covered[i]))
            continue;
        snprintf(name, sizeof(name), "+0x%02x", i);
        snprintf(ov, sizeof(ov), "%02x", a[start+i]);
        snprintf(nv, sizeof(nv), "%02x", b[start+i]);
        field_event(name, ov, nv, human, hsize);
    }
}

static void diff_channel(const unsigned char *a, const unsigned char *b,
    unsigned start, char *human, int hsize)
{
    const channel_t *ca = (const channel_t*) &a[start];
    const channel_t *cb = (const channel_t*) &b[start];
    unsigned char covered[64];
    int f, k;

    memset(covered, 0, sizeof(covered));
    for (f=0; f<NCHANFIELDS; f++) {
        int off = CHAN_FIELD_TAB[f].byte, nb = CHAN_FIELD_TAB[f].nbytes;
        unsigned mask = CHAN_FIELD_TAB[f].mask;
        int changed = 0;

        for (k=0; k<nb; k++) {
            unsigned m = (nb == 1) ? mask : 0xff;

            covered[off+k] |= m;
            if ((a[start+off+k] ^ b[start+off+k]) & m)
                changed = 1;
        }
        if (! changed)
            continue;
        if (CHAN_FIELD_TAB[f].formatted) {
            char ov[64], nv[64];

            chan_field(ca, CHAN_FIELD_TAB[f].name, ov, sizeof(ov));
            chan_field(cb, CHAN_FIELD_TAB[f].name, nv, sizeof(nv));
            field_event(CHAN_FIELD_TAB[f].name, ov, nv, human, hsize);
        } else {
            field_event(CHAN_FIELD_TAB[f].name, 0, 0, human, hsize);
        }
    }
    cps_diff_channel(a, b, start, covered, field_event, human, hsize);
    other_bytes_event(a, b, start, covered, 64, human, hsize);
}

static void diff_general(const unsigned char *a, const unsigned char *b,
    unsigned start, char *human, int hsize)
{
    const general_settings_t *ga = (const general_settings_t*) &a[start];
    const general_settings_t *gb = (const general_settings_t*) &b[start];
    unsigned char covered[CPS_GENERAL_END - OFFSET_SETTINGS];
    char ov[64], nv[64];
    unsigned i;

    memset(covered, 0, sizeof(covered));
    // Intro lines at +0 and +20, Radio ID at +68, Name at +112.
    for (i=0; i<20; i++)
        covered[i] = 0xff;
    if (memcmp(ga->intro_line1, gb->intro_line1, 20) != 0) {
        name_utf8(ga->intro_line1, 10, ov, sizeof(ov));
        name_utf8(gb->intro_line1, 10, nv, sizeof(nv));
        field_event("Intro Line 1", ov, nv, human, hsize);
    }
    for (i=20; i<40; i++)
        covered[i] = 0xff;
    if (memcmp(ga->intro_line2, gb->intro_line2, 20) != 0) {
        name_utf8(ga->intro_line2, 10, ov, sizeof(ov));
        name_utf8(gb->intro_line2, 10, nv, sizeof(nv));
        field_event("Intro Line 2", ov, nv, human, hsize);
    }
    for (i=68; i<71; i++)
        covered[i] = 0xff;
    if (memcmp(ga->radio_id, gb->radio_id, 3) != 0) {
        snprintf(ov, sizeof(ov), "%ld", uv380_radio_id(a));
        snprintf(nv, sizeof(nv), "%ld", uv380_radio_id(b));
        field_event("ID", ov, nv, human, hsize);
    }
    for (i=112; i<144; i++)
        covered[i] = 0xff;
    if (memcmp(ga->radio_name, gb->radio_name, 32) != 0) {
        name_utf8(ga->radio_name, 16, ov, sizeof(ov));
        name_utf8(gb->radio_name, 16, nv, sizeof(nv));
        field_event("Name", ov, nv, human, hsize);
    }
    // The CPS General Setting fields (cpsfields.c), by name.
    cps_diff_general(a, b, start, covered, sizeof(covered), field_event, human, hsize);
    other_bytes_event(a, b, start, covered, sizeof(covered), human, hsize);
}

//
// Zone: the record in the zone table holds the name and members 1-16 of A;
// the extension record holds A 17-64 and all of B.  Both are one zone, so
// both are compared here whichever of them held the changed byte; lists are
// compared whole and printed as the config prints them.
//
static void diff_zone(const unsigned char *a, const unsigned char *b,
    int index, char *human, int hsize)
{
    unsigned zs = OFFSET_ZONES + index*64, xs = OFFSET_ZONEXT + index*224;
    const zone_t *za = (const zone_t*) &a[zs];
    const zone_t *zb = (const zone_t*) &b[zs];
    const zone_ext_t *xa = (const zone_ext_t*) &a[xs];
    const zone_ext_t *xb = (const zone_ext_t*) &b[xs];
    uint16_t la[64], lb[64];
    char ov[512], nv[512];

    if (memcmp(za->name, zb->name, 32) != 0) {
        name_utf8(za->name, 16, ov, sizeof(ov));
        name_utf8(zb->name, 16, nv, sizeof(nv));
        field_event("Name", ov, nv, human, hsize);
    }
    memcpy(la, za->member_a, 32); memcpy(la + 16, xa->ext_a, 96);
    memcpy(lb, zb->member_a, 32); memcpy(lb + 16, xb->ext_a, 96);
    if (memcmp(la, lb, sizeof(la)) != 0) {
        fmt_chanlist(ov, sizeof(ov), la, 64);
        fmt_chanlist(nv, sizeof(nv), lb, 64);
        field_event("Channels A", ov, nv, human, hsize);
    }
    if (memcmp(xa->member_b, xb->member_b, 128) != 0) {
        fmt_chanlist(ov, sizeof(ov), xa->member_b, 64);
        fmt_chanlist(nv, sizeof(nv), xb->member_b, 64);
        field_event("Channels B", ov, nv, human, hsize);
    }
}

static void diff_named_list(const unsigned char *a, const unsigned char *b,
    unsigned start, unsigned len, unsigned list_off, int list_n,
    const char *list_name, char *human, int hsize)
{
    char ov[512], nv[512];
    unsigned char covered[256];
    unsigned i;

    memset(covered, 0, sizeof(covered));
    for (i=0; i<32; i++)
        covered[i] = 0xff;
    if (memcmp(&a[start], &b[start], 32) != 0) {
        name_utf8((const uint16_t*) &a[start], 16, ov, sizeof(ov));
        name_utf8((const uint16_t*) &b[start], 16, nv, sizeof(nv));
        field_event("Name", ov, nv, human, hsize);
    }
    for (i=list_off; i<list_off + list_n*2; i++)
        covered[i] = 0xff;
    if (memcmp(&a[start+list_off], &b[start+list_off], list_n*2) != 0) {
        fmt_chanlist(ov, sizeof(ov), (const uint16_t*) &a[start+list_off], list_n);
        fmt_chanlist(nv, sizeof(nv), (const uint16_t*) &b[start+list_off], list_n);
        field_event(list_name, ov, nv, human, hsize);
    }
    if (strcmp(list_name, "Channels") == 0) {
        // Scan list: priority channels and transmit channel at +32.
        static const char *SL_NAME[3] = { "PCh1", "PCh2", "TxCh" };
        int k;

        for (k=0; k<3; k++) {
            unsigned off = 32 + k*2;
            unsigned va = a[start+off] | (a[start+off+1] << 8);
            unsigned vb = b[start+off] | (b[start+off+1] << 8);

            covered[off] = covered[off+1] = 0xff;
            if (va == vb)
                continue;
            snprintf(ov, sizeof(ov), va == 0xffff ? (k == 2 ? "Last" : "-") :
                va == 0 ? "Sel" : "%u", va);
            snprintf(nv, sizeof(nv), vb == 0xffff ? (k == 2 ? "Last" : "-") :
                vb == 0 ? "Sel" : "%u", vb);
            field_event(SL_NAME[k], ov, nv, human, hsize);
        }
        cps_diff_scanlist(a, b, start, covered, field_event, human, hsize);
    }
    other_bytes_event(a, b, start, covered, len, human, hsize);
}

static void diff_contact(const unsigned char *a, const unsigned char *b,
    unsigned start, char *human, int hsize)
{
    const contact_t *ca = (const contact_t*) &a[start];
    const contact_t *cb = (const contact_t*) &b[start];
    unsigned char covered[36];
    char ov[64], nv[64];

    memset(covered, 0, sizeof(covered));
    covered[0] = covered[1] = covered[2] = 0xff;
    if (CONTACT_ID(ca) != CONTACT_ID(cb)) {
        snprintf(ov, sizeof(ov), "%d", CONTACT_ID(ca));
        snprintf(nv, sizeof(nv), "%d", CONTACT_ID(cb));
        field_event("ID", ov, nv, human, hsize);
    }
    covered[3] = 0x3f;
    if (ca->type != cb->type) {
        snprintf(ov, sizeof(ov), "%s", ca->type < 4 ? CONTACT_TYPE[ca->type] : "?");
        snprintf(nv, sizeof(nv), "%s", cb->type < 4 ? CONTACT_TYPE[cb->type] : "?");
        field_event("Type", ov, nv, human, hsize);
    }
    if (ca->receive_tone != cb->receive_tone) {
        snprintf(ov, sizeof(ov), "%s", ca->receive_tone ? "+" : "-");
        snprintf(nv, sizeof(nv), "%s", cb->receive_tone ? "+" : "-");
        field_event("RxTone", ov, nv, human, hsize);
    }
    memset(covered + 4, 0xff, 32);
    if (memcmp(ca->name, cb->name, 32) != 0) {
        name_utf8(ca->name, 16, ov, sizeof(ov));
        name_utf8(cb->name, 16, nv, sizeof(nv));
        field_event("Name", ov, nv, human, hsize);
    }
    other_bytes_event(a, b, start, covered, 36, human, hsize);
}

//
// Emit the "fields" array for one changed record, and a one-line human
// summary of it in 'human'.
//
void uv380_diff_fields(const unsigned char *a, const unsigned char *b,
    const diff_record_t *rec, unsigned rec_start, unsigned rec_len,
    char *human, int hsize)
{
    human[0] = 0;
    ev_arr("fields");
    if (strcmp(rec->kind, "channel") == 0)
        diff_channel(a, b, rec_start, human, hsize);
    else if (strcmp(rec->kind, "general") == 0)
        diff_general(a, b, rec_start, human, hsize);
    else if (strcmp(rec->kind, "zone") == 0)
        diff_zone(a, b, rec->index - 1, human, hsize);
    else if (strcmp(rec->kind, "scanlist") == 0)
        diff_named_list(a, b, rec_start, rec_len, 42, 31, "Channels", human, hsize);
    else if (strcmp(rec->kind, "grouplist") == 0)
        diff_named_list(a, b, rec_start, rec_len, 32, 32, "Contacts", human, hsize);
    else if (strcmp(rec->kind, "contact") == 0)
        diff_contact(a, b, rec_start, human, hsize);
    else if (strcmp(rec->kind, "menu") == 0 || strcmp(rec->kind, "buttons") == 0 ||
             strcmp(rec->kind, "onetouch") == 0 || strcmp(rec->kind, "numberkey") == 0 ||
             strcmp(rec->kind, "emergency") == 0 || strcmp(rec->kind, "emsystem") == 0 ||
             strcmp(rec->kind, "dtmfsystem") == 0 || strcmp(rec->kind, "dtmfencode") == 0 ||
             strcmp(rec->kind, "dtmfdecode") == 0 || strcmp(rec->kind, "vfo") == 0) {
        unsigned char covered[64];

        memset(covered, 0, sizeof(covered));
        cps_diff_record(rec->kind, a, b, rec_start, rec_len, covered, field_event, human, hsize);
        other_bytes_event(a, b, rec_start, covered, rec_len, human, hsize);
    }
    else if (strcmp(rec->kind, "message") == 0) {
        char ov[300], nv[300];

        name_utf8((const uint16_t*) &a[rec_start], 144, ov, sizeof(ov));
        name_utf8((const uint16_t*) &b[rec_start], 144, nv, sizeof(nv));
        field_event("Text", ov, nv, human, hsize);
    } else {
        unsigned char covered[256];

        memset(covered, 0, sizeof(covered));
        other_bytes_event(a, b, rec_start, covered,
            rec_len < sizeof(covered) ? rec_len : sizeof(covered), human, hsize);
    }
    ev_arr_end();
}

//
// TYT MD-UV380
//
radio_device_t radio_uv380 = {
    "TYT MD-UV380",
    uv380_download,
    uv380_upload,
    uv380_is_compatible,
    uv380_read_image,
    uv380_save_image,
    uv380_print_version,
    uv380_print_config,
    uv380_verify_config,
    uv380_parse_parameter,
    uv380_parse_header,
    uv380_parse_row,
    uv380_update_timestamp,
    uv380_write_csv,
    0,
    uv380_parse_finish,
};

//
// TYT MD-UV390
//
radio_device_t radio_uv390 = {
    "TYT MD-UV390",
    uv380_download,
    uv380_upload,
    uv380_is_compatible,
    uv380_read_image,
    uv380_save_image,
    uv380_print_version,
    uv380_print_config,
    uv380_verify_config,
    uv380_parse_parameter,
    uv380_parse_header,
    uv380_parse_row,
    uv380_update_timestamp,
    uv380_write_csv,
    0,
    uv380_parse_finish,
};

//
// TYT MD-2017
//
radio_device_t radio_md2017 = {
    "TYT MD-2017",
    uv380_download,
    uv380_upload,
    uv380_is_compatible,
    uv380_read_image,
    uv380_save_image,
    uv380_print_version,
    uv380_print_config,
    uv380_verify_config,
    uv380_parse_parameter,
    uv380_parse_header,
    uv380_parse_row,
    uv380_update_timestamp,
    uv380_write_csv,
};

//
// TYT MD-9600
//
radio_device_t radio_md9600 = {
    "TYT MD-9600",
    uv380_download,
    uv380_upload,
    uv380_is_compatible,
    uv380_read_image,
    uv380_save_image,
    uv380_print_version,
    uv380_print_config,
    uv380_verify_config,
    uv380_parse_parameter,
    uv380_parse_header,
    uv380_parse_row,
    uv380_update_timestamp,
    uv380_write_csv,
};

//
// Baofeng DM-1701, Retevis RT84
//
radio_device_t radio_rt84 = {
    "Retevis RT84",
    uv380_download,
    uv380_upload,
    uv380_is_compatible,
    uv380_read_image,
    uv380_save_image,
    uv380_print_version,
    uv380_print_config,
    uv380_verify_config,
    uv380_parse_parameter,
    uv380_parse_header,
    uv380_parse_row,
    uv380_update_timestamp,
    uv380_write_csv,
};
