# SPDX-License-Identifier: GPL-3.0-or-later
"""Find privacy key material in a blob of bytes.

The radios' AES/ARC4 keys exist in clear in CPS key files (.dec). Two things
must never carry them: a commit to this repository (tools/check-key-material.py,
the pre-commit hook) and a diagnostics file a user sends with a bug report
(backend/diagnostics.py). Both use this one check, which looks for every key
held in the given key files, in every form a key has been seen in on this
project: raw bytes in file order, raw bytes in CPS grid order (reversed), and
hex in either order with any separators. Any 8 consecutive bytes of a key
count; an ARC4 key (5 bytes) is looked for whole.

Nothing here ever prints a key: a finding names the file it was found in and
the key file and slot it came from.
"""

import glob
import os
import re

DEC_SIZE = 20480
RECORD = 100
KEY_LEN = {1: 5, 3: 16, 4: 32}

BLOCKED_SUFFIXES = (".dec", ".img", ".pcap", ".pcapng", ".rdt", ".bak")
BLOCKED_NAMES = ("ledger.tsv", "units.tsv", "radios.tsv", "current-keyset")
BLOCKED_DIRS = ("prewrite/",)

WINDOW = 8
NONHEX = re.compile(rb"[^0-9a-f]")


def fleet_folder():
    d = os.environ.get("TYT_STATE_DIR")
    if d:
        return d
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "tytcps")


def keys_from_dec(path):
    """(label, key bytes in file order) for every non-trivial key in a .dec."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if len(data) != DEC_SIZE:
        return []
    found = []
    for slot in range(16):
        rec = data[slot * RECORD:(slot + 1) * RECORD]
        t = int.from_bytes(rec[0:4], "little")
        n = KEY_LEN.get(t)
        if not n:
            continue
        key = rec[0x24:0x24 + n]
        # Unused slots hold all zero or the CPS default 01 00 ... 00.
        if key.count(0) >= n - 1:
            continue
        found.append(("%s slot %d" % (os.path.basename(path), slot + 1), key))
    return found


def collect(patterns):
    """({key: label}, [key files]) from paths or globs."""
    keys = {}
    files = set()
    for pat in patterns:
        for p in glob.glob(os.path.expanduser(str(pat))):
            files.add(os.path.realpath(p))
    for p in sorted(files):
        for label, key in keys_from_dec(p):
            keys.setdefault(key, label)
    return keys, sorted(files)


def keys_in_folder(keys_dir):
    """Every key in the .dec files of a fleet folder's keys/."""
    d = glob.escape(str(keys_dir))           # a folder named "Fleet [A]" is not a pattern
    return collect([os.path.join(d, "*.dec"), os.path.join(d, "*.DEC")])


def keys_for_scan(keys_dir):
    """({key: label}, [names]) for a scan that must prove something: every
    key in keys_dir's .dec files (part-saved ones included), and the key
    files, or the folder, that couldn't be read. With any of those the scan
    can't say a file is clean."""
    keys, unreadable = {}, []
    try:
        names = sorted(os.listdir(str(keys_dir)))
    except FileNotFoundError:
        return keys, unreadable              # no key sets yet: nothing to find
    except OSError:
        return keys, [str(keys_dir)]
    for name in names:
        if not name.lower().endswith(".dec"):
            continue
        path = os.path.join(str(keys_dir), name)
        try:
            with open(path, "rb") as f:
                size = len(f.read())
        except OSError:
            unreadable.append(name)
            continue
        if size != DEC_SIZE:
            unreadable.append(name)
            continue
        for label, key in keys_from_dec(path):
            keys.setdefault(key, label)
    return keys, unreadable


def needles(keys):
    out = []
    for key, label in keys.items():
        w = min(WINDOW, len(key))
        for order, k in (("file order", key), ("grid order", key[::-1])):
            for i in range(len(k) - w + 1):
                part = k[i:i + w]
                out.append(("raw", part, "%s (raw, %s)" % (label, order)))
                out.append(("hex", part.hex().encode(), "%s (hex, %s)" % (label, order)))
    return out


def scan_blob(name, data, keys_needles, names=True):
    """Problems found in one file: key material, and (names=True) a name or
    type that belongs in a fleet folder."""
    problems = []
    low = name.lower()
    base = os.path.basename(low)
    if names and (low.endswith(BLOCKED_SUFFIXES) or base in BLOCKED_NAMES or
                  any(("/" + d) in ("/" + low) for d in BLOCKED_DIRS)):
        problems.append("%s: this kind of file belongs in a fleet folder, never in the repository" % name)
    if not keys_needles:
        return problems
    # Hex is searched with every non-hex character removed, so a key written
    # with spaces, colons, dashes or line breaks between its digits is found.
    stripped = NONHEX.sub(b"", data.lower())
    seen = set()
    for kind, needle, label in keys_needles:
        if label in seen:
            continue
        if needle in (stripped if kind == "hex" else data):
            seen.add(label)
            problems.append("%s: contains key material from %s" % (name, label))
    return problems
