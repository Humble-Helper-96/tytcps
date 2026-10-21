# SPDX-License-Identifier: GPL-3.0-or-later
"""The codeplug as the engine's conf text, edited row by row.

TYTcps edits the conf TEXT, never the image. This module
parses the text the engine prints into scalars and tables, lets rows be
changed, added, deleted and renumbered, and renders it back with every line
the operator did not change passed through verbatim: comments, blank lines,
column alignment, the trailing "# contact" on digital rows, everything.

The parsing rules are the engine's own (radio_parse_config() in radio.c):
  - a line whose first character is '#' is a comment;
  - a line starting with a non-space character is a parameter if it holds
    ':', otherwise a table header;
  - a line starting with a space is a table row (or an indented comment);
  - blank lines do not end a table, only the next header or parameter does.

Every table in the conf is a complete replacement: the engine erases a table
when it reads the table's first row. A table with no rows is therefore left
as the image had it, which is why the last row of a table cannot be deleted
here (see ConfDocument.can_delete).
"""

import itertools
import re

# Grid columns per table, in conf order. Zones merge the engine's "1a" and
# "1b" lines (channel lists A and B) into one row.
COLUMNS = {
    "Digital": ["#", "Name", "Receive", "Transmit", "Power", "Scan", "TOT", "RO",
                "Admit", "Color", "Slot", "RxGL", "TxContact", "Privacy", "Key"],
    "Analog": ["#", "Name", "Receive", "Transmit", "Power", "Scan", "TOT", "RO",
               "Admit", "Sq", "RxTone", "TxTone", "Width"],
    "Zone": ["#", "Name", "Channels A", "Channels B"],
    "Scanlist": ["#", "Name", "PCh1", "PCh2", "TxCh", "Channels"],
    "Contact": ["#", "Name", "Type", "ID", "RxTone"],
    "Grouplist": ["#", "Name", "Contacts"],
    "Message": ["#", "Text"],
    # The stock CPS's other pages (engine cpsfields.c). Menu and Buttons rows
    # are keyed by name; the others by number.
    "Menu": ["Item", "Shown"],
    "Buttons": ["Key", "Short", "Long"],
    "OneTouch": ["#", "Mode", "Call", "CallType", "Message"],
    "NumberKey": ["#", "Contact"],
    "ScanTiming": ["#", "Hold[ms]", "Sample[ms]"],
    "ChanDigital": ["#", "Width", "Sq", "RxRef", "TxRef", "Rekey", "AS", "LW", "VOX", "TA",
                    "PCC", "EAA", "DCC", "AI", "DCDM", "Leader", "EmSys", "InCall", "MsgFmt"],
    "ChanAnalog": ["#", "RxRef", "TxRef", "Rekey", "AS", "LW", "VOX", "TA", "RxSig", "TxSig",
                   "QTRev", "TurnOff", "PTTID", "RevBurst", "Decode"],
    # Digit Emergency System, DTMF Signaling (7.6).
    "EmergencySystem": ["#", "Name", "AlarmType", "AlarmMode", "TxInt", "Impolite", "Polite",
                        "HotMic[s]", "Revert"],
    "DTMFSystem": ["#", "FirstDelay[ms]", "FirstTime[ms]", "Duration[ms]", "Interval[ms]",
                   "StarHash[ms]", "DKey[ms]", "NextSeq[s]", "AutoReset[s]", "SideTone", "PTTID",
                   "GroupCode", "KeyUp", "KeyDown"],
    "DTMFEncode": ["#", "Code"],
    "DTMFDecode": ["#", "ID", "Response", "DecodeType", "ACK", "ACKDelay[ms]", "Revert"],
}

# Tables whose rows are keyed by a name, not a record number.
KEYED = ("Menu", "Buttons")
# Tables that describe records of other tables: rows are never added or
# deleted by hand, only changed (and dropped with the record they describe).
FIXED = ("Menu", "Buttons", "OneTouch", "NumberKey", "ScanTiming", "ChanDigital", "ChanAnalog",
         "DTMFSystem", "DTMFEncode", "DTMFDecode")
# Emergency systems are numbered without gaps: one is added after the last
# and only the last is deleted. A deleted one stays in the conf as a row
# whose cells are all "-", which is how the engine is told to delete it
# (an absent row would leave it as it is).
DASH_DELETE = ("EmergencySystem",)

# Order the engine prints the tables in.
TABLE_ORDER = ["Digital", "Analog", "Zone", "Scanlist", "Contact", "Grouplist", "Message",
               "Menu", "Buttons", "OneTouch", "NumberKey", "ScanTiming", "ChanDigital",
               "ChanAnalog", "EmergencySystem", "DTMFSystem", "DTMFEncode", "DTMFDecode"]

