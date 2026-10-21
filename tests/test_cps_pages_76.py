# SPDX-License-Identifier: GPL-3.0-or-later
"""Digit Emergency System, DTMF Signaling and VFO Mode (7.6): conf model,
engine agreement, forms. Offline, fictional data."""

import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import World
from tests.test_cps_fields import FormsBase, preview
from tytcps.backend import codeplug
from tytcps.backend import cpsfields as CF
from tytcps.backend.conf import ConfDocument

SYS = ["Regular", "Emergency_Alarm", "-", "15", "5", "10", "-"]


def pages_image(w):
    """The demo with the three pages filled in as the CPS would: two
    emergency systems, a DTMF encode, VFO A analog and VFO B digital."""
    demo = w.demo_image()
    doc = ConfDocument(w.engine.run(codeplug.print_image(demo)).result["conf"])
    for k, v in {"Radio Disable Decode": "+", "Remote Monitor Decode": "-",
                 "Emergency Remote Monitor Decode": "+", "Remote Monitor Duration[s]": "10",
                 "Tx Sync Wakeup TOT[ms]": "150", "Tx Wakeup Message Limit": "3"}.items():
        doc.set_scalar(k, v)
    for v, mode, freq in (("A", "Analog", "467.55000"), ("B", "Digital", "451.12500")):
        for k, val in {"Channel Mode": mode, "Band Width": "12.5", "Squelch": "3",
                       "TOT[s]": "60", "Power": "Low", "Step[kHz]": "12.5",
                       "RX Frequency(MHz)": freq, "TX Frequency(MHz)": freq,
                       "CTCSS/DCS Dec": "-", "CTCSS/DCS Enc": "-", "Scan List": "-",
                       "Contact Name": "1", "Group List": "1", "Emergency System": "-",
                       "Color Code": "1", "Repeater Slot": "1", "Privacy": "None",
                       "Admit Criteria": "Always"}.items():
            doc.set_scalar("VFO %s %s" % (v, k), val)
    doc.set_scalar("VFO B Privacy", "Enhanced")
    doc.set_scalar("VFO B Privacy No.", "8")
    doc.add_row("EmergencySystem", ["System1"] + SYS)
    doc.add_row("EmergencySystem", ["Backup"] + SYS)
    doc.tables["DTMFEncode"].find(1).cells[1] = "1"
    for r in doc.rows("DTMFDecode"):
        r.cells[1:] = ["-", "Active", "None", "-", "Off", "Selected"]
    out = w.root / "pages-out"
    out.mkdir(exist_ok=True)
    (out / "e.conf").write_text(doc.render())
    r = w.engine.run(codeplug.apply(demo, out / "e.conf", out))
    assert r.ok, r.stderr
    img = w.root / "pages.img"
    shutil.copyfile(out / "device.img", img)
    return img


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = World()
        cls.img = pages_image(cls.w)

    @classmethod
    def tearDownClass(cls):
        cls.w.close()

    def open(self, img=None):
        cp, r = codeplug.open_file(self.w.engine, img or self.img)
        self.assertIsNotNone(cp, r and r.stderr)
        return cp

    def test_blank_pages_read_back_unchanged(self):
        cp = self.open(self.w.demo_image())
        doc = cp.doc
        self.assertEqual(len(doc.rows("DTMFSystem")), 4)
        self.assertEqual(len(doc.rows("DTMFEncode")), 32)
        self.assertEqual(len(doc.rows("DTMFDecode")), 8)
        self.assertEqual(doc.rows("EmergencySystem"), [])
        self.assertEqual(doc.render(), doc.text)
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.changed, 0)

    def test_pages_image_prints_what_was_set(self):
        doc = self.open().doc
        self.assertEqual([r.cells[1] for r in doc.rows("EmergencySystem")], ["System1", "Backup"])
        self.assertEqual(doc.scalar("VFO B Privacy No."), "8")
        self.assertEqual(doc.scalar("VFO A RX Frequency(MHz)"), "467.55000")

    def test_vfo_edit_is_attributed_to_its_vfo(self):
        cp = self.open()
        cp.doc.set_scalar("VFO B Squelch", "9")
        cp.doc.set_scalar("Tx Wakeup Message Limit", "1")
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({(r["kind"], r.get("index")) for r in p.records}, {("vfo", 2), ("emergency", None)})
        self.assertEqual(p.unexplained, [])

    def test_vfo_privacy_none_clears_the_key(self):
        cp = self.open()
        cp.doc.set_scalar("VFO B Privacy", "None")
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        out = ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])
        self.assertEqual(out.scalar("VFO B Privacy"), "None")
        self.assertEqual(out.scalar("VFO B Privacy No."), "1")

    def test_dtmf_rows(self):
        cp = self.open()
        doc = cp.doc
        sys1 = doc.tables["DTMFSystem"].find(1)
        sys1.cells[CF.DTMF_SYSTEM.index([f for f in CF.DTMF_SYSTEM if f.key == "KeyUp"][0]) + 1] = "12*#"
        doc.tables["DTMFEncode"].find(3).cells[1] = "77"
        doc.tables["DTMFDecode"].find(2).cells[2] = "Kill"
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({(r["kind"], r.get("index")) for r in p.records},
                         {("dtmfsystem", 1), ("dtmfencode", 3), ("dtmfdecode", 2)})
        self.assertEqual(p.unexplained, [])

    def test_engine_problem_is_located(self):
        cp = self.open()
        cp.doc.tables["DTMFDecode"].find(1).cells[4] = "5"       # ACK to an empty encode
        p = preview(self.w, cp)
        self.assertFalse(p.ok)
        self.assertTrue(any(e.get("section") == "DTMFDecode" and str(e.get("id")) == "1" and
                            e.get("column") == "ACK" for e in p.errors), p.errors)

    def test_emergency_add_and_delete_last(self):
        cp = self.open()
        doc = cp.doc
        row = doc.add_row("EmergencySystem")
        self.assertEqual(row.cells, ["3", "System3"] + SYS)
        doc.delete_rows("EmergencySystem", [row])            # a new row just goes
        self.assertEqual(doc.render(), doc.text)
        first, last = sorted(doc.rows("EmergencySystem"), key=lambda r: r.number)
        self.assertIsNotNone(doc.can_delete("EmergencySystem", [first]))
        self.assertIsNone(doc.can_delete("EmergencySystem", [last]))
        doc.delete_rows("EmergencySystem", [last])
        self.assertRegex(doc.render(), r"\n +2 +(- +){7}-\n")
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({(r["kind"], r.get("index")) for r in p.records}, {("emsystem", 2)})
        self.assertEqual(p.unexplained, [])
        out = ConfDocument(self.w.engine.run(codeplug.print_image(p.image)).result["conf"])
        self.assertEqual([r.cells[1] for r in out.rows("EmergencySystem")], ["System1"])

    def test_a_used_system_cant_be_deleted(self):
        doc = self.open().doc
        last = doc.tables["EmergencySystem"].find(2)
        doc.set_scalar("VFO B Emergency System", "2")
        self.assertIn("VFO B", doc.can_delete("EmergencySystem", [last]))
        doc.set_scalar("VFO B Emergency System", "-")
        col = [c for c in doc.rows("ChanDigital")][0]
        col.cells[CF.CHAN_DIGITAL.index([f for f in CF.CHAN_DIGITAL if f.key == "EmSys"][0]) + 1] = "2"
        self.assertIn("channel %d" % col.number, doc.can_delete("EmergencySystem", [last]))

    def test_hints(self):
        tips = {f.key: f.tip for f in CF.all_general()}
        self.assertIn("Chinese", tips["Voice Announcement"])
        for key in ("Channels Hang Time[ms]", "Public Zone", "Front Keyboard Lock"):
            self.assertTrue(tips[key].startswith("Undocumented."), key)
        for group in CF.vfo_fields("A"):
            for f in group[1]:
                self.assertTrue(f.tip, f.key)
        for f in CF.EMERGENCY + CF.EMSYS + CF.DTMF_SYSTEM + CF.DTMF_DECODE + [CF.DTMF_ENCODE]:
            self.assertTrue(f.tip, f.key)

    # -- review fixes ----------------------------

    def test_vfos_follow_contact_group_and_scan_list_changes(self):
        doc = self.open().doc
        self.assertEqual(doc.scalar_references("Contact", 1), ["VFO A", "VFO B"])
        c1, c2 = doc.tables["Contact"].find(1), doc.tables["Contact"].find(2)
        doc.swap_numbers("Contact", c1, c2)
        self.assertEqual(doc.scalar("VFO B Contact Name"), "2")
        doc.delete_rows("Contact", [doc.tables["Contact"].find(2)])
        self.assertEqual(doc.scalar("VFO B Contact Name"), "-")
        g1, g2 = doc.tables["Grouplist"].find(1), doc.tables["Grouplist"].find(2)
        if g2 is not None:
            doc.swap_numbers("Grouplist", g1, g2)
            self.assertEqual(doc.scalar("VFO B Group List"), "2")
        doc.set_scalar("VFO A Scan List", "1")
        self.assertIn("VFO A", doc.scalar_references("Scanlist", 1))
        doc.delete_rows("Scanlist", [doc.tables["Scanlist"].find(1)])
        self.assertEqual(doc.scalar("VFO A Scan List"), "-")

    def test_reverts_follow_channel_changes(self):
        cp = self.open()
        doc = cp.doc
        doc.tables["EmergencySystem"].find(1).cells[8] = "5"
        doc.tables["DTMFDecode"].find(1).cells[6] = "5"
        kinds = {r.kind for r, c in doc.references("Digital", 5)}
        self.assertTrue({"EmergencySystem", "DTMFDecode"} <= kinds, kinds)
        doc.delete_rows("Digital", [doc.tables["Digital"].find(5)])
        self.assertEqual(doc.tables["EmergencySystem"].find(1).cells[8], "-")
        self.assertEqual(doc.tables["DTMFDecode"].find(1).cells[6], "Selected")
        doc.tables["EmergencySystem"].find(2).cells[8] = "1"
        doc.swap_numbers("Digital", doc.tables["Digital"].find(1), doc.tables["Digital"].find(2))
        self.assertEqual(doc.tables["EmergencySystem"].find(2).cells[8], "2")
        p = preview(self.w, cp)
        self.assertTrue(p.ok, p.errors)
        self.assertEqual(p.unexplained, [])

    def test_an_analog_vfo_doesnt_hold_a_system(self):
        doc = self.open().doc
        doc.set_scalar("VFO A Emergency System", "2")         # VFO A is analog
        last = doc.tables["EmergencySystem"].find(2)
        self.assertIsNone(doc.can_delete("EmergencySystem", [last]))
        doc.delete_rows("EmergencySystem", [last])
        self.assertEqual(doc.scalar("VFO A Emergency System"), "-")

    def test_record_labels(self):
        self.assertEqual(codeplug.record_label({"kind": "vfo", "index": 1, "name": "VFO A"}), "VFO A")
        self.assertEqual(codeplug.record_label({"kind": "emsystem", "index": 1, "name": "System1"}),
                         'Emergency system 1 "System1"')
        self.assertEqual(codeplug.record_label({"kind": "emergency", "index": 0, "name": ""}),
                         "Digit Emergency System")


