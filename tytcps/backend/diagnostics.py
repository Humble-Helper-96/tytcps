# SPDX-License-Identifier: GPL-3.0-or-later
"""Save diagnostics: one .zip a user can attach to a bug report.

Everything in it is text the caller gathers: versions, the USB checks, the
radio last identified, the end of the log, any crash traces, the open
codeplug's settings and the roster and ledger. Here it is made safe to send:

- the three codeplug passwords are removed wherever they appear;
- unit blocks and key-set hashes are shortened as the app shows them
  (1a2b…9f0e);
- every file is scanned, before and after that, for the keys of every key
  set in the fleet folder, with the check the repository's pre-commit hook
  uses (backend/keyscan.py). Any hit, or a key file that can't be read to
  check against, and nothing is saved.

No key file and no codeplug image ever goes in: a codeplug image holds the
legacy Basic/Enhanced keys in clear.
"""

import io
import os
import re
import zipfile
from pathlib import Path

from . import keyscan

# "Power On Password: 1234" anywhere on a line (config text, or quoted in a
# message), and "Power On Password 1234 -> 5678" (diff text).
PASSWORD_LINE = re.compile(r"((?:Power On|Radio Program|PC Programming) Password\s*:)[^\n'\"]*",
                           re.IGNORECASE)
PASSWORD_DIFF = re.compile(r"((?:Power On|Radio Program|PC Programming) Password)\s+\S+\s+->\s+\S+",
                           re.IGNORECASE)
SHA = re.compile(r"\b([0-9a-fA-F]{4})[0-9a-fA-F]{56}([0-9a-fA-F]{4})\b")
UNIT = re.compile(r"\b([0-9a-fA-F]{4})[0-9a-fA-F]{24}([0-9a-fA-F]{4})\b")


class Refused(Exception):
    """Key material was found; `problems` name where, never the key."""

    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


class Unchecked(Exception):
    """The fleet's key files couldn't be read, so nothing can be shown to be
    free of keys; `names` are the files (or the folder)."""

    def __init__(self, names):
        super().__init__(", ".join(names))
        self.names = names


def strip_passwords(text):
    text = PASSWORD_LINE.sub(r"\1 (removed)", text)
    return PASSWORD_DIFF.sub(r"\1 (removed)", text)


def needles(keys_dir):
    """The scanner's needles for every key in keys_dir; Unchecked if any key
    file can't be read."""
    keys, unreadable = keyscan.keys_for_scan(keys_dir)
    if unreadable:
        raise Unchecked(unreadable)
    return keyscan.needles(keys)


def check_text(name, text, keys_dir):
    """Raise Refused/Unchecked unless text is free of the fleet's keys."""
    problems = keyscan.scan_blob(name, text.encode("utf-8", "replace"), needles(keys_dir),
                                 names=False)
    if problems:
        raise Refused(problems)


def shorten(text):
    """Key-set hashes and unit blocks as the app shows them: 0671…47f5."""
    text = SHA.sub(lambda m: "%s…%s" % (m.group(1), m.group(2)), text)
    return UNIT.sub(lambda m: "%s…%s" % (m.group(1), m.group(2)), text)


def build(members, keys_dir):
    """The zip, as bytes, from {name: text}. Raises Refused if any member
    holds key material from a key set in keys_dir, before or after it is
    shortened; every member loses the three passwords first. Unchecked if
    the key files can't be read."""
    ns = needles(keys_dir)
    out, problems = {}, []
    for name, text in members.items():
        if text is None:
            continue
        text = strip_passwords(text)
        final = shorten(text)
        for data in (text.encode("utf-8", "replace"), final.encode("utf-8", "replace")):
            for p in keyscan.scan_blob(name, data, ns, names=False):
                if p not in problems:
                    problems.append(p)
        out[name] = final
    if problems:
        raise Refused(problems)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in out.items():
            # A hand-edited roster may hold bytes that aren't UTF-8.
            z.writestr("tytcps-diagnostics/" + name, text.encode("utf-8", "backslashreplace"))
    return buf.getvalue()


def save(path, data):
    """Write the zip atomically; an existing file is replaced only whole."""
    path = Path(path)
    tmp = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
