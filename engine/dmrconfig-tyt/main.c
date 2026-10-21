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
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include "radio.h"
#include "util.h"
#include "report.h"
#include "state.h"

#ifndef GITCOMMIT
#define GITCOMMIT "unknown"
#endif
#ifndef GITBRANCH
#define GITBRANCH "unknown"
#endif

const char version[] = VERSION;
const char *copyright;

//
// Version of the --json event and exit-code contract documented in
// README-tyt-plus.md.  TYTcps checks it.
//
#define JSON_API 3

extern char *optarg;
extern int optind;

int trace_flag = 0;

void usage()
{
    fprintf(stderr, "DMR Config, Version %s, %s\n", version, copyright);
    fprintf(stderr, "tyt-plus fork, commit %s\n", GITCOMMIT);
    fprintf(stderr, "Usage:\n");
    fprintf(stderr, "    dmrconfig -r [-t] [-o dir]\n");
    fprintf(stderr, "                         Read codeplug from the radio twice; the reads must agree.\n");
    fprintf(stderr, "                         Save it to 'device.img' and 'device.conf' (in dir).\n");
    fprintf(stderr, "    dmrconfig -w [-t] [--expect-unit A207] file.img\n");
    fprintf(stderr, "                         Write codeplug to the radio.\n");
    fprintf(stderr, "    dmrconfig -v [-t] file.conf\n");
    fprintf(stderr, "                         Verify configuration script for the radio.\n");
    fprintf(stderr, "    dmrconfig -z file.conf\n");
    fprintf(stderr, "                         Read (validate) a configuration file.\n");
    fprintf(stderr, "    dmrconfig -c [-t] [-F fleet.dec] [--expect-unit A207] file.conf\n");
    fprintf(stderr, "                         Apply configuration script to the radio.\n");
    fprintf(stderr, "    dmrconfig -c [-F fleet.dec] [-o dir] file.img file.conf\n");
    fprintf(stderr, "                         Apply configuration script to the codeplug image.\n");
    fprintf(stderr, "                         Store modified copy to a file 'device.img' (in dir).\n");
    fprintf(stderr, "    dmrconfig file.img\n");
    fprintf(stderr, "                         Display configuration from the codeplug image.\n");
    fprintf(stderr, "    dmrconfig -u [-t] file.csv\n");
    fprintf(stderr, "                         Update contacts database from CSV file.\n");
    fprintf(stderr, "    dmrconfig identify [-t]\n");
    fprintf(stderr, "                         Which radio is connected: model, unit, serial.\n");
    fprintf(stderr, "                         Reads no codeplug and no keys.\n");
    fprintf(stderr, "    dmrconfig -K [-t] [--expect-unit A207] fleet.dec\n");
    fprintf(stderr, "                         Write the AES/privacy key table to the radio.\n");
    fprintf(stderr, "                         The whole fleet table goes every time.\n");
    fprintf(stderr, "    dmrconfig -k [-t]\n");
    fprintf(stderr, "                         Read key slot types and names (keys read back zero).\n");
    fprintf(stderr, "    dmrconfig keys show|new|set|clear ...\n");
    fprintf(stderr, "                         Inspect, create and edit key files. Touches no radio.\n");
    fprintf(stderr, "    dmrconfig ledger add-existing --unit A207 --keyset fleet.dec [--note TEXT]\n");
    fprintf(stderr, "                         Record keys a radio already holds.\n");
    fprintf(stderr, "    dmrconfig diff a.img b.img\n");
    fprintf(stderr, "                         Which records two codeplug images differ in.\n");
    fprintf(stderr, "Options:\n");
    fprintf(stderr, "    -r           Read codeplug from the radio.\n");
    fprintf(stderr, "    -w           Write codeplug to the radio.\n");
    fprintf(stderr, "    -c           Configure the radio from a text script.\n");
    fprintf(stderr, "    -v           Verify config file.\n");
    fprintf(stderr, "    -z           Validate config file.\n");
    fprintf(stderr, "    -u           Update contacts database.\n");
    fprintf(stderr, "    -l           List all supported radios.\n");
    fprintf(stderr, "    -K           Write the AES/privacy key table.\n");
    fprintf(stderr, "    -k           Read key slot types and names.\n");
    fprintf(stderr, "    -F file.dec  Fleet key table, for checking channel Key references.\n");
    fprintf(stderr, "    -o dir       Output folder for -r and an offline -c.\n");
    fprintf(stderr, "    -t           Trace USB protocol.\n");
    fprintf(stderr, "    --json       Events on stdout, one JSON object per line.\n");
    fprintf(stderr, "    --expect-unit A207\n");
    fprintf(stderr, "                 With -K, -w or -c to a radio: write only to this unit\n");
    fprintf(stderr, "                 (its a2 07 block, as identify prints it).\n");
    fprintf(stderr, "    --version    Print the version and commit.\n");
    fprintf(stderr, "Environment:\n");
    fprintf(stderr, "    TYT_STATE_DIR  Fleet folder: ledger, radio roster, pre-write images.\n");
    fprintf(stderr, "                   Default $XDG_DATA_HOME/tytcps or ~/.local/share/tytcps.\n");
    die(EXIT_USAGE, "Usage error.");
}

