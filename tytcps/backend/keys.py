# SPDX-License-Identifier: GPL-3.0-or-later
"""Key sets: the 16 privacy key slots of a CPS .dec file.

A key set is a FLEET-WIDE CONTRACT, slot for slot. The radio sends a
channel's slot number over the air and the receiver looks that number up in
its OWN table, so every radio must hold the identical set.
Radios never give keys back, so the ledger and an on-air test are the only
checks there are.

Keys are held here in CPS grid order, as the operator sees and types them;
the engine reverses them into file order itself. Key bytes are never logged,
never written to a temp file, and never put on a command line (they go to
`keys set` on stdin). A key set file is never edited in place: an edit is
saved as a new file.
"""

import datetime
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from .engine import Command

DEC_SIZE = 20480
NSLOTS = 16
NAME_MAX = 16
TYPES = {"ARC4": 5, "AES128": 16, "AES256": 32}
TYPE_NAMES = ["ARC4", "AES128", "AES256"]


@dataclass
class Slot:
    slot: int
    type: str = "empty"          # "empty" or one of TYPES
    name: str = ""
    key: bytes = b""             # CPS grid order; empty when the slot is empty

    @property
    def filled(self):
        return self.type in TYPES and len(self.key) == TYPES[self.type]

    @property
    def length(self):
        return TYPES.get(self.type, 0)

    def problem(self):
        """Why this slot cannot be saved, or None (E-K2)."""
        if self.type == "empty":
            return None
        if self.type not in TYPES:
            return "Unknown type %s." % self.type
        if len(self.name) > NAME_MAX:
            return "Name is longer than %d characters." % NAME_MAX
        if "\t" in self.name or "\n" in self.name:
            return "Name can't contain tabs or line breaks."
        if len(self.key) != self.length:
            return "%s needs %d bytes; this slot has %d." % (self.type, self.length, len(self.key))
        return None


@dataclass
class KeySet:
    slots: list = field(default_factory=lambda: [Slot(i + 1, "empty", str(i + 1)) for i in range(NSLOTS)])
    file: Path = None            # the saved file this came from, None for a draft from nothing
    sha256: str = ""
    original: bytes = None       # bytes of an imported file, while unmodified
    contract_changed: set = field(default_factory=set)   # slots whose key or type changed

    def filled(self):
        return [s for s in self.slots if s.filled]

    def problems(self):
        return {s.slot: p for s in self.slots for p in [s.problem()] if p}

    def summary(self):
        """`1 AES256 "Fleet-A" · 2 AES128 "Fleet-B" · 4-16 empty`."""
        parts = []
        empty = []

        def flush():
            if empty:
                parts.append(("%d-%d empty" % (empty[0], empty[-1])) if len(empty) > 1
                             else "%d empty" % empty[0])
                empty.clear()
        for s in self.slots:
            if s.filled:
                flush()
                parts.append('%d %s "%s"' % (s.slot, s.type, s.name))
            else:
                empty.append(s.slot)
        flush()
        return " · ".join(parts)


def keyset_from_show(result, path=None):
    """A KeySet from `keys show --json`'s result event."""
    ks = KeySet(slots=[], file=Path(path) if path else None, sha256=result.get("sha256", ""))
    for s in result["slots"]:
        hexkey = s.get("key") or ""
        t = s.get("type", "empty")
        if not s.get("in_use"):
            t = "empty"
            hexkey = ""
        ks.slots.append(Slot(int(s["slot"]), t, s.get("name", ""), bytes.fromhex(hexkey)))
    ks.slots.sort(key=lambda s: s.slot)
    return ks


def parse_hex(text):
    """Key bytes from typed hex: spaces, colons and dashes allowed (7.8)."""
    clean = re.sub(r"[\s:\-]", "", text)
    if not clean:
        return b""
    if not re.fullmatch(r"[0-9A-Fa-f]*", clean):
        raise ValueError("Use hex digits 0-9 and A-F only.")
    if len(clean) % 2:
        raise ValueError("Hex needs two digits per byte.")
    return bytes.fromhex(clean)


def grouped_hex(key, group=4):
    """Grid-order hex in groups of four characters, for the reveal."""
    h = key.hex().upper()
    return " ".join(h[i:i + group] for i in range(0, len(h), group))


def generate(type_name):
    """Random key bytes from the OS CSPRNG for a slot type."""
    return secrets.token_bytes(TYPES[type_name])


def sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def dated_name(keys_dir, today=None):
    """fleet-YYYY-MM-DD.dec, then -2, -3 ... on the same day."""
    today = today or datetime.date.today()
    base = "fleet-%s" % today.isoformat()
    name = base + ".dec"
    n = 2
    while (Path(keys_dir) / name).exists():
        name = "%s-%d.dec" % (base, n)
        n += 1
    return name


def display_name(file_name):
    """fleet-2026-01-15.dec -> fleet-2026-01-15."""
    name = Path(file_name).name
    return name[:-4] if name.lower().endswith(".dec") else name


# -- engine commands ---------------------------------------------------------

def show(path, short=str):
    """`keys show --json`: types, names and keys. stdout is never logged."""
    return Command(["keys", "show", str(path)], "dmrconfig keys show %s" % short(path),
                   secret=True, label="keys-show")


def new(path, short=str, env=None):
    return Command(["keys", "new", str(path)], "dmrconfig keys new %s" % short(path),
                   label="keys-new", env=env or {})


def set_slot(path, slot, short=str, env=None):
    """`keys set --no-backup`, the key on stdin so it is on no command line."""
    return Command(["keys", "set", "--no-backup", "--name", slot.name, str(path),
                    str(slot.slot), slot.type, "-"],
                   'dmrconfig keys set --no-backup --name "%s" %s %d %s <key hidden>'
                   % (slot.name, short(path), slot.slot, slot.type),
                   stdin=(slot.key.hex() + "\n").encode(), secret=True, label="keys-set",
                   env=env or {})


