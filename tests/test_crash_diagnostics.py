# SPDX-License-Identifier: GPL-3.0-or-later
"""The crash handler, the log file and Save diagnostics.

The diagnostics bundle is the one file a stranger sends with a bug report,
so what must hold is checked on real content: a fleet with a key set and a
codeplug with all three passwords set gives a bundle in which the scanner
finds no key, no password value is left, and no unit block appears whole.
Offscreen; no radio is touched.
"""

import os
import subprocess
import sys
import threading
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.common import World
from tests.test_gui_flows import GuiBase, pump

ROOT = Path(__file__).resolve().parent.parent
A = "0badcafe0badcafe0badcafe00001001"


class LogFile(unittest.TestCase):
    def test_rotates_and_tail_reaches_back(self):
        import tempfile
        from tytcps.backend import applog
        d = Path(tempfile.mkdtemp())
        log = applog.AppLog(d)
        old = applog.MAX_BYTES
        applog.MAX_BYTES = 4096
        try:
            for i in range(200):
                self.assertTrue(log.write("line %d %s" % (i, "x" * 40)))
        finally:
            applog.MAX_BYTES = old
        self.assertTrue(log.old.is_file())
        self.assertLessEqual(log.path.stat().st_size, 4096 + 100)
        tail = log.tail()
        self.assertIn("line 199", tail)
        self.assertEqual(oct(log.path.stat().st_mode & 0o777), "0o600")

    def test_unwritable_log_never_raises(self):
        from tytcps.backend.applog import AppLog
        log = AppLog("/proc/tytcps-no")
        self.assertFalse(log.entry("x", "y"))
        self.assertTrue(log.failed)


class Crash(GuiBase):
    def handler(self, busy=False):
        from PyQt6.QtWidgets import QWidget
        from tytcps.backend.applog import AppLog
        from tytcps.crash import CrashHandler

        class Win(QWidget):
            saved = 0

            def radio_busy(self):
                return busy

            def save_diagnostics(self):
                Win.saved += 1
        h = CrashHandler()
        h.log = AppLog(self.w.fleet.folder)
        h.window = Win()
        return h

    def test_message_log_and_save_diagnostics(self):
        from PyQt6.QtWidgets import QMessageBox
        h = self.handler(busy=True)
        seen = {}

        def answer(box):
            seen["text"] = box.text() + " " + box.informativeText()
            [b for b in box.buttons() if b.text() == "Save diagnostics…"][0].click()
        self.robot.expect(lambda w: isinstance(w, QMessageBox) and "Something went wrong" in w.text(),
                          answer)
        try:
            raise ValueError("boom")
        except ValueError:
            h._excepthook(*sys.exc_info())
        pump(self.app, until=lambda: "text" in seen, timeout=5)
        self.assertIn("A radio operation is still running", seen["text"])
        self.assertEqual(h.window.saved, 1)
        log = h.log.path.read_text()
        self.assertIn("Unexpected error", log)
        self.assertIn("ValueError: boom", log)
        # another error at once: logged, not shown again (a second box would
        # be dismissed by the robot into robot.seen)
        h._excepthook(ValueError, ValueError("again"), None)
        pump(self.app, 0.5)
        self.assertFalse(any("Something went wrong" in t for c, t in self.robot.seen))
        self.assertIn("ValueError: again", h.log.path.read_text())
        self.assertEqual(len(h.traces), 2)

    def test_a_repeating_error_is_counted_not_relogged(self):
        h = self.handler()
        for _ in range(50):
            h.record("Traceback ...\nZeroDivisionError: in paint\n")
        pump(self.app, 0.3)
        log = h.log.path.read_text()
        self.assertEqual(log.count("Traceback ..."), 1)          # the full trace once
        self.assertIn("The same error again (10 times so far)", log)
        self.assertEqual(len(h.traces), 1)

    def test_slot_and_thread_exceptions_are_caught(self):
        h = self.handler()
        saved = (sys.excepthook, threading.excepthook)
        h.install()
        got = []
        h.caught.connect(got.append)
        try:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, lambda: 1 / 0)          # an exception inside a Qt slot
            pump(self.app, until=lambda: got, timeout=5)
            t = threading.Thread(target=lambda: [][1], name="worker")
            t.start()
            t.join()
            pump(self.app, until=lambda: len(got) >= 2, timeout=5)
        finally:
            sys.excepthook, threading.excepthook = saved
        self.assertIn("ZeroDivisionError", got[0])
        self.assertIn("In thread worker", got[1])
        self.assertIn("IndexError", got[1])


