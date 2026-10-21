# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock CPS's pages (General Setting, Menu, Buttons, channel and scan
list details): conf model, engine agreement, forms. Offline, fictional data."""

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import World
from tytcps.backend import codeplug
from tytcps.backend import cpsfields as CF
from tytcps.backend.conf import ConfDocument


def preview(w, cp):
    p, _, _ = codeplug.run_preview(w.engine, cp.base, cp.edited_text(), cp.doc.edited_records())
    return p


def cps_image(w, edit=None):
    """A fictional codeplug set up the way the CPS sets one up: the demo (a
    blank base, so its settings are raw values) with CPS values in the
    fields these tests use. One Touch 1 calls contact 3 with message 2 and
    Number Key 0 calls contact 3; nothing else uses either."""
    import shutil
    demo = w.demo_image()
    doc = ConfDocument(w.engine.run(codeplug.print_image(demo)).result["conf"])
    for k, v in {"VOX Sensitivity": "3", "Long Press Duration[ms]": "1000",
                 "Menu Hang Time[s]": "10", "Call Alert Tone Duration[s]": "Continue",
                 "Scan Digital Hang Time[ms]": "500", "Scan Analog Hang Time[ms]": "500",
                 "Radio ID 1": "5", "Radio ID 2": "-", "Radio ID 3": "-"}.items():
        doc.set_scalar(k, v)
    for r in doc.rows("OneTouch"):
        r.cells[1:] = ["Digital", "1", "Text", "1"]
    doc.tables["OneTouch"].find(1).cells[1:] = ["Digital", "3", "Text", "2"]
    for r in doc.rows("NumberKey"):
        r.cells[1] = "-"
    doc.tables["NumberKey"].find(0).cells[1] = "3"
    for r in doc.rows("Buttons"):
        r.cells[1:] = ["Power_Select", "Unassigned"]
    for r in doc.rows("Digital"):
        if r.cells[12] == "3":
            r.cells[12] = "1"
    for r in doc.rows("Grouplist"):
        r.cells[2] = "1"
    if edit:
        edit(doc)
    n = len(list(w.root.glob("cps-*")))
    out = w.root / ("cps-%d" % n)
    out.mkdir()
    (out / "e.conf").write_text(doc.render())
    r = w.engine.run(codeplug.apply(demo, out / "e.conf", out))
    assert r.ok, r.stderr
    img = w.root / ("cps-%d.img" % n)
    shutil.copyfile(out / "device.img", img)
    return img


class Engine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World()
        cls.img = cls.w.demo_image()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def open(self):
        cp, r = codeplug.open_file(self.w.engine, self.img)
        self.assertIsNotNone(cp, r and r.stderr)
        return cp

    def test_blank_settings_round_trip_through_raw_values(self):
        # demo.img was built on an all-0xFF image: its settings have no CPS meaning
        cp = self.open()
        self.assertTrue(cp.doc.scalar("VOX Sensitivity").startswith("raw:"))
        self.assertEqual(cp.doc.render(), cp.doc.text)
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.changed, 0)

    def test_every_table_is_there(self):
        cp = self.open()
        for kind in ("Menu", "Buttons", "OneTouch", "NumberKey", "ScanTiming", "ChanDigital",
                     "ChanAnalog"):
            self.assertTrue(cp.doc.rows(kind), kind)
        self.assertEqual(len(cp.doc.rows("ChanDigital")), len(cp.doc.rows("Digital")))
        self.assertEqual(len(cp.doc.rows("ChanAnalog")), len(cp.doc.rows("Analog")))

    def test_general_edit_is_attributed(self):
        cp = self.open()
        cp.doc.set_scalar("Talk Permit Tone", "None")
        cp.doc.set_scalar("Menu Hang Time[s]", "10")
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        kinds = {r["kind"] for r in p.records}
        self.assertEqual(kinds, {"general", "menu"})
        self.assertEqual(p.unexplained, [])

    def test_channel_details_edit(self):
        cp = self.open()
        row = cp.doc.tables["ChanDigital"].find(2)
        row.cells[CF.CHAN_DIGITAL.index([f for f in CF.CHAN_DIGITAL if f.key == "Width"][0]) + 1] = "25"
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual([(r["kind"], r["index"]) for r in p.records], [("channel", 2)])
        self.assertEqual(p.unexplained, [])

    def test_delete_and_add_channels_keep_details_consistent(self):
        cp = self.open()
        doc = cp.doc
        doc.delete_rows("Digital", [doc.tables["Digital"].find(3)])
        self.assertIsNone(doc.tables["ChanDigital"].find(3))
        new = doc.add_row("Analog")
        doc.add_detail_row("ChanAnalog", new.number, CF.NEW_ANALOG)
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.unexplained, [])
        # the new channel's details are what the engine gives a new channel
        out = ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])
        self.assertEqual(out.tables["ChanAnalog"].find(new.number).cells[1:], CF.NEW_ANALOG)

    def test_contact_renumber_follows_into_onetouch(self):
        cp = self.open()
        doc = cp.doc
        a, b = doc.tables["Contact"].find(1), doc.tables["Contact"].find(2)
        before = [r.cells[2] for r in doc.rows("OneTouch")]
        doc.swap_numbers("Contact", a, b)
        after = [r.cells[2] for r in doc.rows("OneTouch")]
        self.assertEqual(after, [{"1": "2", "2": "1"}.get(c, c) for c in before])
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.unexplained, [])


class ReviewRound4(unittest.TestCase):
    """The CPS-fields review's confirmed findings (2026-10-12), backend side."""

    @classmethod
    def setUpClass(cls):
        cls.w = World()
        cls.img = cps_image(cls.w)

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def open(self, img=None):
        cp, r = codeplug.open_file(self.w.engine, img or self.img)
        self.assertIsNotNone(cp, r and r.stderr)
        return cp

    def printed(self, p):
        return ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])

    def test_onetouch_mode_change_is_the_cps_reset(self):
        cp = self.open()
        self.assertTrue(cp.doc.onetouch_mode(1, "Analog"))
        self.assertEqual(cp.doc.tables["OneTouch"].find(1).cells, ["1", "Analog", "1", "DTMF-1", "1"])
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(self.printed(p).tables["OneTouch"].find(1).cells,
                         ["1", "Analog", "1", "DTMF-1", "1"])
        self.assertTrue(cp.doc.onetouch_mode(1, "Digital"))
        self.assertEqual(cp.doc.tables["OneTouch"].find(1).cells, ["1", "Digital", "1", "Text", "1"])

    def test_onetouch_none_keeps_the_rest_as_printed(self):
        cp = self.open()
        cp.doc.onetouch_mode(2, "None")
        self.assertEqual(cp.doc.tables["OneTouch"].find(2).cells, ["2", "None", "1", "raw:0x1", "1"])
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(self.printed(p).tables["OneTouch"].find(2).cells,
                         ["2", "None", "1", "raw:0x1", "1"])

    def test_mismatched_call_type_is_refused_by_the_engine(self):
        cp = self.open()
        cp.doc.tables["OneTouch"].find(1).cells[1] = "Analog"      # Text left behind
        p = preview(self.w, cp)
        self.assertFalse(p.ok)
        self.assertEqual((p.errors[0].get("section"), p.errors[0].get("column")), ("OneTouch", "CallType"))

    def test_contact_and_message_users_are_named_and_cps_rules_applied(self):
        cp = self.open()
        doc = cp.doc
        users = {(r.kind, r.cells[0]) for r, c in doc.references("Contact", 3)}
        self.assertEqual(users, {("OneTouch", "1"), ("NumberKey", "0")})
        self.assertEqual({(r.kind, r.cells[0]) for r, c in doc.references("Message", 2)},
                         {("OneTouch", "1")})
        doc.delete_rows("Contact", [doc.tables["Contact"].find(3)])
        self.assertEqual(doc.tables["OneTouch"].find(1).cells, ["1", "None", "-", "raw:0x1", "2"])
        self.assertEqual(doc.tables["NumberKey"].find(0).cells, ["0", "-"])
        self.assertEqual(doc.tables["OneTouch"].find(2).cells, ["2", "Digital", "1", "Text", "1"])
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.unexplained, [])

    def test_preview_labels_name_the_new_records(self):
        self.assertEqual(codeplug.record_label({"kind": "numberkey", "index": 1, "name": ""}),
                         "Number Key 0")
        self.assertEqual(codeplug.record_label({"kind": "menu"}), "Menu items")
        self.assertEqual(codeplug.record_label({"kind": "buttons"}), "Buttons")
        self.assertEqual(codeplug.record_label({"kind": "onetouch", "index": 3, "name": ""}),
                         "One Touch Access 3")
        cp = self.open()
        cp.doc.tables["NumberKey"].find(0).cells[1] = "2"
        p = preview(self.w, cp)
        self.assertEqual([codeplug.record_label(r) for r in p.records], ["Number Key 0"])

    def test_new_digital_channel_details_are_what_the_engine_gives(self):
        cp = self.open()
        new = cp.doc.add_row("Digital")
        cp.doc.add_detail_row("ChanDigital", new.number, CF.NEW_DIGITAL)
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(self.printed(p).tables["ChanDigital"].find(new.number).cells[1:],
                         CF.NEW_DIGITAL)

    def test_form_ranges_are_the_engines(self):
        # Every num field's range in display units equals the engine's: a
        # value just outside prints raw:, so the form can show it as kept.
        cp = self.open()
        for f in [f for f in CF.all_general() + [CF.MENU_HANG, CF.LONG_PRESS] if f.kind == "num"]:
            for v, ok in ((f.lo, True), (f.hi, True), (f.hi + f.unit, False)):
                doc = ConfDocument(cp.doc.text)
                doc.set_scalar(f.key, str(v))
                out = self.w.root / ("r-%s-%d" % (abs(hash(f.key)), v))
                out.mkdir(exist_ok=True)
                (out / "e.conf").write_text(doc.render())
                r = self.w.engine.run(codeplug.apply(cp.base, out / "e.conf", out))
                self.assertEqual(r.ok, ok, (f.key, v, r.error))
            if f.unit > 1:
                doc = ConfDocument(cp.doc.text)
                doc.set_scalar(f.key, str(f.lo + f.unit + 1 if f.lo + f.unit + 1 <= f.hi else f.lo + 1))
                (out / "e.conf").write_text(doc.render())
                self.assertFalse(self.w.engine.run(codeplug.apply(cp.base, out / "e.conf", out)).ok, f.key)


