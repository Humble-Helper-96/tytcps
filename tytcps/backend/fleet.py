# SPDX-License-Identifier: GPL-3.0-or-later
"""The fleet folder: key sets, the ledger and the radio roster.

    <fleet>/keys/fleet-YYYY-MM-DD.dec   key sets (0600), never edited in place
    <fleet>/current-keyset              one line: the current set's file name
    <fleet>/ledger.tsv                  appended by the engine only (-K, F8)
    <fleet>/radios.tsv                  roster; the engine fills it in, TYTcps
                                        edits only the label and flags columns
    <fleet>/prewrite/                   the engine's pre-write images

The ledger is the only record of which key set a radio holds, because radios
never give keys back. TYTcps reads it and never writes it.
"""

import fcntl
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import keys as keysmod

LEDGER = "ledger.tsv"
ROSTER = "radios.tsv"
ROSTER_LOCK = "radios.tsv.lock"
CURRENT = "current-keyset"

ROSTER_HEADER = (
    "# TYTcps radio roster. One line per radio, keyed on its a2 07 unit block.\n"
    "# radio_id, last_seen and last_write are filled in by dmrconfig-tyt on every\n"
    "# identify, read, codeplug write and key write. label and flags are yours.\n"
    "#a207\tradio_id\tlabel\tlast_seen\tlast_write\tflags\n")


def short_unit(a207):
    """First 4 and last 4 hex characters: 1a2b…9f0e."""
    if not a207 or len(a207) <= 8:
        return a207 or "?"
    return "%s…%s" % (a207[:4], a207[-4:])


def dash(v):
    return None if v in (None, "", "-") else v


@dataclass
class LedgerLine:
    number: int          # line number in the file, 1-based
    when: str
    a207: str
    serial: str
    radio_id: str
    label: str
    sha256: str
    file: str
    tool: str
    note: str = None

    @property
    def manual(self):
        return self.tool == "manual"

    @property
    def keyset_name(self):
        return keysmod.display_name(self.file)


@dataclass
class Unit:
    a207: str
    radio_id: str = None
    label: str = None
    last_seen: str = None
    last_write: str = None
    flags: list = field(default_factory=list)
    extra: list = field(default_factory=list)

    @property
    def hidden(self):
        return "hidden" in self.flags

    @property
    def short(self):
        return short_unit(self.a207)


@dataclass
class KeysStatus:
    """What the ledger says about one unit's keys, against the current set."""
    kind: str            # "current", "old", "none"
    line: LedgerLine = None

    @property
    def manual(self):
        return self.line is not None and self.line.manual