class Diagnostics(GuiBase):
    def fleet_with_codeplug(self):
        """Keys in the fleet, a codeplug with all three passwords set."""
        name, sha = self.make_keys()
        self.identify()
        self.win.open_file(str(self.radio))
        pump(self.app, 0.3)
        doc = self.ctx.codeplug.doc
        doc.set_scalar("Power On Password", "13572468")
        doc.set_scalar("Radio Program Password", "97531864")
        doc.set_scalar("PC Programming Password", "zq8Xw3")
        self.ctx.doc_edited.emit()
        return name, sha

    def bundle(self):
        out = self.w.root / "diag.zip"
        self.assertEqual(self.win.save_diagnostics(str(out)), str(out))
        z = zipfile.ZipFile(out)
        return {n.split("/", 1)[1]: z.read(n).decode("utf-8") for n in z.namelist()}

    def test_bundle_has_no_keys_passwords_or_whole_units(self):
        from tytcps.backend import keyscan
        name, sha = self.fleet_with_codeplug()
        files = self.bundle()
        self.assertTrue({"README.txt", "system.txt", "radio.txt", "log.txt", "codeplug.conf",
                         "fleet.txt"} <= set(files), files.keys())
        everything = "\n".join(files.values())
        for secret in ("13572468", "97531864", "zq8Xw3"):
            self.assertNotIn(secret, everything)
        self.assertIn("Power On Password: (removed)", files["codeplug.conf"])
        self.assertIn("PC Programming Password: (removed)", files["codeplug.conf"])
        self.assertNotIn(A, everything)
        self.assertIn("0bad…1001", everything)
        self.assertNotIn(sha, everything)
        keys, _ = keyscan.keys_in_folder(self.w.fleet.keys_dir)
        self.assertEqual(len(keys), 3)
        ns = keyscan.needles(keys)
        for n, text in files.items():
            self.assertEqual(keyscan.scan_blob(n, text.encode(), ns, names=False), [], n)

    def test_bundle_carries_the_real_log_and_crash_traces(self):
        from tytcps.backend.applog import AppLog
        from tytcps.crash import CrashHandler
        self.ctx.applog = AppLog(self.w.fleet.folder)
        self.ctx.applog.entry("run", "Unit: a207=%s serial=000001\nexit 0" % A)
        h = CrashHandler()
        h.log = self.ctx.applog
        h.record("Traceback (most recent call last):\nKeyError: 'boom'\n")
        (self.w.fleet.folder / "logs" / "fault.log").write_text("Fatal Python error: test\n")
        self.ctx.crash = h
        files = self.bundle()
        self.assertIn("serial=000001", files["log.txt"])
        self.assertIn("a207=0bad…1001", files["log.txt"])
        self.assertIn("KeyError: 'boom'", files["crash.txt"])
        self.assertIn("Fatal Python error: test", files["crash.txt"])
        self.assertNotIn(A, "\n".join(files.values()))

    def test_password_in_a_log_line_is_removed(self):
        from tytcps.backend import diagnostics as D
        text = D.strip_passwords("x.conf line 3, General Power On Password: bad\n"
                                 "    'Power On Password: 1234567'\n"
                                 "General settings  PC Programming Password ab12 -> cd34\n")
        for secret in ("1234567", "ab12", "cd34", ": bad"):
            self.assertNotIn(secret, text)

    def test_unreadable_key_file_means_nothing_is_saved(self):
        name, _ = self.make_keys()
        p = self.w.fleet.keys_dir / name
        p.chmod(0)
        try:
            out = self.w.root / "u.zip"
            self.assertIsNone(self.win.save_diagnostics(str(out)))
        finally:
            p.chmod(0o600)
        self.assertFalse(out.exists())
        self.assertTrue(any("couldn't be read to check" in t for c, t in self.robot.seen))

    def test_folder_name_with_brackets_is_still_scanned(self):
        from tytcps.backend import keys, keyscan
        odd = self.w.root / "Fleet [A]" / "keys"
        odd.mkdir(parents=True)
        name, _ = self.make_keys()
        (odd / name).write_bytes((self.w.fleet.keys_dir / name).read_bytes())
        self.assertEqual(len(keyscan.keys_in_folder(odd)[0]), 3)
        self.assertEqual(len(keyscan.keys_for_scan(odd)[0]), 3)

    def test_copy_diagnostics_is_checked_too(self):
        from tytcps.backend import keys
        name, _ = self.make_keys()
        key = keys.load(self.w.engine, self.w.fleet.keys_dir / name).slots[0].key
        self.win.drawer.last_text = lambda n=3, radio_only=False, raw=False: "leak " + key.hex()
        from PyQt6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText("before")
        self.win.copy_diagnostics()
        pump(self.app, 0.2)
        self.assertEqual(QGuiApplication.clipboard().text(), "before")
        self.assertTrue(any("would have contained a key" in t for c, t in self.robot.seen))

    def test_key_material_refuses_the_whole_bundle(self):
        from tytcps.backend import diagnostics as D
        from tytcps.backend import keys
        name, _ = self.make_keys()
        ks = keys.load(self.w.engine, self.w.fleet.keys_dir / name)
        key = ks.slots[0].key
        for form in (key.hex(), key[::-1].hex().upper(), ":".join("%02x" % b for b in key[4:14])):
            with self.subTest(form=form[:6]):
                with self.assertRaises(D.Refused) as e:
                    D.build({"log.txt": "something " + form + " else"}, self.w.fleet.keys_dir)
                self.assertIn("log.txt", e.exception.problems[0])
                self.assertNotIn(form, " ".join(e.exception.problems))

    def test_refused_bundle_is_not_saved(self):
        from tytcps.backend import keys
        name, _ = self.make_keys()
        key = keys.load(self.w.engine, self.w.fleet.keys_dir / name).slots[1].key
        self.win.drawer.last_text = lambda n=3, radio_only=False, raw=False: "leak " + key.hex()
        out = self.w.root / "leak.zip"
        self.assertIsNone(self.win.save_diagnostics(str(out)))
        self.assertFalse(out.exists())
        self.assertTrue(any("would have contained a key" in t for c, t in self.robot.seen))

    def test_menu_has_save_diagnostics(self):
        names = [a.text() for a in self.win.menu.actions()]
        self.assertIn("Save diagnostics…", names)


