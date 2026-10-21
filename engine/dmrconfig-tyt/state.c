// SPDX-License-Identifier: BSD-3-Clause
/*
 * The fleet folder: key-set ledger, radio roster and pre-write images.
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
#include <dirent.h>
#include <sys/stat.h>
#include <sys/file.h>
#include "state.h"
#include "report.h"
#include "util.h"

#define ROSTER_NAME     "radios.tsv"
#define ROSTER_LOCK     "radios.tsv.lock"
#define LEDGER_NAME     "ledger.tsv"
#define PREWRITE_DIR    "prewrite"

const char *state_dir(void)
{
    static char dir[1024];
    const char *d = getenv("TYT_STATE_DIR");

    if (d && *d)
        return d;
    if (dir[0])
        return dir;

    d = getenv("XDG_DATA_HOME");
    if (d && *d == '/') {
        snprintf(dir, sizeof(dir), "%s/tytcps", d);
    } else {
        const char *home = getenv("HOME");

        snprintf(dir, sizeof(dir), "%s/.local/share/tytcps",
            (home && *home) ? home : ".");
    }
    return dir;
}

void state_path(char *buf, int size, const char *name)
{
    snprintf(buf, size, "%s/%s", state_dir(), name);
}

//
// mkdir -p, with the last component 0700 and any parents 0755 as usual.
//
int state_dir_ensure(void)
{
    char path[1024], *p;
    struct stat st;

    snprintf(path, sizeof(path), "%s", state_dir());
    if (stat(path, &st) == 0) {
        if (S_ISDIR(st.st_mode))
            return 0;
        errno = ENOTDIR;
        return -1;
    }
    for (p = path + 1; *p; p++) {
        if (*p != '/')
            continue;
        *p = 0;
        if (mkdir(path, 0755) < 0 && errno != EEXIST)
            return -1;
        *p = '/';
    }
    if (mkdir(path, 0700) < 0 && errno != EEXIST)
        return -1;
    return 0;
}

void iso_now(char *buf, int size)
{
    time_t t = time(0);
    struct tm *tm = localtime(&t);

    if (! tm || ! strftime(buf, size, "%Y-%m-%dT%H:%M:%S%z", tm))
        snprintf(buf, size, "%ld", (long) t);
}

//
// -------------------------------------------------------------------------
// SHA-256, so the ledger can record which key set a radio holds.
// Public domain implementation, FIPS 180-4.
// -------------------------------------------------------------------------
//
typedef struct {
    uint32_t state[8];
    uint64_t nbits;
} sha256_t;

static const uint32_t K256[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,
    0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
    0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,
    0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,
    0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,
    0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

#define ROR(x,n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha256_block(sha256_t *c, const uint8_t *p)
{
    uint32_t w[64], a, b, d, e, f, g, h, t1, t2, cc;
    int i;

    for (i=0; i<16; i++)
        w[i] = ((uint32_t) p[i*4] << 24) | (p[i*4+1] << 16) |
               (p[i*4+2] << 8) | p[i*4+3];
    for (; i<64; i++) {
        uint32_t s0 = ROR(w[i-15],7) ^ ROR(w[i-15],18) ^ (w[i-15] >> 3);
        uint32_t s1 = ROR(w[i-2],17) ^ ROR(w[i-2],19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    a = c->state[0]; b = c->state[1]; cc = c->state[2]; d = c->state[3];
    e = c->state[4]; f = c->state[5]; g  = c->state[6]; h = c->state[7];
    for (i=0; i<64; i++) {
        t1 = h + (ROR(e,6) ^ ROR(e,11) ^ ROR(e,25)) + ((e & f) ^ (~e & g))
             + K256[i] + w[i];
        t2 = (ROR(a,2) ^ ROR(a,13) ^ ROR(a,22))
             + ((a & b) ^ (a & cc) ^ (b & cc));
        h = g; g = f; f = e; e = d + t1;
        d = cc; cc = b; b = a; a = t1 + t2;
    }
    c->state[0] += a; c->state[1] += b; c->state[2] += cc; c->state[3] += d;
    c->state[4] += e; c->state[5] += f; c->state[6] += g;  c->state[7] += h;
}

void sha256_hex(const unsigned char *data, int len, char out[65])
{
    sha256_t c;
    uint8_t tail[128];
    int i, n, pad;

    c.state[0] = 0x6a09e667; c.state[1] = 0xbb67ae85;
    c.state[2] = 0x3c6ef372; c.state[3] = 0xa54ff53a;
    c.state[4] = 0x510e527f; c.state[5] = 0x9b05688c;
    c.state[6] = 0x1f83d9ab; c.state[7] = 0x5be0cd19;
    c.nbits = (uint64_t) len * 8;

    for (n = 0; n + 64 <= len; n += 64)
        sha256_block(&c, &data[n]);

    // Final block(s): remainder, 0x80, zero pad, 64-bit big-endian length.
    memset(tail, 0, sizeof(tail));
    memcpy(tail, &data[n], len - n);
    tail[len - n] = 0x80;
    pad = (len - n < 56) ? 64 : 128;
    for (i=0; i<8; i++)
        tail[pad - 1 - i] = (uint8_t) (c.nbits >> (i * 8));
    sha256_block(&c, tail);
    if (pad == 128)
        sha256_block(&c, tail + 64);

    for (i=0; i<8; i++)
        sprintf(out + i*8, "%08x", c.state[i]);
    out[64] = 0;
}

//
// -------------------------------------------------------------------------
// The roster.
// -------------------------------------------------------------------------
//

//
// Split a TSV line in place into at most nf fields; the last field keeps
// any remaining tabs.  Returns the count.
//
static int split_tsv(char *line, char **f, int nf)
{
    int n = 0;
    char *p = line;

    while (n < nf) {
        f[n++] = p;
        if (n == nf)
            break;
        p = strchr(p, '\t');
        if (! p)
            break;
        *p++ = 0;
    }
    return n;
}

static void chomp(char *s)
{
    int n = strlen(s);

    while (n > 0 && (s[n-1] == '\n' || s[n-1] == '\r'))
        s[--n] = 0;
}

//
// Copy a field for display, cutting at a UTF-8 character boundary.
//
static void copy_field(char *dst, int size, const char *src)
{
    int n = strlen(src);

    if (n >= size) {
        n = size - 1;
        while (n > 0 && ((unsigned char) src[n] & 0xc0) == 0x80)
            n--;
    }
    memcpy(dst, src, n);
    dst[n] = 0;
}

static void entry_defaults(roster_entry_t *e, const char *a207)
{
    copy_field(e->a207, sizeof(e->a207), a207 ? a207 : "");
    strcpy(e->radio_id, "-");
    strcpy(e->label, "-");
    strcpy(e->last_seen, "-");
    strcpy(e->last_write, "-");
    strcpy(e->flags, "-");
}

int roster_lookup(const char *a207, roster_entry_t *e)
{
    char path[1024], *line = 0;
    size_t cap = 0;
    FILE *fp;
    int found = 0;

    entry_defaults(e, a207);
    if (! a207 || ! *a207)
        return 0;
    state_path(path, sizeof(path), ROSTER_NAME);
    fp = fopen(path, "r");
    if (! fp)
        return 0;
    while (getline(&line, &cap, fp) > 0) {
        char *f[6];
        int n;

        chomp(line);
        if (line[0] == '#' || line[0] == 0)
            continue;
        n = split_tsv(line, f, 6);
        if (strcasecmp(f[0], a207) != 0)
            continue;
        if (n > 1 && *f[1]) copy_field(e->radio_id, sizeof(e->radio_id), f[1]);
        if (n > 2 && *f[2]) copy_field(e->label, sizeof(e->label), f[2]);
        if (n > 3 && *f[3]) copy_field(e->last_seen, sizeof(e->last_seen), f[3]);
        if (n > 4 && *f[4]) copy_field(e->last_write, sizeof(e->last_write), f[4]);
        if (n > 5 && *f[5]) copy_field(e->flags, sizeof(e->flags), f[5]);
        found = 1;
        break;
    }
    free(line);
    fclose(fp);
    return found;
}

//
// Does the fleet folder exist?  The fork creates it only for the ledger;
// for the roster and pre-write images a missing folder means "no fleet
// folder yet", which is TYTcps's first-run dialog's job to create.
//
static int state_dir_exists(void)
{
    struct stat st;

    return stat(state_dir(), &st) == 0 && S_ISDIR(st.st_mode);
}

int roster_seen(const char *a207, const char *radio_id, int wrote_codeplug)
{
    char path[1024], tmp[1100], lockpath[1024], now[40];
    char *line = 0;
    size_t cap = 0;
    FILE *in, *out;
    int lockfd, found = 0, fd;

    if (! a207 || ! *a207)
        return -1;
    if (! state_dir_exists()) {
        fprintf(stderr, "Roster: no fleet folder at %s, not recorded.\n",
            state_dir());
        return -1;
    }
    state_path(path, sizeof(path), ROSTER_NAME);
    state_path(lockpath, sizeof(lockpath), ROSTER_LOCK);
    snprintf(tmp, sizeof(tmp), "%s.tmp.%d", path, (int) getpid());
    iso_now(now, sizeof(now));

    // One writer at a time.  TYTcps takes the same lock to edit a label.
    lockfd = open(lockpath, O_RDWR | O_CREAT, 0600);
    if (lockfd >= 0)
        flock(lockfd, LOCK_EX);

    // A roster that exists but cannot be read is left alone: replacing it
    // would lose every other unit and label.
    in = fopen(path, "r");
    if (! in && errno != ENOENT) {
        report_warning("roster_failed", "Cannot read %s: %s. The radio roster "
            "was not updated.", path, strerror(errno));
        if (lockfd >= 0)
            close(lockfd);
        return -1;
    }

    fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0600);
    out = (fd < 0) ? 0 : fdopen(fd, "w");
    if (! out) {
        report_warning("roster_failed", "Cannot write %s: %s. The radio "
            "roster was not updated.", tmp, strerror(errno));
        if (in)
            fclose(in);
        if (lockfd >= 0)
            close(lockfd);
        return -1;
    }

    if (! in) {
        fprintf(out, "# TYTcps radio roster. One line per radio, keyed on its "
            "a2 07 unit block.\n");
        fprintf(out, "# radio_id, last_seen and last_write are filled in by "
            "dmrconfig-tyt on every\n# identify, read, codeplug write and key "
            "write. label and flags are yours.\n");
        fprintf(out, "#a207\tradio_id\tlabel\tlast_seen\tlast_write\tflags\n");
    } else {
        while (getline(&line, &cap, in) > 0) {
            char *f[6];
            int n, k;

            chomp(line);
            if (line[0] == '#' || line[0] == 0 || found) {
                fprintf(out, "%s\n", line);
                continue;
            }
            {
                // Compare the first field without cutting the line up.
                size_t klen = strcspn(line, "\t");

                if (klen != strlen(a207) || strncasecmp(line, a207, klen) != 0) {
                    fprintf(out, "%s\n", line);
                    continue;
                }
            }
            // This unit: rewrite radio_id, last_seen and last_write, and
            // carry label, flags and anything after them through verbatim.
            n = split_tsv(line, f, 6);
            fprintf(out, "%s\t%s\t%s\t%s\t%s", f[0],
                radio_id ? radio_id : (n > 1 && *f[1] ? f[1] : "-"),
                n > 2 && *f[2] ? f[2] : "-", now,
                wrote_codeplug ? now : (n > 4 && *f[4] ? f[4] : "-"));
            for (k=5; k<n; k++)
                fprintf(out, "\t%s", f[k]);
            if (n <= 5)
                fprintf(out, "\t-");
            fprintf(out, "\n");
            found = 1;
        }
        free(line);
        if (ferror(in)) {
            // A read that stopped part-way is not the end of the roster.
            report_warning("roster_failed", "Error reading %s. The radio "
                "roster was not updated.", path);
            fclose(in);
            fclose(out);
            unlink(tmp);
            if (lockfd >= 0)
                close(lockfd);
            return -1;
        }
        fclose(in);
    }
    if (! found)
        fprintf(out, "%s\t%s\t-\t%s\t%s\t-\n", a207, radio_id ? radio_id : "-",
            now, wrote_codeplug ? now : "-");
    if (fflush(out) != 0 || fsync(fileno(out)) != 0 || fclose(out) != 0 ||
        rename(tmp, path) < 0) {
        report_warning("roster_failed", "Cannot update %s: %s. The radio "
            "roster was not updated.", path, strerror(errno));
        unlink(tmp);
        if (lockfd >= 0)
            close(lockfd);
        return -1;
    }
    if (lockfd >= 0)
        close(lockfd);
    fprintf(stderr, "Roster: %s %s\n", path, found ? "updated" : "new unit added");
    return 0;
}

//
// -------------------------------------------------------------------------
// The ledger.
// -------------------------------------------------------------------------
//
#define LEDGER_HEADER "#when\ta207\tserial\tdmr_id\tlabel\tdec_sha256" \
                      "\tdec_file\ttool\tnote"

//
// Everything ledger_append() will need, tried now: open read-write for
// append, lock, stat, read the end.
//
int ledger_preflight(char *path, int size)
{
    struct stat st;
    char last;
    int fd, err;

    state_path(path, size, LEDGER_NAME);
    if (state_dir_ensure() < 0)
        return -1;
    fd = open(path, O_RDWR | O_APPEND | O_CREAT, 0600);
    if (fd < 0)
        return -1;
    if (flock(fd, LOCK_EX) < 0 || fstat(fd, &st) < 0 ||
        (st.st_size > 0 && pread(fd, &last, 1, st.st_size - 1) != 1)) {
        err = errno ? errno : EIO;
        close(fd);
        errno = err;
        return -1;
    }
    close(fd);
    return 0;
}

//
// Write all of buf, or fail.
//
static int write_all(int fd, const char *buf, size_t len)
{
    while (len > 0) {
        ssize_t n = write(fd, buf, len);

        if (n < 0)
            return -1;
        buf += n;
        len -= n;
    }
    return 0;
}

//
// What the existing ledger needs before a new line: a newline if the last
// line is unterminated, and the nine-column header if the last header line
// is the older eight-column one.  Lines are only ever appended, so the
// header is added as a fresh comment line rather than rewritten.
//
static void ledger_prefix(int fd, off_t size, char *prefix, int psize)
{
    char *buf, *p, *lasthdr = 0;
    off_t start = size > 65536 ? size - 65536 : 0;
    ssize_t n;

    prefix[0] = 0;
    if (size == 0)
        return;
    buf = malloc(size - start + 1);
    if (! buf)
        return;
    n = pread(fd, buf, size - start, start);
    if (n <= 0) {
        free(buf);
        return;
    }
    buf[n] = 0;
    if (buf[n-1] != '\n')
        strcat(prefix, "\n");
    for (p = buf; (p = strstr(p, "#when\t")) != 0; p++)
        if (p == buf || p[-1] == '\n')
            lasthdr = p;
    if (lasthdr) {
        char *eol = strchr(lasthdr, '\n');
        size_t len = eol ? (size_t) (eol - lasthdr) : strlen(lasthdr);

        if (len != strlen(LEDGER_HEADER) ||
            strncmp(lasthdr, LEDGER_HEADER, len) != 0)
            snprintf(prefix + strlen(prefix), psize - strlen(prefix),
                "# From here on, lines have a ninth column, note.\n%s\n",
                LEDGER_HEADER);
    }
    free(buf);
}

int ledger_append(const char *a207, const char *serial, const char *dmrid,
    const char *label, const char *sha, const char *decfile,
    const char *tool, const char *note, char *line, int linesize)
{
    char path[1024], stamp[64], prefix[512], *text;
    struct stat st;
    int fd, err;
    size_t len;

    iso_now(stamp, sizeof(stamp));
    if (snprintf(line, linesize, "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s",
            stamp, a207, (serial && *serial) ? serial : "-",
            (dmrid && *dmrid) ? dmrid : "-", (label && *label) ? label : "-",
            sha, decfile, tool, (note && *note) ? note : "-") >= linesize) {
        // Never record a cut-down line.
        errno = EOVERFLOW;
        return -1;
    }

    if (state_dir_ensure() < 0)
        return -1;
    state_path(path, sizeof(path), LEDGER_NAME);

    fd = open(path, O_RDWR | O_APPEND | O_CREAT, 0600);
    if (fd < 0)
        return -1;
    if (flock(fd, LOCK_EX) < 0 || fstat(fd, &st) < 0) {
        err = errno;
        close(fd);
        errno = err;
        return -1;
    }
    if (st.st_size == 0)
        snprintf(prefix, sizeof(prefix),
            "# TYT MD-UV390 Plus key-table ledger.\n"
            "# Keys cannot be read back from the radio. This file is the only "
            "record of\n# which key set each radio holds.\n%s\n", LEDGER_HEADER);
    else
        ledger_prefix(fd, st.st_size, prefix, sizeof(prefix));

    // One write of the whole addition.  If it fails part-way, cut the file
    // back to where it was, so a later line is never glued onto half of this
    // one.
    len = strlen(prefix) + strlen(line) + 1;
    text = malloc(len + 1);
    if (! text) {
        close(fd);
        errno = ENOMEM;
        return -1;
    }
    snprintf(text, len + 1, "%s%s\n", prefix, line);
    if (write_all(fd, text, len) < 0 || fsync(fd) < 0) {
        err = errno;
        if (ftruncate(fd, st.st_size) < 0)
            fprintf(stderr, "Could not cut %s back to %ld bytes: %s\n", path,
                (long) st.st_size, strerror(errno));
        free(text);
        close(fd);
        errno = err;
        return -1;
    }
    free(text);
    if (close(fd) < 0)
        return -1;
    fprintf(stderr, "Ledger: %s\n", path);
    return 0;
}

//
// -------------------------------------------------------------------------
// Pre-write images.
// -------------------------------------------------------------------------
//
static int cmp_names(const void *a, const void *b)
{
    return strcmp(*(char* const*) a, *(char* const*) b);
}

//
// The images kept for a unit, oldest first.  The names sort by time.
// Returns the count; the caller frees the names.
//
static int prewrite_list(const char *dir, const char *a207, char **names,
    int max)
{
    DIR *d = opendir(dir);
    struct dirent *de;
    int n = 0, plen = strlen(a207);

    if (! d)
        return 0;
    while ((de = readdir(d)) != 0 && n < max) {
        int len = strlen(de->d_name);

        if (strncasecmp(de->d_name, a207, plen) != 0 || de->d_name[plen] != '-')
            continue;
        if (len < 4 || strcmp(de->d_name + len - 4, ".img") != 0)
            continue;
        names[n++] = strdup(de->d_name);
    }
    closedir(d);
    qsort(names, n, sizeof(names[0]), cmp_names);
    return n;
}

//
// Is this file exactly these bytes?
//
static int same_image(const char *path, const unsigned char *img, int len)
{
    FILE *f = fopen(path, "rb");
    unsigned char buf[8192];
    int pos = 0, same = 1;
    size_t n;

    if (! f)
        return 0;
    while (same && (n = fread(buf, 1, sizeof(buf), f)) > 0) {
        if (pos + (int) n > len || memcmp(buf, img + pos, n) != 0)
            same = 0;
        pos += n;
    }
    fclose(f);
    return same && pos == len;
}

int prewrite_save(const char *a207, const unsigned char *img, int len,
    char *path, int size, int *reused)
{
    char dir[1100], stamp[32], *names[512];
    time_t t = time(0);
    struct tm *tm = gmtime(&t);
    int fd = -1, i, n;
    const char *unit = a207;

    *reused = 0;
    if (! state_dir_exists()) {
        errno = ENOENT;
        return -1;
    }
    // Without the unit there is no telling whose image it is, and keeping
    // the newest five of "unknown" could retire another radio's.
    if (! unit || ! *unit) {
        errno = ENODEV;
        return -1;
    }
    snprintf(dir, sizeof(dir), "%s/%s", state_dir(), PREWRITE_DIR);
    if (mkdir(dir, 0700) < 0 && errno != EEXIST)
        return -1;

    // The radio still holds what the newest kept image holds (say, a second
    // write of the same codeplug): keep that one rather than a copy of it,
    // so repeats do not push older states out.
    n = prewrite_list(dir, unit, names, 512);
    if (n > 0) {
        snprintf(path, size, "%s/%s", dir, names[n-1]);
        if (same_image(path, img, len))
            *reused = 1;
    }
    for (i=0; i<n; i++)
        free(names[i]);
    if (*reused)
        return 0;

    // UTC, so the names sort by time across a DST change, and always a
    // two-digit sequence, so two saves in one second sort in order too.
    if (! tm || ! strftime(stamp, sizeof(stamp), "%Y%m%dT%H%M%SZ", tm))
        snprintf(stamp, sizeof(stamp), "%ld", (long) t);
    for (i=1; i<100; i++) {
        snprintf(path, size, "%s/%s-%s-%02d.img", dir, unit, stamp, i);
        fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
        if (fd >= 0 || errno != EEXIST)
            break;
    }
    if (fd < 0)
        return -1;
    if (write_all(fd, (const char*) img, len) < 0 || fsync(fd) != 0) {
        int err = errno;

        close(fd);
        unlink(path);
        errno = err ? err : EIO;
        return -1;
    }
    close(fd);

    // Keep the newest PREWRITE_KEEP of this unit.
    n = prewrite_list(dir, unit, names, 512);
    for (i=0; i<n; i++) {
        if (i < n - PREWRITE_KEEP) {
            char old[1400];

            snprintf(old, sizeof(old), "%s/%s", dir, names[i]);
            if (unlink(old) == 0)
                fprintf(stderr, "Pre-write image retired: %s\n", old);
        }
        free(names[i]);
    }
    return 0;
}
