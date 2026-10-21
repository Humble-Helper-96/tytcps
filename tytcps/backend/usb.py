# SPDX-License-Identifier: GPL-3.0-or-later
"""Is a radio on the bus? Read from sysfs: no USB I/O.

TYTcps opens no USB device itself. It looks for 0483:df11 under
/sys/bus/usb/devices once a second, and checks whether the device node is
writable with access(). A change of device number is how a restart shows:
the radio leaves the bus when a session ends and comes back 2.7 s later on a
new number.
"""

import grp
import os
import pwd
import re
from dataclasses import dataclass
from pathlib import Path

VENDOR, PRODUCT = "0483", "df11"
SYSFS = Path("/sys/bus/usb/devices")
RULE_DIRS = ["/etc/udev/rules.d", "/run/udev/rules.d", "/usr/lib/udev/rules.d", "/lib/udev/rules.d"]
# Inside a Flatpak the computer's own /etc is at /run/host/etc (the manifest
# asks for it read-only); the sandbox's /etc and /usr are the runtime's.
FLATPAK_RULE_DIRS = ["/run/host/etc/udev/rules.d"]


@dataclass(frozen=True)
class UsbRadio:
    sysfs: str
    busnum: int
    devnum: int
    writable: bool

    @property
    def node(self):
        return "/dev/bus/usb/%03d/%03d" % (self.busnum, self.devnum)

    @property
    def key(self):
        return (self.busnum, self.devnum)


def _read(p):
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def scan():
    """Every 0483:df11 on the bus."""
    found = []
    try:
        entries = list(SYSFS.iterdir())
    except OSError:
        return found
    for d in entries:
        if ":" in d.name:
            continue
        if _read(d / "idVendor").lower() != VENDOR or _read(d / "idProduct").lower() != PRODUCT:
            continue
        try:
            bus, dev = int(_read(d / "busnum")), int(_read(d / "devnum"))
        except ValueError:
            continue
        node = "/dev/bus/usb/%03d/%03d" % (bus, dev)
        found.append(UsbRadio(d.name, bus, dev, os.access(node, os.R_OK | os.W_OK)))
    found.sort(key=lambda r: r.key)
    return found


@dataclass
class UdevRule:
    path: str
    group: str = None        # GROUP="..." if the rule sets one
    world: bool = False      # MODE="0666" or similar
    uaccess: bool = False    # TAG+="uaccess": the logged-in user gets access


def find_rule():
    """The installed udev rule that covers 0483:df11, or None."""
    for d in (FLATPAK_RULE_DIRS if os.environ.get("FLATPAK_ID") else RULE_DIRS):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if not name.endswith(".rules"):
                continue
            path = os.path.join(d, name)
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("#"):
                    continue
                low = s.lower()
                if '"0483"' in low and '"df11"' in low:
                    g = re.search(r'GROUP\s*=\s*"([^"]+)"', s)
                    m = re.search(r'MODE\s*=\s*"0?([0-7]{3})"', s)
                    return UdevRule(path, g.group(1) if g else None,
                                    bool(m and m.group(1)[2] in "67"),
                                    # uaccess is applied by 73-seat-late.rules,
                                    # so only a rule that runs before it counts
                                    "uaccess" in low and name < "73")
    return None


def user_groups():
    user = pwd.getpwuid(os.getuid()).pw_name
    names = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
    try:
        names.add(grp.getgrgid(os.getgid()).gr_name)
    except KeyError:
        pass
    return names


def session_groups():
    """Groups this process actually has (a new membership needs a new login)."""
    out = set()
    for gid in os.getgroups():
        try:
            out.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            pass
    return out


def access_problem(rule=None):
    """E-U1 / E-U2, or None when this user should be able to open the radio."""
    rule = rule if rule is not None else find_rule()
    if rule is None:
        return "no_rule"
    if rule.world or rule.uaccess:
        return None
    if rule.group and rule.group not in session_groups():
        return "not_in_group"
    return None