# The engine's header lines, used only when a table that was absent (the
# engine prints a table only when it has entries) gets its first row.
HEADERS = {
    "Digital": "Digital Name             Receive   Transmit Power Scan TOT RO Admit  Color Slot RxGL TxContact Privacy   Key",
    "Analog": "Analog  Name             Receive   Transmit Power Scan TOT RO Admit  Sq RxTone TxTone Width",
    "Zone": "Zone    Name             Channels",
    "Scanlist": "Scanlist Name             PCh1 PCh2 TxCh Channels",
    "Contact": "Contact Name             Type    ID       RxTone",
    "Grouplist": "Grouplist Name             Contacts",
    "Message": "Message Text",
    "Menu": "Menu     Item                Shown",
    "Buttons": "Buttons  Key            Short                    Long",
    "OneTouch": "OneTouch Mode    Call  CallType Message",
    "NumberKey": "NumberKey Contact",
    "ScanTiming": "ScanTiming  Hold[ms] Sample[ms]",
    "ChanDigital": "ChanDigital Width Sq    RxRef  TxRef  Rekey AS LW VOX TA PCC EAA DCC AI DCDM Leader EmSys InCall MsgFmt",
    "ChanAnalog": "ChanAnalog  RxRef  TxRef  Rekey AS LW VOX TA RxSig  TxSig  QTRev  TurnOff PTTID RevBurst Decode",
    "EmergencySystem": "EmergencySystem Name             AlarmType      AlarmMode                         TxInt Impolite Polite HotMic[s] Revert",
    "DTMFSystem": "DTMFSystem  FirstDelay[ms] FirstTime[ms] Duration[ms] Interval[ms] StarHash[ms] DKey[ms] NextSeq[s] AutoReset[s] SideTone PTTID      GroupCode KeyUp            KeyDown",
    "DTMFEncode": "DTMFEncode  Code",
    "DTMFDecode": "DTMFDecode  ID               Response DecodeType ACK   ACKDelay[ms] Revert",
}

# Which diff record kind (the engine's `diff --json`) each table's rows are.
RECORD_KIND = {
    "Digital": "channel", "Analog": "channel", "Zone": "zone",
    "Scanlist": "scanlist", "Contact": "contact", "Grouplist": "grouplist",
    "Message": "message",
    "Menu": "menu", "Buttons": "buttons", "OneTouch": "onetouch", "NumberKey": "numberkey",
    "ScanTiming": "scanlist", "ChanDigital": "channel", "ChanAnalog": "channel",
    "EmergencySystem": "emsystem", "DTMFSystem": "dtmfsystem", "DTMFEncode": "dtmfencode",
    "DTMFDecode": "dtmfdecode",
}

# Scalars that live in the menu and button records, not the general one.
SCALAR_RECORD = {"Menu Hang Time[s]": "menu", "Long Press Duration[ms]": "buttons"}
# The Digit Emergency System page's own settings (record 0x5A70).
EMERGENCY_SCALARS = ("Radio Disable Decode", "Remote Monitor Decode",
                     "Emergency Remote Monitor Decode", "Remote Monitor Duration[s]",
                     "Tx Sync Wakeup TOT[ms]", "Tx Wakeup Message Limit")
for _k in EMERGENCY_SCALARS:
    SCALAR_RECORD[_k] = "emergency"


def scalar_record(name):
    """(diff record kind, index) a scalar lives in: VFO A/B are vfo 1/2."""
    if name.startswith("VFO A "):
        return "vfo", 1
    if name.startswith("VFO B "):
        return "vfo", 2
    return SCALAR_RECORD.get(name, "general"), 0

# Highest record number per table (uv380.c NCHAN, NZONES, ...).
LIMITS = {"Digital": 3000, "Analog": 3000, "Zone": 250, "Scanlist": 250,
          "Contact": 10000, "Grouplist": 250, "Message": 50, "EmergencySystem": 32}

# Members per list cell (uv380.c): zone A 16+48, zone B 64, scan list 31,
# group list 32.
LIST_LIMITS = {("Zone", 2): 64, ("Zone", 3): 64, ("Scanlist", 5): 31,
               ("Grouplist", 2): 32}

SCALARS_EDITABLE = ["ID", "Name", "Intro Line 1", "Intro Line 2"]
SCALARS_READONLY = ["Radio", "Last Programmed Date", "CPS Software Version"]

# The engine reads a conf line with fgets() into 256 bytes, newline included,
# so a row longer than 254 bytes of UTF-8 is cut and its tail read as
# another row.
MAX_LINE = 254