class SharedScanner(unittest.TestCase):
    """tools/check-key-material.py runs the same check as the bundle."""

    def setUp(self):
        self.w = World()

    def tearDown(self):
        self.w.close()

    def test_pre_commit_tool_uses_the_package_scanner(self):
        from tytcps.backend import keys
        ks = keys.KeySet()
        ks.slots[0].type, ks.slots[0].name, ks.slots[0].key = "AES256", "S1", keys.generate("AES256")
        name, _ = keys.save_new(self.w.engine, ks, self.w.fleet.keys_dir)
        clean = self.w.root / "clean.txt"
        clean.write_text("nothing here\n")
        leak = self.w.root / "leak.txt"
        leak.write_text("key: %s\n" % ks.slots[0].key[::-1].hex())
        env = dict(os.environ, TYT_STATE_DIR=str(self.w.fleet.folder))
        tool = [sys.executable, str(ROOT / "tools" / "check-key-material.py")]
        ok = subprocess.run(tool + [str(clean)], env=env, capture_output=True, text=True)
        bad = subprocess.run(tool + [str(leak)], env=env, capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(bad.returncode, 1, bad.stderr)
        self.assertIn("slot 1", bad.stderr)
        self.assertNotIn(ks.slots[0].key.hex(), bad.stderr + bad.stdout)


if __name__ == "__main__":
    unittest.main()
