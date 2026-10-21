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

//
// Connect to the radio via the serial port.
// Identify the type of device.
//
void radio_connect(void);

//
// Close the serial port.
//
void radio_disconnect(void);
void radio_disconnect_after_write(void);

//
// Read firmware image from the device.
//
void radio_download(void);

//
// Read the device twice.  Returns 1 when the reads agree, else 0 with the
// number of differing bytes and the first of them.
//
int radio_download_twice(unsigned *ndiff, unsigned *first);

//
// The "unit" event, and the roster update for this session (tyt-plus).
//
void radio_report_unit(const char *ident);
void radio_roster_seen(long radio_id, int wrote_codeplug);

//
// --expect-unit: the a2 07 unit block a write must find, lower-case hex, or
// null.  radio_require_unit() refuses a session whose unit is a different
// one (exit 17) or cannot be read (exit 14), while nothing is written;
// radio_check_unit() does it for the codeplug session just connected.
//
extern const char *radio_expect_unit;
void radio_require_unit(const char *a207);
void radio_check_unit(void);

//
// Radio ID, name and image size of the codeplug in memory, for layouts this
// fork knows; -1, "" and 0 otherwise.
//
long radio_image_id(void);
void radio_check_image_fits(void);
void radio_privacy_warnings(void);
void radio_image_name(char *buf, int size);
int radio_image_size(void);

//
// Results of the last radio_verify_upload().
//
extern int radio_verify_volatile;
extern unsigned radio_verify_ndiff, radio_verify_first;

//
// Configuration problems with their location (tyt-plus, UI-SPEC F9).
// conf_error(): a row parser names the bad column and returns 0.
// conf_fail(): the same, for a parser that cannot return (stops).
// conf_problem_begin(): a problem found after parsing; finish the event
// with error_event_end() from report.h.
//
void conf_error(const char *column, const char *fmt, ...)
    __attribute__((format(printf, 2, 3)));
void conf_fail(const char *column, const char *fmt, ...)
    __attribute__((noreturn, format(printf, 2, 3)));
void conf_problem_begin(int code, int table_id, const char *id,
    const char *section, const char *column);

//
// Read the device twice and require the two reads to agree. Use this for any
// read whose result will be written back - see the comment in radio.c.
//
void radio_download_verified(void);

//
// Read back what was just written and check it landed. Returns 1 on success.
//
int radio_verify_upload(void);

//
// Write firmware image to the device.
//
void radio_upload(int cont_flag);

//
// Print a generic information about the device.
//
void radio_print_version(FILE *out);

//
// Print full information about the device configuration.
//
void radio_print_config(FILE *out, int verbose);

//
// Read firmware image from the binary file.
//
void radio_read_image(const char *filename);

//
// Save firmware image to the binary file.
//
void radio_save_image(const char *filename);

//
// Read the configuration from text file, and modify the firmware.
//
void radio_parse_config(const char *filename);

//
// Attempt to read the configuration file, see if it can be parsed successfully for any radio.
//
void radio_validate_config(const char *filename);

//
// Check the configuration.
//
void radio_verify_config(void);

//
// Update CSV contacts database.
//
void radio_write_csv(const char *filename);

//
// List all supported radios.
//
void radio_list(void);

//
// Check for compatible radio model.
//
int radio_is_compatible(const char *ident);

//
// Does this DFU identify string belong to a radio whose privacy/AES key
// table layout we know?  See privacy.c.
//
int radio_is_privacy_capable(const char *ident);

//
// Privacy / AES key table operations (privacy.c).
//
void privacy_write_keys(const char *filename);
void privacy_read_keys(void);
void privacy_identify(void);
void privacy_keys_command(int argc, char **argv);
void privacy_ledger_command(int argc, char **argv);

//
// dmrconfig diff a.img b.img (imgdiff.c).
//
void image_diff_command(int argc, char **argv);
void privacy_load_dec(const char *filename, unsigned char *blob);
void privacy_print_table(FILE *out, const unsigned char *blob, int show_keys);
int privacy_slot_available(const unsigned char *blob, int slot);
const char *privacy_slot_type_name(const unsigned char *blob, int slot);