static void print_version(void)
{
    printf("dmrconfig-tyt %s (branch %s, commit %s)\n", version, GITBRANCH,
        GITCOMMIT);
    ev_begin("result");
    ev_str("command", "version");
    ev_bool("ok", 1);
    ev_str("program", "dmrconfig-tyt");
    ev_str("version", version);
    ev_str("branch", GITBRANCH);
    ev_str("commit", GITCOMMIT);
    ev_int("api", JSON_API);
    ev_end();
}

//
// Output path inside the -o folder, or the current folder.
//
static void out_path(char *buf, int size, const char *dir, const char *name)
{
    if (dir)
        snprintf(buf, size, "%s/%s", dir, name);
    else
        snprintf(buf, size, "%s", name);
}

static void check_outdir(const char *dir)
{
    struct stat st;

    if (dir && (stat(dir, &st) < 0 || ! S_ISDIR(st.st_mode)))
        die(EXIT_IO, "-o %s: not a folder.", dir);
}

//
// Common fields of a result that names an image in memory.
//
static void image_fields(const char *path)
{
    char name[64];
    long id = radio_image_id();
    int size = radio_image_size();

    radio_image_name(name, sizeof(name));
    if (path)
        ev_str("image", path);
    if (size > 0) {
        char sha[65];

        sha256_hex(radio_mem, size, sha);
        ev_str("sha256", sha);
        ev_int("size", size);
    }
    if (id >= 0)
        ev_int("radio_id", id);
    else
        ev_str("radio_id", 0);
    ev_str("name", name[0] ? name : 0);
}

//
// The pre-write image: the codeplug as the
// radio held it immediately before a -c or -w.  It costs nothing for -c,
// which reads the radio anyway, and it is how a test radio was recovered
// from a corrupted write.  Kept in the fleet folder, last five per unit.
//
// The verified read is held in memory and saved only once the write is
// certain to go ahead - after the config parsed and checked, after the file
// was found to fit the radio - so that runs which write nothing never push
// a real restore point out of the five.
//
static unsigned char prewrite_buf[1024*1024*2];  // as radio_mem
static int prewrite_size;

static void hold_prewrite(void)
{
    prewrite_size = radio_image_size();
    if (prewrite_size > 0)
        memcpy(prewrite_buf, radio_mem, prewrite_size);
}

static const char *save_prewrite(void)
{
    static char path[1200];
    int reused = 0;

    if (prewrite_size <= 0)
        return 0;
    report_phase("prewrite");
    if (prewrite_save(unit_a207(), prewrite_buf, prewrite_size, path,
            sizeof(path), &reused) < 0) {
        if (errno == ENOENT)
            report_warning("prewrite_skipped", "No fleet folder at %s, so no "
                "pre-write image was kept. Set TYT_STATE_DIR, or let TYTcps "
                "create the folder. The write goes ahead and is verified.",
                state_dir());
        else if (errno == ENODEV)
            report_warning("prewrite_skipped", "The radio's unit block could "
                "not be read, so no pre-write image was kept (it could not "
                "be told apart from another radio's). The write goes ahead "
                "and is verified.");
        else
            report_warning("prewrite_failed", "Could not save the pre-write "
                "image in %s/prewrite: %s. The write goes ahead; the radio is "
                "still verified after it.", state_dir(), strerror(errno));
        return 0;
    }
    fprintf(stderr, "Pre-write image: %s%s\n", path,
        reused ? " (same as the last one kept)" : "");
    ev_begin("prewrite");
    ev_str("path", path);
    ev_bool("reused", reused);
    ev_end();
    return path;
}

static void write_result(const char *command, const char *file,
    const char *prewrite)
{
    ev_begin("result");
    ev_str("command", command);
    ev_bool("ok", 1);
    if (file)
        ev_str("file", file);
    ev_bool("verified", 1);
    ev_int("volatile", radio_verify_volatile);
    ev_str("a207", *unit_a207() ? unit_a207() : 0);
    ev_str("prewrite", prewrite);
    image_fields(0);
    ev_end();
}

