// SPDX-License-Identifier: BSD-3-Clause
/*
 * Machine-readable reporting for the tyt-plus fork.
 *
 * With --json, stdout carries exactly one JSON object per line and nothing
 * else.  Human text stays on stderr, unchanged, for the log.  A program
 * driving this tool (TYTcps) reads the events and the exit code and never
 * parses prose.
 *
 * Copyright (C) 2026 TYTcps contributors.  Same BSD-style terms as the rest
 * of dmrconfig.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <unistd.h>
#include "report.h"

int json_mode;
int radio_state = RADIO_UNCHANGED;

static FILE *json_out;
static const char *cur_phase = "start";
static void (*cleanup_fn)(void);
static int failing;
static int exiting_code;

//
// One nesting level per open object or array: whether a comma is due.
//
#define MAXDEPTH 16
static int depth;
static int need_comma[MAXDEPTH];

static const struct {
    int         code;
    const char *name;
} CODE_TAB[] = {
    { EXIT_OK,               "ok"                },
    { EXIT_IO,               "io_error"          },
    { EXIT_USAGE,            "usage"             },
    { EXIT_NO_RADIO,         "no_radio"          },
    { EXIT_NO_PERMISSION,    "no_permission"     },
    { EXIT_BUSY,             "busy"              },
    { EXIT_UNSUPPORTED,      "unsupported_model" },
    { EXIT_READS_DISAGREE,   "reads_disagree"    },
    { EXIT_WRITE_UNVERIFIED, "write_unverified"  },
    { EXIT_TRANSFER,         "transfer_failed"   },
    { EXIT_KEYFILE,          "keyfile_invalid"   },
    { EXIT_CONF,             "conf_invalid"      },
    { EXIT_KEY_SLOT_EMPTY,   "key_slot_empty"    },
    { EXIT_LEDGER,           "ledger_failed"     },
    { EXIT_UNIT_UNREADABLE,  "unit_unreadable"   },
    { EXIT_MULTIPLE_RADIOS,  "multiple_radios"   },
    { EXIT_IMAGE,            "image_invalid"     },
    { EXIT_UNIT_MISMATCH,    "unit_mismatch"     },
    { EXIT_KEYS_REFUSED,     "keys_refused"      },
    { EXIT_UNCLASSIFIED,     "failed"            },
};

static const char *RADIO_STATE_NAME[] = {
    "unchanged",
    "codeplug_incomplete",
    "codeplug_differs",
    "keys_unknown",
    "keys_written",
    "codeplug_written",
    "codeplug_unverified",
    "contacts_incomplete",
    "contacts_written",
};

const char *exit_code_name(int code)
{
    unsigned i;

    for (i=0; i<sizeof(CODE_TAB)/sizeof(CODE_TAB[0]); i++)
        if (CODE_TAB[i].code == code)
            return CODE_TAB[i].name;
    return "failed";
}

void report_init(int json)
{
    int fd;

    json_mode = json;
    if (! json)
        return;

    // Keep the real stdout for events, and point fd 1 at stderr, so that
    // every printf() in the upstream code - traces, tables, banners - lands
    // in the log and can never corrupt the event stream.
    fflush(stdout);
    fd = dup(1);
    if (fd < 0 || ! (json_out = fdopen(fd, "w"))) {
        perror("dup stdout");
        exit(EXIT_IO);
    }
    dup2(2, 1);
    setvbuf(json_out, 0, _IOLBF, 0);
}

void report_set_cleanup(void (*fn)(void))
{
    cleanup_fn = fn;
}

//
// JSON string body.  Names come from the radio as UTF-16 converted to UTF-8,
// so they are normally valid; anything that is not valid UTF-8 is replaced by
// U+FFFD rather than passed through, since one bad byte would make the whole
// line unparseable.
//
static void put_string(const char *s)
{
    const unsigned char *p = (const unsigned char*) s;

    fputc('"', json_out);
    while (*p) {
        unsigned c = *p;

        if (c == '"' || c == '\\') {
            fputc('\\', json_out);
            fputc(c, json_out);
            p++;
        } else if (c == '\n') {
            fputs("\\n", json_out);
            p++;
        } else if (c == '\t') {
            fputs("\\t", json_out);
            p++;
        } else if (c == '\r') {
            fputs("\\r", json_out);
            p++;
        } else if (c < 0x20 || c == 0x7f) {
            fprintf(json_out, "\\u%04x", c);
            p++;
        } else if (c < 0x80) {
            fputc(c, json_out);
            p++;
        } else {
            // Strict UTF-8 (RFC 3629): no overlongs, no surrogates (the
            // CESU-8 that per-unit UTF-16 conversion produces), nothing
            // past U+10FFFF.  Python's json module refuses all three.
            int n = (c >= 0xf0 && c < 0xf5) ? 3 :
                    (c >= 0xe0) && (c < 0xf0) ? 2 :
                    (c >= 0xc2) && (c < 0xe0) ? 1 : -1;
            int i, ok = (n > 0);

            for (i=1; ok && i<=n; i++)
                if ((p[i] & 0xc0) != 0x80)
                    ok = 0;
            if (ok && c == 0xe0 && p[1] < 0xa0) ok = 0;    // overlong
            if (ok && c == 0xed && p[1] >= 0xa0) ok = 0;   // surrogate
            if (ok && c == 0xf0 && p[1] < 0x90) ok = 0;    // overlong
            if (ok && c == 0xf4 && p[1] >= 0x90) ok = 0;   // > U+10FFFF
            if (ok) {
                fwrite(p, 1, n + 1, json_out);
                p += n + 1;
            } else {
                fputs("\\ufffd", json_out);
                p++;
            }
        }
    }
    fputc('"', json_out);
}

static void put_key(const char *key)
{
    if (need_comma[depth])
        fputc(',', json_out);
    need_comma[depth] = 1;
    if (key) {
        put_string(key);
        fputc(':', json_out);
    }
}

void ev_begin(const char *event)
{
    if (! json_mode)
        return;
    depth = 0;
    need_comma[0] = 0;
    fputc('{', json_out);
    put_key("event");
    put_string(event);
}

void ev_str(const char *key, const char *value)
{
    if (! json_mode)
        return;
    put_key(key);
    if (value)
        put_string(value);
    else
        fputs("null", json_out);
}

void ev_int(const char *key, long long value)
{
    if (! json_mode)
        return;
    put_key(key);
    fprintf(json_out, "%lld", value);
}

void ev_bool(const char *key, int value)
{
    if (! json_mode)
        return;
    put_key(key);
    fputs(value ? "true" : "false", json_out);
}

void ev_hex(const char *key, const unsigned char *data, int len)
{
    int i;

    if (! json_mode)
        return;
    put_key(key);
    fputc('"', json_out);
    for (i=0; i<len; i++)
        fprintf(json_out, "%02x", data[i]);
    fputc('"', json_out);
}

void ev_obj(const char *key)
{
    if (! json_mode)
        return;
    put_key(key);
    fputc('{', json_out);
    if (depth < MAXDEPTH - 1)
        depth++;
    need_comma[depth] = 0;
}

void ev_obj_end(void)
{
    if (! json_mode)
        return;
    fputc('}', json_out);
    if (depth > 0)
        depth--;
}

void ev_arr(const char *key)
{
    if (! json_mode)
        return;
    put_key(key);
    fputc('[', json_out);
    if (depth < MAXDEPTH - 1)
        depth++;
    need_comma[depth] = 0;
}

void ev_arr_end(void)
{
    if (! json_mode)
        return;
    fputc(']', json_out);
    if (depth > 0)
        depth--;
}

void ev_end(void)
{
    if (! json_mode)
        return;
    // Close anything a caller left open, so a line is always valid JSON.
    while (depth > 0) {
        fputc('}', json_out);
        depth--;
    }
    fputs("}\n", json_out);
    fflush(json_out);
}

const char *report_current_phase(void)
{
    return cur_phase;
}

void report_phase(const char *phase)
{
    cur_phase = phase;
    ev_begin("phase");
    ev_str("phase", phase);
    ev_end();
}

void report_progress(int done, int total)
{
    ev_begin("progress");
    ev_str("phase", cur_phase);
    ev_int("done", done);
    ev_int("total", total);
    ev_end();
}

//
// Progress for a transfer of 'total' units.  The '#' marks keep their
// upstream spacing (one per 32 codeplug blocks); events go out at roughly
// every 2%, and always at the end.
//
void report_tick(int done, int total)
{
    static int last_pct = -1;
    int pct;

    if (total <= 0)
        return;
    pct = done * 50 / total;
    if (done == 1 || pct != last_pct || done == total) {
        last_pct = pct;
        report_progress(done, total);
    }
}

static void vwarning(const char *code, const char *fmt, va_list ap)
{
    char msg[1024];

    vsnprintf(msg, sizeof(msg), fmt, ap);
    fprintf(stderr, "%s\n", msg);
    ev_begin("warning");
    ev_str("code", code);
    ev_str("message", msg);
    ev_end();
}

void report_warning(const char *code, const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vwarning(code, fmt, ap);
    va_end(ap);
}

static int fail_code;

#define MAXCTX 4
static const char *ctx_key[MAXCTX];
static char ctx_val[MAXCTX][2100];     // a key file name may be up to 2048
static int nctx;

void report_context(const char *key, const char *value)
{
    if (nctx < MAXCTX) {
        ctx_key[nctx] = key;
        snprintf(ctx_val[nctx], sizeof(ctx_val[nctx]), "%s", value ? value : "");
        nctx++;
    }
}

void fail_begin(int code)
{
    int i;

    fail_code = code;
    ev_begin("error");
    ev_str("code", exit_code_name(code));
    ev_int("exit", code);
    ev_str("phase", cur_phase);
    ev_str("radio", RADIO_STATE_NAME[radio_state]);
    for (i=0; i<nctx; i++)
        ev_str(ctx_key[i], ctx_val[i]);
}

static void vend_message(const char *fmt, va_list ap)
{
    char msg[2048];

    vsnprintf(msg, sizeof(msg), fmt, ap);
    fprintf(stderr, "%s\n", msg);
    ev_str("message", msg);
    ev_end();
}

void error_event_end(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vend_message(fmt, ap);
    va_end(ap);
}

void fail_exit(int code)
{
    // A failure inside the cleanup itself (say, the reboot command failing
    // on a radio that just dropped off the bus) must not recurse.
    if (! failing) {
        failing = 1;
        exiting_code = code;
        if (cleanup_fn)
            cleanup_fn();
    }
    fflush(stdout);
    fflush(stderr);
    exit(code);
}

void fail_end(const char *fmt, ...)
{
    va_list ap;
    int code = fail_code;

    va_start(ap, fmt);
    vend_message(fmt, ap);
    va_end(ap);
    fail_exit(code);
}

void fail_end_json(const char *msg)
{
    int code = fail_code;

    ev_str("message", msg);
    ev_end();
    fail_exit(code);
}

void die(int code, const char *fmt, ...)
{
    va_list ap;

    if (failing) {
        // Already on the way out, and this failed inside the cleanup: log
        // it, but leave with the first failure's code, which is the one the
        // error event reported.
        va_start(ap, fmt);
        vfprintf(stderr, fmt, ap);
        fputc('\n', stderr);
        va_end(ap);
        fflush(stderr);
        exit(exiting_code);
    }
    fail_begin(code);
    va_start(ap, fmt);
    vend_message(fmt, ap);
    va_end(ap);
    fail_exit(code);
}
