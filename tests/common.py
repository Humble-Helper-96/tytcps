# SPDX-License-Identifier: GPL-3.0-or-later
"""Test helpers: a private XDG world, the bundled engine, a fictional codeplug."""

import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO_CONF = HERE / "fixtures" / "demo.conf"


class World:
    """Temporary XDG folders so no test touches the user's own."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="tytcps-test-"))
        self.old = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME",
                                                   "XDG_RUNTIME_DIR", "TYT_STATE_DIR")}
        for k, sub in (("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                       ("XDG_RUNTIME_DIR", "run")):
            (self.root / sub).mkdir(mode=0o700)
            os.environ[k] = str(self.root / sub)
        os.environ.pop("TYT_STATE_DIR", None)
        from tytcps.backend.engine import Engine, locate_engine
        from tytcps.backend.fleet import Fleet
        from tytcps.backend.paths import RuntimeDir, default_fleet_folder
        self.fleet = Fleet(default_fleet_folder())
        self.fleet.create()
        self.runtime = RuntimeDir()
        self.engine = Engine(locate_engine(), self.fleet.folder, self.runtime)

    def demo_image(self):
        """The fictional demo codeplug as an image file."""
        blank = self.root / "blank.img"
        blank.write_bytes(b"\xff" * 851968)
        out = self.root / "demo-out"
        out.mkdir(exist_ok=True)
        from tytcps.backend import codeplug
        r = self.engine.run(codeplug.apply(blank, DEMO_CONF, out))
        assert r.ok, r.stderr
        img = self.root / "demo.img"
        shutil.copyfile(out / "device.img", img)
        return img

    def close(self):
        self.runtime.cleanup()
        shutil.rmtree(self.root, ignore_errors=True)
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
