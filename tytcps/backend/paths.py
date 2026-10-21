# SPDX-License-Identifier: GPL-3.0-or-later
"""Where TYTcps keeps things. Nothing is hard-coded to
any one person's folders: everything comes from the XDG variables."""

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

APP = "tytcps"


def in_flatpak():
    return bool(os.environ.get("FLATPAK_ID"))


def data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def default_fleet_folder():
    # Inside a Flatpak, XDG_DATA_HOME is the app's private folder under
    # ~/.var/app; the fleet folder stays where a checkout keeps it, so the
    # ledger and roster are the same whichever way TYTcps was installed.
    if in_flatpak():
        return Path(os.environ.get("HOST_XDG_DATA_HOME")
                    or Path.home() / ".local" / "share") / APP
    return data_home() / APP


def settings_file():
    return config_home() / APP / "settings.ini"


def documents_folder():
    """The user's Documents folder (xdg-user-dir), else ~/Documents."""
    try:
        out = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True,
                             text=True, timeout=2).stdout.strip()
        if out and Path(out).is_dir() and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    p = Path.home() / "Documents"
    return p if p.is_dir() else Path.home()


class RuntimeDir:
    """$XDG_RUNTIME_DIR/tytcps/<pid>/, one subfolder per engine run.

    Every run gets its own folder because an offline apply always writes
    ./device.img. Key material never goes here: key
    sets are written only into the fleet folder. Deleted on exit.
    """

    def __init__(self):
        base = os.environ.get("XDG_RUNTIME_DIR")
        if base and os.path.isdir(base):
            root = Path(base) / APP
        else:
            root = Path(tempfile.gettempdir()) / ("%s-%d" % (APP, os.getuid()))
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.path = root / str(os.getpid())
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        self.path.mkdir(mode=0o700)
        self._n = 0
        self._lock = threading.Lock()

    def new_run(self, label="run"):
        with self._lock:
            self._n += 1
            n = self._n
        d = self.path / ("%03d-%s" % (n, label))
        d.mkdir(mode=0o700)
        return d

    def file(self, name):
        return self.path / name

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)