class PagesForms(FormsBase):
    def setUp(self):
        super().setUp()
        self.win.open_file(str(pages_image(self.w)))
        self.pump(0.8)

    def widget(self, tab, key, table=None, number=None):
        for x in tab.widgets:
            if x.f.key == key and (table is None or (x.b.table == table and str(x.b.key) == str(number))):
                return x
        raise AssertionError("no widget %s" % key)

    def test_tabs_are_there(self):
        titles = [self.win.tabs.tabText(i).rstrip(" •") for i in range(self.win.tabs.count())]
        for t in ("Emergency", "DTMF", "VFO"):
            self.assertIn(t, titles)

    def test_vfo_form_edits_its_scalar(self):
        sq = self.widget(self.win.vfo_tab, "VFO A Squelch")
        self.assertEqual(sq.w.currentText(), "3")
        sq.w.setCurrentIndex(sq.w.findText("7"))
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({(r["kind"], r.get("index")) for r in p.records}, {("vfo", 1)})
        self.assertEqual(p.unexplained, [])
        i = [i for i in range(self.win.tabs.count()) if self.win.tabs.tabText(i).startswith("VFO")][0]
        self.assertIn("•", self.win.tabs.tabText(i))

    def test_vfo_fields_follow_mode_and_privacy(self):
        t = self.win.vfo_tab
        self.assertFalse(self.widget(t, "VFO A Color Code").isEnabled())       # A is analog
        self.assertTrue(self.widget(t, "VFO A CTCSS/DCS Dec").isEnabled())
        self.assertTrue(self.widget(t, "VFO B Privacy No.").isEnabled())       # B: Enhanced 8
        priv = self.widget(t, "VFO B Privacy")
        priv.w.setCurrentIndex(priv.w.findText("None"))
        self.pump(0.3)
        self.assertFalse(self.widget(t, "VFO B Privacy No.").isEnabled())

    def test_frequency_and_tone_fields(self):
        t = self.win.vfo_tab
        rx = self.widget(t, "VFO A RX Frequency(MHz)")
        rx.w.setText("200")
        rx._text_edited("200")
        self.assertTrue(rx.error)
        self.assertTrue(t.has_errors())
        rx.w.setText("146.52")
        rx._text_edited("146.52")
        self.assertIsNone(rx.error)
        # written when finished, not while typing (review 10)
        self.assertEqual(self.ctx.codeplug.doc.scalar("VFO A RX Frequency(MHz)"), "467.55000")
        rx.commit()
        self.assertEqual(self.ctx.codeplug.doc.scalar("VFO A RX Frequency(MHz)"), "146.52000")
        tone = self.widget(t, "VFO A CTCSS/DCS Dec")
        tone.w.setCurrentIndex(tone.w.findData("D023N"))
        self.assertEqual(self.ctx.codeplug.doc.scalar("VFO A CTCSS/DCS Dec"), "D023N")
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)

    def test_dtmf_encode_1_cant_be_emptied(self):
        w = self.widget(self.win.dtmf_tab, "Code", "DTMFEncode", 1)
        w.w.setText("")
        w._text_edited("")
        self.assertTrue(w.error)
        w._text_edited("12a")
        self.assertIsNone(w.error)
        self.assertEqual(self.ctx.codeplug.doc.tables["DTMFEncode"].find(1).cells[1], "12A")

    def test_emergency_add_button(self):
        t = self.win.emergency_tab
        t.load()
        self.assertEqual(t.grid.rowCount(), 2)
        t.b_add.click()
        self.pump(0.3)
        self.assertEqual(t.grid.rowCount(), 3)
        self.assertEqual(self.ctx.codeplug.doc.tables["EmergencySystem"].find(3).cells[1], "System3")
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertTrue(p.ok, p.errors)
        self.assertEqual({(r["kind"], r.get("index")) for r in p.records}, {("emsystem", 3)})

    def test_admit_list_follows_the_mode(self):
        t = self.win.vfo_tab
        a = self.widget(t, "VFO A Admit Criteria")
        b = self.widget(t, "VFO B Admit Criteria")
        items = lambda w: [w.w.itemText(i) for i in range(w.w.count())]
        self.assertNotIn("Color Code", items(a))               # A is analog
        self.assertNotIn("Correct CTCSS/CDCSS", items(b))      # B is digital
        b.w.setCurrentIndex(b.w.findText("Color Code"))
        mode = self.widget(t, "VFO B Channel Mode")
        mode.w.setCurrentIndex(mode.w.findText("Analog"))
        self.pump(0.3)
        self.assertEqual(self.ctx.codeplug.doc.scalar("VFO B Admit Criteria"), "Always")
        self.assertIn("Correct CTCSS/CDCSS", items(self.widget(t, "VFO B Admit Criteria")))

    def test_a_name_of_dash_is_refused(self):
        t = self.win.emergency_tab
        t.load()
        w = self.widget(t, "Name", "EmergencySystem", 2)
        w._text_edited("-")
        self.assertTrue(w.error)
        self.assertEqual(self.ctx.codeplug.doc.tables["EmergencySystem"].find(2).cells[1], "Backup")

    def test_typed_tenths_are_kept_by_save(self):
        w = self.widget(self.win.dtmf_tab, "NextSeq[s]", "DTMFSystem", 1)
        w.w.lineEdit().setText("3.5")
        w.commit()
        self.assertEqual(self.ctx.codeplug.doc.tables["DTMFSystem"].find(1).cells[7], "3.5")

    def test_channel_emergency_system_is_a_picker(self):
        panel = [p for p in self.win.channels.panels() if p.table == "ChanDigital"][0]
        w = [x for x in panel.widgets if x.f.key == "EmSys"][0]
        panel.show_record(1)
        texts = [w.w.itemText(i) for i in range(w.w.count())]
        self.assertEqual(texts[:3], ["None", "1 · System1", "2 · Backup"])

    def test_engine_error_goes_to_its_field(self):
        self.ctx.codeplug.doc.tables["DTMFDecode"].find(1).cells[4] = "5"
        self.ctx.doc_edited.emit()
        self.pump(1.5)
        p = self.win.preview_ctl.current()
        self.assertFalse(p.ok)
        self.win._goto_event(p.errors[0])
        w = self.widget(self.win.dtmf_tab, "ACK", "DTMFDecode", 1)
        self.assertIn("c0392b", w.w.styleSheet())


if __name__ == "__main__":
    unittest.main()
