# SPDX-License-Identifier: GPL-3.0-or-later
"""Fault-injection sweep of the GUI, as Phase 6.0 swept the engine.

Each radio write is broken in every way the engine can break: killed as
each phase starts, an exit code outside the table, an error event with
nothing behind it, malformed output lines, a full disk, a fleet folder that
can't be written. After every run:

  - no Python exception escaped (PyQt hands slot exceptions to excepthook);
  - the message says "nothing was written" only when nothing was;
  - a broken codeplug write keeps its intended image as the recovery, and a
    broken key write marks the unit's keys unknown, in the fleet folder;
  - nothing was run again by itself;
  - the radio bar comes back.

Offscreen, against tests/fake_engine.py. No radio is touched.
"""

import errno
import os
import shutil
import sys
import traceback
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_gui_flows import GuiBase, pump

A = "0badcafe0badcafe0badcafe00001001"
NOTHING = "Nothing was written"

PHASES = {
    "codeplug": ["connect", "read1", "read2", "compare", "parse", "check", "prewrite", "erase",
                 "write", "verify"],
    "image": ["connect", "read1", "read2", "prewrite", "erase", "write", "verify"],
    "keys": ["connect", "keys"],
}
WRITING = {"codeplug": "erase", "image": "erase", "keys": "keys"}


class SweepBase(GuiBase):
    def setUp(self):
        super().setUp()
        self.caught = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.caught.append(
            "".join(traceback.format_exception(t, v, tb)))
        self.runs = []
        self.boxes = []                 # message-box texts shown during write()
        self.ctx.runner.radio_started.connect(lambda cmd: self.runs.append(cmd.label))
        self.make_keys()
        self.identify()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        m = self.win.channels.digital.model
        r = [i for i, row in enumerate(m.rows()) if row.cells[0] == "2"][0]
        m.setData(m.index(r, 13), "Basic")
        self.assertTrue(pump(self.app, until=lambda: self.win.preview_ctl.state() == "clean"))
        self.image = self.w.root / "restore.img"
        shutil.copyfile(self.radio, self.image)

    def tearDown(self):
        sys.excepthook = self._hook
        for p in (self.w.fleet.folder, self.w.fleet.keys_dir):
            if p.exists():
                os.chmod(p, 0o700)
        super().tearDown()

    def no_exceptions(self):
        self.assertEqual(self.caught, [], "\n".join(self.caught))

    def reset(self):
        """Back to an identified radio with no recovery or unknown keys."""
        for k in [k for k in os.environ if k.startswith("FAKE_") and
                  k not in ("FAKE_IMAGE", "FAKE_DELAY")]:
            os.environ.pop(k)
        self.w.fleet.set_codeplug_incomplete(A, None)
        self.ctx.mark_keys_unknown(A, False)
        self.assertTrue(self.settle())
        self.win.bar.poll()             # see the restart now, not at the next 1 s tick
        if self.win.bar.state != "identified":
            self.identify()
        self.runs.clear()

    def write(self, kind, env):
        """One write through its dialog; (RunResult, outcome text, dialog).

        The robot can't answer a message box opened from inside its own
        handler (Qt won't fire its timer again until the handler returns),
        so message boxes are answered here: recorded in self.boxes, Yes to
        a question."""
        from PyQt6.QtWidgets import QMessageBox
        from tytcps.ui.dialogs import WriteCodeplugDialog, WriteImageDialog, WriteKeysDialog
        cls = {"codeplug": WriteCodeplugDialog, "image": WriteImageDialog,
               "keys": WriteKeysDialog}[kind]
        button = {"codeplug": "Write codeplug", "image": "Write again", "keys": "Write keys"}[kind]
        seen = {}

        def go(d):
            pump(self.app, until=lambda: d.b_write.isEnabled(), timeout=10)
            from PyQt6.QtWidgets import QLabel
            seen["why"] = "write enabled %s, gate %r, bar %s, form: %s" % (
                d.b_write.isEnabled(), d.gate_problem(), self.win.bar.state,
                " | ".join(l.text() for l in d.findChildren(QLabel) if l.text())[:600])
            os.environ.update(env)
            seen["dialog"] = d
            self.click(d, button)
            if d.running:
                pump(self.app, until=lambda: d.result is not None, timeout=20)
            seen["res"] = d.result
            seen["text"] = self.outcome_text(d) if d.result is not None else ""
            if d.result is not None:
                d.close_btn.click()
            else:
                d.reject()              # refused before it started
        saved = {n: getattr(QMessageBox, n) for n in ("warning", "information", "question",
                                                       "critical")}

        def box(name):
            def answer(*a, **k):
                self.boxes.append(a[2] if len(a) > 2 else k.get("text", ""))
                return (QMessageBox.StandardButton.Yes if name == "question"
                        else QMessageBox.StandardButton.Ok)
            return staticmethod(answer)
        for n in saved:
            setattr(QMessageBox, n, box(n))
        try:
            self.robot.expect(lambda w: isinstance(w, cls), go)
            if kind == "image":
                self.win.write_image(self.image)
            elif kind == "codeplug":
                self.win.write_codeplug()
            else:
                self.win.write_keys()
            pump(self.app, 0.2)
        finally:
            for n, f in saved.items():
                setattr(QMessageBox, n, f)
        self.why = seen.get("why", "the dialog never opened")
        return seen.get("res"), seen.get("text", ""), seen.get("dialog")

    def assert_state(self, kind, res, text, written):
        """The message and the fleet folder agree with how far the run got."""
        self.assertIsNotNone(res, self.why)
        self.assertFalse(res.ok)
        if written:
            self.assertNotIn(NOTHING, text)
        else:
            self.assertIn(NOTHING, text)
        if kind in ("codeplug", "image"):
            rec = self.w.fleet.codeplug_incomplete(A)
            if written:
                self.assertIsNotNone(rec, "no recovery image kept")
            else:
                self.assertIsNone(rec)
        else:
            from tytcps.backend.fleet import Fleet
            unknown = A in Fleet(self.w.fleet.folder).keys_unknown()
            self.assertEqual(unknown, written)
        self.assertEqual(len(self.runs), 1, self.runs)       # never re-run by itself
        self.no_exceptions()
        self.assertTrue(self.settle())


