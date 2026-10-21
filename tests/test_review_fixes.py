# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for the write-path review before the first GUI write to
a radio. Offscreen, against
tests/fake_engine.py: no radio is touched."""

import os
import stat
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import World
from tests.test_gui_flows import GuiBase, pump

B = "0badcafe0badcafe0badcafe0000b002"


class Dialogs(GuiBase):
    def open_demo_and_edit(self):
        self.win.open_file(str(self.radio))
        pump(self.app, 0.5)
        m = self.win.channels.digital.model
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
        m.setData(m.index(r, 13), "Basic")
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean"))

    def test_general_tab_rejects_octal_id(self):
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        g = self.win.general
        idw = [w for w in g.widgets if getattr(w, "key", None) == "ID"][0]
        idw.setText("03102")
        idw._edited("03102")
        self.assertTrue(g.has_errors())
        self.assertEqual(self.ctx.codeplug.doc.scalar("ID"), "1001")
        idw._edited("3102")
        self.assertFalse(g.has_errors())
        self.assertEqual(self.ctx.codeplug.doc.scalar("ID"), "3102")

    def test_dialog_follows_the_radio(self):
        self.make_keys()
        self.identify()
        self.open_demo_and_edit()
        from tytcps.ui.dialogs import WriteCodeplugDialog
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            seen["before"] = d.b_write.isEnabled()
            # another radio is identified behind the dialog
            self.ctx.unit = dict(self.ctx.unit, a207=B)
            self.ctx.radio_changed.emit()
            pump(self.app, 0.5)
            seen["after"] = d.b_write.isEnabled()
            seen["note"] = d.gate_note.text()
            d.reject()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        self.assertTrue(seen["before"])
        self.assertFalse(seen["after"])
        self.assertIn("different radio", seen["note"])

    def test_other_unit_is_refused_before_anything_is_read(self):
        """7.3: the write names its unit (--expect-unit) and the engine
        refuses another radio right after connecting (was: the GUI killed
        the engine during the reads)."""
        self.make_keys()
        self.identify()
        self.open_demo_and_edit()
        before = self.radio.read_bytes()
        os.environ["FAKE_A207"] = B           # a different radio answers the write
        from tytcps.ui.dialogs import WriteCodeplugDialog
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            self.click(d, "Write codeplug")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            seen["text"] = self.outcome_text(d)
            seen["res"] = d.result
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        res = seen["res"]
        self.assertEqual(res.code, "unit_mismatch")
        self.assertIn("--expect-unit", res.command.args)
        self.assertEqual([e.get("phase") for e in res.events if e.get("event") == "phase"],
                         ["connect"])
        self.assertIn("A different radio is connected", seen["text"])
        self.assertIn("Nothing was written", seen["text"])
        self.assertEqual(self.radio.read_bytes(), before)
        self.assertIsNone(self.w.fleet.codeplug_incomplete("0badcafe0badcafe0badcafe00001001"))
        self.assertTrue(self.settle())
        self.assertEqual(self.ctx.unit["a207"], B)      # the bar shows the radio found

    def test_engine_warnings_are_shown_and_bar_holds(self):
        self.make_keys()
        self.identify()
        self.open_demo_and_edit()
        os.environ["FAKE_WARNINGS"] = "reboot_failed,prewrite_skipped"
        from tytcps.ui.dialogs import WriteCodeplugDialog
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            self.click(d, "Write codeplug")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            seen["text"] = self.outcome_text(d)
            d.close_btn.click()
        # the radio doesn't restart: same device number
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.ctx.runner.radio_finished.disconnect()
        self.ctx.runner.radio_finished.connect(self.win._job_finished)
        self.win.write_codeplug()
        self.assertIn("still in programming mode", seen["text"])
        self.assertIn("No backup", seen["text"])
        pump(self.app, 1.2)
        self.assertEqual(self.win.bar.state, "stuck")
        self.assertFalse(self.win.bar.b_write.isEnabled())
        self.dev[0] += 1          # switched off: it leaves the bus...
        from tytcps.backend import usb
        scan = usb.scan
        usb.scan = lambda: []
        pump(self.app, 1.2)
        usb.scan = scan
        pump(self.app, 1.2)
        self.assertEqual(self.win.bar.state, "connected")

    def test_write_again_writes_the_intended_image_whole(self):
        self.make_keys()
        self.identify()
        self.open_demo_and_edit()
        os.environ["FAKE_SCENARIO"] = "write_unverified"
        from tytcps.ui.dialogs import WriteCodeplugDialog, WriteImageDialog
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            self.click(d, "Write codeplug")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            seen["attempt"] = d.attempt_image
            os.environ["FAKE_SCENARIO"] = "ok"
            d._action("write_again")

        def image(d):
            seen["preset"] = d.path
            d.reject()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.robot.expect(lambda w: isinstance(w, WriteImageDialog), image)
        self.win.write_codeplug()
        pump(self.app, until=lambda: "preset" in seen, timeout=15)
        self.assertEqual(seen["preset"], seen["attempt"])

    def test_keys_unknown_survives_a_restart_and_clears(self):
        self.make_keys()
        self.identify()
        from tytcps.ui.dialogs import WriteKeysDialog
        a207 = self.ctx.unit["a207"]
        for scenario in ("transfer_failed_keys", "crash_after_keys"):
            os.environ["FAKE_SCENARIO"] = scenario

            def go(d):
                self.click(d, "Write keys")
                pump(self.app, until=lambda: d.result is not None, timeout=15)
                d.close_btn.click()
            self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
            self.win.write_keys()
            self.assertTrue(self.settle())
            from tytcps.backend.fleet import Fleet
            self.assertIn(a207, Fleet(self.w.fleet.folder).keys_unknown(), scenario)
            self.assertIn("unknown", self.win.bar.line2.text())
            # cleared by a completed key write
            os.environ["FAKE_SCENARIO"] = "ok"

            def ok(d):
                self.click(d, "Write keys")
                pump(self.app, until=lambda: d.result is not None, timeout=15)
                d.close_btn.click()
            self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), ok)
            self.win.write_keys()
            self.assertTrue(self.settle())
            self.assertNotIn(a207, Fleet(self.w.fleet.folder).keys_unknown())

    def test_menu_has_no_extra_read_or_write_items(self):
        """Read is the radio bar's button; there is one way to write a codeplug."""
        texts = []
        for a in self.win.menu.actions():
            texts.append(a.text())
            if a.menu():
                texts += [b.text() for b in a.menu().actions()]
        self.assertFalse([t for t in texts if "New from radio" in t or "as-is" in t], texts)

    def test_unsaved_prompt_names_the_file_and_defaults_to_cancel(self):
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        self.ctx.codeplug.doc.tables["Digital"].find(2).cells[13] = "Basic"
        before = self.radio.read_bytes()
        seen = {}
        from PyQt6.QtWidgets import QMessageBox

        def answer(box):
            seen["text"] = box.text()
            seen["default"] = box.defaultButton().text()
            box.defaultButton().click()
        self.robot.expect(lambda w: isinstance(w, QMessageBox), answer)
        self.assertFalse(self.win._unsaved_ok("reading a radio"))
        self.assertIn("radio.img", seen["text"])
        self.assertEqual(seen["default"].replace("&", ""), "Cancel")
        self.assertEqual(self.radio.read_bytes(), before)

    def test_views_refresh_after_a_key_write(self):
        name, sha = self.make_keys()
        self.identify()
        from tytcps.ui.dialogs import WriteKeysDialog

        def go(d):
            self.click(d, "Write keys")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
        self.win.write_keys()
        self.assertTrue(self.settle())
        self.assertEqual(self.win.keys.h_on.text(), "1 of 1 radio")
        self.assertNotIn("unknown", self.win.fleet.table.item(0, 3).text())

    def test_keys_tab_write_follows_the_bar(self):
        self.make_keys()
        self.assertEqual(self.win.bar.state, "connected")      # not identified
        self.win.keys.table.selectRow(0)
        pump(self.app, 0.2)
        self.assertFalse(self.win.keys.a_write.isEnabled())
        self.win.keys.write_keys_requested.emit()
        pump(self.app, 0.3)
        self.assertTrue(any("Identify" in t for c, t in self.robot.seen))

    def test_no_write_starts_while_busy(self):
        self.make_keys()
        self.identify()
        self.ctx.runner.retry_pending = True
        self.assertTrue(self.ctx.runner.busy)
        self.win.write_keys()
        pump(self.app, 0.3)
        self.assertTrue(any("already running" in t for c, t in self.robot.seen))
        self.ctx.runner.retry_pending = False


