#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the README screenshots offscreen, from fictional data only.

    python3 tools/screenshots.py docs/screenshots

The codeplug is tests/fixtures/demo.conf, the key set is random, the radios
and ledger lines are made up, and the radio is tests/fake_engine.py, which
never opens USB. Nothing from a real fleet folder is read.
"""

import os
import shutil
import sys
import time
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    from tests.common import World
    os.environ["TYTCPS_ENGINE"] = str(REPO / "tests" / "fake_engine.py")
    os.environ["FAKE_DELAY"] = "0.01"
    os.environ["FAKE_A207"] = "a1b2aa000000000000000000c0dec3d4"
    w = World()
    radio = w.root / "radio.img"
    shutil.copyfile(w.demo_image(), radio)
    os.environ["FAKE_IMAGE"] = str(radio)

    from PyQt6.QtWidgets import QApplication
    app = QApplication(["tytcps"])
    app.setStyle("Fusion")
    from tytcps.backend import keys, usb
    from tytcps.backend.usb import UsbRadio
    dev = [7]
    usb.scan = lambda: [UsbRadio("1-9", 1, dev[0], True)]

    ks = keys.KeySet()
    for slot, t, n in ((1, "AES256", "Fleet-A"), (2, "AES128", "Fleet-B"), (3, "ARC4", "Legacy")):
        s = ks.slots[slot - 1]
        s.type, s.name, s.key = t, n, keys.generate(t)
    name, sha = keys.save_new(w.engine, ks, w.fleet.keys_dir)
    w.fleet.set_current(name)
    old = "%064x" % 0xABCDEF
    roster = w.fleet.folder / "radios.tsv"
    with open(roster, "a") as f:
        f.write("a1b2aa000000000000000000c0dec3d4\t1001\tTruck 3\t2026-10-11T19:40:00-0800\t2026-10-11T19:41:10-0800\t-\n")
        f.write("e5f6aa000000000000000000c0de7a8b\t1002\tTruck 5\t2026-10-11T19:52:00-0800\t2026-10-11T19:53:30-0800\t-\n")
        f.write("90abaa000000000000000000c0decd12\t1003\t-\t2026-10-11T20:05:00-0800\t-\t-\n")
    with open(w.fleet.folder / "ledger.tsv", "w") as f:
        f.write("#when\ta207\tserial\tdmr_id\tlabel\tdec_sha256\tdec_file\ttool\tnote\n")
        f.write("2026-06-02T10:00:00-0800\te5f6aa000000000000000000c0de7a8b\t000002\t1002\tTruck 5\t%s\tkeys/fleet-2026-06-02.dec\t1.1.264\t-\n" % old)
        f.write("2026-10-11T19:45:00-0800\ta1b2aa000000000000000000c0dec3d4\t000001\t1001\tTruck 3\t%s\tkeys/%s\t1.1.264\t-\n" % (sha, name))

    from tytcps.ui.context import Context
    from tytcps.ui.jobs import JobRunner
    from tytcps.ui.mainwindow import MainWindow
    from tytcps.ui.dialogs import WriteCodeplugDialog
    from tytcps.ui.preview import PreviewPanel
    from tytcps.backend import radio as R
    check = w.engine.check()
    runner = JobRunner(w.engine)
    runner.radio_finished.connect(lambda res: dev.__setitem__(0, dev[0] + 1))   # the restart
    ctx = Context(w.engine, w.fleet, runner, w.runtime, check)
    win = MainWindow(ctx)
    win.resize(1280, 760)
    win.show()

    def pump(sec=0.0, until=None, timeout=15):
        t = time.time()
        while True:
            app.processEvents()
            if until and until():
                return
            if not until and time.time() - t >= sec:
                return
            if time.time() - t > timeout:
                raise SystemExit("timed out")
            time.sleep(0.01)

    runner.run_radio(R.identify())
    pump(until=lambda: not runner.busy)
    pump(until=lambda: win.bar.state == "identified")
    win.open_file(str(radio))
    pump(1.0)
    m = win.channels.digital.model
    r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
    m.setData(m.index(r, 13), "Basic")
    pump(until=lambda: win.preview_ctl.state() == "clean")
    win.tabs.setCurrentIndex(next(i for i in range(win.tabs.count())
                                  if win.tabs.tabText(i).startswith("Channels")))
    win.channels.digital.view.setCurrentIndex(m.index(r, 13))
    pump(0.4)
    win.grab().save(str(out / "channels.png"))

    p = PreviewPanel(win.preview_ctl.current(), win)
    p.show()
    pump(0.3)
    p.grab().save(str(out / "preview.png"))
    p.close()

    d = WriteCodeplugDialog(ctx, win.preview_ctl, win)
    d.show()
    pump(until=lambda: d.preview is not None)
    pump(0.3)
    d.adjustSize()
    pump(0.2)
    d.grab().save(str(out / "write-codeplug.png"))
    d.close()

    win.tabs.setCurrentWidget(win.keys)
    pump(0.3)
    win.grab().save(str(out / "keys.png"))
    win.tabs.setCurrentWidget(win.fleet)
    pump(0.3)
    win.grab().save(str(out / "fleet.png"))
    ctx.codeplug = None
    win.close()
    w.close()
    print("screenshots in", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(REPO / "docs" / "screenshots"))