static void write_not_verified(void)
{
    radio_roster_seen(-1, 0);
    fail_begin(EXIT_WRITE_UNVERIFIED);
    ev_int("bytes", radio_verify_ndiff);
    ev_int("first", radio_verify_first);
    fail_end("The write did not verify: after writing, the radio still "
        "differs from the codeplug in %u bytes (first at 0x%05x), on two "
        "reads. Do not use this radio until this is fixed: write again, or "
        "write a codeplug file you know is good with -w.",
        radio_verify_ndiff, radio_verify_first);
}

//
// Remove long options that apply to every command, wherever they are.
//
static int take_flag(int *argc, char **argv, const char *flag)
{
    int i, j, found = 0;

    for (i=1; i<*argc; ) {
        if (strcmp(argv[i], flag) == 0) {
            for (j=i; j<*argc-1; j++)
                argv[j] = argv[j+1];
            (*argc)--;
            found = 1;
        } else {
            i++;
        }
    }
    return found;
}

//
// --expect-unit A207 (or --expect-unit=A207), wherever it is on the line:
// the unit block in hex, as identify prints it.  Returns it in lower case,
// or null when the option is not given.
//
static const char *take_expect_unit(int *argc, char **argv)
{
    static char unit[65];
    const char *value = 0;
    int i, j, n = 0, k;

    for (i=1; i<*argc; ) {
        if (strcmp(argv[i], "--expect-unit") == 0) {
            if (i + 1 >= *argc)
                die(EXIT_USAGE, "--expect-unit needs the unit block in hex.");
            value = argv[i+1];
            n = 2;
        } else if (strncmp(argv[i], "--expect-unit=", 14) == 0) {
            value = argv[i] + 14;
            n = 1;
        } else {
            i++;
            continue;
        }
        if (unit[0])
            die(EXIT_USAGE, "--expect-unit is given more than once.");
        k = strlen(value);
        if (k < 2 || k > 64 || k % 2)
            die(EXIT_USAGE, "--expect-unit %s: expected the unit block in hex, "
                "as identify prints it.", value);
        for (j=0; j<k; j++) {
            char c = value[j];

            if (c >= 'A' && c <= 'F')
                c += 'a' - 'A';
            if (! ((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                die(EXIT_USAGE, "--expect-unit %s: expected the unit block in "
                    "hex, as identify prints it.", value);
            unit[j] = c;
        }
        unit[k] = 0;
        for (j=i; j<*argc-n; j++)
            argv[j] = argv[j+n];
        *argc -= n;
    }
    return unit[0] ? unit : 0;
}

static void expect_unit_usage(void)
{
    die(EXIT_USAGE, "--expect-unit goes with -K, -w or -c to a radio only.");
}

int main(int argc, char **argv)
{
    int read_flag = 0, write_flag = 0, config_flag = 0, csv_flag = 0;
    int list_flag = 0, verify_flag = 0, validate_flag = 0;
    int keywrite_flag = 0, keyread_flag = 0;
    int json, version_flag, first;
    const char *keyfile = 0, *outdir = 0;
    static unsigned char fleet_keys[PRIVACY_TABLE_SIZE];

    copyright = "Copyright (C) 2018 Serge Vakulenko KK6ABQ";
    trace_flag = 0;

    json = take_flag(&argc, argv, "--json");
    version_flag = take_flag(&argc, argv, "--version");
    report_init(json);
    setvbuf(stdout, 0, _IOLBF, 0);
    setvbuf(stderr, 0, _IOLBF, 0);
    radio_expect_unit = take_expect_unit(&argc, argv);
    if (radio_expect_unit && version_flag)
        expect_unit_usage();

    if (version_flag) {
        print_version();
        return 0;
    }

    // Subcommands come first on the line, after any -t.  They take options
    // of their own, so getopt must not see them.
    // Only skip the -t flags here; getopt counts them for the other commands,
    // and counting them twice would turn a plain -t into -t -t, which dumps
    // codeplug data.
    for (first=1; first<argc && strcmp(argv[first], "-t") == 0; first++)
        ;
    if (first < argc && (strcmp(argv[first], "keys") == 0 ||
                         strcmp(argv[first], "ledger") == 0 ||
                         strcmp(argv[first], "diff") == 0 ||
                         strcmp(argv[first], "identify") == 0))
        trace_flag = first - 1;
    if (first < argc) {
        const char *sub = argv[first];
        int sargc = argc - first - 1;
        char **sargv = argv + first + 1;

        if (radio_expect_unit && (strcmp(sub, "keys") == 0 ||
                                  strcmp(sub, "ledger") == 0 ||
                                  strcmp(sub, "diff") == 0 ||
                                  strcmp(sub, "identify") == 0))
            expect_unit_usage();
        if (strcmp(sub, "keys") == 0) {
            privacy_keys_command(sargc, sargv);
            return 0;
        }
        if (strcmp(sub, "ledger") == 0) {
            privacy_ledger_command(sargc, sargv);
            return 0;
        }
        if (strcmp(sub, "diff") == 0) {
            image_diff_command(sargc, sargv);
            return 0;
        }
        if (strcmp(sub, "identify") == 0) {
            int i;

            for (i=0; i<sargc; i++) {
                if (strcmp(sargv[i], "-t") != 0)
                    usage();
                trace_flag++;
            }
            privacy_identify();
            return 0;
        }
    }

    for (;;) {
        switch (getopt(argc, argv, "tcwrulvzKkF:o:")) {
        case 't': ++trace_flag;  continue;
        case 'K': ++keywrite_flag; continue;
        case 'k': ++keyread_flag;  continue;
        case 'F': keyfile = optarg; continue;
        case 'o': outdir = optarg; continue;
        case 'r': ++read_flag;   continue;
        case 'w': ++write_flag;  continue;
        case 'c': ++config_flag; continue;
        case 'u': ++csv_flag;    continue;
        case 'l': ++list_flag;   continue;
	case 'v': ++verify_flag; continue;
        case 'z': ++validate_flag; continue;
        default:
            usage();
        case EOF:
            break;
        }
        break;
    }
    argc -= optind;
    argv += optind;
    if (radio_expect_unit && list_flag)
        expect_unit_usage();
    if (list_flag) {
        radio_list();
        ev_begin("result");
        ev_str("command", "list");
        ev_bool("ok", 1);
        ev_end();
        exit(0);
    }

    if (read_flag + write_flag + config_flag + csv_flag + verify_flag +
        validate_flag + keywrite_flag + keyread_flag > 1) {
        fprintf(stderr, "Only one of -r, -w, -c, -v, -z, -u, -K or -k options is allowed.\n");
        usage();
    }
    check_outdir(outdir);
    if (radio_expect_unit && ! (keywrite_flag || write_flag ||
                                (config_flag && argc == 1)))
        expect_unit_usage();

    // A fleet key table given with -F lets verify_config check that every
    // channel's Universal key slot actually holds a key.
    if (keyfile) {
        privacy_load_dec(keyfile, fleet_keys);
        radio_fleet_keys = fleet_keys;
    }

    if (keywrite_flag) {
        // Write the AES/privacy key table.
        if (argc != 1)
            usage();

        privacy_write_keys(argv[0]);

    } else if (keyread_flag) {
        // Read key slot types and names.
        if (argc != 0)
            usage();

        privacy_read_keys();

    } else if (write_flag) {
        // Restore image file to device.
        const char *prewrite = 0;
        unsigned ndiff, firstdiff;

        if (argc != 1)
            usage();

        // Check the file before touching the radio.
        radio_read_image(argv[0]);

        radio_connect();
        radio_check_unit();

        // Refuse a file for another kind of radio before reading this one.
        radio_read_image(argv[0]);
        radio_check_image_fits();

        // Two reads for the pre-write image.  -w does not depend on what the
        // radio holds, so reads that disagree only cost the pre-write image,
        // not the write.  A read that fails outright ends the run with
        // nothing written, as it would end the write's own verify.
        if (radio_download_twice(&ndiff, &firstdiff))
            hold_prewrite();
        else
            report_warning("prewrite_skipped", "The two reads before the "
                "write disagree (%u bytes, first at 0x%05x), so no pre-write "
                "image was kept. The write goes ahead and is verified.",
                ndiff, firstdiff);

        radio_read_image(argv[0]);
        radio_check_image_fits();
        prewrite = save_prewrite();
        radio_print_version(stdout);
        radio_upload(0);
        if (! radio_verify_upload()) {
            radio_disconnect_after_write();
            write_not_verified();
        }
        radio_disconnect_after_write();
        radio_roster_seen(radio_image_id(), 1);
        write_result("write_image", argv[0], prewrite);

    } else if (config_flag) {
        if (argc != 1 && argc != 2)
            usage();

        if (argc == 2) {
            // Apply text config to image file.
            char path[1200];

            out_path(path, sizeof(path), outdir, "device.img");
            radio_read_image(argv[0]);
            radio_print_version(stdout);
            radio_parse_config(argv[1]);
            radio_verify_config();
            report_phase("save");
            radio_save_image(path);
            ev_begin("result");
            ev_str("command", "apply");
            ev_bool("ok", 1);
            ev_str("base", argv[0]);
            ev_str("conf", argv[1]);
            image_fields(path);
            ev_end();

        } else {
            // Update device from text config file.
            //
            // This path reads the radio and writes the result back, so the
            // read MUST be verified: a silent corrupt read would otherwise be
            // programmed into flash. See radio_download_verified().
            const char *prewrite;

            radio_connect();
            radio_check_unit();
            radio_download_verified();
            hold_prewrite();
            radio_print_version(stdout);
            radio_save_image("backup.img");
            radio_parse_config(argv[0]);
            radio_verify_config();
            prewrite = save_prewrite();
            radio_upload(1);
            if (! radio_verify_upload()) {
                radio_disconnect_after_write();
                write_not_verified();
            }
            radio_disconnect_after_write();
            radio_roster_seen(radio_image_id(), 1);
            write_result("write_conf", argv[0], prewrite);
        }

    } else if (verify_flag) {
        if (argc != 1)
	    usage();

	// Verify text config file.
	radio_connect();
	radio_parse_config(argv[0]);
	radio_verify_config();
	radio_disconnect();
        ev_begin("result");
        ev_str("command", "verify");
        ev_bool("ok", 1);
        ev_end();

    } else if (read_flag) {
        char imgpath[1200], confpath[1200];
        unsigned ndiff, firstdiff;
        FILE *conf;

        if (argc != 0)
            usage();

        out_path(imgpath, sizeof(imgpath), outdir, "device.img");
        out_path(confpath, sizeof(confpath), outdir, "device.conf");

        // Dump device to image file.  Two reads that must agree: the
        // two-read rule belongs here, not in every caller.
        radio_connect();
        if (! radio_download_twice(&ndiff, &firstdiff)) {
            fprintf(stderr, "\nTWO READS OF THIS RADIO DISAGREE: %u bytes, "
                "first at 0x%05x.\n", ndiff, firstdiff);
            radio_disconnect();
            fail_begin(EXIT_READS_DISAGREE);
            ev_int("bytes", ndiff);
            ev_int("first", firstdiff);
            fail_end("Two reads of this radio disagree (%u bytes, first at "
                "0x%05x). Nothing was saved, and nothing was written. Unplug "
                "the radio, plug it back in and try again.", ndiff, firstdiff);
        }
        radio_print_version(stdout);
        radio_disconnect_after_write();
        report_phase("save");
        radio_save_image(imgpath);

        // Print configuration to file.
        fprintf(stderr, "Print configuration to file '%s'.\n", confpath);
        conf = fopen(confpath, "w");
        if (!conf)
            die(EXIT_IO, "%s: %s", confpath, strerror(errno));
        radio_print_config(conf, 1);
        if (ferror(conf) | fclose(conf))
            die(EXIT_IO, "%s: write failed: %s", confpath, strerror(errno));

        radio_roster_seen(radio_image_id(), 0);
        radio_privacy_warnings();
        ev_begin("result");
        ev_str("command", "read");
        ev_bool("ok", 1);
        ev_bool("reads_agree", 1);
        ev_str("conf", confpath);
        ev_str("a207", *unit_a207() ? unit_a207() : 0);
        image_fields(imgpath);
        ev_end();

    } else if (csv_flag) {
        // Update contacts database on the device.
        if (argc != 1)
            usage();

        radio_connect();
        radio_write_csv(argv[0]);
        radio_disconnect();
        ev_begin("result");
        ev_str("command", "write_csv");
        ev_bool("ok", 1);
        ev_end();

    } else if (validate_flag) {
        if (argc != 1)
            usage();
        radio_validate_config(argv[0]);
    } else {
        if (argc != 1)
            usage();

        // Print configuration from image file.
        radio_read_image(argv[0]);
        if (! json_mode) {
            radio_print_config(stdout, !isatty(1));
        } else {
            // The config text is the result: one string in the event, so
            // the stream stays one object per line.
            char *text = 0;
            size_t len = 0;
            FILE *mem = open_memstream(&text, &len);

            if (! mem)
                die(EXIT_IO, "Out of memory.");
            radio_print_config(mem, 1);
            fclose(mem);
            radio_privacy_warnings();
            ev_begin("result");
            ev_str("command", "print");
            ev_bool("ok", 1);
            image_fields(0);
            ev_str("conf", text);
            ev_end();
            free(text);
        }
    }
    return 0;
}
