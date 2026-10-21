#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (C) 2026 TYTcps contributors.
"""--expect-unit against a fake radio, and password lines never echoed
.

    python3 tests/test_expect_unit.py ./dmrconfig-fakeusb ./dmrconfig

The first program is the engine linked against tests/fakeusb.c, which plays
one MD-UV390 and logs every request; the second is the normal build, used
only for offline commands (making a key file). No radio is touched.

What must hold: a write meant for one unit never sends anything to another.
A different unit, or one whose a2 07 block can't be read, is refused right
after connecting - no codeplug read, no erase, no write, no key table - and
the radio still gets its restart (91 05).
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile

FAKE, REAL = (os.path.abspath(p) for p in sys.argv[1:3])   # runs happen in temp folders
A = "0badcafe0badcafe0badcafe00001001"      # the fake radio's default unit
B = "0badcafe0badcafe0badcafe0000b002"      # another radio's

tmp = tempfile.mkdtemp(prefix="expect-unit-")
fleet = os.path.join(tmp, "fleet")
os.mkdir(fleet, 0o700)
failures = []


def run(args, prog=FAKE, env=None, stdin=None):
    """(exit, events, log lines) of one engine run in its own folder."""
    log = os.path.join(tmp, "usb.log")
    if os.path.exists(log):
        os.unlink(log)
    work = tempfile.mkdtemp(dir=tmp)
    e = dict(os.environ, TYT_STATE_DIR=fleet, FAKEUSB_LOG=log)
    for k in ("FAKEUSB_A207", "FAKEUSB_FAIL", "FAKEUSB_IMAGE", "FAKEUSB_RADIOS", "FAKEUSB_MODEL"):
        e.pop(k, None)
    e.update(env or {})
    p = subprocess.run([prog, "--json"] + args, cwd=work, env=e, input=stdin,
                       capture_output=True)
    events = [json.loads(l) for l in p.stdout.decode().splitlines() if l.strip()]
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    return p.returncode, events, lines


def error(events):
    errs = [e for e in events if e.get("event") == "error"]
    return errs[-1] if errs else {}


def check(name, cond, detail=""):
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, ("  (%s)" % detail) if detail and not cond else ""))
    if not cond:
        failures.append(name)


def nothing_sent(lines):
    """No codeplug read or write, no erase, no key table."""
    return not any(l.startswith(("READ", "WRITE", "ERASE", "KEYS")) or l == "CMD da 02"
                   for l in lines)


def ledger_lines():
    try:
        return [l for l in open(os.path.join(fleet, "ledger.tsv")) if not l.startswith("#")]
    except OSError:
        return []


# A key file with a test key in slot 1 (made here, never printed).
dec = os.path.join(tmp, "test.dec")
code, _, _ = run(["keys", "new", dec], prog=REAL)
assert code == 0, "keys new failed"
code, _, _ = run(["keys", "set", "--no-backup", dec, "1", "AES256", "-"], prog=REAL,
                 stdin=secrets.token_hex(32).encode())
assert code == 0, "keys set failed"
blank = os.path.join(tmp, "blank.img")
with open(blank, "wb") as f:
    f.write(b"\xff" * 851968)
conf = os.path.join(tmp, "write.conf")
with open(conf, "w") as f:
    f.write("Name: Test\n")

# --- -K -----------------------------------------------------------------------

# Every write below names a fictional unit, which a real radio refuses,
# except one near the end that has no --expect-unit at all. So before going
# on, make sure the program really is the fake build: only the fake writes
# the request log.
if os.path.realpath(FAKE) == os.path.realpath(REAL):
    sys.exit("The first program must be the fake build (dmrconfig-fakeusb), not %s." % REAL)
n0 = len(ledger_lines())
code, ev, log = run(["--expect-unit", A, "-K", dec])
if "OPEN" not in log:
    sys.exit("%s did not write the fake radio's log: not the fake build. Stopped before "
             "anything could reach a real radio." % FAKE)
check("-K to the expected unit is written", code == 0 and log.count("CMD da 02") == 1 and
      sum(l.startswith("KEYS") for l in log) == 20, "exit %d" % code)
check("-K to the expected unit adds a ledger line", len(ledger_lines()) == n0 + 1)

n0 = len(ledger_lines())
code, ev, log = run(["--expect-unit", B, "-K", dec])
e = error(ev)
check("-K to another unit: exit 17 unit_mismatch", code == 17 and e.get("code") == "unit_mismatch",
      "exit %d %s" % (code, e))
check("-K to another unit: names both units", e.get("expected") == B and e.get("a207") == A)
check("-K to another unit: radio unchanged, refused at connect",
      e.get("radio") == "unchanged" and e.get("phase") == "connect")
check("-K to another unit: no key table sent", nothing_sent(log), log)
check("-K to another unit: the radio is restarted", "CMD 91 05" in log)
check("-K to another unit: no ledger line", len(ledger_lines()) == n0)
check("-K to another unit: the unit event shows the radio found",
      any(x.get("event") == "unit" and x.get("a207") == A for x in ev))

# (-K refused an unreadable unit block before --expect-unit existed; kept so
# it stays refused. The new check's own unreadable path is the -w/-c cases.)
for blk in ("zero", "fail"):
    code, ev, log = run(["--expect-unit", A, "-K", dec], env={"FAKEUSB_A207": blk})
    check("-K, unit block %s: exit 14, nothing sent" % blk,
          code == 14 and error(ev).get("radio") == "unchanged" and nothing_sent(log),
          "exit %d" % code)

code, ev, log = run(["--expect-unit", A.upper(), "-K", dec])
check("-K: the unit is compared without regard to case", code == 0, "exit %d" % code)
code, ev, log = run(["--expect-unit=" + A, "-K", dec])
check("-K: --expect-unit=A207 form", code == 0, "exit %d" % code)
code, ev, log = run(["-K", dec], env={"FAKEUSB_A207": B})
check("-K without --expect-unit writes any radio, as before", code == 0, "exit %d" % code)

# --- -w -----------------------------------------------------------------------

code, ev, log = run(["--expect-unit", A, "-w", blank])
res = [x for x in ev if x.get("event") == "result"]
check("-w to the expected unit is written and verified",
      code == 0 and any(l.startswith("ERASE") for l in log) and res and res[-1].get("verified"),
      "exit %d" % code)

pre = set(os.listdir(os.path.join(fleet, "prewrite"))) if os.path.isdir(os.path.join(fleet, "prewrite")) else set()
code, ev, log = run(["--expect-unit", B, "-w", blank])
e = error(ev)
check("-w to another unit: exit 17, radio unchanged",
      code == 17 and e.get("code") == "unit_mismatch" and e.get("radio") == "unchanged",
      "exit %d %s" % (code, e))
check("-w to another unit: nothing read, erased or written", nothing_sent(log), log)
check("-w to another unit: the radio is restarted", "CMD 91 05" in log)
post = set(os.listdir(os.path.join(fleet, "prewrite"))) if os.path.isdir(os.path.join(fleet, "prewrite")) else set()
check("-w to another unit: no pre-write image kept", post == pre)

code, ev, log = run(["-w", blank, "--expect-unit", B])
check("-w: --expect-unit after the file is still checked", code == 17 and nothing_sent(log),
      "exit %d" % code)

code, ev, log = run(["--expect-unit", A, "-w", blank], env={"FAKEUSB_A207": "zero"})
check("-w, unit block unreadable: exit 14, nothing sent", code == 14 and nothing_sent(log),
      "exit %d" % code)

# --- -c to a radio --------------------------------------------------------------

# The expected unit goes on to read the radio: shown by failing that read.
code, ev, log = run(["--expect-unit", A, "-c", conf], env={"FAKEUSB_FAIL": "READ"})
e = error(ev)
check("-c to the expected unit goes on to read the radio",
      code == 9 and e.get("phase") == "read1" and e.get("radio") == "unchanged",
      "exit %d %s" % (code, e))
code, ev, log = run(["--expect-unit", B, "-c", conf])
e = error(ev)
check("-c to another unit: exit 17, radio unchanged",
      code == 17 and e.get("code") == "unit_mismatch" and e.get("radio") == "unchanged",
      "exit %d %s" % (code, e))
check("-c to another unit: nothing read, erased or written", nothing_sent(log), log)
code, ev, log = run(["--expect-unit", A, "-c", conf], env={"FAKEUSB_A207": "fail"})
check("-c, unit block unreadable: exit 14, nothing sent", code == 14 and nothing_sent(log),
      "exit %d" % code)

# --- a radio that refuses the key table (7.2: a non-Plus model might) -----------

n0 = len(ledger_lines())
code, ev, log = run(["--expect-unit", A, "-K", dec], env={"FAKEUSB_FAIL": "KEYCMD"})
e = error(ev)
check("-K refused by the radio: exit 18 keys_refused", code == 18 and e.get("code") == "keys_refused",
      "exit %d %s" % (code, e))
check("-K refused by the radio: radio unchanged, no key block sent",
      e.get("radio") == "unchanged" and not any(l.startswith("KEYS") for l in log), log)
check("-K refused by the radio: no ledger line", len(ledger_lines()) == n0)
check("-K refused by the radio: the radio is restarted", "CMD 91 05" in log)
code, ev, log = run(["--expect-unit", A, "-K", dec], env={"FAKEUSB_FAIL": "KEYS"})
check("-K, connection lost on a key block: still transfer_failed, keys unknown",
      code == 9 and error(ev).get("radio") == "keys_unknown", "exit %d %s" % (code, error(ev)))

# --- usage ----------------------------------------------------------------------

for args in (["--expect-unit", A, "-r"], ["--expect-unit", A, "identify"],
             ["--expect-unit", A, "-k"], ["--expect-unit", A, "keys", "show", dec],
             ["--expect-unit", A, "-c", blank, conf, "-o", tmp],
             ["--expect-unit", "xyz1", "-K", dec], ["--expect-unit", "abc", "-K", dec],
             ["-K", dec, "--expect-unit"], ["--expect-unit", A, "--expect-unit", A, "-K", dec],
             ["--expect-unit", "0" * 66, "-K", dec], ["--expect-unit", A, "-l"],
             ["--expect-unit", A, "--version"]):
    code, ev, log = run(args)
    check("usage: %s" % " ".join(a.replace(tmp, "<tmp>") for a in args),
          code == 2 and "OPEN" not in log, "exit %d, log %s" % (code, log[:3]))

code, ev, _ = run(["--version"], prog=REAL)
check("--version reports api 3", any(x.get("api") == 3 for x in ev))

# --- a password is never repeated back (7.3 review: logs and diagnostics) --------

for line, secret in (("Power On Password: 1234567", "1234567"),
                     ("Radio Program Password: 12a45678", "12a45678"),
                     ("PC Programming Password: abc defgh", "abc defgh"),
                     ("PC Programming Password: raw:0x1234567890abcdef12", "1234567890abcdef12")):
    bad = os.path.join(tmp, "pw.conf")
    with open(bad, "w") as f:
        f.write(line + "\n")
    out = tempfile.mkdtemp(dir=tmp)
    p = subprocess.run([REAL, "--json", "-c", "-o", out, blank, bad], capture_output=True,
                       env=dict(os.environ, TYT_STATE_DIR=fleet))
    text = (p.stdout + p.stderr).decode("utf-8", "replace")
    check("refused, not echoed: %s" % line.split(":")[0],
          p.returncode == 11 and secret not in text, "exit %d" % p.returncode)

shutil.rmtree(tmp, ignore_errors=True)
if failures:
    print("\n%d FAILED" % len(failures))
    sys.exit(1)
print("\nall passed")
