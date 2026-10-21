#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a desktop launcher for this TYTcps checkout, for the current user.

Writes $XDG_DATA_HOME/applications/tytcps.desktop (default
~/.local/share/applications) and the icon into
$XDG_DATA_HOME/icons/hicolor/scalable/apps/tytcps.svg. The launcher runs
bin/tytcps from wherever this checkout is; nothing about any one machine is
written into the repository. Remove with --remove.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
DESKTOP = DATA / "applications" / "tytcps.desktop"
ICON = DATA / "icons" / "hicolor" / "scalable" / "apps" / "tytcps.svg"

ENTRY = """[Desktop Entry]
Type=Application
Name=TYTcps
GenericName=Radio programmer
Comment=Program TYT MD-UV390 Plus radios, AES privacy keys included
Exec="{exe}" %f
Icon=tytcps
Terminal=false
Categories=Utility;HamRadio;
Keywords=TYT;DMR;MD-UV390;codeplug;CPS;radio;
StartupWMClass=tytcps
"""


def main(argv):
    if "--remove" in argv:
        for p in (DESKTOP, ICON):
            if p.exists():
                p.unlink()
                print("removed", p)
        return 0
    exe = REPO / "bin" / "tytcps"
    if not (REPO / "tytcps" / "libexec" / "dmrconfig-tyt").exists():
        print("Build the engine first: make", file=sys.stderr)
        return 1
    DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    ICON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / "tytcps" / "data" / "tytcps.svg", ICON)
    DESKTOP.write_text(ENTRY.format(exe=str(exe).replace("\\", "\\\\").replace('"', '\\"')))
    os.chmod(DESKTOP, 0o644)
    for cmd in (["update-desktop-database", str(DESKTOP.parent)],
                ["gtk-update-icon-cache", "-q", "-t", str(DATA / "icons" / "hicolor")]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            pass
    print("installed", DESKTOP)
    print("icon     ", ICON)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