# sscanf("%s") in the engine splits on ASCII whitespace only (no setlocale),
# so a no-break space or U+3000 is part of a name, not a separator.
_WS = re.compile(r"[ \t\n\v\f\r]+")


def tokens(text):
    text = text.strip(" \t\n\v\f\r")
    return _WS.split(text) if text else []

_uid = itertools.count(1)


class ConfParseError(Exception):
    def __init__(self, line, message):
        super().__init__("line %d: %s" % (line + 1, message))
        self.line = line
        self.message = message


def table_kind(header_line):
    """The engine's strncasecmp() match of a header line, or None. The new
    tables are tried first, as the engine does (cps_parse_header)."""
    low = header_line.lower()
    for kind in ("Menu", "Buttons", "OneTouch", "NumberKey", "ScanTiming", "ChanDigital",
                 "ChanAnalog", "EmergencySystem", "DTMFSystem", "DTMFEncode", "DTMFDecode",
                 "Digital", "Analog", "Zone", "Scanlist", "Contact", "Grouplist", "Message"):
        if low.startswith(kind.lower()):
            return kind
    return None


# ---------------------------------------------------------------------------
# Channel and contact lists: "1-2,18,17,7-13,6". Order matters to the radio
# and the engine keeps it, so it is never sorted here.
# ---------------------------------------------------------------------------

def parse_list(text):
    """Numbers in stored order. Raises ValueError on a malformed list."""
    text = text.strip()
    if text in ("", "-"):
        return []
    out = []
    for part in text.split(","):
        if not part:
            raise ValueError("empty item in list %r" % text)
        if "-" in part[1:]:
            a, b = part.split("-", 1)
            a, b = int(a), int(b)
            # The engine adds last+1..cnum, so a descending range adds nothing
            # beyond its first number.
            out.append(a)
            out.extend(range(a + 1, b + 1))
        else:
            out.append(int(part))
    return out


def format_list(numbers):
    """Compact form that keeps order: only ascending runs become ranges."""
    if not numbers:
        return "-"
    parts = []
    i = 0
    n = len(numbers)
    while i < n:
        j = i
        while j + 1 < n and numbers[j + 1] == numbers[j] + 1:
            j += 1
        if j > i:
            parts.append("%d-%d" % (numbers[i], numbers[j]))
        else:
            parts.append(str(numbers[i]))
        i = j + 1
    return ",".join(parts)


# ---------------------------------------------------------------------------

class Row:
    """One record. `cells` are conf tokens, one per COLUMNS entry."""

    def __init__(self, kind, cells, lines=(), comment=None):
        self.kind = kind
        self.cells = list(cells)
        self.lines = tuple(lines)            # original line indices
        self.orig = tuple(cells) if lines else None
        self.comment = comment               # digital rows: "# Contact_1"
        self.uid = next(_uid)
        self.orig_number = self.number if lines else None

    @property
    def number(self):
        m = re.match(r"\d+", self.cells[0])
        return int(m.group()) if m else 0

    @property
    def is_new(self):
        return self.orig is None

    @property
    def edited(self):
        return self.orig is None or tuple(self.cells) != self.orig

    def edited_columns(self):
        if self.orig is None:
            return set(range(len(self.cells)))
        return {i for i, (a, b) in enumerate(zip(self.cells, self.orig)) if a != b}

    def __repr__(self):
        return "Row(%s %r)" % (self.kind, self.cells)


class Table:
    def __init__(self, kind):
        self.kind = kind
        self.header_index = None     # line index of the header, None if absent
        self.header = HEADERS[kind]
        self.rows = []
        self.deleted = []            # rows that had lines in the original text
        self.last_line = None        # index of the last original row line

    def find(self, number):
        for r in self.rows:
            if r.number == number:
                return r
        return None


class Scalar:
    def __init__(self, name, line, value):
        self.name = name
        self.line = line
        self.orig = value
        self.value = value

    @property
    def edited(self):
        return self.value != self.orig