class ListCells(GuiBase):
    """Operator feedback (2026-10-18): a list cell must show that it opens a
    picker. Its Edit… button opens it with one click; double-click still does."""

    def test_edit_button_opens_the_picker(self):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        from tytcps.ui import grid
        self.win.open_file(str(self.radio))
        pump(self.app, 0.5)
        tab = self.win.grouplists
        self.win.tabs.setCurrentWidget([ph for t, ph, w in self.win.cp_tabs if w is tab][0])
        self.win.show()
        pump(self.app, 0.3)
        opened = []
        orig = grid.Picker.exec
        grid.Picker.exec = lambda dlg: (opened.append(dlg.windowTitle()), 0)[1]
        try:
            col = [c.kind for c in tab.model.cols].index("list")
            idx = tab.model.index(0, col)
            rect = tab.view.visualRect(idx)
            fm = tab.view.fontMetrics()
            b = grid.Delegate.button_rect(rect, fm)
            tip = tab.model.data(idx, Qt.ItemDataRole.ToolTipRole)
            self.assertIn("Edit…", tip)
            QTest.mouseClick(tab.view.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(rect.left() + 10, rect.center().y()))
            pump(self.app, 0.1)
            self.assertEqual(opened, [])                    # a plain click only selects
            QTest.mouseClick(tab.view.viewport(), Qt.MouseButton.LeftButton, pos=b.center())
            pump(self.app, 0.1)
            self.assertEqual(len(opened), 1)
        finally:
            grid.Picker.exec = orig