class KillSweep(SweepBase):
    def test_engine_killed_at_every_phase(self):
        for kind, phases in PHASES.items():
            for p in phases:
                with self.subTest(kind=kind, phase=p):
                    self.reset()
                    res, text, d = self.write(kind, {"FAKE_KILL_AT": p})
                    written = phases.index(p) >= phases.index(WRITING[kind])
                    self.assert_state(kind, res, text, written)
                    if written and kind == "codeplug":
                        rec = self.w.fleet.codeplug_incomplete(A)
                        self.assertEqual(rec.read_bytes(), Path(d.attempt_image).read_bytes())

    def test_killed_read_and_identify(self):
        for label, start, p in (("read", self.win.read, "read2"),
                                ("identify", self.win.identify, "connect")):
            with self.subTest(label):
                self.reset()
                before = self.ctx.codeplug
                os.environ["FAKE_KILL_AT"] = p
                if label == "read":
                    self.ctx.codeplug = None
                start()
                pump(self.app, until=lambda: self.robot.seen, timeout=10)
                self.assertTrue(any(NOTHING in t for c, t in self.robot.seen), self.robot.seen)
                self.assertEqual(len(self.runs), 1)
                self.robot.seen.clear()
                self.no_exceptions()
                self.ctx.codeplug = before


class ExitSweep(SweepBase):
    def test_exit_codes_outside_the_table(self):
        cases = []
        for kind, phases in PHASES.items():
            before = phases[1] if phases[1] != WRITING[kind] else phases[0]
            for p in (before, WRITING[kind]):
                for n in (3, 42, 200, 254):
                    cases.append((kind, {"FAKE_EXIT_AT": "%s:%d" % (p, n)},
                                  phases.index(p) >= phases.index(WRITING[kind])))
        for kind in PHASES:
            # the write finished, then the exit code or the result disowns it
            cases.append((kind, {"FAKE_FINAL_EXIT": "3"}, True))
            cases.append((kind, {"FAKE_FINAL_EXIT": "17"}, True))
            cases.append((kind, {"FAKE_RESULT_OK": "false"}, True))
        for kind, env, written in cases:
            with self.subTest(kind=kind, env=env):
                self.reset()
                res, text, d = self.write(kind, env)
                self.assert_state(kind, res, text, written)

    def test_error_events_out_of_line(self):
        for kind, env, written in (
                ("codeplug", {"FAKE_ERROR_AT": "write:transfer_failed:codeplug_incomplete:0"}, True),
                ("codeplug", {"FAKE_ERROR_AT": "write:frobnicated:weird:42"}, True),
                ("codeplug", {"FAKE_ERROR_AT": "read1:frobnicated:unchanged:42"}, False),
                ("keys", {"FAKE_ERROR_AT": "keys:frobnicated:weird:42"}, True),
                ("keys", {"FAKE_ERROR_AT": "connect:frobnicated:unchanged:200"}, False)):
            with self.subTest(kind=kind, env=env):
                self.reset()
                res, text, d = self.write(kind, env)
                self.assert_state(kind, res, text, written)


    def test_written_and_verified_then_trouble_keeps_no_recovery(self):
        """codeplug_written: the radio holds what was asked for, so the next
        write isn't blocked behind a recovery (7.3 review R1)."""
        self.reset()
        res, text, d = self.write("codeplug",
                                  {"FAKE_ERROR_AT": "verify:transfer_failed:codeplug_written"})
        self.assertIn("The radio holds what you asked for", text)
        self.assertIsNone(self.w.fleet.codeplug_incomplete(A))
        self.no_exceptions()

    def test_recovery_is_kept_even_if_the_message_fails(self):
        """7.3 review R2: an error while showing the outcome must not lose the
        recovery image (the crash handler keeps the program running)."""
        from tytcps.ui.dialogs import WriteCodeplugDialog
        self.reset()
        saved = WriteCodeplugDialog.show_outcome

        def broken(dialog, res):
            raise RuntimeError("message failed")
        WriteCodeplugDialog.show_outcome = broken
        try:
            res, text, d = self.write("codeplug", {"FAKE_KILL_AT": "write"})
        finally:
            WriteCodeplugDialog.show_outcome = saved
        self.assertIsNotNone(self.w.fleet.codeplug_incomplete(A))
        self.assertEqual(len(self.caught), 1)
        self.assertIn("message failed", self.caught[0])
        self.caught.clear()