class ConfDocument:
    """Parsed conf text that renders back with unedited lines verbatim."""

    def __init__(self, text):
        self.text = text
        self.lines = text.split("\n")
        self.scalars = {}
        self.tables = {k: Table(k) for k in TABLE_ORDER}
        self.unspaced = set()        # row lines the engine printed without a leading space
        self._parse()

    # -- parsing -----------------------------------------------------------

    def _parse(self):
        current = None
        zone_rows = {}
        for i, raw in enumerate(self.lines):
            line = raw.rstrip(" \t\r\n")
            if not line or line.startswith("#"):
                continue
            if line[0].isdigit() and current is not None:
                # The engine prints a record number of five digits (contact
                # 10000) with no leading space, which its own parser would
                # take for a header. Read it as the row it is; the row is
                # rendered with a space in front.
                self.unspaced.add(i)
                current.last_line = i
                self._parse_row(current, i, line, zone_rows)
                continue
            if line[0] not in " \t":
                current = None
                if ":" in line:
                    name, value = line.split(":", 1)
                    self.scalars[name] = Scalar(name, i, value.strip(" \t"))
                    continue
                kind = table_kind(line)
                if kind is None:
                    raise ConfParseError(i, "unknown table %r" % line.split()[0])
                t = self.tables[kind]
                if t.header_index is not None:
                    raise ConfParseError(i, "table %s appears twice" % kind)
                t.header_index = i
                t.header = line
                current = t
                continue
            body = line.lstrip(" \t")
            if body.startswith("#"):
                continue
            if current is None:
                raise ConfParseError(i, "a table row outside any table")
            current.last_line = i
            self._parse_row(current, i, body, zone_rows)

    def _parse_row(self, t, i, body, zone_rows):
        kind = t.kind
        if kind == "Message":
            m = re.match(r"(\d+)[ \t]*(.*)$", body)
            if not m:
                raise ConfParseError(i, "message row without a number")
            t.rows.append(Row(kind, [m.group(1), m.group(2)], (i,)))
            return
        comment = None
        if kind == "Digital":
            m = re.search(r"(?<=[ \t])#", body)
            if m:
                comment = body[m.start():]
                body = body[:m.start()]
        toks = tokens(body)
        if kind == "Zone":
            if len(toks) < 3:
                raise ConfParseError(i, "a zone row has 3 columns")
            m = re.match(r"(\d+)([aAbB])$", toks[0])
            if not m:
                raise ConfParseError(i, "zone number must be like 1a or 1b")
            num, ab = m.group(1), m.group(2).lower()
            row = zone_rows.get(num)
            if row is None:
                row = Row(kind, [num, "-", "-", "-"], ())
                row._zone_lines = {}
                zone_rows[num] = row
                t.rows.append(row)
            row._zone_lines[ab] = i
            if ab == "a":
                row.cells[1] = toks[1]
                row.cells[2] = toks[2]
            else:
                row.cells[3] = toks[2]
            row.lines = tuple(sorted(row._zone_lines.values()))
            row.orig = tuple(row.cells)
            row.orig_number = row.number
            return
        ncols = len(COLUMNS[kind])
        if kind == "Digital" and len(toks) == 13:
            # An upstream conf: no Privacy/Key columns. Kept as it is; the
            # engine leaves the privacy bytes alone (I-C1).
            toks = toks + ["", ""]
        if len(toks) < ncols:
            raise ConfParseError(i, "a %s row has %d columns; this one has %d"
                                 % (kind, ncols, len(toks)))
        t.rows.append(Row(kind, toks[:ncols], (i,), comment))

    # -- queries -----------------------------------------------------------

    def scalar(self, name, default=""):
        s = self.scalars.get(name)
        return s.value if s else default

    def set_scalar(self, name, value):
        s = self.scalars.get(name)
        if s is None:
            s = self.scalars[name] = Scalar(name, None, None)
        s.value = value

    def rows(self, kind):
        return self.tables[kind].rows

    def is_edited(self):
        if any(s.edited for s in self.scalars.values()):
            return True
        for t in self.tables.values():
            if t.deleted or any(r.edited for r in t.rows):
                return True
        return False

    def edited_records(self):
        """(record kind, number) the operator's edits touch, as `diff` names them."""
        out = set()
        for s in self.scalars.values():
            if s.edited:
                out.add(scalar_record(s.name))
        for t in self.tables.values():
            rk = RECORD_KIND[t.kind]
            for r in t.rows:
                if r.edited:
                    out.add((rk, record_index(t.kind, r.number)))
                    if r.orig_number is not None:
                        out.add((rk, record_index(t.kind, r.orig_number)))
            for r in t.deleted:
                out.add((rk, record_index(t.kind, r.orig_number)))
        return out

    def channel_rows(self):
        return self.rows("Digital") + self.rows("Analog")

    def channel(self, number):
        return self.tables["Digital"].find(number) or self.tables["Analog"].find(number)

    def name_of(self, kind, number):
        if kind in ("Digital", "Analog", "channel"):
            r = self.channel(number)
        else:
            r = self.tables[kind].find(number)
        return r.cells[1] if r else None

    def used_numbers(self, kind):
        if kind in ("Digital", "Analog"):
            return {r.number for r in self.channel_rows()}
        return {r.number for r in self.rows(kind)}

    def next_free_number(self, kind):
        used = self.used_numbers(kind)
        for n in range(1, LIMITS[kind] + 1):
            if n not in used:
                return n
        return None

    def universal_users(self, slot):
        """Digital rows that use key-set slot `slot` (Universal privacy)."""
        return [r for r in self.rows("Digital")
                if r.cells[13].lower() == "universal" and r.cells[14] == str(slot)]

    # -- references --------------------------------------------------------

    def references(self, kind, number):
        """[(row, column)] cells that refer to record `number` of `kind`."""
        refs = []
        n = str(number)
        if kind in ("Digital", "Analog"):
            for r in self.rows("Zone"):
                for c in (2, 3):
                    if number in _safe_list(r.cells[c]):
                        refs.append((r, c))
            for r in self.rows("Scanlist"):
                for c in (2, 3, 4):
                    if r.cells[c] == n:
                        refs.append((r, c))
                if number in _safe_list(r.cells[5]):
                    refs.append((r, 5))
            # Emergency and DTMF decode revert channels (7.6 review 3).
            for r in self.rows("EmergencySystem"):
                if r.cells[8] == n:
                    refs.append((r, 8))
            for r in self.rows("DTMFDecode"):
                if r.cells[6] == n:
                    refs.append((r, 6))
        elif kind == "Scanlist":
            for r in self.channel_rows():
                if r.cells[5] == n:
                    refs.append((r, 5))
        elif kind == "Grouplist":
            for r in self.rows("Digital"):
                if r.cells[11] == n:
                    refs.append((r, 11))
        elif kind == "Contact":
            for r in self.rows("Digital"):
                if r.cells[12] == n:
                    refs.append((r, 12))
            for r in self.rows("Grouplist"):
                if number in _safe_list(r.cells[2]):
                    refs.append((r, 2))
            for r in self.rows("OneTouch"):
                if r.cells[2] == n:
                    refs.append((r, 2))
            for r in self.rows("NumberKey"):
                if r.cells[1] == n:
                    refs.append((r, 1))
        elif kind == "Message":
            for r in self.rows("OneTouch"):
                if r.cells[3] == "Text" and r.cells[4] == n:
                    refs.append((r, 4))
        elif kind == "EmergencySystem":
            col = COLUMNS["ChanDigital"].index("EmSys")
            for r in self.rows("ChanDigital"):
                if r.cells[col] == n:
                    refs.append((r, col))
        return refs

    # The VFO fields that pick a record: (record kind, VFO field).
    VFO_REFS = (("Contact", "Contact Name"), ("Grouplist", "Group List"),
                ("Scanlist", "Scan List"), ("EmergencySystem", "Emergency System"))

    def scalar_references(self, kind, number):
        """The VFOs ("VFO A", "VFO B") whose fields pick record `number` of
        `kind`. An analog VFO's emergency system is greyed out and doesn't
        count: deleting the system clears it."""
        out = []
        for k, field in self.VFO_REFS:
            if k != kind:
                continue
            for v in ("A", "B"):
                if self.scalar("VFO %s %s" % (v, field)) != str(number):
                    continue
                if k == "EmergencySystem" and self.scalar("VFO %s Channel Mode" % v) != "Digital":
                    continue
                out.append("VFO " + v)
        return out

    def emergency_users(self, number):
        """What uses emergency system `number`: channel numbers and VFO names."""
        out = ["channel %d" % r.number for r, c in self.references("EmergencySystem", number)]
        return out + self.scalar_references("EmergencySystem", number)

    def _rewrite_refs(self, kind, mapping):
        """Apply {old: new or None} to every reference to `kind` records."""
        def map_list(text):
            nums = _safe_list(text)
            if nums is None:
                return text
            out = []
            for x in nums:
                if x in mapping:
                    if mapping[x] is not None:
                        out.append(mapping[x])
                else:
                    out.append(x)
            return format_list(out) if out != nums else text

        def map_single(text, gone):
            if text.isdigit() and int(text) in mapping:
                m = mapping[int(text)]
                return gone if m is None else str(m)
            return text

        def map_vfos(field, gone):
            for v in ("A", "B"):
                key = "VFO %s %s" % (v, field)
                if key in self.scalars:
                    new = map_single(self.scalar(key), gone)
                    if new != self.scalar(key):
                        self.set_scalar(key, new)

        if kind in ("Digital", "Analog"):
            for r in self.rows("Zone"):
                for c in (2, 3):
                    _set(r, c, map_list(r.cells[c]))
            for r in self.rows("Scanlist"):
                _set(r, 2, map_single(r.cells[2], "-"))
                _set(r, 3, map_single(r.cells[3], "-"))
                _set(r, 4, map_single(r.cells[4], "Last"))
                _set(r, 5, map_list(r.cells[5]))
            # A revert to a deleted channel becomes None / Selected, as the
            # CPS resets it when its page opens.
            for r in self.rows("EmergencySystem"):
                _set(r, 8, map_single(r.cells[8], "-"))
            for r in self.rows("DTMFDecode"):
                _set(r, 6, map_single(r.cells[6], "Selected"))
            self._rekey("ChanDigital", mapping)
            self._rekey("ChanAnalog", mapping)
        elif kind == "EmergencySystem":
            for v in ("A", "B"):
                if self.scalar("VFO %s Channel Mode" % v) != "Digital":
                    key = "VFO %s Emergency System" % v
                    new = map_single(self.scalar(key), "-")
                    if key in self.scalars and new != self.scalar(key):
                        self.set_scalar(key, new)
        elif kind == "Scanlist":
            for r in self.channel_rows():
                _set(r, 5, map_single(r.cells[5], "-"))
            self._rekey("ScanTiming", mapping)
            map_vfos("Scan List", "-")
        elif kind == "Message":
            for r in self.rows("OneTouch"):
                if r.cells[3] == "Text":
                    _set(r, 4, map_single(r.cells[4], "-"))
        elif kind == "Grouplist":
            for r in self.rows("Digital"):
                _set(r, 11, map_single(r.cells[11], "-"))
            map_vfos("Group List", "-")
        elif kind == "Contact":
            map_vfos("Contact Name", "-")
            for r in self.rows("Digital"):
                _set(r, 12, map_single(r.cells[12], "-"))
            for r in self.rows("Grouplist"):
                _set(r, 2, map_list(r.cells[2]))
            for r in self.rows("OneTouch"):
                c = r.cells[2]
                if c.isdigit() and int(c) in mapping and mapping[int(c)] is None:
                    # The CPS's rule (map 2.4): a row whose contact is
                    # deleted becomes Mode None with no contact.
                    set_onetouch_mode(r, "None")
                    _set(r, 2, "-")
                else:
                    _set(r, 2, map_single(c, "-"))
            for r in self.rows("NumberKey"):
                _set(r, 1, map_single(r.cells[1], "-"))

    def onetouch_mode(self, number, mode, contacts=None, messages=None):
        """Change One Touch row `number`'s Mode the way the CPS does (map
        2.4): Digital gets Text, message 1, contact 1; Analog gets DTMF-1,
        encode 1, contact 1; None keeps the rest, its call type written
        the way the engine prints it under None (raw:0xN). A contact or
        message that doesn't exist becomes -."""
        r = self.tables["OneTouch"].find(number)
        if r is None or r.cells[1] == mode:
            return False
        have_c = {x.cells[0] for x in self.rows("Contact")} if contacts is None else contacts
        have_m = {x.cells[0] for x in self.rows("Message")} if messages is None else messages
        set_onetouch_mode(r, mode)
        if mode == "Digital":
            _set(r, 3, "Text")
            _set(r, 4, "1" if "1" in have_m else "-")
        elif mode == "Analog":
            _set(r, 3, "DTMF-1")
            _set(r, 4, "1")
        if mode in ("Digital", "Analog"):
            _set(r, 2, "1" if "1" in have_c else "-")
        return True

    def _rekey(self, kind, mapping):
        """Rows keyed by another table's record number follow it: renumbered
        with it, dropped with it."""
        t = self.tables[kind]
        for r in list(t.rows):
            n = r.number
            if n not in mapping:
                continue
            if mapping[n] is None:
                t.rows.remove(r)
                if not r.is_new:
                    t.deleted.append(r)
            else:
                _set(r, 0, str(mapping[n]))

    # -- edits -------------------------------------------------------------

    def can_delete(self, kind, rows):
        """None if the rows may be deleted, else the reason."""
        if kind in ("Digital", "Analog"):
            if len(self.channel_rows()) - len(rows) < 1:
                return ("A codeplug needs at least one channel.")
            return None
        if kind == "EmergencySystem":
            numbers = sorted(r.number for r in self.rows(kind))
            gone = sorted(r.number for r in rows)
            if gone != numbers[len(numbers) - len(gone):]:
                return ("Emergency systems are numbered without gaps: delete from the last one.")
            for n in gone:
                users = self.emergency_users(n)
                if users:
                    return ("Emergency system %d is used by %s." % (n, ", ".join(users)))
        if len(self.rows(kind)) - len(rows) < 1:
            return ("This table needs at least one row.")
        return None

    def delete_rows(self, kind, rows):
        """Delete rows and drop every reference to them."""
        t = self.tables[kind]
        mapping = {}
        for r in rows:
            if r in t.rows:
                t.rows.remove(r)
                if not r.is_new:
                    t.deleted.append(r)
                mapping[r.number] = None
        self._rewrite_refs(kind, mapping)

    def add_row(self, kind, cells=None, after=None):
        """A new row with the lowest free number; `cells` without the number."""
        t = self.tables[kind]
        n = self.next_free_number(kind)
        if n is None:
            return None
        if cells is None:
            cells = default_cells(kind)
            if kind == "EmergencySystem":
                cells[0] = "System%d" % n
        row = Row(kind, [str(n)] + list(cells))
        if after is not None and after in t.rows:
            t.rows.insert(t.rows.index(after) + 1, row)
        else:
            t.rows.append(row)
        return row

    def add_detail_row(self, kind, number, cells):
        """A ChanDigital/ChanAnalog/ScanTiming row for a record just added."""
        t = self.tables[kind]
        if t.find(number) is not None:
            return t.find(number)
        row = Row(kind, [str(number)] + list(cells))
        t.rows.append(row)
        t.rows.sort(key=lambda r: r.number)
        return row

    def duplicate_row(self, row):
        return self.add_row(row.kind, row.cells[1:], after=row)

    def swap_numbers(self, kind, a, b):
        """Exchange the record numbers of rows a and b, keeping references."""
        na, nb = a.number, b.number
        _set_number(a, nb)
        _set_number(b, na)
        self._rewrite_refs(kind, {na: nb, nb: na})
        rows = self.tables[kind].rows
        ia, ib = rows.index(a), rows.index(b)
        rows[ia], rows[ib] = rows[ib], rows[ia]

    def revert(self):
        """Back to the text as parsed."""
        self.__init__(self.text)

    # -- rendering ---------------------------------------------------------

    def render(self):
        """The conf text: original lines where nothing changed."""
        out_lines = list(self.lines)
        replace = {}      # line index -> list of lines (empty list = drop)
        for s in self.scalars.values():
            if s.edited:
                text = "%s: %s" % (s.name, s.value)
                if s.line is None:
                    replace.setdefault(self._scalar_anchor(), []).append(text)
                else:
                    replace[s.line] = [text]
        appended_tables = []
        for kind in TABLE_ORDER:
            t = self.tables[kind]
            for r in t.deleted:
                for i in r.lines:
                    replace[i] = []
                if kind in DASH_DELETE and r.lines:
                    replace[r.lines[0]] = [format_row(t.header, [str(r.orig_number)] +
                                                      ["-"] * (len(COLUMNS[kind]) - 1))]
            new_rows = []
            for r in t.rows:
                if r.is_new:
                    new_rows.append(r)
                    continue
                rendered = self._render_row(t, r)
                for k, i in enumerate(r.lines):
                    replace[i] = [rendered[k]] if k < len(rendered) else []
                for extra in rendered[len(r.lines):]:
                    replace[r.lines[-1]].append(extra)
            if new_rows:
                text = []
                for r in new_rows:
                    text += self._render_row(t, r)
                if t.header_index is not None:
                    anchor = t.last_line if t.last_line is not None else t.header_index
                    base = replace.get(anchor, [out_lines[anchor]])
                    replace[anchor] = base + text
                else:
                    appended_tables.append((kind, [HEADERS[kind]] + text))
        result = []
        for i, line in enumerate(out_lines):
            if i in replace:
                result.extend(replace[i])
            else:
                result.append(line)
        if appended_tables:
            result = self._insert_tables(result, appended_tables)
        return "\n".join(result)

    def row_bytes(self, row):
        """Longest rendered line of a row, in UTF-8 bytes (MAX_LINE)."""
        t = self.tables[row.kind]
        return max((len(l.encode("utf-8")) for l in self._render_row(t, row)), default=0)

    def _scalar_anchor(self):
        # A scalar that was absent goes after the last scalar line.
        lines = [s.line for s in self.scalars.values() if s.line is not None]
        return max(lines) if lines else len(self.lines) - 1

    def _render_row(self, t, r):
        if not r.edited:
            return [(" " + self.lines[i]) if i in self.unspaced else self.lines[i] for i in r.lines]
        if t.kind == "Zone":
            a = format_row(t.header, [r.cells[0] + "a", r.cells[1], r.cells[2]])
            b = format_row(t.header, [r.cells[0] + "b", "-", r.cells[3]])
            return [a, b]
        if t.kind == "Message":
            return [format_message(r.cells[0], r.cells[1])]
        if t.kind in KEYED:
            return [format_keyed(t.header, r.cells)]
        cells = list(r.cells)
        if t.kind == "Digital" and cells[13] == "" and cells[14] == "":
            cells = cells[:13]           # an upstream row stays upstream
        line = format_row(t.header, cells)
        if t.kind == "Digital":
            name = self.name_of("Contact", int(cells[12])) if cells[12].isdigit() else None
            if name:
                line += "   # " + name
        return [line]

    def _insert_tables(self, result, tables):
        """Insert whole new tables before the next table in engine order."""
        for kind, block in tables:
            later = TABLE_ORDER[TABLE_ORDER.index(kind) + 1:]
            pos = None
            for i, line in enumerate(result):
                if line and line[0] not in " \t#" and ":" not in line and table_kind(line) in later:
                    pos = i
                    # Step back over the comment block that introduces it.
                    while pos > 0 and result[pos - 1].startswith("#"):
                        pos -= 1
                    break
            if pos is None:
                for i, line in enumerate(result):
                    if line.startswith("ID:") or line.startswith("# Unique DMR ID"):
                        pos = i
                        break
            if pos is None:
                pos = len(result)
            result[pos:pos] = block + [""]
        return result