class FormsBase(unittest.TestCase):
    def setUp(self):
        from PyQt6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.w = World()
        from tytcps.ui.context import Context
        from tytcps.ui.jobs import JobRunner
        from tytcps.ui.mainwindow import MainWindow
        self.ctx = Context(self.w.engine, self.w.fleet, JobRunner(self.w.engine), self.w.runtime,
                           self.w.engine.check())
        self.win = MainWindow(self.ctx)
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)

    def tearDown(self):
        self.ctx.codeplug = None
        self.win.close()
        self.w.close()

    def pump(self, t):
        e = time.time()
        while time.time() - e < t:
            self.app.processEvents()
            time.sleep(0.01)



class Forms(FormsBase):
    def test_forms_edit_the_conf(self):
        g = [x for x in self.win.general.widgets if getattr(x, "f", None) and
             x.f.key == "Save Preamble"][0]
        g.w.setChecked(not g.w.isChecked())
        m = [x for x in self.win.menu_tab.widgets if x.b.key == "Scan"][0]
        m.w.setChecked(not m.w.isChecked())
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({r["kind"] for r in p.records}, {"general", "menu"})
        self.assertEqual(p.unexplained, [])
        self.assertIn("•", self.win.tabs.tabText(0))
        self.assertIn("•", self.win.tabs.tabText(1))

    def test_raw_value_is_shown_and_kept(self):
        vox = [x for x in self.win.general.widgets if getattr(x, "f", None) and
               x.f.key == "VOX Sensitivity"][0]
        self.assertIn("kept", vox.note.text())
        self.assertFalse(self.ctx.codeplug.doc.is_edited())