class GarbageSweep(SweepBase):
    KINDS = ["text", "badutf8", "array", "noevent", "truncated", "huge", "nul"]

    def test_malformed_lines_around_good_events(self):
        for kind in ("codeplug", "keys"):
            for g in self.KINDS:
                with self.subTest(kind=kind, garbage=g):
                    self.reset()
                    res, text, d = self.write(kind, {"FAKE_GARBAGE": g})
                    self.assertTrue(res.ok, (g, res.code, res.stderr[-300:]))
                    self.assertGreaterEqual(res.bad_lines, 1)
                    block = [b for b in self.win.drawer.blocks if b.radio][-1]
                    self.assertTrue(any("couldn't be read" in l for l in block.lines))
                    self.no_exceptions()
                    self.assertTrue(self.settle())

    def test_broken_result_line(self):
        for kind in PHASES:
            with self.subTest(kind=kind):
                self.reset()
                res, text, d = self.write(kind, {"FAKE_GARBAGE": "result"})
                self.assertEqual(res.exit, 0)
                self.assertIsNone(res.result)
                self.assert_state(kind, res, text, True)

    def test_broken_result_line_on_a_read(self):
        self.reset()
        os.environ["FAKE_GARBAGE"] = "result"
        self.ctx.codeplug = None
        self.win.read()
        pump(self.app, until=lambda: self.robot.seen, timeout=10)
        self.assertTrue(any(NOTHING in t for c, t in self.robot.seen), self.robot.seen)
        self.assertIsNone(self.ctx.codeplug)
        self.no_exceptions()