# ---------------------------------------------------------------------------

def _safe_list(text):
    try:
        return parse_list(text)
    except ValueError:
        return None


def _set(row, col, value):
    if row.cells[col] != value:
        row.cells[col] = value


ONETOUCH_TYPES = {"Call": 0, "Text": 1, "DTMF-1": 8, "DTMF-2": 9, "DTMF-3": 10, "DTMF-4": 11}


def set_onetouch_mode(row, mode):
    """Set a One Touch row's Mode. A call type word that the new mode doesn't
    show (Call/Text are Digital's, DTMF-n Analog's) is rewritten as the raw
    value the engine prints for it, so the row still says what is stored."""
    _set(row, 1, mode)
    t = row.cells[3]
    ok = {"Digital": ("Call", "Text"), "Analog": ("DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4")}
    if t in ONETOUCH_TYPES and t not in ok.get(mode, ()):
        _set(row, 3, "raw:0x%X" % ONETOUCH_TYPES[t])


def _set_number(row, n):
    row.cells[0] = str(n)


def default_cells(kind):
    """A new row's cells after the number, as the CPS would fill them."""
    return {
        "Digital": ["Channel", "400.000", "+0", "Low", "-", "60", "-", "Color",
                    "1", "1", "-", "-", "None", "-"],
        "Analog": ["Channel", "400.000", "+0", "Low", "-", "60", "-", "-", "4",
                   "-", "-", "12.5"],
        "Zone": ["Zone", "-", "-"],
        "Scanlist": ["Scan_list", "-", "-", "Last", "-"],
        "Contact": ["Contact", "Group", "1", "-"],
        "Grouplist": ["Group_list", "-"],
        "Message": ["Message"],
        # The CPS's Add (0x4453e0): Regular, Emergency Alarm, 15, 5, 10 s.
        "EmergencySystem": ["System", "Regular", "Emergency_Alarm", "-", "15", "5", "10", "-"],
    }[kind]


