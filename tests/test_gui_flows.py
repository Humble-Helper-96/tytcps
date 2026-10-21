# SPDX-License-Identifier: GPL-3.0-or-later
"""The GUI's radio flows, offscreen, against tests/fake_engine.py.

No radio is touched: the fake engine never opens USB, and the sysfs watch
is replaced by a simulated device that restarts (new device number) after
every run, as the radio does.
"""

import os
import shutil
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import World

HERE = Path(__file__).resolve().parent


class Robot:
    """Answers modal dialogs from a script while exec() runs."""

    def __init__(self, app):
        from PyQt6.QtCore import QTimer
        self.app = app
        self.script = []          # [(match(widget) -> bool, act(widget))]
        self.seen = []            # (class, text) of every modal seen
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(40)
        self.last = None

    def expect(self, match, act):
        self.script.append((match, act))

    def tick(self):
        from PyQt6.QtWidgets import QMessageBox
        w = self.app.activeModalWidget()
        if w is None or w is self.last and not self.script:
            return
        for i, (match, act) in enumerate(self.script):
            if match(w):
                self.script.pop(i)
                self.last = w
                act(w)
                return
        if isinstance(w, QMessageBox) and w is not self.last:
            self.last = w
            self.seen.append(("QMessageBox", w.text() + " | " + w.informativeText()))
            w.done(0)


def pump(app, sec=0.0, until=None, timeout=10.0):
    t = time.time()
    while True:
        app.processEvents()
        if until is not None and until():
            return True
        if until is None and time.time() - t >= sec:
            return True
        if time.time() - t > timeout:
            return False
        time.sleep(0.01)


class GuiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ["TYTCPS_ENGINE"] = str(HERE / "fake_engine.py")
        os.environ["FAKE_DELAY"] = "0.01"
        os.environ["FAKE_SCENARIO"] = "ok"
        self.w = World()
        self.radio = self.w.root / "radio.img"
        shutil.copyfile(self.w.demo_image(), self.radio)
        os.environ["FAKE_IMAGE"] = str(self.radio)
        from tytcps.backend import usb
        from tytcps.backend.usb import UsbRadio
        self.dev = [5]
        self._scan = usb.scan
        usb.scan = lambda: [UsbRadio("1-9", 1, self.dev[0], True)]
        from tytcps.ui.context import Context
        from tytcps.ui.jobs import JobRunner
        from tytcps.ui.mainwindow import MainWindow
        check = self.w.engine.check()
        self.assertTrue(check.ok, check.problem)
        runner = JobRunner(self.w.engine)
        self.ctx = Context(self.w.engine, self.w.fleet, runner, self.w.runtime, check)
        self.win = MainWindow(self.ctx)
        self.win.show()
        # the radio restarts after each run: new device number 0.3 s later
        runner.radio_finished.connect(lambda res: self.dev.__setitem__(0, self.dev[0] + 1))
        self.robot = Robot(self.app)

    def tearDown(self):
        from tytcps.backend import usb
        usb.scan = self._scan
        pump(self.app, until=lambda: not self.ctx.runner.busy, timeout=10)
        self.ctx.codeplug = None          # no "save changes?" question
        self.win.keys.draft = None        # no "key set hasn't been saved" question
        self.robot.timer.stop()
        self.win.close()
        self.win.deleteLater()
        pump(self.app, 0.1)
        self.w.close()
        for k in [k for k in os.environ if k.startswith("FAKE_")] + ["TYTCPS_ENGINE"]:
            os.environ.pop(k, None)

    def settle(self):
        return pump(self.app, until=lambda: not self.ctx.runner.busy and
                    self.win.bar.state in ("identified", "connected"), timeout=10)

    def make_keys(self):
        from tytcps.backend import keys
        ks = keys.KeySet()
        for slot, t in ((1, "AES256"), (2, "AES128"), (3, "ARC4")):
            s = ks.slots[slot - 1]
            s.type, s.name, s.key = t, "S%d" % slot, keys.generate(t)
        name, sha = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.w.fleet.set_current(name)
        self.ctx.refresh_keyset()
        self.ctx.keyset_changed.emit()
        return name, sha

    def identify(self):
        self.win.identify()
        self.assertTrue(self.settle())
        self.assertEqual(self.win.bar.state, "identified")

    def click(self, dialog, text):
        [b for b in dialog.bb.buttons() if b.text() == text][0].click()

    def outcome_text(self, d):
        out = []
        for i in range(d.outcome.count()):
            it = d.outcome.itemAt(i)
            if it.widget() is not None and hasattr(it.widget(), "text"):
                out.append(it.widget().text())
        return " ".join(out)


