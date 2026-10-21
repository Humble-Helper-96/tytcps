# SPDX-License-Identifier: GPL-3.0-or-later
"""The open codeplug: a base image plus its conf text, edited.

A codeplug file is the engine's 851968-byte image (like a CPS .rdt). TYTcps
shows and edits the conf text the engine prints for it; the image is only
ever produced by the engine applying that text.

    open     dmrconfig <file.img>                       -> conf text
    preview  dmrconfig -c -o <tmp> [-F keys] base conf  -> <tmp>/device.img
             dmrconfig diff base <tmp>/device.img       -> what would change
    save     the preview's apply, then the image moved into place
"""

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .conf import ConfDocument, ConfParseError, RECORD_KIND
from .engine import Command

IMAGE_SIZE = 851968


def print_image(image, short=str):
    return Command([str(image)], "dmrconfig %s" % short(image), label="open")


def apply(base, conf, out_dir, keyset=None, short=str):
    """Offline -c: base image + conf -> out_dir/device.img (F9 errors)."""
    args = ["-c", "-o", str(out_dir)]
    disp = "dmrconfig -c -o %s" % short(out_dir)
    if keyset:
        args += ["-F", str(keyset)]
        disp += " -F %s" % short(keyset)
    args += [str(base), str(conf)]
    disp += " %s %s" % (short(base), short(conf))
    return Command(args, disp, label="apply")


def diff(a, b, short=str):
    return Command(["diff", str(a), str(b)], "dmrconfig diff %s %s" % (short(a), short(b)),
                   label="diff")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Codeplug:
    """One open codeplug (the CPS model: one at a time)."""

    def __init__(self, base, conf_text, path=None, title=None, radio_id=None):
        self.base = Path(base)            # private copy in the runtime folder
        self.path = Path(path) if path else None   # the file on disk, if saved
        self.doc = ConfDocument(conf_text)
        self.title = title or (self.path.name if self.path else "Untitled")
        self.radio_id = radio_id
        self.unsaved_read = path is None  # read from a radio, never saved

    @property
    def dirty(self):
        return self.unsaved_read or self.doc.is_edited()

    def edited_text(self):
        return self.doc.render()

    # Scalars a write leaves as the radio has them, unless edited here.
    RADIO_OWN = ("ID", "Name")

    def write_text(self):
        """The conf to write to a radio: the edited text without its ID: and
        Name: lines, so the radio keeps its own Radio ID and Name (the engine
        leaves what a conf doesn't name as the radio has it). An ID or Name
        changed on the General tab is written. The document is unchanged."""
        out = []
        for line in self.edited_text().split("\n"):
            key = line.split(":", 1)[0] if ":" in line and line[:1] not in " \t#" else None
            if key in self.RADIO_OWN and not self.identity_edited(key):
                continue
            out.append(line)
        return "\n".join(out)

    def identity_edited(self, key):
        s = self.doc.scalars.get(key)
        return bool(s and s.edited)


def name_token(display):
    """A display name as a conf token: '_' for spaces, '-' when empty."""
    display = display.strip()
    return display.replace(" ", "_") if display else "-"


def name_display(token):
    if token in ("-", ""):
        return ""
    return token.replace("_", " ")


def open_file(engine, path):
    """Open a codeplug file. Returns (Codeplug, RunResult)."""
    path = Path(path)
    run_base = engine.runtime.file("base-%d.img" % time.monotonic_ns())
    shutil.copyfile(path, run_base)
    os.chmod(run_base, 0o600)
    r = engine.run(print_image(run_base, engine.short))
    if not r.ok:
        run_base.unlink(missing_ok=True)
        return None, r
    res = r.result
    try:
        cp = Codeplug(run_base, res["conf"], path=path, radio_id=res.get("radio_id"))
    except ConfParseError as e:
        return None, unreadable(r, e)
    return cp, r


def from_read(engine, image, when_label):
    """A codeplug from a radio read: titled, unsaved."""
    run_base = engine.runtime.file("base-%d.img" % time.monotonic_ns())
    shutil.copyfile(image, run_base)
    os.chmod(run_base, 0o600)
    r = engine.run(print_image(run_base, engine.short))
    if not r.ok:
        return None, r
    res = r.result
    rid = res.get("radio_id")
    title = "Read from Radio ID %s — %s" % (rid if rid is not None else "?", when_label)
    try:
        cp = Codeplug(run_base, res["conf"], path=None, title=title, radio_id=rid)
    except ConfParseError as e:
        return None, unreadable(r, e)
    return cp, r