//
// Fleet key file named with -F, for checking channel key references.
// Null when none was given.
//
extern const unsigned char *radio_fleet_keys;

//
// Device-dependent interface to the radio.
//
typedef struct _radio_device_t radio_device_t;
struct _radio_device_t {
    const char *name;
    void (*download)(radio_device_t *radio);
    void (*upload)(radio_device_t *radio, int cont_flag);
    int (*is_compatible)(radio_device_t *radio);
    void (*read_image)(radio_device_t *radio, FILE *img);
    void (*save_image)(radio_device_t *radio, FILE *img);
    void (*print_version)(radio_device_t *radio, FILE *out);
    void (*print_config)(radio_device_t *radio, FILE *out, int verbose);
    int (*verify_config)(radio_device_t *radio);
    void (*parse_parameter)(radio_device_t *radio, char *param, char *value);
    int (*parse_header)(radio_device_t *radio, char *line);
    int (*parse_row)(radio_device_t *radio, int table_id, int first_row, char *line);
    void (*update_timestamp)(radio_device_t *radio);
    void (*write_csv)(radio_device_t *radio, FILE *csv);
    int channel_count;
    void (*parse_finish)(radio_device_t *radio);    // after the whole config, or 0
};

extern radio_device_t radio_md380;      // TYT MD-380
extern radio_device_t radio_md390;      // TYT MD-390
extern radio_device_t radio_md2017;     // TYT MD-2017
extern radio_device_t radio_uv380;      // TYT MD-UV380
extern radio_device_t radio_uv390;      // TYT MD-UV390
extern radio_device_t radio_md9600;     // TYT MD-9600
extern radio_device_t radio_d900;       // Zastone D900
extern radio_device_t radio_dp880;      // Zastone DP880
extern radio_device_t radio_rt27d;      // Radtel RT-27D
extern radio_device_t radio_rd5r;       // Baofeng RD-5R
extern radio_device_t radio_gd77;       // Radioddity GD-77, version 3.1.1 and later
extern radio_device_t radio_dm1801;     // Baofeng DM-1801
extern radio_device_t radio_d868uv;     // Anytone AT-D868UV
extern radio_device_t radio_d878uv;     // Anytone AT-D878UV
extern radio_device_t radio_d878uv2;    // Anytone AT-D878UV2
extern radio_device_t radio_dmr6x2;     // BTECH DMR-6x2
extern radio_device_t radio_rt84;       // Baofeng DM-1701, Retevis RT84

//
// The MD-UV380 codeplug layout (uv380.c), shared by the UV380, UV390,
// MD-2017, MD-9600 and RT84 drivers.
//
int uv380_is_family(const radio_device_t *dev);
int uv380_image_size(void);
long uv380_radio_id(const unsigned char *mem);
void uv380_radio_name(const unsigned char *mem, char *buf, int size);
void uv380_report_privacy_warnings(void);

//
// Describe the bytes that differ between two images of this layout, as
// records (channel 2 "TAC_2": Key 2 -> 1).  See imgdiff.c.
//
typedef struct {
    const char *kind;           // "channel", "zone", "general", ... or 0
    int         index;          // 1-based record number, 0 for none
    char        name[64];       // record name, UTF-8, may be empty
} diff_record_t;
int uv380_diff_record(const unsigned char *a, const unsigned char *b,
    unsigned offset, diff_record_t *rec, unsigned *rec_start, unsigned *rec_len);
void uv380_diff_fields(const unsigned char *a, const unsigned char *b,
    const diff_record_t *rec, unsigned rec_start, unsigned rec_len,
    char *human, int hsize);

//
// Radio: memory contents.
//
extern unsigned char radio_mem[];

//
// The memory image as it was when radio_parse_config() started: checks on
// what a config changes compare against it.
//
extern unsigned char conf_mem_before[];

//
// File descriptor of serial port with programming cable attached.
//
extern int radio_port;

//
// Read/write progress counter.
//
extern int radio_progress;
