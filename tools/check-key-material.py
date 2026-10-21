#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refuse a commit that carries privacy key material.

The radios' AES/ARC4 keys exist in clear in CPS key files (.dec). Nothing from
a fleet folder may ever enter this repository, so this check looks for every
key held in the key files it can find, in every form a key has been seen in on
this project: raw bytes in file order, raw bytes in CPS grid order (reversed),
and hex in either order with any separators.

Key files are found in:
  - git config tytcps.keyfile (repeatable; a path or a glob), for key files
    kept outside a fleet folder;
  - the fleet folder's keys/*.dec ($TYT_STATE_DIR, else
    $XDG_DATA_HOME/tytcps, else ~/.local/share/tytcps).

It also refuses files that belong in a fleet folder by name or type: .dec key
files, codeplug images, ledgers, rosters and USB captures.

Usage:
  check-key-material.py --staged     the index (pre-commit hook)
  check-key-material.py --all        every tracked file
  check-key-material.py PATH...      files or folders on disk

Never prints a key: only the file it was found in and which key file and slot
it came from.
"""

import glob
import os
import subprocess
import sys

# The check itself lives in the program, which also runs it over every
# diagnostics file before saving one (tytcps/backend/keyscan.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tytcps.backend.keyscan import collect, fleet_folder, needles, scan_blob  # noqa: E402


def key_file_patterns():
    pats = []
    try:
        out = subprocess.run(["git", "config", "--get-all", "tytcps.keyfile"],
                             capture_output=True, text=True).stdout
        pats += [p.strip() for p in out.splitlines() if p.strip()]
    except OSError:
        pass
    pats.append(os.path.join(glob.escape(fleet_folder()), "keys", "*.dec"))
    return pats


def collect_keys():
    return collect(key_file_patterns())


def staged_files():
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "-z",
                          "--diff-filter=ACMR"], capture_output=True, check=True).stdout
    for name in out.split(b"\0"):
        if not name:
            continue
        name = name.decode("utf-8", "replace")
        blob = subprocess.run(["git", "show", ":" + name], capture_output=True).stdout
        yield name, blob


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout
    for name in out.split(b"\0"):
        if not name:
            continue
        name = name.decode("utf-8", "replace")
        try:
            with open(name, "rb") as f:
                yield name, f.read()
        except OSError:
            continue


def disk_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d != ".git"]
                for fn in files:
                    full = os.path.join(root, fn)
                    try:
                        with open(full, "rb") as f:
                            yield full, f.read()
                    except OSError:
                        continue
        else:
            with open(p, "rb") as f:
                yield p, f.read()


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 2
    keys, files = collect_keys()
    ns = needles(keys)
    if argv[0] == "--staged":
        source = staged_files()
    elif argv[0] == "--all":
        source = tracked_files()
    else:
        source = disk_files(argv)
    problems = []
    count = 0
    for name, data in source:
        count += 1
        problems += scan_blob(name, data, ns)
    if not keys:
        print("check-key-material: no key files found to compare against "
              "(set git config tytcps.keyfile); only file names were checked.",
              file=sys.stderr)
    if problems:
        print("check-key-material: REFUSED. Key material or fleet files would enter the repository:",
              file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    print("check-key-material: %d file(s) clean against %d key(s) from %d key file(s)."
          % (count, len(keys), len(files)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