class DiskSweep(SweepBase):
    def _enospc(self, *a, **k):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    def test_refused_key_write_leaves_the_other_radio_alone(self):
        """The radio on the cable is B, whose last key write broke off: a
        refused write (unit_mismatch) must not clear B's mark, and A's goes
        back to what it was (7.3; was: B's mark cleared)."""
        B = "0badcafe0badcafe0badcafe0000b002"
        self.reset()
        self.w.fleet.set_keys_unknown(B, True)
        res, text, d = self.write("keys", {"FAKE_A207": B})
        self.assertEqual(res.code, "unit_mismatch")
        self.assertIn("A different radio is connected", text)
        from tytcps.backend.fleet import Fleet
        unknown = Fleet(self.w.fleet.folder).keys_unknown()
        self.assertIn(B, unknown)
        self.assertNotIn(A, unknown)
        self.no_exceptions()

    def test_ledger_full_after_the_keys(self):
        self.reset()
        res, text, d = self.write("keys", {"FAKE_SCENARIO": "ledger_failed"})
        self.assertEqual(res.code, "ledger_failed")
        self.assertIn("Don't write the keys again", text)
        from tytcps.backend.fleet import Fleet
        self.assertNotIn(A, Fleet(self.w.fleet.folder).keys_unknown())   # they were written
        self.no_exceptions()

    def test_keys_unknown_mark_cant_be_saved(self):
        self.reset()
        from PyQt6.QtWidgets import QMessageBox
        saved = self.w.fleet.set_keys_unknown
        self.w.fleet.set_keys_unknown = self._enospc
        try:
            res, text, d = self.write("keys", {})
        finally:
            self.w.fleet.set_keys_unknown = saved
        self.assertIsNone(res)                       # refused before the transfer
        self.assertEqual(self.runs, [])
        self.assertTrue(any("Nothing was written" in t for t in self.boxes), self.boxes)
        self.no_exceptions()

    def test_recovery_image_cant_be_saved(self):
        self.reset()
        saved = self.w.fleet.set_codeplug_incomplete
        self.w.fleet.set_codeplug_incomplete = self._enospc
        try:
            res, text, d = self.write("codeplug", {"FAKE_KILL_AT": "write"})
        finally:
            self.w.fleet.set_codeplug_incomplete = saved
        self.assertIn("Couldn't save this radio's recovery state", text)
        self.assertIn("may now be incomplete", text)
        self.no_exceptions()

    def test_log_file_cant_be_written(self):
        from tytcps.backend.applog import AppLog
        self.reset()
        log = AppLog(self.w.root / "no-such-dir" / "x")
        log.dir = Path("/proc/tytcps-cant-write")          # never writable
        log.path = log.dir / "tytcps.log"
        self.win.drawer.applog = log
        res, text, d = self.write("codeplug", {})
        self.assertTrue(res.ok)
        self.assertTrue(log.failed)
        self.no_exceptions()

    def test_diagnostics_cant_be_saved(self):
        from tytcps.backend import diagnostics as D
        saved = D.save
        D.save = self._enospc
        try:
            self.assertIsNone(self.win.save_diagnostics(str(self.w.root / "d.zip")))
        finally:
            D.save = saved
        self.assertTrue(any("Couldn't save" in t for c, t in self.robot.seen))
        self.no_exceptions()


class ReadOnlyFleet(SweepBase):
    def lock(self):
        os.chmod(self.w.fleet.keys_dir, 0o500)
        os.chmod(self.w.fleet.folder, 0o500)

    def test_key_write_refused_before_the_transfer(self):
        self.reset()
        self.lock()
        res, text, d = self.write("keys", {})
        self.assertIsNone(res)
        self.assertEqual(self.runs, [])
        self.assertTrue(any("Nothing was written" in t for t in self.boxes), self.boxes)
        self.no_exceptions()

    def test_codeplug_write_goes_ahead_and_says_so(self):
        self.reset()
        self.lock()
        res, text, d = self.write("codeplug", {})
        self.assertTrue(res.ok)
        self.assertIn("radio list (radios.tsv) couldn't be updated", text)
        # clearing a recovery flag that isn't set writes nothing, so it can't fail
        self.assertNotIn("Couldn't save this radio's recovery state", text)
        self.no_exceptions()

    def test_fleet_tab_edits_say_so(self):
        self.reset()
        self.lock()
        self.win.fleet.rename(A, "Truck 3")
        self.win.fleet.hide_unit(A, True)
        pump(self.app, 0.2)
        self.assertTrue(any("label wasn't saved" in t for c, t in self.robot.seen))
        self.assertTrue(any("radio list wasn't changed" in t for c, t in self.robot.seen))
        self.no_exceptions()

    def test_fleet_and_keys_edits_fail_plainly(self):
        from PyQt6.QtWidgets import QMessageBox
        from tytcps.backend import keys
        self.reset()
        self.lock()
        # label and hide (Fleet tab), saving and choosing key sets (Keys tab)
        for fn in (lambda: self.w.fleet.set_label(A, "Truck 3"),
                   lambda: self.w.fleet.set_hidden(A, True)):
            with self.assertRaises(OSError):
                fn()
        k = self.win.keys
        k.table.selectRow(0)
        self.robot.expect(lambda w: isinstance(w, QMessageBox) and "Replace slot" in w.text(),
                          lambda w: w.button(QMessageBox.StandardButton.Yes).click())
        k.generate()
        k.save_new()
        pump(self.app, 0.2)
        self.assertTrue(any("wasn't saved" in t for c, t in self.robot.seen), self.robot.seen)
        self.assertTrue(k.has_draft())                  # the draft is kept
        self.assertFalse(k._set_current(self.ctx.current_name))
        self.no_exceptions()

    def test_diagnostics_still_save_elsewhere(self):
        self.reset()
        self.lock()
        out = self.w.root / "diag.zip"
        self.assertEqual(self.win.save_diagnostics(str(out)), str(out))
        self.assertTrue(out.is_file())
        self.no_exceptions()


if __name__ == "__main__":
    unittest.main()
