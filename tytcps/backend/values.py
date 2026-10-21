# SPDX-License-Identifier: GPL-3.0-or-later
"""Values the engine's conf parser accepts (uv380.c, util.c), so the grid can
check a cell as it is typed. The engine's offline apply behind the preview
remains the authoritative check."""

import re

POWER = ["High", "Mid", "Low"]
ADMIT_DIGITAL = ["-", "Free", "Color"]
ADMIT_ANALOG = ["-", "Free", "Tone"]
PRIVACY = ["None", "Basic", "Enhanced", "Universal"]
WIDTH = ["12.5", "20", "25"]
CALL_TYPES = ["Group", "Private", "All"]
TOT = [str(s) for s in range(0, 556, 15)]
SQUELCH = [str(n) for n in range(10)]
COLOR = [str(n) for n in range(16)]
SLOTS = ["1", "2"]
MAX_ID = 16777215
# A radio's own ID (Radio ID, Radio ID 1-3): the CPS clamps it here, below the
# All Call ID (cps-field-map.md R8b).
MAX_RADIO_ID = 16776415

CTCSS = ["%.1f" % (t / 10) for t in (
    670, 693, 719, 744, 770, 797, 825, 854, 885, 915,
    948, 974, 1000, 1035, 1072, 1109, 1148, 1188, 1230, 1273,
    1318, 1365, 1413, 1462, 1514, 1567, 1598, 1622, 1655, 1679,
    1713, 1738, 1773, 1799, 1835, 1862, 1899, 1928, 1966, 1995,
    2035, 2065, 2107, 2181, 2257, 2291, 2336, 2418, 2503, 2541)]

DCS = [23, 25, 26, 31, 32, 36, 43, 47, 51, 53, 54, 65, 71, 72, 73, 74, 114, 115,
       116, 122, 125, 131, 132, 134, 143, 145, 152, 155, 156, 162, 165, 172, 174,
       205, 212, 223, 225, 226, 243, 244, 245, 246, 251, 252, 255, 261, 263, 265,
       266, 271, 274, 306, 311, 315, 325, 331, 332, 343, 346, 351, 356, 364, 365,
       371, 411, 412, 413, 423, 431, 432, 445, 446, 452, 454, 455, 462, 464, 465,
       466, 503, 506, 516, 523, 526, 532, 546, 565, 606, 612, 624, 627, 631, 632,
       654, 662, 664, 703, 712, 723, 731, 732, 734, 743, 754]

TONES = ["-"] + CTCSS + ["D%03dN" % d for d in DCS] + ["D%03dI" % d for d in DCS]

BANDS = "136-174 and 400-480 MHz"


def band_ok(mhz):
    # The engine checks the whole MHz (is_valid_frequency(int)).
    m = int(mhz)
    return 136 <= m <= 174 or 400 <= m <= 480


def check_receive(text):
    try:
        f = float(text)
    except ValueError:
        return "Receive %r is not a frequency in MHz." % text
    if not band_ok(f):
        return "Receive %s is outside %s." % (text, BANDS)
    return None


def check_transmit(text, receive):
    try:
        f = float(text)
    except ValueError:
        return "Transmit %r is not a frequency or a +/- offset." % text
    if text[:1] in "+-":
        try:
            f += float(receive)
        except ValueError:
            return None
    if not band_ok(f):
        return "Transmit %s gives %.4f MHz, outside %s." % (text, f, BANDS)
    return None


def check_tone(text):
    t = text.strip()
    if t == "-":
        return None
    m = re.fullmatch(r"[Dd](\d{1,3})([NnIi])", t)
    if m:
        return None if int(m.group(1)) in DCS else "%s is not a DCS code." % t
    try:
        hz = float(t)
    except ValueError:
        return "Tone %r: use -, a CTCSS tone like 100.0, or a DCS code like D023N." % t
    return None if ("%.1f" % hz) in CTCSS else "%s Hz is not a standard CTCSS tone." % t


def check_name(text, limit=16, required=True):
    """A display name (spaces as spaces). The engine stores an empty name as
    "no record", so clearing a name would delete the record: use Delete."""
    if required and not text.strip():
        return "A name is required. To remove this record, use Delete."
    if len(text) > limit:
        return "Names are up to %d characters." % limit
    bad = [c for c in text if (ord(c) < 32 or ord(c) == 127 or c in "\t\n\r\v\f")]
    if bad:
        return "Names can't contain tabs, line breaks or control characters."
    if any(ord(c) > 0xFFFF for c in text):
        return "Emoji and similar characters can't be stored on the radio."
    return None


def check_text(text, limit=144):
    """Message text: printed as-is, but the engine reads '_' back as a space."""
    if not text.strip():
        return "A message needs text. To remove it, use Delete."
    if len(text) > limit:
        return "Messages are up to %d characters." % limit
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return "Messages can't contain tabs, line breaks or control characters."
    if any(ord(c) > 0xFFFF for c in text):
        return "Emoji and similar characters can't be stored on the radio."
    return None
