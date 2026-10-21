# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio operations, one engine run each.

Each function returns a Command; the caller runs it (ui.jobs for the GUI,
Engine.run for the CLI and tests). Every one of these opens the radio, which
shows "PC Programming Mode" and restarts at the end of the session, identify
included: the radio is back on USB about 2.7 s later.
"""

from .engine import Command
from .fleet import short_unit

# Seconds the radio takes to come back on USB after a run (O3: 2.70-2.73 s),
# and how long to wait for it before treating it as gone.
RESTART_SECONDS = 2.7
RESTART_TIMEOUT = 5.0


def identify():
    return Command(["identify"], "dmrconfig identify", radio=True, label="identify")


def read(out_dir, short=str):
    """Two reads that must agree (F4); device.img and device.conf in out_dir."""
    return Command(["-r", "-o", str(out_dir)], "dmrconfig -r -o %s" % short(out_dir),
                   radio=True, label="read")


def _expect(unit):
    """--expect-unit: every write names the unit it is for, and the engine
    refuses any other radio before it reads, erases or sends anything (a
    radio swapped onto the cable during a restart looks the same here)."""
    if not unit:
        raise ValueError("a write needs the unit it is for")
    return ["--expect-unit", unit], "dmrconfig --expect-unit %s" % short_unit(unit)


def write_conf(conf, keyset=None, short=str, *, unit):
    """Apply a conf to the radio: two reads, apply, erase, write, verify."""
    args, disp = _expect(unit)
    if keyset:
        args += ["-F", str(keyset)]
        disp += " -F %s" % short(keyset)
    args += ["-c", str(conf)]
    disp += " -c %s" % short(conf)
    return Command(args, disp, radio=True, label="write-codeplug")


def write_image(image, short=str, *, unit):
    """Write a whole codeplug file as it is (Advanced)."""
    args, disp = _expect(unit)
    return Command(args + ["-w", str(image)], "%s -w %s" % (disp, short(image)),
                   radio=True, label="write-image")


def read_keys():
    """Slot types and names. The radio never returns the keys themselves."""
    return Command(["-k"], "dmrconfig -k", radio=True, label="read-keys")


def write_keys(fleet, keyset_name, *, unit):
    """Send a key set. The fork appends the ledger line itself.

    The run folder gets a `keys` link to the fleet's keys folder, so the
    ledger records the file as keys/<name>, relative to the fleet folder,
    whatever the folder is called on this machine.
    """
    rel = "keys/%s" % keyset_name
    args, disp = _expect(unit)
    return Command(args + ["-K", rel], "%s -K %s" % (disp, rel), radio=True,
                   label="write-keys", links={"keys": str(fleet / "keys")})