class Backend(unittest.TestCase):
    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_saving_a_set_one_slot_beyond_one_in_service(self):
        from tytcps.backend import keys
        ks = keys.KeySet()
        for slot, t in ((1, "AES256"), (2, "AES128")):
            s = ks.slots[slot - 1]
            s.type, s.name, s.key = t, "S%d" % slot, keys.generate(t)
        name, sha = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        r = self.w.engine.run(keys.add_existing(self.w.fleet.folder, "00" * 16, name, "test"))
        self.assertTrue(r.ok, r.stderr)
        self.w.fleet.set_current(name)
        s3 = ks.slots[2]
        s3.type, s3.name, s3.key = "ARC4", "S3", keys.generate("ARC4")
        name2, sha2 = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.assertNotEqual(sha2, sha)
        # an empty set in the ledger doesn't block the next save either
        empty, esha = keys.save_new(self.w.engine, keys.KeySet(), self.w.fleet.keys_dir)
        self.w.engine.run(keys.add_existing(self.w.fleet.folder, "11" * 16, empty, "test"))
        keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)

    def test_partials_are_cleaned_up(self):
        from tytcps.backend import keys
        kd = self.w.fleet.keys_dir
        dead = 999999
        while os.path.exists("/proc/%d" % dead):
            dead += 1
        stale = [kd / (".partial-%d-fleet-x.dec" % dead), kd / ("fleet-x.dec.tmp.%d" % dead)]
        live = kd / (".partial-%d-fleet-y.dec" % os.getpid())
        for p in stale + [live]:
            p.write_bytes(b"\0" * 10)
        removed = keys.cleanup_partials(kd)
        self.assertEqual(sorted(removed), sorted(p.name for p in stale))
        self.assertTrue(live.exists())

    def test_export_is_private_from_the_first_byte(self):
        from tytcps.backend import keys
        dest = self.w.root / "export.dec"
        old = os.umask(0)
        try:
            keys.write_private(dest, b"x" * 20480)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o600)
        link = self.w.root / "link.dec"
        link.symlink_to(self.w.root / "elsewhere.dec")
        with self.assertRaises(OSError):
            keys.write_private(link, b"x")

    def test_ledger_failure_off_radio_is_not_E_K5(self):
        from tytcps.backend.engine import Command, RunResult
        from tytcps.ui.messages import explain
        r = RunResult(Command(["ledger"], "x", label="ledger"), 13,
                      [{"event": "error", "code": "ledger_failed", "radio": "unchanged",
                        "message": "Permission denied"}], "", 0.1, self.w.root)
        m = explain(r)
        self.assertEqual(m.id, "E-S5")
        self.assertIn("No radio", m.state)


class Conf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World()
        from tytcps.backend import codeplug
        cls.cp, _ = codeplug.open_file(cls.w.engine, cls.w.demo_image())

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def model(self, kind):
        from PyQt6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tytcps.backend.conf import ConfDocument
        from tytcps.ui.grid import ConfModel

        class Ctx:
            codeplug = None

            def current_slots(self):
                return []
        ctx = Ctx()
        import copy
        ctx.codeplug = copy.copy(self.cp)
        ctx.codeplug.doc = ConfDocument(self.cp.doc.text)
        return ConfModel(ctx, kind), ctx.codeplug.doc

    def test_tab_in_a_name_is_an_error(self):
        m, doc = self.model("Zone")
        m.setData(m.index(0, 1), "Ops\t5")
        self.assertTrue(m.has_errors())

    def test_empty_name_is_an_error_not_a_delete(self):
        m, doc = self.model("Contact")
        m.setData(m.index(0, 1), "  ")
        self.assertTrue(m.has_errors())

    def test_long_message_is_an_error(self):
        m, doc = self.model("Message")
        m.setData(m.index(0, 1), "é" * 130)
        self.assertTrue(m.has_errors())

    def test_clearing_a_tone_means_none(self):
        m, doc = self.model("Analog")
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "7"][0]
        m.setData(m.index(r, 10), "")
        self.assertEqual(m.rows()[r].cells[10], "-")
        self.assertFalse(m.has_errors())

    def test_nbsp_stays_inside_a_name(self):
        from tytcps.backend.conf import ConfDocument
        text = self.cp.doc.text.replace("Operations", "Ops 5")
        d = ConfDocument(text)
        z = d.tables["Zone"].find(1)
        self.assertEqual(z.cells[1], "Ops 5")
        self.assertEqual(z.cells[2], "1-4")

    def test_five_digit_row_without_a_space(self):
        from tytcps.backend.conf import ConfDocument
        text = self.cp.doc.text.replace("    4   Base", "10000   Base")
        d = ConfDocument(text)
        self.assertIsNotNone(d.tables["Contact"].find(10000))
        self.assertIn(" 10000   Base", d.render())


if __name__ == "__main__":
    unittest.main()