def header_columns(header):
    """Start column of each header token."""
    return [m.start() for m in re.finditer(r"\S+", header)]


def format_row(header, cells):
    """A row aligned under `header` the way the engine prints it.

    The record number is right-aligned to end at column 5, as "%5d" does;
    every other value starts under its header word, or one space after the
    previous value if that one is too long. A row always starts with a space,
    since the engine reads a line starting with anything else as a header.
    """
    starts = header_columns(header)
    first = cells[0]
    line = first.rjust(5) if len(first) < 5 else " " + first
    for k, cell in enumerate(cells[1:], start=1):
        col = starts[k] if k < len(starts) else len(line) + 1
        if len(line) < col:
            line += " " * (col - len(line))
        else:
            line += " "
        line += cell
    return line


def record_index(kind, number):
    """The diff's index for a row: number keys count from 0, the diff from 1;
    Menu and Buttons are single records (0)."""
    if kind in KEYED:
        return 0
    if kind == "NumberKey":
        return number + 1
    return number


def format_keyed(header, cells):
    """A Menu or Buttons row: each value under its header word (the first
    header word is the table's name, so the row starts under the second)."""
    starts = header_columns(header)
    line = ""
    for k, cell in enumerate(cells, start=1):
        col = starts[k] if k < len(starts) else len(line) + 1
        if len(line) < col:
            line += " " * (col - len(line))
        else:
            line += " "
        line += cell
    return line if line.startswith(" ") else " " + line


def format_message(number, text):
    line = number.rjust(5) + "   " + text
    return line if line.startswith(" ") else " " + line