class Fleet:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.problems = []           # E-S3: unreadable lines, (file, number)

    # -- the folder ------------------------------------------------------------

    @property
    def keys_dir(self):
        return self.folder / "keys"

    def exists(self):
        return self.folder.is_dir()

    def create(self):
        """First run: the folder (0700), keys/, an empty ledger, an empty roster."""
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.folder, 0o700)
        self.keys_dir.mkdir(mode=0o700, exist_ok=True)
        ledger = self.folder / LEDGER
        if not ledger.exists():
            fd = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)        # the engine writes the header with its first line
        roster = self.folder / ROSTER
        if not roster.exists():
            fd = os.open(roster, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(ROSTER_HEADER)

    # -- key sets --------------------------------------------------------------

    def keysets(self):
        """[(file name, mtime)] of the .dec files in keys/, newest first."""
        if not self.keys_dir.is_dir():
            return []
        out = []
        for p in self.keys_dir.iterdir():
            if p.suffix.lower() == ".dec" and p.is_file() and not p.name.startswith("."):
                out.append((p.name, p.stat().st_mtime))
        out.sort(key=lambda x: (-x[1], x[0]))
        return out

    def current_name(self):
        """The current key set's file name, or None."""
        try:
            name = (self.folder / CURRENT).read_text().strip()
        except OSError:
            return None
        return name or None

    def current_path(self):
        name = self.current_name()
        return self.keys_dir / name if name else None

    def current_missing(self):
        """E-S2: current-keyset names a file that isn't there."""
        p = self.current_path()
        return p is not None and not p.is_file()

    def set_current(self, name):
        tmp = self.folder / (CURRENT + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write((name or "") + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp, self.folder / CURRENT)

    def keyset_sha(self, name):
        try:
            return keysmod.sha256_file(self.keys_dir / name)
        except OSError:
            return None

    # -- the ledger --------------------------------------------------------------

    def ledger(self):
        lines = []
        self.problems = [p for p in self.problems if p[0] != LEDGER]
        try:
            text = (self.folder / LEDGER).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return lines
        for n, raw in enumerate(text.split("\n"), start=1):
            if not raw.strip() or raw.startswith("#"):
                continue
            f = raw.split("\t")
            if len(f) not in (8, 9) or len(f[5]) != 64 or not f[1]:
                self.problems.append((LEDGER, n))
                continue
            lines.append(LedgerLine(n, f[0], f[1].lower(), f[2], f[3], f[4], f[5].lower(),
                                    f[6], f[7], f[8] if len(f) > 8 else None))
        return lines

    def history(self, a207):
        a = a207.lower()
        return [l for l in self.ledger() if l.a207 == a]

    def keys_status(self, a207, current_sha, ledger=None, unknown=None):
        """current / old / none from the ledger's last line for the unit, or
        unknown when a key write to it broke off (E-K4): that overrides the
        ledger everywhere a status is shown or counted."""
        ledger = self.ledger() if ledger is None else ledger
        mine = [l for l in ledger if l.a207 == a207.lower()]
        unknown = self.keys_unknown() if unknown is None else unknown
        if a207.lower() in unknown:
            return KeysStatus("unknown", mine[-1] if mine else None)
        if not mine:
            return KeysStatus("none")
        last = mine[-1]
        if current_sha and last.sha256 == current_sha.lower():
            return KeysStatus("current", last)
        return KeysStatus("old", last)

    # -- the roster ----------------------------------------------------------------

    def roster(self):
        units = []
        self.problems = [p for p in self.problems if p[0] != ROSTER]
        try:
            text = (self.folder / ROSTER).read_text(encoding="utf-8", errors="surrogateescape")
        except OSError:
            return units
        for n, raw in enumerate(text.split("\n"), start=1):
            if not raw.strip() or raw.startswith("#"):
                continue
            f = raw.split("\t")
            if len(f) < 4 or not f[0]:
                self.problems.append((ROSTER, n))
                continue
            f += ["-"] * (6 - len(f))
            flags = [x for x in f[5].split(",") if x and x != "-"]
            units.append(Unit(f[0].lower(), dash(f[1]), dash(f[2]), dash(f[3]), dash(f[4]),
                              flags, f[6:]))
        return units

    def unit(self, a207):
        for u in self.roster():
            if u.a207 == a207.lower():
                return u
        return None

    def set_label(self, a207, label):
        label = " ".join((label or "").replace("\t", " ").split())
        self._edit_roster(a207, label=label or "-")

    def set_hidden(self, a207, hidden):
        self._edit_roster(a207, flag=("hidden", hidden))

    def set_keys_unknown(self, a207, unknown):
        """Persist E-K4: a key write to this unit broke off part-way, so its
        key table is unknown whatever the ledger's last line says. Cleared by
        the next completed key write or a record made by hand."""
        self._edit_roster(a207, flag=("keys_unknown", unknown), add=unknown)

    def keys_unknown(self):
        return {u.a207 for u in self.roster() if "keys_unknown" in u.flags}

    def set_codeplug_incomplete(self, a207, image=None):
        """A codeplug write to this unit broke off or didn't verify. Keep the
        image it was writing, so the recovery writes that image whole (-w)
        and never a conf over the damaged radio. image=None clears it."""
        rec = self.folder / "recovery"
        target = rec / ("%s.img" % a207.lower())
        if image is not None:
            rec.mkdir(mode=0o700, exist_ok=True)
            tmp = rec / (".%s.tmp" % a207.lower())
            data = Path(image).read_bytes()
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp, target)
            self._edit_roster(a207, flag=("codeplug_incomplete", True), add=True)
        else:
            self._edit_roster(a207, flag=("codeplug_incomplete", False))
            if target.exists():
                target.unlink()

    def codeplug_incomplete(self, a207):
        """The image an unfinished write was writing, or None."""
        u = self.unit(a207)
        p = self.folder / "recovery" / ("%s.img" % a207.lower())
        return p if u is not None and "codeplug_incomplete" in u.flags and p.is_file() else None

    def _read_roster_text(self, path):
        try:
            # Hand edits may hold any bytes; keep them as they are.
            return path.read_text(encoding="utf-8", errors="surrogateescape")
        except FileNotFoundError:
            return ROSTER_HEADER

    @staticmethod
    def _roster_edited(text, a207, label, flag, add):
        """The roster text with one unit's label or flags changed, or None
        when nothing changes."""
        out, found = [], False
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        for raw in lines:
            f = raw.split("\t")
            if raw and not raw.startswith("#") and f[0].lower() == a207:
                found = True
                f += ["-"] * (6 - len(f))
                if label is not None:
                    f[2] = label
                if flag is not None:
                    name, on = flag
                    flags = [x for x in f[5].split(",") if x and x != "-" and x != name]
                    if on:
                        flags.append(name)
                    f[5] = ",".join(flags) or "-"
                raw = "\t".join(f)
            out.append(raw)
        if not found:
            if not add:
                return None
            flags = flag[0] if flag and flag[1] else "-"
            out.append("\t".join([a207, "-", label or "-", "-", "-", flags]))
        new = "\n".join(out) + "\n"
        return None if new == text else new

    def _edit_roster(self, a207, label=None, flag=None, add=False):
        """Change one unit's label or flags under the engine's own lock, and
        replace the file atomically, as the engine does. `add` appends a line
        for a unit the roster doesn't have yet. An edit that changes nothing
        takes no lock and writes nothing, so clearing a flag that isn't set
        works in a fleet folder that can't be written."""
        a207 = a207.lower()
        path = self.folder / ROSTER
        if self._roster_edited(self._read_roster_text(path), a207, label, flag, add) is None:
            return
        lockfd = os.open(self.folder / ROSTER_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX)
            new = self._roster_edited(self._read_roster_text(path), a207, label, flag, add)
            if new is None:
                return
            tmp = path.with_name("%s.tmp.%d" % (ROSTER, os.getpid()))
            try:
                fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as fh:
                    fh.write(new)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.rename(tmp, path)
            except BaseException:
                if tmp.exists():
                    tmp.unlink()
                raise
        finally:
            os.close(lockfd)
