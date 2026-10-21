# SPDX-License-Identifier: GPL-3.0-or-later
"""Every entry of the error catalogue, raised the way it
happens: the engine's errors through tests/fake_engine.py, the
ones TYTcps finds itself through the condition behind them. Each checks the
message TYTcps picks and what it says happened to the radio. No radio is
touched.
"""

import os
import shutil
import stat
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import DEMO_CONF, World
from tests.test_gui_flows import GuiBase, pump

HERE = Path(__file__).resolve().parent
A = "0badcafe0badcafe0badcafe00001001"
B = "0badcafe0badcafe0badcafe0000b002"
NOTHING = "Nothing was written"


class EngineErrors(unittest.TestCase):
    """The engine's refusals and failures, run through the fake engine and
    explained by ui.messages, as a dialog or the main window shows them."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ["TYTCPS_ENGINE"] = str(HERE / "fake_engine.py")
        os.environ["FAKE_DELAY"] = "0"
        self.w = World()
        self.radio = self.w.root / "radio.img"
        shutil.copyfile(self.w.demo_image(), self.radio)
        os.environ["FAKE_IMAGE"] = str(self.radio)
        from tytcps.backend import keys
        ks = keys.KeySet()
        for slot, t in ((1, "AES256"), (2, "AES128"), (3, "ARC4")):
            s = ks.slots[slot - 1]
            s.type, s.name, s.key = t, "S%d" % slot, keys.generate(t)
        self.keyset, _ = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.conf = self.w.root / "write.conf"
        self.conf.write_text(DEMO_CONF.read_text())

    def tearDown(self):
        os.chmod(self.w.fleet.folder, 0o700)
        self.w.close()
        for k in [k for k in os.environ if k.startswith("FAKE_")] + ["TYTCPS_ENGINE"]:
            os.environ.pop(k, None)

    # -- commands ------------------------------------------------------------------

    def read(self):
        from tytcps.backend import radio
        out = self.w.runtime.new_run("out")
        return radio.read(out)

    def identify(self):
        from tytcps.backend import radio
        return radio.identify()

    def write_conf(self):
        from tytcps.backend import radio
        return radio.write_conf(self.conf, self.w.fleet.keys_dir / self.keyset, unit=A)

    def write_image(self):
        from tytcps.backend import radio
        return radio.write_image(self.radio, unit=A)

    def write_keys(self):
        from tytcps.backend import radio
        return radio.write_keys(self.w.fleet.folder, self.keyset, unit=A)

    def explain(self, cmd, **env):
        from tytcps.ui import messages
        for k, v in env.items():
            os.environ[k] = v
        try:
            res = self.w.engine.run(cmd, timeout=30)
        finally:
            for k in env:
                os.environ.pop(k, None)
        self.assertFalse(res.ok, res.stderr)
        return res, messages.explain(res)

    def check(self, msg, mid, state=None, severe=False, buttons=None):
        self.assertEqual(msg.id, mid, "%s: %s" % (msg.id, msg.title))
        if state is not None:
            self.assertIn(state, msg.state, msg)
        self.assertEqual(msg.severe, severe, msg)
        if buttons is not None:
            self.assertEqual(msg.buttons, buttons)

    # -- environment and USB -------------------------------------------------------

    def test_E_U1_no_permission(self):
        _, m = self.explain(self.identify(), FAKE_ERROR_AT="connect:no_permission:unchanged")
        self.check(m, "E-U1", NOTHING, buttons=["fix_usb"])

    def test_E_U3_busy(self):
        _, m = self.explain(self.read(), FAKE_ERROR_AT="connect:busy:unchanged")
        self.check(m, "E-U3", NOTHING, buttons=["retry"])

    def test_E_U4_two_radios(self):
        _, m = self.explain(self.read(), FAKE_ERROR_AT="connect:multiple_radios:unchanged")
        self.check(m, "E-U4", NOTHING)

    # -- radio and codeplug --------------------------------------------------------

    def test_E_R1_no_radio(self):
        _, m = self.explain(self.read(), FAKE_SCENARIO="no_radio")
        self.check(m, "E-R1", NOTHING, buttons=["retry"])

    def test_E_R3_reads_disagree(self):
        _, m = self.explain(self.read(), FAKE_SCENARIO="reads_disagree")
        self.check(m, "E-R3", "the radio is unchanged", buttons=["retry", "diagnostics"])

    def test_E_R4_write_unverified(self):
        _, m = self.explain(self.write_conf(), FAKE_SCENARIO="write_unverified")
        self.check(m, "E-R4", "Don't use this radio", severe=True,
                   buttons=["write_again"])
        self.assertIn("12 bytes", m.body)

    def test_E_R5_incomplete(self):
        _, m = self.explain(self.write_conf(),
                            FAKE_ERROR_AT="write:transfer_failed:codeplug_incomplete")
        self.check(m, "E-R5", "incomplete", severe=True, buttons=["write_again"])

    def test_E_R5_unverified(self):
        _, m = self.explain(self.write_conf(),
                            FAKE_ERROR_AT="verify:transfer_failed:codeplug_unverified")
        self.check(m, "E-R5", "unconfirmed", severe=True)

    def test_E_R5_after_the_write(self):
        _, m = self.explain(self.write_conf(),
                            FAKE_ERROR_AT="verify:transfer_failed:codeplug_written")
        self.check(m, "E-R5", "holds what you asked for")

    def test_E_R5_before_the_write(self):
        _, m = self.explain(self.write_conf(), FAKE_ERROR_AT="read1:transfer_failed:unchanged")
        self.check(m, "E-R5", NOTHING, buttons=["retry"])

    def test_E_R6_unsupported_model(self):
        _, m = self.explain(self.write_keys(), FAKE_SCENARIO="unsupported_model")
        self.check(m, "E-R6", NOTHING)
        self.assertIn("MD-9600", m.body)

    def test_E_R7_image_invalid(self):
        _, m = self.explain(self.write_image(), FAKE_ERROR_AT="connect:image_invalid:unchanged")
        self.check(m, "E-R7", NOTHING)

    def test_E_R8_another_radio_for_each_write(self):
        for cmd in (self.write_conf(), self.write_image(), self.write_keys()):
            with self.subTest(cmd.label):
                res, m = self.explain(cmd, FAKE_A207=B)
                self.assertEqual(res.exit, 17)
                self.check(m, "E-R8", "the radio is unchanged")
                self.assertIn("0bad…b002", m.body)
                self.assertIn("0bad…1001", m.body)
                self.assertFalse(res.reached("read1", "erase", "write", "keys"))

    def test_E_R8_from_the_exit_code_alone(self):
        res, m = self.explain(self.write_keys(), FAKE_EXIT_AT="connect:17")
        self.check(m, "E-R8", "the radio is unchanged")
        self.assertEqual(m.body, "Identify the radio and try again.")

    # -- conf and preview ----------------------------------------------------------

    def test_E_C1_conf_invalid_is_located(self):
        from tytcps.backend import codeplug
        from tytcps.ui import messages
        bad = self.w.root / "bad.conf"
        bad.write_text(DEMO_CONF.read_text().replace("451.3750", "520.0000"))
        out = self.w.runtime.new_run("out")
        res = self.w.engine.run(codeplug.apply(self.radio, bad, out))
        m = messages.explain(res)
        self.assertEqual(m.id, "E-C1")
        self.assertTrue(m.title.startswith("Channels (digital) row 2"), m.title)
        self.assertIn(NOTHING, m.state)

    def test_E_C2_key_slot_empty(self):
        from tytcps.backend import codeplug, keys
        from tytcps.ui import messages
        empty = self.w.root / "empty.dec"
        self.assertTrue(self.w.engine.run(keys.new(empty)).ok)
        out = self.w.runtime.new_run("out")
        res = self.w.engine.run(codeplug.apply(self.radio, self.conf, out, empty))
        m = messages.explain(res)
        self.assertEqual(m.id, "E-C2")
        self.assertIn("is empty in the current key set", m.title)
        self.assertEqual(m.buttons, ["goto", "open_keys"])

    # -- keys and ledger -------------------------------------------------------------

    def test_E_K1_not_a_key_file(self):
        from tytcps.backend import keys
        from tytcps.ui import messages
        junk = self.w.root / "junk.dec"
        junk.write_bytes(b"\0" * 100)
        res = self.w.engine.run(keys.show(junk))
        self.assertEqual(messages.explain(res).id, "E-K1")

    def test_E_K3_unit_unreadable(self):
        for cmd in (self.write_keys(), self.write_conf()):
            with self.subTest(cmd.label):
                res, m = self.explain(cmd, FAKE_A207="")
                self.assertEqual(res.exit, 14)
                self.check(m, "E-K3", NOTHING, buttons=["retry"])

    def test_E_K4_transfer_broke_off(self):
        res, m = self.explain(self.write_keys(), FAKE_SCENARIO="transfer_failed_keys")
        self.check(m, "E-K4", "keys are unknown", severe=True, buttons=["write_keys_again"])
        self.assertEqual(res.a207, A)

    def test_E_K4_engine_killed(self):
        res, m = self.explain(self.write_keys(), FAKE_SCENARIO="crash_after_keys")
        self.check(m, "E-K4", "keys are unknown", severe=True)

    def test_E_K6_keys_refused(self):
        res, m = self.explain(self.write_keys(), FAKE_ERROR_AT="keys:keys_refused:unchanged")
        self.assertEqual(res.exit, 18)
        self.check(m, "E-K6", NOTHING)
        self.assertIn("Plus", m.body)

    def test_E_K5_ledger_failed_after_the_keys(self):
        _, m = self.explain(self.write_keys(), FAKE_SCENARIO="ledger_failed")
        self.check(m, "E-K5", "holds the new keys", severe=True,
                   buttons=["record_now", "copy_line"])

    def test_E_S4_ledger_not_writable_before_the_keys(self):
        os.chmod(self.w.fleet.folder, 0o500)
        _, m = self.explain(self.write_keys())
        self.check(m, "E-S4", NOTHING)

    def test_E_S5_hand_record_fails(self):
        from tytcps.backend import keys
        from tytcps.ui import messages
        led = self.w.fleet.folder / "ledger.tsv"
        led.chmod(0o400)
        try:
            res = self.w.engine.run(keys.add_existing(self.w.fleet.folder, A, self.keyset, ""))
        finally:
            led.chmod(0o600)
        m = messages.explain(res)
        self.assertEqual(m.id, "E-S5")
        self.assertIn("No radio was touched", m.state)

    # -- anything else -------------------------------------------------------------

    def test_E_X_unknown_code_before_writing(self):
        _, m = self.explain(self.read(), FAKE_ERROR_AT="connect:frobnicated:unchanged:42")
        self.check(m, "E-X", NOTHING)
        self.assertIn("diagnostics", m.buttons)

    def test_unknown_code_after_writing_is_not_nothing_written(self):
        _, m = self.explain(self.write_conf(), FAKE_ERROR_AT="write:frobnicated:weird:42")
        self.assertTrue(m.severe)
        self.assertNotIn(NOTHING, m.state)


class GuiCatalogue(GuiBase):
    """The entries TYTcps detects itself, and the warnings and notes."""

    def form_text(self, d):
        from PyQt6.QtWidgets import QLabel
        return " ".join(l.text() for l in d.findChildren(QLabel))

    # -- environment -----------------------------------------------------------------

    def test_E_F1_wrong_engine(self):
        from tytcps.backend.engine import Engine, locate_engine
        from tytcps.ui.firstrun import checks
        os.environ["FAKE_VERSION"] = "0.0.1"
        bad = Engine(locate_engine(), self.w.fleet.folder, self.w.runtime).check()
        self.assertFalse(bad.ok)
        self.assertIn("expected", bad.problem)
        self.assertEqual(checks(bad)[0][3], "E-F1")
        good = self.ctx.engine_check
        self.ctx.engine_check = bad
        try:
            self.win.bar.poll()
            self.win.update_state()
            self.assertFalse(self.win.bar.b_read.isEnabled())
            self.assertIn("programming engine is missing or the wrong version",
                          self.win.bar.line2.text())
        finally:
            self.ctx.engine_check = good

    def test_E_U1_E_U2_usb_access(self):
        from tytcps.backend import usb
        from tytcps.ui.firstrun import checks
        saved = (usb.find_rule, usb.session_groups, usb.user_groups)
        try:
            usb.find_rule = lambda: None
            rows = {r[0]: r for r in checks(self.ctx.engine_check)}
            self.assertEqual(rows["USB access rule"][3], "E-U1")
            usb.find_rule = lambda: usb.UdevRule("/etc/udev/rules.d/99-x.rules", group="plugdev")
            usb.session_groups = lambda: set()
            usb.user_groups = lambda: set()
            rows = {r[0]: r for r in checks(self.ctx.engine_check)}
            self.assertEqual(rows["Group membership"][3], "E-U2")
            self.assertIn("usermod", rows["Group membership"][2])
            usb.user_groups = lambda: {"plugdev"}
            rows = {r[0]: r for r in checks(self.ctx.engine_check)}
            self.assertIn("Log out and back in", rows["Group membership"][2])
        finally:
            usb.find_rule, usb.session_groups, usb.user_groups = saved
        # a radio this user can't open
        scan = usb.scan
        usb.scan = lambda: [usb.UsbRadio("1-9", 1, self.dev[0], False)]
        try:
            self.win.bar.poll()
            self.assertEqual(self.win.bar.state, "no_permission")
            self.assertIn("can't open it", self.win.bar.line1.text())
        finally:
            usb.scan = scan

    def test_E_U4_two_radios_on_the_bus(self):
        from tytcps.backend import usb
        scan = usb.scan
        usb.scan = lambda: [usb.UsbRadio("1-9", 1, 5, True), usb.UsbRadio("1-8", 1, 6, True)]
        try:
            self.win.bar.poll()
            self.win.update_state()
            self.assertEqual(self.win.bar.state, "multiple")
            self.assertFalse(self.win.bar.b_read.isEnabled())
        finally:
            usb.scan = scan

    def test_E_R2_restarting_is_retried_once(self):
        self.identify()
        os.environ["FAKE_SCENARIO"] = "no_radio"
        statuses = []
        orig = self.win.drawer.set_status
        self.win.drawer.set_status = lambda t: (statuses.append(t), orig(t))
        n0 = len(self.win.drawer.blocks)
        self.win.read()
        pump(self.app, until=lambda: any("No radio found" in t for c, t in self.robot.seen),
             timeout=15)
        self.assertIn("Radio restarting, retrying…", statuses)
        self.assertEqual(len([b for b in self.win.drawer.blocks[n0:] if b.radio]), 2)
        self.assertTrue(any("No radio found" in t for c, t in self.robot.seen))

    # -- radio and codeplug: success texts -----------------------------------------------

    def _write_demo(self, env):
        self.make_keys()
        self.identify()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        m = self.win.channels.digital.model
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
        m.setData(m.index(r, 13), "Basic")
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean"))
        os.environ.update(env)
        statuses = []
        orig = self.win.drawer.set_status
        self.win.drawer.set_status = lambda t: (statuses.append(t), orig(t))
        from tytcps.ui.dialogs import WriteCodeplugDialog
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            self.click(d, "Write codeplug")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            seen["text"] = self.outcome_text(d)
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        return seen.get("text", ""), statuses

    def test_verify_retry_and_volatile(self):
        text, statuses = self._write_demo({"FAKE_VERIFY_RETRY": "1", "FAKE_VOLATILE": "2"})
        self.assertIn("Re-reading to confirm…", statuses)
        self.assertIn("Written and verified", text)
        self.assertIn("2 bytes the radio changes by itself were ignored", text)

    def test_I_R1_last_programmed_date_tooltip(self):
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        self.assertIn("Updated by every codeplug write", self.win.general.ro["Last Programmed Date"].toolTip())

    def test_E_C3_privacy_inconsistent_on_read(self):
        os.environ["FAKE_WARNINGS"] = "privacy_inconsistent"
        self.win.read()
        pump(self.app, until=lambda: self.robot.seen, timeout=10)
        self.assertTrue(any("encryption set but switched off" in t for c, t in self.robot.seen))

    def test_W_P1_bytes_outside_the_edit(self):
        from tytcps.backend import codeplug as cpmod
        from tytcps.ui.dialogs import WriteCodeplugDialog
        self.make_keys()
        self.identify()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.preview is not None, timeout=10)
            d.preview = cpmod.Preview(d.preview.conf_sha, True, image=d.preview.image,
                                      diff=d.preview.diff, errors=[], unexplained=[{"bytes": 9}])
            d._warnings()
            seen["text"] = self.form_text(d)
            seen["enabled"] = d.b_write.isEnabled()
            d.reject()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        self.assertIn("9 bytes change in records you didn't edit", seen["text"])
        self.assertTrue(seen["enabled"])          # a warning, not an error

    def test_I_C1_conf_without_privacy_columns(self):
        from PyQt6.QtWidgets import QFileDialog
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        # the demo with the Digital table's Privacy and Key columns cut off:
        # an upstream dmrconfig conf
        lines, digital = [], False
        for l in DEMO_CONF.read_text().splitlines():
            if l.startswith("Digital"):
                digital = True
                l = " ".join(l.split()[:-2])
            elif digital and l.startswith(" "):
                l = "    " + " ".join(l.split()[:-2])
            else:
                digital = False
            lines.append(l)
        conf = self.w.root / "upstream.conf"
        conf.write_text("\n".join(lines) + "\n")
        orig = QFileDialog.getOpenFileName
        QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(conf), ""))
        try:
            self.win.import_conf()
        finally:
            QFileDialog.getOpenFileName = orig
        pump(self.app, 0.2)
        self.assertTrue(any("no Privacy or Key columns" in t for c, t in self.robot.seen),
                        self.robot.seen)

    def test_I_C2_date_stamp_listed_as_always_changes(self):
        from tytcps.ui.preview import PreviewPanel
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        m = self.win.channels.digital.model
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
        m.setData(m.index(r, 13), "Basic")
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean"))
        panel = PreviewPanel(self.win.preview_ctl.current(), self.win)
        from PyQt6.QtWidgets import QTreeWidget, QTableWidget
        texts = []
        for t in panel.findChildren(QTreeWidget):
            it = t.invisibleRootItem()
            stack = [it]
            while stack:
                x = stack.pop()
                for i in range(x.childCount()):
                    c = x.child(i)
                    texts.append(" ".join(c.text(j) for j in range(t.columnCount())))
                    stack.append(c)
        for t in panel.findChildren(QTableWidget):
            for row in range(t.rowCount()):
                texts.append(" ".join(t.item(row, j).text() for j in range(t.columnCount())
                                      if t.item(row, j)))
        panel.deleteLater()
        self.assertTrue(any("Always changes" in x for x in texts), texts[:10])
        self.assertEqual(self.win.preview_ctl.current().changed, 1)    # not counted

    # -- keys -----------------------------------------------------------------------------

    def test_W_K2_no_key_set(self):
        from tytcps.ui.dialogs import WriteCodeplugDialog
        self.identify()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.preview is not None, timeout=10)
            pump(self.app, 0.3)
            seen["text"] = self.form_text(d)
            d.reject()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        self.assertIn("No key set is loaded", seen["text"])

    def test_E_K2_slot_checks(self):
        from tytcps.backend import keys
        s = keys.Slot(1, "AES256", "x", b"\1" * 20)
        self.assertEqual(s.problem(), "AES256 needs 32 bytes; this slot has 20.")
        with self.assertRaises(ValueError) as e:
            keys.parse_hex("zz")
        self.assertIn("Use hex digits 0-9 and A-F only", str(e.exception))

    def test_I_K1_slot_names_banner(self):
        from tytcps.ui.keys_tab import RADIO_BANNER
        self.make_keys()
        self.identify()
        done = {}
        self.ctx.runner.radio_finished.connect(lambda r: done.setdefault("r", r))
        self.win.read_names()
        pump(self.app, until=lambda: "r" in done, timeout=10)
        pump(self.app, 0.2)
        self.assertEqual(self.win.keys.banner.text(), RADIO_BANNER)
        self.assertTrue(self.win.keys.banner.isVisibleTo(self.win.keys))

    def test_I_K2_W_K4_W_K5_write_keys_dialog(self):
        from tytcps.backend import keys
        from tytcps.ui.dialogs import WriteKeysDialog
        name, sha = self.make_keys()
        ks = keys.KeySet()
        ks.slots[0].type, ks.slots[0].name, ks.slots[0].key = "AES256", "X", keys.generate("AES256")
        other, _ = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.identify()                     # no Radio ID known yet
        self.win.keys.reload(other)
        seen = {}

        def go(d):
            seen["form"] = self.form_text(d)
            self.click(d, "Write keys")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            seen["out"] = self.outcome_text(d)
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), go)
        self.win.write_keys()
        self.assertIn("This isn't the current key set", seen["form"])           # W-K4
        self.assertIn("This radio's ID isn't known yet", seen["form"])          # W-K5
        self.assertIn("Keys can't be read back from the radio", seen["out"])    # I-K2

    def test_W_K1_W_K3_write_codeplug_dialog(self):
        from tytcps.backend import keys
        from tytcps.ui.dialogs import WriteCodeplugDialog, WriteKeysDialog
        self.make_keys()
        self.identify()

        def give(d):
            self.click(d, "Write keys")
            pump(self.app, until=lambda: d.result is not None, timeout=15)
            d.close_btn.click()
        self.robot.expect(lambda w: isinstance(w, WriteKeysDialog), give)
        self.win.write_keys()
        self.assertTrue(self.settle())
        # a new current set with slot 3 empty: the radio is now on an old set
        # (W-K3) and channel 4 names an empty slot (W-K1)
        ks = keys.KeySet()
        for slot, t in ((1, "AES256"), (2, "AES128")):
            s = ks.slots[slot - 1]
            s.type, s.name, s.key = t, "N%d" % slot, keys.generate(t)
        name, _ = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        self.w.fleet.set_current(name)
        self.ctx.refresh_keyset()
        self.ctx.keyset_changed.emit()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.preview is not None, timeout=10)
            pump(self.app, 0.3)
            seen["text"] = self.form_text(d)
            seen["enabled"] = d.b_write.isEnabled()
            d.reject()
        self.robot.expect(lambda w: isinstance(w, WriteCodeplugDialog), go)
        self.win.write_codeplug()
        self.assertIn("This radio has an old key set", seen["text"])
        self.assertIn("uses key slot 3, which is empty", seen["text"])
        self.assertFalse(seen["enabled"])

    def test_W_K6_fleet_contract_warning(self):
        from PyQt6.QtWidgets import QMessageBox
        from tytcps.ui.keys_tab import CONTRACT_WARNING
        name, _ = self.make_keys()
        k = self.win.keys
        k.reload(name)
        k.table.selectRow(0)
        self.robot.expect(lambda w: isinstance(w, QMessageBox) and "Replace slot" in w.text(),
                          lambda w: w.button(QMessageBox.StandardButton.Yes).click())
        k.generate()
        pump(self.app, 0.2)
        self.assertTrue(k.has_draft())
        self.assertIn(CONTRACT_WARNING.split("%s")[0], k.bar_text.text())

    # -- fleet folder ----------------------------------------------------------------------

    def test_E_S1_fleet_folder_cant_be_made(self):
        from tytcps.backend.fleet import Fleet
        ro = self.w.root / "ro"
        ro.mkdir(mode=0o500)
        try:
            with self.assertRaises(OSError):
                Fleet(ro / "tytcps").create()
        finally:
            ro.chmod(0o700)

    def test_E_S2_current_key_set_missing(self):
        from tytcps.ui.mainwindow import MainWindow
        self.w.fleet.set_current("fleet-1999-01-01.dec")
        self.assertTrue(self.w.fleet.current_missing())
        listeners = list(self.ctx.engine.listeners)
        win2 = MainWindow(self.ctx)
        pump(self.app, 0.1)
        self.ctx.engine.listeners[:] = listeners
        self.ctx.bar = self.win.bar
        win2.bar.timer.stop()
        win2.deleteLater()
        self.assertTrue(any("current key set file is missing" in t for c, t in self.robot.seen))

    def test_E_S3_unreadable_ledger_line(self):
        led = self.w.fleet.folder / "ledger.tsv"
        led.write_text("#when\ta207\n2026-01-01\tnot a ledger line\n")
        self.ctx.fleet_changed.emit()
        pump(self.app, 0.2)
        self.assertIn("Line 2 of ledger.tsv couldn't be read", self.win.fleet.problems.text())


if __name__ == "__main__":
    unittest.main()
