#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for dmrconfig-tyt that never opens USB, for GUI tests.

Offline commands (print, offline -c, diff, keys, ledger) go to the real
bundled engine. Radio commands are simulated against an image file
($FAKE_IMAGE) that plays the radio's codeplug, emitting the engine's JSON
events with short delays.

$FAKE_SCENARIO picks a failure:
  ok (default), no_radio, reads_disagree, write_unverified,
  transfer_failed_keys, ledger_failed, unsupported_model,
  crash_after_keys (killed by a signal mid key transfer, no error event)
$FAKE_A207 is the unit block the "radio" reports (change it to simulate
another radio on the cable; empty = the block can't be read).
--expect-unit is honoured as the engine does: another unit is refused with
unit_mismatch (exit 17), an unreadable one with unit_unreadable (14), both
right after the unit event and before anything is read or written.
$FAKE_WARNINGS is a comma list of warning codes emitted before a successful
result, e.g. reboot_failed,prewrite_skipped.

Fault injection, all optional:
  FAKE_KILL_AT=<phase>           SIGKILL itself as that phase starts
  FAKE_EXIT_AT=<phase>:<n>       exit n as that phase starts, no error event
  FAKE_ERROR_AT=<phase>:<code>:<radio>[:<exit>]
                                 an error event as that phase starts, then exit
  FAKE_FINAL_EXIT=<n>            exit n after a successful result
  FAKE_RESULT_OK=false           the result says ok: false
  FAKE_GARBAGE=<kinds>           malformed stdout lines after connect: text,
                                 badutf8, array, noevent, truncated, huge, nul;
                                 "result" breaks the result line itself
  FAKE_VOLATILE=<n>              volatile bytes in a write's result
  FAKE_VERIFY_RETRY=1            a write re-reads before verifying
  FAKE_VERSION=<v>               what --version reports (default: the pin)
A fleet folder that can't be written behaves as the engine does: -K refuses
before touching the radio (io_error, nothing written); other commands warn
roster_failed.

Test-only. TYTcps finds it through TYTCPS_ENGINE; it answers --version with
the pinned version so the GUI accepts it.
"""

import datetime
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "tytcps"
REAL = PKG / "libexec" / "dmrconfig-tyt"
PIN = json.loads((PKG / "engine_pin.json").read_text())
A207 = os.environ.get("FAKE_A207", "0badcafe0badcafe0badcafe00001001")
SCEN = os.environ.get("FAKE_SCENARIO", "ok")
DELAY = float(os.environ.get("FAKE_DELAY", "0.05"))
STATE = Path(os.environ.get("TYT_STATE_DIR", "."))
EXITS = {"io_error": 1, "usage": 2, "no_radio": 3, "no_permission": 4, "busy": 5,
         "unsupported_model": 6, "reads_disagree": 7, "write_unverified": 8,
         "transfer_failed": 9, "keyfile_invalid": 10, "conf_invalid": 11, "key_slot_empty": 12,
         "ledger_failed": 13, "unit_unreadable": 14, "multiple_radios": 15, "image_invalid": 16,
         "unit_mismatch": 17, "keys_refused": 18}
EXPECT = None
CONTEXT = {}            # fields every error event carries (-K after connect)


def out(line):
    """One raw stdout line (bytes or str)."""
    if isinstance(line, str):
        line = line.encode("utf-8")
    sys.stdout.buffer.write(line + b"\n")
    sys.stdout.buffer.flush()


def garbage():
    return [g for g in os.environ.get("FAKE_GARBAGE", "").split(",") if g]


def ev(**kw):
    if kw.get("event") == "result" and "result" in garbage():
        out(json.dumps(kw)[:-7])         # a result line cut short: unreadable
        return
    out(json.dumps(kw))


def emit_garbage():
    for g in garbage():
        if g == "text":
            out("Write device: ####")
        elif g == "badutf8":
            out(b'{"event": "warning", "code": "x", "message": "\xff\xfe"}')
        elif g == "array":
            out("[1, 2, 3]")
        elif g == "noevent":
            out('{"code": "no_event_field"}')
        elif g == "truncated":
            out('{"event": "phase", "pha')
        elif g == "huge":
            out("x" * (1024 * 1024))
        elif g == "nul":
            out(b"\x00\x00{\x00}")


def at(spec_name, p):
    """The FAKE_*_AT spec for phase p, split, or None."""
    spec = os.environ.get(spec_name, "")
    parts = spec.split(":")
    return parts if spec and parts[0] == p else None


def phase(p):
    ev(event="phase", phase=p)
    if os.environ.get("FAKE_KILL_AT") == p:
        os.kill(os.getpid(), signal.SIGKILL)
    x = at("FAKE_EXIT_AT", p)
    if x:
        sys.exit(int(x[1]))
    x = at("FAKE_ERROR_AT", p)
    if x:
        code, radio = x[1], x[2]
        n = int(x[3]) if len(x) > 3 else EXITS.get(code, 255)
        print("fake error %s at %s" % (code, p), file=sys.stderr)
        ev(event="error", code=code, exit=n, phase=p, radio=radio,
           message="fake %s" % code, **CONTEXT)
        sys.exit(n)
    time.sleep(DELAY)


def err(code, radio, msg, **kw):
    print(msg, file=sys.stderr)
    fields = dict(CONTEXT, **kw)
    ev(event="error", code=code, exit=EXITS[code], radio=radio, message=msg, **fields)
    sys.exit(EXITS[code])


def warn(code, msg):
    print("warning: %s" % msg, file=sys.stderr)
    ev(event="warning", code=code, message=msg)


def warnings():
    for code in [c for c in os.environ.get("FAKE_WARNINGS", "").split(",") if c]:
        warn(code, "fake %s" % code)


def result(**kw):
    if os.environ.get("FAKE_RESULT_OK") == "false":
        kw["ok"] = False
    ev(**kw)
    n = os.environ.get("FAKE_FINAL_EXIT")
    sys.exit(int(n) if n else 0)


def now():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def writable_state():
    return STATE.is_dir() and os.access(STATE, os.W_OK)


def roster(radio_id=None, wrote=False):
    if not A207 or not STATE.is_dir():
        return
    if not writable_state():
        warn("roster_failed", "Could not update radios.tsv: Permission denied")
        return
    p = STATE / "radios.tsv"
    lines = p.read_text().splitlines() if p.exists() else [
        "#a207\tradio_id\tlabel\tlast_seen\tlast_write\tflags"]
    rows, found = [], False
    for l in lines:
        f = l.split("\t")
        if l and not l.startswith("#") and f[0] == A207:
            f += ["-"] * (6 - len(f))
            f[1] = radio_id or f[1]
            f[3] = now()
            if wrote:
                f[4] = now()
            l = "\t".join(f)
            found = True
        rows.append(l)
    if not found:
        rows.append("\t".join([A207, radio_id or "-", "-", now(), now() if wrote else "-", "-"]))
    try:
        p.write_text("\n".join(rows) + "\n")
    except OSError as e:
        warn("roster_failed", "Could not update radios.tsv: %s" % e.strerror)


def known():
    p = STATE / "radios.tsv"
    try:
        for l in p.read_text().splitlines():
            f = l.split("\t")
            if A207 and f[0] == A207:
                return f[1] if f[1] != "-" else None, f[2] if len(f) > 2 and f[2] != "-" else None
    except OSError:
        pass
    return None, None


def unit(keys=False, write=False):
    phase("connect")
    if SCEN == "no_radio":
        err("no_radio", "unchanged", "No radio detected.")
    model = "MD-9600" if SCEN == "unsupported_model" else "MD-UV390"
    u = dict(event="unit", model=model, a207=A207 or None, serial="000001", firmware="S119.038",
             privacy_capable=model == "MD-UV390")
    if keys:
        rid, label = known()
        u.update(known=rid is not None, radio_id=rid, label=label)
    ev(**u)
    print("Connect to TYT %s." % model, file=sys.stderr)
    if not A207 and not keys:
        warn("unit_unreadable", "The radio's a2 07 unit block came back empty, so the roster "
             "cannot be updated for this session.")
    emit_garbage()
    if write and EXPECT:
        if not A207:
            err("unit_unreadable", "unchanged", "Cannot read the a2 07 unit block, so this radio "
                "cannot be confirmed as unit %s. Nothing was written." % EXPECT)
        if A207.lower() != EXPECT:
            err("unit_mismatch", "unchanged", "This is unit %s, not unit %s that the write was "
                "meant for. Nothing was written." % (A207, EXPECT), expected=EXPECT, a207=A207)
    return u


def image_id(path):
    data = Path(path).read_bytes()
    return int.from_bytes(data[0x2084:0x2087], "little")


def real(args):
    os.execv(str(REAL), [str(REAL)] + args)


def take_expect(args):
    global EXPECT
    if "--expect-unit" in args:
        i = args.index("--expect-unit")
        if i + 1 >= len(args):
            err("usage", "unchanged", "--expect-unit needs the unit block in hex.")
        EXPECT = args[i + 1].lower()
        del args[i:i + 2]
    return args


def main(argv):
    args = take_expect([a for a in argv if a != "--json"])
    if "--version" in args:
        ev(event="result", command="version", ok=True, program=PIN["program"],
           version=os.environ.get("FAKE_VERSION", PIN["version"]), branch=PIN["branch"],
           commit=PIN["commit"], api=PIN["api"])
        return 0
    radio_write = args[:1] in (["-K"], ["-w"]) or ("-c" in args and "-o" not in args)
    if EXPECT and not radio_write:
        err("usage", "unchanged", "--expect-unit goes with -K, -w or -c to a radio only.")
    img = os.environ.get("FAKE_IMAGE")
    if args and args[0] == "identify":
        u = unit(keys=True)
        roster()
        rid, label = known()
        result(event="result", command="identify", ok=True, model=u["model"],
               firmware=u["firmware"], serial=u["serial"], a207=A207 or None,
               privacy_capable=u["privacy_capable"], known=rid is not None, radio_id=rid,
               label=label, last_seen=now())
    if args[:1] == ["-r"]:
        outdir = Path(args[args.index("-o") + 1]) if "-o" in args else Path(".")
        unit()
        for p in ("read1", "read2"):
            phase(p)
            for i in range(0, 101, 25):
                ev(event="progress", phase=p, done=i * 8519, total=851968)
                time.sleep(DELAY / 5)
        phase("compare")
        if SCEN == "reads_disagree":
            err("reads_disagree", "unchanged", "The two reads differ in 1024 bytes.",
                bytes=1024, first=0)
        phase("save")
        shutil.copyfile(img, outdir / "device.img")
        rid = image_id(img)
        roster(str(rid))
        warnings()
        result(event="result", command="read", ok=True, reads_agree=True,
               image=str(outdir / "device.img"),
               sha256=hashlib.sha256(Path(img).read_bytes()).hexdigest(), radio_id=rid,
               name=None, a207=A207 or None)
    if "-c" in args and "-o" in args:
        real(argv)          # offline apply: TYTcps always gives it -o
    if "-c" in args:
        conf = args[args.index("-c") + 1]
        unit(write=True)
        for p in ("read1", "read2", "compare", "parse", "check"):
            phase(p)
        tmp = Path(".") / "fake-apply"
        tmp.mkdir(exist_ok=True)
        cmd = [str(REAL), "--json", "-c", "-o", str(tmp)]
        if "-F" in args:
            cmd += ["-F", args[args.index("-F") + 1]]
        r = subprocess.run(cmd + [img, conf], capture_output=True, text=True)
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            return r.returncode
        phase("prewrite")
        if A207 and writable_state():
            # As the engine: the radio as it was, kept before anything is erased.
            pre = STATE / "prewrite"
            pre.mkdir(exist_ok=True)
            stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            shutil.copyfile(img, pre / ("%s-%s.img" % (A207, stamp)))
        phase("erase")
        phase("write")
        for i in range(0, 101, 20):
            ev(event="progress", phase="write", done=i * 8519, total=851968)
            time.sleep(DELAY / 5)
        if SCEN == "write_unverified":
            phase("verify")
            err("write_unverified", "codeplug_differs", "Write NOT verified: 12 bytes differ.",
                bytes=12, first=0x40042)
        shutil.copyfile(tmp / "device.img", img)
        phase("verify")
        if os.environ.get("FAKE_VERIFY_RETRY"):
            phase("verify_retry")
        rid = image_id(img)
        roster(str(rid), wrote=True)
        print("Write verified: the radio matches the image byte for byte.", file=sys.stderr)
        warnings()
        result(event="result", command="write_conf", ok=True, verified=True,
               volatile=int(os.environ.get("FAKE_VOLATILE", "0")), a207=A207 or None,
               radio_id=rid, name=None)
    if args[:1] == ["-w"]:
        src = args[1]
        unit(write=True)
        for p in ("read1", "read2", "prewrite", "erase", "write", "verify"):
            phase(p)
        shutil.copyfile(src, img)
        roster(str(image_id(img)), wrote=True)
        warnings()
        result(event="result", command="write_image", ok=True, verified=True,
               volatile=int(os.environ.get("FAKE_VOLATILE", "0")), a207=A207 or None)
    if args[:1] == ["-k"]:
        unit(keys=True)
        phase("keys_read")
        slots = [dict(slot=i, type="AES256", type_code=4, name=str(i), length=32)
                 for i in range(1, 17)]
        result(event="result", command="read_keys", ok=True, a207=A207 or None, slots=slots)
    if args[:1] == ["-K"]:
        dec = args[1]
        led = STATE / "ledger.tsv"
        if not writable_state() or (led.exists() and not os.access(led, os.W_OK)):
            err("io_error", "unchanged", "Cannot write the ledger %s: Permission denied. Nothing "
                "was written to the radio." % led)
        u = unit(keys=True, write=True)
        if not u["privacy_capable"]:
            err("unsupported_model", "unchanged", "Radio identifies as 'MD-9600'.",
                model="MD-9600")
        if not A207:
            err("unit_unreadable", "unchanged", "Cannot read the a2 07 unit block. Nothing "
                "was written.")
        sha = hashlib.sha256(Path(dec).read_bytes()).hexdigest()
        CONTEXT.update(a207=A207, sha256=sha, file=dec)
        phase("keys")
        for i in range(0, 21, 5):
            ev(event="progress", phase="keys", done=i, total=20)
            time.sleep(DELAY / 5)
        if SCEN == "crash_after_keys":
            os.kill(os.getpid(), signal.SIGKILL)
        if SCEN == "transfer_failed_keys":
            err("transfer_failed", "keys_unknown", "cannot write 1024 bytes", phase="keys")
        rid, label = known()
        line = "\t".join([now(), A207, "000001", rid or "-", label or "-", sha, dec,
                          PIN["version"], "-"])
        if SCEN == "ledger_failed":
            err("ledger_failed", "keys_written", "cannot append to the ledger: No space left on "
                "device. The key write HAS happened.", line=line)
        if not led.exists() or led.stat().st_size == 0:
            led.write_text("#when\ta207\tserial\tdmr_id\tlabel\tdec_sha256\tdec_file\ttool\tnote\n")
        with open(led, "a") as f:
            f.write(line + "\n")
        roster()
        warnings()
        result(event="result", command="write_keys", ok=True, file=dec, sha256=sha, a207=A207,
               serial="000001", radio_id=rid, label=label, ledger=str(led), line=line,
               verify="on_air_only", slots=[])
    real(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
