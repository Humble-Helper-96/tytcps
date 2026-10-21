// SPDX-License-Identifier: BSD-3-Clause
/*
 * dmrconfig diff a.img b.img: which records two codeplug images differ in.
 *
 * This is the logic of src/cmp_img.py moved into the tool that knows the
 * layout.  The bytes every config write rewrites (the Last
 * Programmed Date and CPS version, 0x02001-0x0200B) and the bytes the radio
 * changes by itself (0x2F004, 0x2F006) are reported separately, so neither
 * is hidden and neither is counted as a change.  Every other differing byte
 * is attributed to the record that holds it - channel 2 "TAC_2", zone 5,
 * general settings - or reported as outside any known record, which is the
 * signature of a tool rewriting something it should not.
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "radio.h"
#include "util.h"
#include "report.h"

#define DATESTAMP_FIRST 0x02001
#define DATESTAMP_LAST  0x0200b

static int is_volatile(unsigned off)
{
    return off == 0x2f004 || off == 0x2f006;
}

static int is_datestamp(unsigned off)
{
    return off >= DATESTAMP_FIRST && off <= DATESTAMP_LAST;
}

typedef struct {
    unsigned first, last;               // inclusive
} range_t;

typedef struct {
    diff_record_t rec;
    unsigned      rec_start, rec_len;
    unsigned      bytes;
    range_t      *ranges;
    int           nranges, maxranges;
} change_t;

static void add_range(range_t **r, int *n, int *max, unsigned off)
{
    if (*n > 0 && (*r)[*n - 1].last + 1 == off) {
        (*r)[*n - 1].last = off;
        return;
    }
    if (*n == *max) {
        *max = *max ? *max * 2 : 4;
        *r = realloc(*r, *max * sizeof(range_t));
        if (! *r)
            die(EXIT_IO, "Out of memory.");
    }
    (*r)[*n].first = (*r)[*n].last = off;
    (*n)++;
}

static void emit_ranges(const range_t *r, int n)
{
    int i;

    ev_arr("ranges");
    for (i=0; i<n; i++) {
        ev_arr(0);
        ev_int(0, r[i].first);
        ev_int(0, r[i].last);
        ev_arr_end();
    }
    ev_arr_end();
}

static void print_ranges(FILE *out, const range_t *r, int n)
{
    int i;

    for (i=0; i<n && i<4; i++) {
        if (r[i].first == r[i].last)
            fprintf(out, "%s0x%05X", i ? "," : "", r[i].first);
        else
            fprintf(out, "%s0x%05X-0x%05X", i ? "," : "", r[i].first, r[i].last);
    }
    if (n > 4)
        fprintf(out, ",...");
}

static const char *kind_title(const char *kind)
{
    if (! kind)                             return "Outside any record";
    if (strcmp(kind, "channel") == 0)       return "Channel";
    if (strcmp(kind, "zone") == 0)          return "Zone";
    if (strcmp(kind, "scanlist") == 0)      return "Scan list";
    if (strcmp(kind, "grouplist") == 0)     return "Group list";
    if (strcmp(kind, "contact") == 0)       return "Contact";
    if (strcmp(kind, "message") == 0)       return "Message";
    if (strcmp(kind, "general") == 0)       return "General settings";
    if (strcmp(kind, "privacy_legacy") == 0) return "Basic/Enhanced keys";
    if (strcmp(kind, "emergency") == 0)     return "Digit Emergency System";
    if (strcmp(kind, "emsystem") == 0)      return "Emergency system";
    if (strcmp(kind, "dtmfsystem") == 0)    return "DTMF system";
    if (strcmp(kind, "dtmfencode") == 0)    return "DTMF encode";
    if (strcmp(kind, "dtmfdecode") == 0)    return "DTMF decode";
    if (strcmp(kind, "vfo") == 0)           return "VFO";
    return kind;
}

//
// Load an image file into a fresh buffer.  Returns its size; *layout says
// whether it is the MD-UV380 layout this file can attribute.
//
static unsigned char *load(const char *filename, int *size, int *layout)
{
    unsigned char *buf;
    int n;

    radio_read_image(filename);
    n = radio_image_size();
    *layout = (n > 0);
    if (! n) {
        // A layout this fork cannot attribute: compare the file bytes.
        FILE *f = fopen(filename, "rb");
        long len;

        if (! f)
            die(EXIT_IO, "%s: cannot open.", filename);
        fseek(f, 0, SEEK_END);
        len = ftell(f);
        fseek(f, 0, SEEK_SET);
        buf = malloc(len > 0 ? len : 1);
        if (! buf || (len > 0 && fread(buf, 1, len, f) != (size_t) len))
            die(EXIT_IO, "%s: cannot read.", filename);
        fclose(f);
        *size = len;
        return buf;
    }
    buf = malloc(n);
    if (! buf)
        die(EXIT_IO, "Out of memory.");
    memcpy(buf, radio_mem, n);
    *size = n;
    return buf;
}

void image_diff_command(int argc, char **argv)
{
    unsigned char *a, *b;
    int asize, bsize, alayout, blayout, i, nchanges = 0, maxchanges = 0;
    unsigned off, changed = 0, nds = 0, nvol = 0, nunattr = 0;
    unsigned vol_off[2];
    range_t *ds_r = 0, *un_r = 0;
    int ds_n = 0, ds_max = 0, un_n = 0, un_max = 0;
    change_t *ch = 0;
    int last = -1;
    FILE *out = stdout;

    if (argc != 2)
        die(EXIT_USAGE, "Usage: dmrconfig diff [--json] a.img b.img");

    a = load(argv[0], &asize, &alayout);
    b = load(argv[1], &bsize, &blayout);
    if (asize != bsize || alayout != blayout)
        die(EXIT_IMAGE, "%s (%d bytes) and %s (%d bytes) are not the same kind "
            "of codeplug.", argv[0], asize, argv[1], bsize);

    for (off=0; off<(unsigned) asize; off++) {
        diff_record_t rec;
        unsigned rs, rl;

        if (a[off] == b[off])
            continue;
        if (alayout && is_datestamp(off)) {
            nds++;
            add_range(&ds_r, &ds_n, &ds_max, off);
            continue;
        }
        if (alayout && is_volatile(off)) {
            if (nvol < 2)
                vol_off[nvol] = off;
            nvol++;
            continue;
        }
        changed++;
        if (! alayout || ! uv380_diff_record(a, b, off, &rec, &rs, &rl)) {
            nunattr++;
            add_range(&un_r, &un_n, &un_max, off);
            continue;
        }

        // Same record as the previous byte?  Usually yes; otherwise look it
        // up, since a zone lives in two places.
        if (last < 0 || ch[last].rec.kind != rec.kind ||
            ch[last].rec.index != rec.index) {
            last = -1;
            for (i=nchanges-1; i>=0; i--) {
                if (ch[i].rec.kind == rec.kind && ch[i].rec.index == rec.index) {
                    last = i;
                    break;
                }
            }
            if (last < 0) {
                if (nchanges == maxchanges) {
                    maxchanges = maxchanges ? maxchanges * 2 : 16;
                    ch = realloc(ch, maxchanges * sizeof(change_t));
                    if (! ch)
                        die(EXIT_IO, "Out of memory.");
                }
                memset(&ch[nchanges], 0, sizeof(change_t));
                ch[nchanges].rec = rec;
                ch[nchanges].rec_start = rs;
                ch[nchanges].rec_len = rl;
                last = nchanges++;
            }
        }
        ch[last].bytes++;
        add_range(&ch[last].ranges, &ch[last].nranges, &ch[last].maxranges, off);
    }

    //
    // Human report.
    //
    fprintf(out, "%s  %d bytes\n", argv[0], asize);
    fprintf(out, "%s  %d bytes\n", argv[1], bsize);
    if (changed == 0)
        fprintf(out, "No changes outside the bytes that always move.\n");
    else
        fprintf(out, "%u byte%s change%s, in %d record%s%s:\n", changed,
            changed == 1 ? "" : "s", changed == 1 ? "s" : "",
            nchanges, nchanges == 1 ? "" : "s",
            nunattr ? " and outside any record" : "");

    ev_begin("result");
    ev_str("command", "diff");
    ev_bool("ok", 1);
    ev_str("a", argv[0]);
    ev_str("b", argv[1]);
    ev_int("size", asize);
    ev_bool("layout_known", alayout);
    ev_bool("identical", changed == 0);
    ev_int("changed", changed);
    ev_arr("records");
    for (i=0; i<nchanges; i++) {
        char human[1024];

        ev_obj(0);
        ev_str("kind", ch[i].rec.kind);
        if (ch[i].rec.index)
            ev_int("index", ch[i].rec.index);
        ev_str("name", ch[i].rec.name);
        ev_int("bytes", ch[i].bytes);
        emit_ranges(ch[i].ranges, ch[i].nranges);
        uv380_diff_fields(a, b, &ch[i].rec, ch[i].rec_start, ch[i].rec_len,
            human, sizeof(human));
        ev_obj_end();

        fprintf(out, "  %s", kind_title(ch[i].rec.kind));
        if (ch[i].rec.index)
            fprintf(out, " %d", ch[i].rec.index);
        if (ch[i].rec.name[0])
            fprintf(out, " \"%s\"", ch[i].rec.name);
        fprintf(out, "  %u byte%s  ", ch[i].bytes, ch[i].bytes == 1 ? "" : "s");
        print_ranges(out, ch[i].ranges, ch[i].nranges);
        if (human[0])
            fprintf(out, "  %s", human);
        fprintf(out, "\n");
        free(ch[i].ranges);
    }
    ev_arr_end();

    ev_obj("unattributed");
    ev_int("bytes", nunattr);
    emit_ranges(un_r, un_n);
    ev_obj_end();
    if (nunattr) {
        fprintf(out, "  Outside any record  %u byte%s  ", nunattr,
            nunattr == 1 ? "" : "s");
        print_ranges(out, un_r, un_n);
        fprintf(out, "\n");
    }

    ev_obj("datestamp");
    ev_int("bytes", nds);
    emit_ranges(ds_r, ds_n);
    ev_obj_end();
    ev_obj("volatile");
    ev_int("bytes", nvol);
    ev_arr("offsets");
    for (i=0; i<(int) nvol && i<2; i++)
        ev_int(0, vol_off[i]);
    ev_arr_end();
    ev_obj_end();
    ev_end();

    if (alayout) {
        fprintf(out, "Always changes: %u byte%s at 0x%05X-0x%05X (Last "
            "Programmed Date and CPS version)\n", nds, nds == 1 ? "" : "s",
            DATESTAMP_FIRST, DATESTAMP_LAST);
        fprintf(out, "Volatile: %u byte%s at 0x2F004/0x2F006 (the radio "
            "changes these by itself)\n", nvol, nvol == 1 ? "" : "s");
    }
    fprintf(out, "VERDICT: %s\n", changed == 0 ?
        "identical outside the known-moving bytes" :
        nunattr ? "DIFFERS, including bytes outside any record - investigate" :
        "differs in the records listed");

    free(ch);
    free(ds_r);
    free(un_r);
    free(a);
    free(b);
}