def unreadable(r, e):
    """A print result whose text TYTcps can't take apart: reported like an
    engine failure, with the line, instead of failing silently."""
    import dataclasses
    line = r.result["conf"].split("\n")[e.line] if r.result and "conf" in r.result else ""
    msg = ("Can't read line %d of this codeplug (%s): %r. A name starting with '#' can cause "
           "this; rename it in the CPS."
           % (e.line + 1, e.message, line.strip()))
    ev = {"event": "error", "code": "conf_unreadable", "exit": 0, "radio": "unchanged",
          "message": msg}
    return dataclasses.replace(r, events=[x for x in r.events if x.get("event") != "result"] + [ev])


@dataclass
class Preview:
    """The dry run for one exact conf text."""
    conf_sha: str
    ok: bool
    image: Path = None
    diff: dict = None                 # `diff --json` result
    errors: list = None               # conf_invalid / key_slot_empty events
    warnings: list = None
    unexplained: list = None          # records outside the operator's edits
    unattributed: int = 0
    message: str = ""

    @property
    def changed(self):
        return self.diff.get("changed", 0) if self.diff else 0

    @property
    def records(self):
        return self.diff.get("records", []) if self.diff else []

    @property
    def unexplained_bytes(self):
        return sum(r.get("bytes", 0) for r in self.unexplained or []) + self.unattributed


def run_preview(engine, base, text, edited_records, keyset=None):
    """Apply `text` to `base` offline and diff the result. Synchronous: the
    GUI calls it from a worker thread."""
    sha = sha256_text(text)
    run_dir = engine.runtime.new_run("preview")
    conf = run_dir / "edited.conf"
    conf.write_text(text, encoding="utf-8")
    out = run_dir / "out"
    out.mkdir()
    r = engine.run(apply(base, conf, out, keyset, engine.short))
    if not r.ok:
        errs = [e for e in r.errors if e.get("code") in ("conf_invalid", "key_slot_empty")]
        if not errs:
            errs = [r.error]
        return Preview(sha, False, errors=errs, warnings=r.warnings,
                       message=(r.error or {}).get("message", "")), r, None
    image = out / "device.img"
    d = engine.run(diff(base, image, engine.short))
    if not d.ok:
        return Preview(sha, False, errors=[d.error], message=(d.error or {}).get("message", "")), r, d
    res = d.result
    unexplained = []
    for rec in res.get("records", []):
        key = (rec.get("kind"), int(rec.get("index", 0)) if rec.get("kind") != "general" else 0)
        if rec.get("kind") == "general" and ("general", 0) in edited_records:
            continue
        if key not in edited_records:
            unexplained.append(rec)
    p = Preview(sha, True, image=image, diff=res, errors=[], warnings=r.warnings,
                unexplained=unexplained,
                unattributed=(res.get("unattributed") or {}).get("bytes", 0))
    return p, r, d


KIND_LABEL = {
    "channel": "Channel", "zone": "Zone", "scanlist": "Scan list", "contact": "Contact",
    "grouplist": "Group list", "message": "Message", "general": "General settings",
    "privacy_legacy": "Legacy Basic/Enhanced keys",
    "menu": "Menu items", "buttons": "Buttons", "onetouch": "One Touch Access",
    "numberkey": "Number Key", "emergency": "Digit Emergency System",
    "emsystem": "Emergency system", "dtmfsystem": "DTMF system", "dtmfencode": "DTMF encode",
    "dtmfdecode": "DTMF decode", "vfo": "VFO",
}


def record_label(rec):
    kind = rec.get("kind", "?")
    label = KIND_LABEL.get(kind, kind)
    if kind in ("general", "privacy_legacy", "menu", "buttons", "emergency"):
        return label
    if kind in ("vfo", "dtmfsystem", "dtmfencode", "dtmfdecode") and rec.get("name"):
        return rec["name"]              # "VFO A", "DTMF-2", "Encode 5", "Decode 1"
    index = rec.get("index")
    if kind == "numberkey" and isinstance(index, int):
        index -= 1                  # the diff counts from 1, the keys from 0
    name = rec.get("name")
    return '%s %s "%s"' % (label, index, name) if name else "%s %s" % (label, index)


def record_fields(rec):
    parts = []
    for f in rec.get("fields", []):
        if "old" in f and "new" in f:
            parts.append("%s %s → %s" % (f["field"], f["old"], f["new"]))
        else:
            parts.append(f["field"])
    return ", ".join(parts)


def table_of_record(kind):
    return [t for t, k in RECORD_KIND.items() if k == kind]