class GuiFlows(GuiBase):
    def test_identify_read_edit_write(self):
        self.make_keys()
        app, win = self.app, self.win
        self.assertEqual(win.bar.state, "connected")
        win.identify()
        self.assertTrue(self.settle())
        self.assertEqual(win.bar.state, "identified")
        self.assertIn("new radio", win.bar.line1.text())
        seen = []
        win.ctx.runner.radio_event.connect(
            lambda ev: seen.append((win.bar.progress.isVisible() or not win.isVisible(),
                                    win.bar.progress.maximum(), win.bar.progress.value())))
        win.read()
        self.assertTrue(self.settle())
        # 6.6 bench: a read showed no progress bar. The bar moves with the events.
        self.assertTrue(any(m > 0 and v > 0 for vis, m, v in seen), seen[-3:])
        self.assertFalse(win.bar.progress.isVisibleTo(win.bar))
        cp = self.ctx.codeplug
        self.assertIsNotNone(cp)
        self.assertTrue(cp.title.startswith("Read from Radio ID 1001"))
        self.assertIn("Radio ID 1001", win.bar.line1.text())
        # the corrected 6.6 edit: TAC_2 Universal -> Basic, one byte
        m = win.channels.digital.model
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
        m.setData(m.index(r, 13), "Basic")
        self.assertTrue(pump(app, until=lambda: win.preview_ctl.state() == "clean", timeout=10))
        p = win.preview_ctl.current()
        self.assertEqual(p.changed, 1)
        self.assertTrue(win.bar.b_write.isEnabled())
        from tytcps.ui.dialogs import WriteCodeplugDialog

        def write(d):
            from PyQt6.QtWidgets import QLabel
            self.dialog_text = " | ".join(l.text() for l in d.findChildren(QLabel))
            pump(app, until=lambda: d.b_write.isEnabled(), timeout=10)
            d.b_write.click()
            pump(app, until=lambda: d.result is not None, timeout=10)
            self.dialog_result = d.result
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), write)
        win.write_codeplug()
        self.assertIn("The radio keeps its own.", self.dialog_text)
        self.assertTrue(self.dialog_result.ok)
        self.assertTrue(self.settle())
        from tytcps.backend import codeplug
        back, _ = codeplug.open_file(self.w.engine, self.radio)
        self.assertEqual(back.doc.tables["Digital"].find(2).cells[13], "Basic")

    def other_radios_file(self):
        """A codeplug saved from another radio: Radio ID 3202, name Other."""
        from tests.common import DEMO_CONF
        from tytcps.backend import codeplug
        conf = self.w.root / "other.conf"
        conf.write_text(DEMO_CONF.read_text().replace("ID: 1001", "ID: 3202")
                        .replace("Name: Demo_1", "Name: Other"))
        blank = self.w.root / "blank-other.img"
        blank.write_bytes(b"\xff" * 851968)
        out = self.w.root / "other-out"
        out.mkdir()
        r = self.w.engine.run(codeplug.apply(blank, conf, out))
        self.assertTrue(r.ok, r.stderr)
        img = self.w.root / "other.img"
        shutil.copyfile(out / "device.img", img)
        return img

    def write_open_file(self):
        from tytcps.ui.dialogs import WriteCodeplugDialog
        seen = {}

        def write(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            d.b_write.click()
            pump(self.app, until=lambda: d.result is not None, timeout=10)
            seen["res"], seen["attempt"] = d.result, d.attempt_image
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), write)
        self.win.write_codeplug()
        return seen

    def test_another_radios_file_keeps_this_radios_id_and_name(self):
        """Read radio 1, save, then write that file to radio 2: radio 2 keeps
        its own Radio ID and Name, and gets everything else."""
        self.identify()
        self.win.open_file(str(self.other_radios_file()))
        pump(self.app, 0.3)
        self.ctx.codeplug.doc.tables["Digital"].find(2).cells[13] = "Basic"
        self.ctx.doc_edited.emit()
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean",
                             timeout=10))
        seen = self.write_open_file()
        self.assertTrue(seen["res"].ok, seen["res"].error)
        self.assertTrue(self.settle())
        from tytcps.backend import codeplug
        back, _ = codeplug.open_file(self.w.engine, self.radio)
        self.assertEqual((back.doc.scalar("ID"), back.doc.scalar("Name")), ("1001", "Demo_1"))
        self.assertEqual(back.doc.tables["Digital"].find(2).cells[13], "Basic")

    def test_a_broken_write_recovers_with_this_radios_id(self):
        """The codeplug offered after a write that didn't verify carries the
        radio's own Radio ID and Name, not the file's."""
        self.identify()
        self.win.open_file(str(self.other_radios_file()))
        pump(self.app, 0.3)
        self.ctx.codeplug.doc.tables["Digital"].find(2).cells[13] = "Basic"
        self.ctx.doc_edited.emit()
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean",
                             timeout=10))
        os.environ["FAKE_SCENARIO"] = "write_unverified"
        try:
            seen = self.write_open_file()
        finally:
            os.environ["FAKE_SCENARIO"] = "ok"
        self.assertEqual(seen["res"].code, "write_unverified")
        img = Path(seen["attempt"]).read_bytes()
        radio = self.radio.read_bytes()
        self.assertEqual(img[0x2084:0x2088], radio[0x2084:0x2088])
        self.assertEqual(img[0x20B0:0x20D0], radio[0x20B0:0x20D0])
        self.assertEqual(int.from_bytes(img[0x2084:0x2087], "little"), 1001)

    def test_write_keys_records_ledger(self):
        name, sha = self.make_keys()
        win = self.win
        win.identify()
        self.assertTrue(self.settle())
        from tytcps.ui.dialogs import WriteKeysDialog

        def go(d):
            [b for b in d.bb.buttons() if b.text() == "Write keys"][0].click()
            pump(self.app, until=lambda: d.result is not None, timeout=10)
            self.res = d.result
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
        win.write_keys()
        self.assertTrue(self.res.ok, self.res.stderr)
        lines = self.w.fleet.ledger()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].sha256, sha)
        self.assertEqual(lines[0].file, "keys/" + name)
        self.assertTrue(self.settle())
        self.assertIn("(current)", win.bar.line2.text())

    def test_reads_disagree_message(self):
        os.environ["FAKE_SCENARIO"] = "reads_disagree"
        self.win.read()
        pump(self.app, until=lambda: self.robot.seen, timeout=10)
        self.assertIn("Two reads of the radio didn't match", self.robot.seen[0][1])
        self.assertIn("Nothing was written", self.robot.seen[0][1])
        self.assertIsNone(self.ctx.codeplug)

    def test_key_transfer_broke_off_marks_unit(self):
        self.make_keys()
        self.win.identify()
        self.assertTrue(self.settle())
        os.environ["FAKE_SCENARIO"] = "transfer_failed_keys"
        from tytcps.ui.dialogs import WriteKeysDialog

        def go(d):
            [b for b in d.bb.buttons() if b.text() == "Write keys"][0].click()
            pump(self.app, until=lambda: d.result is not None, timeout=10)
            self.res = d.result
            self.outcome = " ".join(d.outcome.itemAt(i).widget().text()
                                    for i in range(d.outcome.count())
                                    if d.outcome.itemAt(i).widget())
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
        self.win.write_keys()
        self.assertEqual(self.res.code, "transfer_failed")
        self.assertIn("keys are unknown", self.outcome)
        self.assertIn(self.ctx.unit["a207"], self.ctx.keys_unknown)
        self.assertEqual(self.w.fleet.ledger(), [])

    def test_keys_refused_leaves_the_unit_as_it_was(self):
        self.make_keys()
        self.win.identify()
        self.assertTrue(self.settle())
        os.environ["FAKE_ERROR_AT"] = "keys:keys_refused:unchanged"
        from tytcps.ui.dialogs import WriteKeysDialog

        def go(d):
            [b for b in d.bb.buttons() if b.text() == "Write keys"][0].click()
            pump(self.app, until=lambda: d.result is not None, timeout=10)
            self.res = d.result
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
        try:
            self.win.write_keys()
        finally:
            os.environ.pop("FAKE_ERROR_AT", None)
        self.assertEqual(self.res.code, "keys_refused")
        self.assertNotIn(self.ctx.unit["a207"], self.ctx.keys_unknown)
        self.assertEqual(self.w.fleet.ledger(), [])

    def test_close_refused_while_running(self):
        os.environ["FAKE_DELAY"] = "0.3"
        self.win.read()
        pump(self.app, 0.2)
        self.assertTrue(self.ctx.runner.busy)
        self.assertFalse(self.win.close())
        self.assertTrue(self.settle())


if __name__ == "__main__":
    unittest.main()