class FormsRound4(FormsBase):
    """The review's confirmed findings, in the forms."""

    def setUp(self):
        super().setUp()
        self.img = cps_image(self.w)
        self.win.open_file(str(self.img))
        self.pump(0.8)

    def field(self, form, key):
        return [x for x in form.widgets if getattr(x, "f", None) and x.f.key == key][0]

    def type_into(self, spin, text):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin, text)
        QTest.keyClick(spin, Qt.Key.Key_Return)
        self.pump(0.2)

    def test_spin_box_refuses_a_value_the_radio_cant_store(self):
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        self.type_into(lp.w, "1100")
        self.assertTrue(lp.error)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1000")
        self.assertTrue(self.win.buttons_tab.has_errors())
        self.win.update_state()
        self.assertFalse(self.win.bar.b_write.isEnabled())
        self.type_into(lp.w, "1250")
        self.assertIsNone(lp.error)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1250")

    def test_arrows_write_and_lowest_value_can_be_chosen_from_kept(self):
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        self.assertEqual(lp.w.text(), "raw:0xFF")
        self.assertIn("kept", lp.note.text())
        self.assertFalse(self.ctx.codeplug.doc.is_edited())
        self.type_into(lp.w, "1000")          # the box's lowest value, also its placeholder
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1000")
        lp.w.stepBy(1)
        self.pump(0.1)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1250")

    def test_kept_raw_shows_in_the_box_not_a_stale_number(self):
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        for key in ("Call Alert Tone Duration[s]", "Scan Digital Hang Time[ms]"):
            f = self.field(self.win.general, key)
            self.assertEqual(f.w.text(), "raw:0xFF", key)
        mh = self.field(self.win.menu_tab, "Menu Hang Time[s]")
        self.assertEqual(mh.w.text(), "raw:0xFF")
        self.win.open_file(str(self.img))
        self.pump(0.8)
        self.assertEqual(mh.w.text(), "10")
        self.assertEqual(self.field(self.win.general, "Scan Digital Hang Time[ms]").w.text(), "500")

    def test_input_error_is_dropped_with_the_file(self):
        rid = self.field(self.win.general, "Radio ID 1")
        rid.w.setText("0")
        rid.w.textEdited.emit("0")
        self.pump(0.1)
        self.assertTrue(self.win.general.has_errors())
        self.assertTrue(self.win._tab_flags(self.win.general)[1])     # the tab's red dot
        self.win.open_file(str(self.img))
        self.pump(0.8)
        self.assertFalse(self.win.general.has_errors())
        self.assertEqual(rid.w.toolTip(), "")

    def test_kept_combo_item_stays_with_its_record(self):
        def raw_width(doc):
            doc.tables["ChanDigital"].find(1).cells[1] = "raw:0x3"
        img = cps_image(self.w, raw_width)
        self.win.open_file(str(img))
        self.pump(0.8)
        ch = self.win.channels
        ch.show_kind("Digital")
        width = [w for w in ch.dpanel.widgets if w.f.key == "Width"][0]
        ch.dpanel.show_record(1)
        self.assertIn("raw:0x03 (kept)", [width.w.itemText(i) for i in range(width.w.count())])
        ch.dpanel.show_record(2)
        self.assertEqual([width.w.itemText(i) for i in range(width.w.count())], ["12.5", "20", "25"])

    def test_onetouch_mode_combo_resets_the_row(self):
        self.win.tabs.setCurrentWidget([ph for t, ph, w in self.win.cp_tabs if w is self.win.buttons_tab][0])
        self.pump(0.3)
        mode = self.win.buttons_tab.ot.cellWidget(0, 0)
        mode.setCurrentIndex(mode.findData("Analog"))
        self.pump(0.5)
        self.assertEqual(self.ctx.codeplug.doc.tables["OneTouch"].find(1).cells,
                         ["1", "Analog", "1", "DTMF-1", "1"])
        ct = self.win.buttons_tab.ot.cellWidget(0, 2)
        self.assertEqual([ct.itemData(i) for i in range(ct.count())], ["DTMF-1", "DTMF-2", "DTMF-3", "DTMF-4"])
        mode = self.win.buttons_tab.ot.cellWidget(0, 0)
        mode.setCurrentIndex(mode.findData("None"))
        self.pump(0.5)
        self.assertFalse(self.win.buttons_tab.ot.cellWidget(0, 2).isEnabled())
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)

    def test_dcdm_needs_a_cps_tot(self):
        doc = self.ctx.codeplug.doc
        d = doc.tables["ChanDigital"].find(1)
        d.cells[CF.CHAN_DIGITAL.index([f for f in CF.CHAN_DIGITAL if f.key == "DCDM"][0]) + 1] = "+"
        doc.tables["Digital"].find(1).cells[6] = "0"
        self.ctx.doc_edited.emit()
        self.assertTrue(self.win.channels.digital.model.has_errors())
        doc.tables["Digital"].find(1).cells[6] = "30"
        self.ctx.doc_edited.emit()
        self.assertFalse(self.win.channels.digital.model.has_errors())

    def test_goto_reaches_the_new_pages(self):
        ph = {w: ph for t, ph, w in self.win.cp_tabs}
        self.win._goto_event({"section": "General", "column": "Long Press Duration[ms]", "message": "x"})
        self.assertIs(self.win.tabs.currentWidget(), ph[self.win.buttons_tab])
        self.win._goto_event({"section": "General", "column": "Menu Hang Time[s]", "message": "x"})
        self.assertIs(self.win.tabs.currentWidget(), ph[self.win.menu_tab])
        self.win._goto_event({"section": "OneTouch", "id": "1", "column": "CallType", "message": "x"})
        self.assertIs(self.win.tabs.currentWidget(), ph[self.win.buttons_tab])
        self.win._goto_event({"section": "ChanDigital", "id": "2", "column": "DCDM", "message": "x"})
        self.pump(0.2)
        self.assertIs(self.win.tabs.currentWidget(), ph[self.win.channels])
        self.assertEqual(self.win.channels.dpanel.number, 2)
        dcdm = [w for w in self.win.channels.dpanel.widgets if w.f.key == "DCDM"][0]
        self.assertIn("c0392b", dcdm.w.styleSheet())
        self.win._goto_event({"section": "ScanTiming", "id": "1", "column": "Hold[ms]", "message": "x"})
        self.pump(0.2)
        self.assertIs(self.win.tabs.currentWidget(), ph[self.win.scanlists])
        self.assertEqual(self.win.scanlists.panel.number, 1)

    def test_radio_id_takes_the_cps_range(self):
        nw = [x for x in self.win.general.widgets if getattr(x, "key", None) == "ID"][0]
        for text, ok in (("16777215", False), ("16776415", True), ("0", True)):
            nw.setText(text)
            nw.textEdited.emit(text)
            self.assertEqual(nw.error is None, ok, text)

    def test_codeplug_writes_only_to_the_uv390_layout(self):
        from tytcps.ui.radiobar import codeplug_model_problem
        self.assertIsNone(codeplug_model_problem({"model": "MD-UV390"}))
        self.assertIsNone(codeplug_model_problem({"model": "MD-UV380"}))
        self.assertIn("MD-9600", codeplug_model_problem({"model": "MD-9600"}))

    # -- re-review of the round-4 fixes ------------------------------------------------

    def test_zero_word_box_shows_kept_and_click_through_writes_nothing(self):
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        ca = self.field(self.win.general, "Call Alert Tone Duration[s]")
        self.assertEqual(ca.w.text(), "raw:0xFF")       # not "Continue"
        ca.w.setFocus()
        ca.w.editingFinished.emit()                      # in and out, nothing typed
        self.pump(0.1)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Call Alert Tone Duration[s]"), "raw:0xFF")
        self.type_into(ca.w, "0")                        # the zero word, typed as 0
        self.assertEqual(self.ctx.codeplug.doc.scalar("Call Alert Tone Duration[s]"), "Continue")
        self.assertEqual(ca.w.text(), "Continue")

    def test_partial_or_empty_entry_writes_nothing(self):
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        lp.w.lineEdit().selectAll()
        QTest.keyClick(lp.w, Qt.Key.Key_Backspace)
        QTest.keyClick(lp.w, Qt.Key.Key_Return)
        self.pump(0.1)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "raw:0xFF")
        self.assertEqual(lp.w.text(), "raw:0xFF")
        self.type_into(lp.w, "12")                       # an intermediate number
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "raw:0xFF")
        self.assertEqual(lp.w.text(), "raw:0xFF")
        lp.w.stepBy(1)                                   # an arrow steps from the bottom
        self.pump(0.1)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1250")

    def test_typed_value_is_committed_before_save(self):
        from PyQt6.QtTest import QTest
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        self.win.tabs.setCurrentWidget([ph for t, ph, w in self.win.cp_tabs if w is self.win.buttons_tab][0])
        self.win.show()
        self.pump(0.2)
        lp.w.setFocus()
        self.pump(0.1)
        lp.w.lineEdit().selectAll()
        QTest.keyClicks(lp.w, "1500")                    # no Enter, focus stays
        self.assertIsNotNone(lp.w.typed)
        self.win._commit_edit()
        self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "1500")
        self.assertTrue(self.ctx.codeplug.dirty)

    def test_cleared_error_releases_the_gate(self):
        rid = self.field(self.win.general, "Radio ID 1")
        rid.w.setText("0")
        rid.w.textEdited.emit("0")
        self.assertIn("Fix the problems", self._why())
        self.win.open_file(str(self.img))
        self.pump(0.8)
        self.assertNotIn("Fix the problems", self._why())
        self.assertFalse(self.win._tab_flags(self.win.general)[1])

    def _why(self):
        self.win.update_state()
        return self.win.bar.b_write.toolTip() if not self.win.bar.b_write.isEnabled() else ""

    def test_dcdm_rule_leaves_a_radios_own_state_alone(self):
        def dcdm_tot0(doc):
            col = CF.CHAN_DIGITAL.index([f for f in CF.CHAN_DIGITAL if f.key == "DCDM"][0]) + 1
            doc.tables["ChanDigital"].find(1).cells[col] = "+"
            doc.tables["Digital"].find(1).cells[6] = "30"
        img = cps_image(self.w, dcdm_tot0)
        # the engine refuses DCDM + with TOT 0 as a change, so put TOT 0 in by hand
        b = bytearray(img.read_bytes())
        b[0x40008] = b[0x40008] & 0xC0
        img.write_bytes(bytes(b))
        self.win.open_file(str(img))
        self.pump(1.5)
        self.assertFalse(self.win.channels.digital.model.has_errors())
        p = self.win.preview_ctl.current()
        self.assertTrue(p is None or p.ok, p and p.errors)
        doc = self.ctx.codeplug.doc
        doc.tables["Digital"].find(1).cells[6] = "180"          # a change to another bad TOT
        self.ctx.doc_edited.emit()
        self.assertTrue(self.win.channels.digital.model.has_errors())

    def test_as_is_write_has_the_model_gate(self):
        from tytcps.ui.dialogs import WriteImageDialog, WriteCodeplugDialog
        self.assertIsNot(WriteImageDialog.gate_problem, WriteCodeplugDialog.__mro__[1].gate_problem)
        self.ctx.unit = {"model": "MD-9600", "a207": "00" * 16}
        dlg = WriteImageDialog.__new__(WriteImageDialog)
        dlg.ctx, dlg.running, dlg.result = self.ctx, False, None
        from tytcps.ui import dialogs
        orig = dialogs.RadioRunDialog.gate_problem
        dialogs.RadioRunDialog.gate_problem = lambda self: None
        try:
            self.assertIn("MD-9600", dlg.gate_problem())
        finally:
            dialogs.RadioRunDialog.gate_problem = orig
            self.ctx.unit = None

    # -- delta check of the re-review fixes --------------------------------------------

    def test_arrow_after_typing_over_kept_steps_from_the_typed_number(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        for key, want in ((Qt.Key.Key_Up, "5250"), (Qt.Key.Key_Down, "4750")):
            lp.load()
            self.assertEqual(lp.w.text(), "raw:0xFF" if key == Qt.Key.Key_Up else "5250")
            lp.w.lineEdit().selectAll()
            QTest.keyClicks(lp.w, "5000")
            QTest.keyClick(lp.w, key)
            self.pump(0.1)
            self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), want)

    def test_number_typed_in_details_goes_to_its_record_before_add(self):
        from PyQt6.QtTest import QTest
        self.win.show()
        ch = self.win.channels
        self.win.tabs.setCurrentWidget([ph for t, ph, w in self.win.cp_tabs if w is ch][0])
        ch.show_kind("Digital")
        row = self.ctx.codeplug.doc.tables["Digital"].find(2)
        ch.digital.goto(row.uid, 0)
        self.pump(0.3)
        rekey = [w for w in ch.dpanel.widgets if w.f.key == "Rekey"][0]
        rekey.w.setFocus()
        self.pump(0.1)
        rekey.w.lineEdit().selectAll()
        QTest.keyClicks(rekey.w, "55")
        ch.digital.add()
        self.pump(0.3)
        col = [f.key for f in CF.CHAN_DIGITAL].index("Rekey") + 1
        self.assertEqual(self.ctx.codeplug.doc.tables["ChanDigital"].find(2).cells[col], "55")

    def test_renumbered_dcdm_channel_is_flagged_as_the_engine_does(self):
        def dcdm(doc):
            col = CF.CHAN_DIGITAL.index([f for f in CF.CHAN_DIGITAL if f.key == "DCDM"][0]) + 1
            doc.tables["ChanDigital"].find(1).cells[col] = "+"
        img = cps_image(self.w, dcdm)
        b = bytearray(img.read_bytes())
        b[0x40008] = b[0x40008] & 0xC0          # TOT Infinite: the radio's own state
        img.write_bytes(bytes(b))
        self.win.open_file(str(img))
        self.pump(1.5)
        t = self.win.channels.digital
        self.assertFalse(t.model.has_errors())
        doc = self.ctx.codeplug.doc
        doc.swap_numbers("Digital", doc.tables["Digital"].find(1), doc.tables["Digital"].find(2))
        self.ctx.doc_edited.emit()
        self.assertTrue(t.model.has_errors())
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertFalse(p.ok)
        doc.swap_numbers("Digital", doc.tables["Digital"].find(2), doc.tables["Digital"].find(1))
        self.ctx.doc_edited.emit()
        self.assertFalse(t.model.has_errors())

    def test_arrow_over_cleared_or_partial_text_keeps_the_kept_value(self):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtTest import QTest
        self.win.open_file(str(self.w.demo_image()))
        self.pump(0.8)
        lp = self.field(self.win.buttons_tab, "Long Press Duration[ms]")
        for typed, how in (("", "down"), ("", "up"), ("5", "down"), ("5", "wheel")):
            lp.load()
            lp.w.lineEdit().selectAll()
            QTest.keyClick(lp.w, Qt.Key.Key_Backspace)
            if typed:
                QTest.keyClicks(lp.w, typed)
            if how == "wheel":
                ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120),
                                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                 Qt.ScrollPhase.NoScrollPhase, False)
                lp.w.wheelEvent(ev)
            else:
                QTest.keyClick(lp.w, Qt.Key.Key_Down if how == "down" else Qt.Key.Key_Up)
            self.pump(0.1)
            self.assertEqual(self.ctx.codeplug.doc.scalar("Long Press Duration[ms]"), "raw:0xFF",
                             (typed, how))
            self.assertEqual(lp.w.text(), "raw:0xFF", (typed, how))

    # -- 6.8: passwords and Model Select, settled by CPS-saved files --------------------

    def answer(self, yes):
        from PyQt6.QtWidgets import QMessageBox
        from tytcps.ui import cpsforms
        self.asked = []
        btn = QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No
        orig = cpsforms.QMessageBox.question
        cpsforms.QMessageBox.question = staticmethod(lambda *a, **k: (self.asked.append(a[2]), btn)[1])
        self.addCleanup(setattr, cpsforms.QMessageBox, "question", orig)

    def test_model_select_only_in_freq_mode(self):
        a = self.field(self.win.general, "Model Select A")
        self.assertFalse(a.isEnabled())
        fc = self.field(self.win.general, "Freq/Channel Mode")
        fc.w.setCurrentIndex(fc.w.findText("Freq"))
        self.pump(0.1)
        self.assertTrue(a.isEnabled())
        a.w.setCurrentIndex(a.w.findText("VFO"))
        self.pump(1.5)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Model Select A"), "VFO")
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)

    def test_lock_and_power_on_password_ask_first(self):
        lock = self.field(self.win.general, "Password and Lock Enable")
        pw = self.field(self.win.general, "Power On Password")
        self.assertFalse(pw.isEnabled())
        self.answer(False)
        lock.w.setChecked(True)
        self.pump(0.1)
        self.assertEqual(len(self.asked), 1)
        self.assertFalse(lock.w.isChecked())
        self.assertEqual(self.ctx.codeplug.doc.scalar("Password and Lock Enable"), "-")
        self.answer(True)
        lock.w.setChecked(True)
        self.pump(0.1)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Password and Lock Enable"), "+")
        self.assertTrue(pw.isEnabled())
        pw.w.setText("1234")
        pw.w.editingFinished.emit()
        self.assertTrue(pw.error)                       # the CPS takes exactly 8 digits
        pw.w.setText("12345678")
        pw.w.editingFinished.emit()
        self.assertIsNone(pw.error)
        self.assertEqual(self.ctx.codeplug.doc.scalar("Power On Password"), "12345678")
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)
        out = ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])
        self.assertEqual(out.scalar("Power On Password"), "12345678")

    def test_program_password(self):
        rp = self.field(self.win.general, "Radio Program Password")
        self.answer(False)
        rp.w.setText("12345678")
        rp.w.editingFinished.emit()
        self.assertEqual(self.ctx.codeplug.doc.scalar("Radio Program Password"), "-")   # declined
        self.answer(True)
        rp.w.setText("12345678")
        rp.w.editingFinished.emit()
        doc = self.ctx.codeplug.doc
        self.assertEqual(doc.scalar("Radio Program Password"), "12345678")
        self.answer(False)
        rp.w.setText("")                                 # clearing needs no confirmation
        rp.w.editingFinished.emit()
        self.assertEqual(doc.scalar("Radio Program Password"), "-")
        self.assertEqual(self.asked, [])

    def test_no_pc_password_field(self):
        # 7.7: the radio doesn't enforce the PC Programming Password, so it
        # isn't offered; a radio's own value passes through any edit.
        self.assertFalse([x for x in self.win.general.widgets
                          if getattr(x, "f", None) and x.f.key == "PC Programming Password"])
        doc = self.ctx.codeplug.doc
        doc.set_scalar("PC Programming Password", "abc")
        bl = self.field(self.win.general, "Back Light Time[s]")
        bl.w.setCurrentIndex((bl.w.currentIndex() + 1) % bl.w.count())
        self.assertEqual(doc.scalar("PC Programming Password"), "abc")
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)
        out = ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])
        self.assertEqual(out.scalar("PC Programming Password"), "abc")

    def test_every_field_has_a_hint(self):
        # Operator: hovering a field (or its name) says what it controls.
        from tytcps.ui.cpsforms import FieldWidget, NameWidget
        forms = [self.win.general, self.win.menu_tab, self.win.buttons_tab,
                 self.win.channels.dpanel, self.win.channels.apanel, self.win.scanlists.panel]
        bare = [(type(f).__name__, getattr(w, "f", None) and w.f.key or getattr(w, "key", "?"))
                for f in forms for w in f.widgets
                if isinstance(w, (FieldWidget, NameWidget)) and not w.toolTip().strip()]
        self.assertEqual(bare, [])
        sp = [w for w in self.win.general.widgets if getattr(w, "f", None) and w.f.key == "Save Preamble"][0]
        self.assertIn("power-save", sp.toolTip())


if __name__ == "__main__":
    unittest.main()