def add_existing(fleet, unit, keyset_name, note, tool="manual"):
    """F8: a ledger line for keys this program did not write."""
    rel = "keys/%s" % keyset_name
    args = ["ledger", "add-existing", "--unit", unit, "--keyset", rel, "--tool", tool]
    disp = "dmrconfig ledger add-existing --unit %s --keyset %s --tool %s" % (unit, rel, tool)
    if note:
        args += ["--note", note]
        disp += ' --note "%s"' % note
    return Command(args, disp, label="ledger", links={"keys": str(Path(fleet) / "keys")})


# -- saving -------------------------------------------------------------------

class SaveError(Exception):
    pass


def save_new(engine, keyset, keys_dir, name=None):
    """Write a key set as a new file in the fleet's keys folder.

    An imported CPS file that was not edited is copied byte for byte, so its
    SHA256 stays the one the radios and the ledger know (a rebuilt file
    differs from a CPS-made one in the unused slots). Anything else is built
    with `keys new` and one `keys set --no-backup` per filled slot (F7),
    under a hidden name, and renamed into place only once complete.
    Returns (file name, sha256).
    """
    keys_dir = Path(keys_dir)
    try:
        keys_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as e:
        raise SaveError("Can't write to the keys folder (%s)." % (e.strerror or e)) from e
    name = name or dated_name(keys_dir)
    final = keys_dir / name
    if final.exists():
        raise SaveError("%s already exists." % name)
    bad = keyset.problems()
    if bad:
        raise SaveError("Slot %d: %s" % next(iter(bad.items())))
    partial = keys_dir / (".partial-%d-%s" % (os.getpid(), name))
    try:
        if keyset.original is not None:
            fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(keyset.original)
                f.flush()
                os.fsync(f.fileno())
        else:
            # `keys set --no-backup` refuses a file whose content matches a set
            # in the ledger or the current set, to protect sets in service. A
            # file being built here passes through the same bytes as sets
            # already saved (a set plus one slot starts as that set), so the
            # build steps run against an empty fleet folder. The protection
            # that matters for a new file, refusing to overwrite a slot that
            # holds a key, is in the file itself and still applies.
            build = {"TYT_STATE_DIR": str(engine.runtime.new_run("keys-build"))}
            r = engine.run(new(partial, engine.short, build))
            if not r.ok:
                raise SaveError(_engine_message(r))
            os.chmod(partial, 0o600)
            for s in keyset.filled():
                r = engine.run(set_slot(partial, s, engine.short, build))
                if not r.ok:
                    raise SaveError("Slot %d: %s" % (s.slot, _engine_message(r)))
        r = engine.run(show(partial, engine.short))
        if not r.ok:
            raise SaveError(_engine_message(r))
        sha = r.result["sha256"]
        saved = keyset_from_show(r.result)
        for a, b in zip(saved.slots, keyset.slots):
            if (a.type, a.key) != (b.type, b.key) or (a.filled and a.name != b.name):
                raise SaveError("Slot %d did not save as entered." % a.slot)
        # Never replace a file that appeared meanwhile (another TYTcps saving
        # the same dated name): link refuses an existing name, rename doesn't.
        try:
            os.link(partial, final)
        except FileExistsError:
            raise SaveError("%s was created meanwhile; save again." % name)
        partial.unlink()
        return name, sha
    except OSError as e:
        raise SaveError("Couldn't save the key set (%s)." % (e.strerror or e)) from e
    finally:
        if partial.exists():
            partial.unlink()


def cleanup_partials(keys_dir):
    """Remove key files a save left behind when TYTcps or the engine was
    killed part-way: .partial-<pid>-* (TYTcps) and *.tmp.<pid> (the engine's
    atomic replace), only when that process no longer exists. They hold key
    material and no view lists them."""
    removed = []
    try:
        names = os.listdir(keys_dir)
    except OSError:
        return removed
    for name in names:
        m = re.fullmatch(r"\.partial-(\d+)-.+", name) or re.fullmatch(r".+\.tmp\.(\d+)", name)
        if not m:
            continue
        pid = int(m.group(1))
        if pid == os.getpid() or os.path.exists("/proc/%d" % pid):
            continue
        try:
            os.unlink(os.path.join(keys_dir, name))
            removed.append(name)
        except OSError:
            pass
    return removed


def write_private(dest, data):
    """Write a clear-text key file readable by this user only, from the first
    byte: created 0600, never through a symlink."""
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd is not None:
            os.close(fd)


def import_file(engine, path):
    """Read a CPS .dec into a draft (E-K1 on a bad file)."""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as e:
        raise SaveError("Can't read %s: %s" % (p.name, e.strerror))
    if len(data) != DEC_SIZE:
        raise SaveError("That isn't a CPS key file (%d bytes; a .dec file is 20480)." % len(data))
    r = engine.run(show(p, engine.short))
    if not r.ok:
        raise SaveError(_engine_message(r))
    ks = keyset_from_show(r.result, None)
    ks.original = data
    ks.sha256 = r.result["sha256"]
    return ks


def load(engine, path):
    r = engine.run(show(path, engine.short))
    if not r.ok:
        raise SaveError(_engine_message(r))
    return keyset_from_show(r.result, path)


def _engine_message(r):
    e = r.error or {}
    return e.get("message") or "the engine stopped with exit %d" % r.exit


def as_json_safe(ks):
    """A description of a key set with no key bytes, for logs and dialogs."""
    return json.dumps([{"slot": s.slot, "type": s.type, "name": s.name, "filled": s.filled}
                       for s in ks.slots])
