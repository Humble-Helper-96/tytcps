# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: radio bar, tabs, preview strip and
the Details drawer, with one codeplug file open at a time."""

import datetime
import os
import shutil
from pathlib import Path

import time

from PyQt6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtWidgets import (QDialog, QFileDialog, QMainWindow, QMenu, QMessageBox, QTabWidget,
                             QVBoxLayout, QWidget)

from .. import __version__
from ..backend import codeplug as cpmod
from ..backend import keys as K
from ..backend import paths, radio
from ..backend.fleet import short_unit
from . import messages
from .dialogs import WriteCodeplugDialog, WriteImageDialog, WriteKeysDialog
from .drawer import Drawer
from .firstrun import SettingsDialog
from .fleet_tab import FleetTab, RecordKeysDialog
from .grid import TableTab
from .keys_tab import KeysTab
from .preview import PreviewController, PreviewPanel, PreviewStrip, error_cells
from .radiobar import RadioBar, codeplug_model_problem
from .cpsforms import (ButtonsTab, DtmfTab, EmergencyTab, GeneralSettingTab, MenuTab, VfoTab,
                       commit_focused)
from .tabs import ChannelsTab, Placeholder, ScanListsTab

PHASE_TEXT = {
    "read": {"connect": "Reading… connecting", "read1": "Reading… read 1 of 2",
             "read2": "Reading… read 2 of 2", "compare": "Reading… comparing",
             "save": "Reading… saving"},
    "write-codeplug": {"connect": "Writing… connecting", "read1": "Writing… read 1 of 2",
                       "read2": "Writing… read 2 of 2", "compare": "Writing… comparing",
                       "parse": "Writing… checking", "check": "Writing… checking",
                       "prewrite": "Writing… keeping the pre-write image", "erase": "Writing… erase",
                       "write": "Writing… write", "verify": "Writing… verify",
                       "verify_retry": "Re-reading to confirm…"},
    "write-image": {"connect": "Writing… connecting", "read1": "Writing… read 1 of 2",
                    "read2": "Writing… read 2 of 2", "prewrite": "Writing… keeping the pre-write image",
                    "erase": "Writing… erase", "write": "Writing… write", "verify": "Writing… verify",
                    "verify_retry": "Re-reading to confirm…"},
    "write-keys": {"connect": "Writing keys… connecting", "keys": "Writing keys… sending 20 blocks"},
    "read-keys": {"connect": "Reading slot names…", "keys_read": "Reading slot names…"},
    "identify": {"connect": "Identifying radio…"},
}
START_TEXT = {"read": "Reading…", "write-codeplug": "Writing…", "write-image": "Writing…",
              "write-keys": "Writing keys…", "read-keys": "Reading slot names…",
              "identify": "Identifying radio…"}


class LogBridge(QObject):
    ran = pyqtSignal(object)


def dot_icon(color):
    pm = QPixmap(10, 10)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 8, 8)
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, ctx, logfile=None):
        super().__init__()
        self.ctx = ctx
        self.setMinimumSize(1024, 640)
        self.resize(1280, 800)
        self.block = None
        self.job_label = None
        self.preview_ctl = PreviewController(ctx, self)

        self.menu = self._build_menu()
        self.bar = RadioBar(ctx, self.menu)
        ctx.bar = self.bar
        self.tabs = QTabWidget()
        self.general = GeneralSettingTab(ctx)
        self.menu_tab = MenuTab(ctx)
        self.buttons_tab = ButtonsTab(ctx)
        self.channels = ChannelsTab(ctx)
        self.zones = TableTab(ctx, "Zone")
        self.scanlists = ScanListsTab(ctx)
        self.contacts = TableTab(ctx, "Contact")
        self.grouplists = TableTab(ctx, "Grouplist")
        self.msgs = TableTab(ctx, "Message")
        self.emergency_tab = EmergencyTab(ctx)
        self.dtmf_tab = DtmfTab(ctx)
        self.vfo_tab = VfoTab(ctx)
        self.keys = KeysTab(ctx)
        self.fleet = FleetTab(ctx)
        self.cp_tabs = []
        for title, w in (("General", self.general), ("Menu", self.menu_tab),
                         ("Buttons", self.buttons_tab), ("Channels", self.channels),
                         ("Zones", self.zones), ("Scan lists", self.scanlists),
                         ("Contacts", self.contacts), ("Group lists", self.grouplists),
                         ("Messages", self.msgs), ("Emergency", self.emergency_tab),
                         ("DTMF", self.dtmf_tab), ("VFO", self.vfo_tab)):
            ph = Placeholder(w)
            self.cp_tabs.append((title, ph, w))
            self.tabs.addTab(ph, title)
        self.tabs.addTab(self.keys, "Keys")
        self.tabs.addTab(self.fleet, "Fleet")
        self.strip = PreviewStrip(self.preview_ctl)
        self.drawer = Drawer(logfile=logfile, applog=ctx.applog)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.setSpacing(6)
        lay.addWidget(self.bar)
        lay.addWidget(self.tabs, 1)
        lay.addWidget(self.strip)
        lay.addWidget(self.drawer)
        self.setCentralWidget(central)

        # engine runs -> log
        self.drawer.copy.clicked.connect(self.copy_diagnostics)
        self.log_bridge = LogBridge()
        self.log_bridge.ran.connect(self.drawer.add_completed)
        ctx.engine.listeners.append(self.log_bridge.ran.emit)
        r = ctx.runner
        r.radio_started.connect(self._job_started)
        r.radio_event.connect(self._job_event)
        r.radio_stderr.connect(lambda t: self.block and self.drawer.append(self.block, t))
        r.radio_finished.connect(self._job_finished)
        r.retrying.connect(self._retrying)

        self.bar.identify_clicked.connect(self.identify)
        self.bar.read_clicked.connect(self.read)
        self.bar.write_codeplug_clicked.connect(self.write_codeplug)
        self.bar.write_keys_clicked.connect(self.write_keys)
        self.bar.fix_clicked.connect(self.settings)
        self.bar.state_changed.connect(self.update_state)
        self.strip.show_clicked.connect(self.show_preview)
        self.strip.goto_clicked.connect(self.goto_error)
        self.preview_ctl.changed.connect(self._preview_changed)
        ctx.doc_edited.connect(self.update_state)
        ctx.form_errors_changed.connect(self.update_state)
        ctx.doc_edited.connect(self._repaint_grids)
        ctx.codeplug_changed.connect(self._codeplug_changed)
        ctx.radio_changed.connect(self.update_state)
        ctx.keyset_changed.connect(self._repaint_grids)
        self.keys.write_keys_requested.connect(self.write_keys)
        self.keys.show_fleet_requested.connect(lambda: self.tabs.setCurrentWidget(self.fleet))
        self.keys.read_names_requested.connect(self.read_names)
        self.keys.changed.connect(self.update_state)
        self.keys.write_allowed = lambda: self.bar.b_keys.isEnabled()
        self.fleet.record_requested.connect(self.record_keys)
        self.tabs.currentChanged.connect(lambda _: self.keys.mask_all())
        self.tabs.currentChanged.connect(self._tab_shown)

        self._codeplug_changed()
        if not ctx.engine_check.ok:
            self.drawer.set_status("Programming engine problem")
        if ctx.fleet.current_missing():
            QMessageBox.warning(self, "TYTcps", "The current key set file is missing (%s). Choose "
                                                "a key set in the Keys tab." % ctx.current_name)

    # -- menu ------------------------------------------------------------------------

    def _build_menu(self):
        m = QMenu(self)

        def add(text, fn, shortcut=None, menu=m):
            a = QAction(text, self)
            # triggered(bool) would hand 'checked' to the first parameter
            # (write_image's preset, open_file's path): call with none.
            a.triggered.connect(lambda checked=False, fn=fn: fn())
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                self.addAction(a)
            menu.addAction(a)
            return a
        add("Open…", self.open_file, "Ctrl+O")
        self.a_save = add("Save", self.save, "Ctrl+S")
        self.a_saveas = add("Save as…", self.save_as, "Ctrl+Shift+S")
        m.addSeparator()
        adv = m.addMenu("Advanced")
        self.a_import = add("Import conf text…", self.import_conf, menu=adv)
        self.a_export = add("Export conf text…", self.export_conf, menu=adv)
        m.addSeparator()
        add("Settings…", self.settings)
        add("Copy diagnostics", self.copy_diagnostics)
        add("Save diagnostics…", self.save_diagnostics)
        add("About TYTcps", self.about)
        add("Quit", self.close, "Ctrl+Q")
        return m

    # -- state -----------------------------------------------------------------------

    def _codeplug_changed(self):
        cp = self.ctx.codeplug
        for title, ph, w in self.cp_tabs:
            ph.set_open(cp is not None)
        self.general.load()
        self.menu_tab.load()
        self.buttons_tab.load()
        for page in self.pages_76():
            page.load()
        for t in self.tables():
            t.model.refresh()
        self.channels.counts()
        self.update_state()

    def tables(self):
        return self.channels.tables() + [self.zones] + self.scanlists.tables() + \
            [self.contacts, self.grouplists, self.msgs]

    def pages_76(self):
        return [self.emergency_tab, self.dtmf_tab, self.vfo_tab]

    def forms(self):
        """Everything with fields that can refuse input: the CPS pages and
        the details panels under the Channels and Scan lists grids."""
        return [self.general, self.menu_tab, self.buttons_tab] + self.pages_76() + \
            self.channels.panels() + self.scanlists.panels()

    def _tab_shown(self, i):
        # Forms that list contacts and messages are rebuilt when shown, not on
        # every edit (rebuilding combos inside their own signal is unsafe).
        w = self.tabs.widget(i)
        for title, ph, inner in self.cp_tabs:
            if ph is w and self.ctx.codeplug is not None and \
                    (inner is self.buttons_tab or inner in self.pages_76()):
                inner.load()

    def _repaint_grids(self):
        for t in self.tables():
            t.model.repaint_all()

        self.keys._used_by()

    def _preview_changed(self):
        p = self.preview_ctl.current()
        cells = error_cells(self.ctx, p) if p and not p.ok else {}
        for t in self.tables():
            t.model.set_engine_errors({(uid, col): msg for (kind, uid, col), msg in cells.items()
                                       if kind == t.kind})
        self.update_state()

    def update_state(self):
        cp = self.ctx.codeplug
        if cp is None:
            self.setWindowTitle("TYTcps")
        else:
            self.setWindowTitle("TYTcps — %s%s" % (cp.title, " •" if cp.dirty else ""))
        for title, ph, w in self.cp_tabs:
            i = self.tabs.indexOf(ph)
            edited, errors = self._tab_flags(w)
            self.tabs.setTabText(i, title + (" •" if edited else ""))
            self.tabs.setTabIcon(i, dot_icon("#c0392b") if errors else QIcon())
        i = self.tabs.indexOf(self.keys)
        self.tabs.setTabText(i, "Keys" + (" •" if self.keys.has_draft() else ""))
        p = self.preview_ctl.current()
        grid_errors = cp is not None and (any(f.has_errors() for f in self.forms()) or
                                          any(t.model.has_errors() for t in self.tables()))
        write_ok = cp is not None and p is not None and p.ok and not grid_errors
        if cp is None:
            why = "Open a codeplug file or read a radio first."
        elif grid_errors or (p is not None and not p.ok):
            why = "Fix the problems marked in red first."
        elif p is None:
            why = "Waiting for the preview of your changes."
        else:
            why = ""
        keys_ok = self.keys.saved is not None and not self.keys.has_draft()
        if self.bar.state in ("restarting", "busy"):
            radio_why = "Wait: the radio is %s." % ("restarting" if self.bar.state == "restarting"
                                                    else "busy")
        elif not self.bar.operable():
            radio_why = "No radio is ready (see the radio bar)."
        elif not self.bar.identified():
            radio_why = "Identify the radio first (radio bar)."
        else:
            radio_why = ""
        if self.keys.has_draft():
            why_keys = ("Save the key set first.")
        elif self.keys.saved is None:
            why_keys = "No key set yet (Keys tab)."
        elif not self.bar.keys_supported() and self.bar.identified():
            why_keys = "This radio model isn't supported for keys."
        else:
            why_keys = radio_why
        model_why = codeplug_model_problem(self.ctx.unit) if self.bar.identified() else None
        why = why or radio_why or model_why
        self.bar.set_buttons(True, write_ok and not model_why, keys_ok, why, why_keys)
        busy = self.ctx.runner.busy
        self.keys.a_read.setEnabled(self.bar.operable() and not busy)
        self.keys.a_write.setEnabled(keys_ok and self.bar.b_keys.isEnabled())
        self.keys.a_write.setToolTip("" if self.keys.a_write.isEnabled() else why_keys)
        self.a_save.setEnabled(cp is not None)
        self.a_saveas.setEnabled(cp is not None)
        self.a_import.setEnabled(cp is not None)
        self.a_export.setEnabled(cp is not None)
        if not busy and self.bar.state not in ("busy", "restarting"):
            self.drawer.set_status("Ready" if self.ctx.engine_check.ok else "Programming engine problem")
        elif self.bar.state == "restarting":
            self.drawer.set_status("Radio restarting…")

    def _tab_flags(self, w):
        cp = self.ctx.codeplug
        if cp is None:
            return False, False
        from ..backend.conf import scalar_record

        def table_edited(kind):
            return bool(cp.doc.tables[kind].deleted or any(r.edited for r in cp.doc.rows(kind)))

        def scalars_edited(record):
            return any(s.edited for s in cp.doc.scalars.values()
                       if scalar_record(s.name)[0] == record)
        if w is self.general:
            return scalars_edited("general"), self.general.has_errors()
        if w is self.menu_tab:
            return scalars_edited("menu") or table_edited("Menu"), self.menu_tab.has_errors()
        if w is self.buttons_tab:
            return (scalars_edited("buttons") or table_edited("Buttons") or
                    table_edited("OneTouch") or table_edited("NumberKey")), \
                self.buttons_tab.has_errors()
        if w is self.emergency_tab:
            return scalars_edited("emergency") or table_edited("EmergencySystem"), w.has_errors()
        if w is self.dtmf_tab:
            return any(table_edited(k) for k in ("DTMFSystem", "DTMFEncode", "DTMFDecode")), \
                w.has_errors()
        if w is self.vfo_tab:
            return scalars_edited("vfo"), w.has_errors()
        tabs = w.tables() if hasattr(w, "tables") else [w]
        kinds = [t.kind for t in tabs] + (w.detail_kinds() if hasattr(w, "detail_kinds") else [])
        edited = any(table_edited(k) for k in kinds)
        errors = any(t.model.has_errors() for t in tabs) or \
            any(p.has_errors() for p in (w.panels() if hasattr(w, "panels") else []))
        return edited, errors

    # -- radio runs ------------------------------------------------------------------

    def _job_started(self, cmd):
        self.job_label = cmd.label
        self.block = self.drawer.start(cmd)
        text = START_TEXT.get(cmd.label, "Working…")
        self.bar.set_retrying(False)
        self.bar.job_started(text)
        self.drawer.set_status(text)
        self.update_state()

    def _job_event(self, ev):
        kind = ev.get("event")
        if kind == "unit":
            self.bar.unit_seen(ev)
        elif kind == "phase":
            self.bar.set_fraction(None)     # a new phase: moving until its first progress
            text = PHASE_TEXT.get(self.job_label, {}).get(ev.get("phase"))
            if text:
                self.bar.job_progress(text)
                self.drawer.set_status(text)
        elif kind == "progress" and ev.get("total"):
            base = PHASE_TEXT.get(self.job_label, {}).get(ev.get("phase"), self.bar.busy_text)
            text = "%s (%d%%)" % (base, 100 * ev["done"] // ev["total"])
            self.bar.set_fraction((ev["done"], ev["total"]))
            self.bar.job_progress(text)
            self.drawer.set_status(text)

    def _job_finished(self, res):
        if self.block:
            self.drawer.finish(self.block, res)
            if not res.ok:
                self.drawer.reveal(self.block)
        opened = res.unit is not None
        if res.command.label == "identify" and res.ok:
            self.bar.unit_seen(res.result)
        self.bar.job_finished(opened)
        # E-K4 and an unfinished codeplug write are recorded by the dialog
        # that ran them (it knows the unit it showed and the image it wrote).
        if any(w.get("code") == "reboot_failed" for w in res.warnings):
            self.bar.radio_stuck()
        self.ctx.fleet_changed.emit()
        self.update_state()

    def _retrying(self):
        self.bar.set_retrying(True)
        self.drawer.set_status("Radio restarting, retrying…")

    def _busy_refuse(self):
        if self.ctx.runner.busy:
            QMessageBox.information(self, "TYTcps", "A radio operation is already running.")
            return True
        return False

    def identify(self):
        if self._busy_refuse():
            return

        def done(res):
            if not res.ok:
                self._fail(res)
            for w in res.warnings:
                self._warning_note(w, res)
        self.ctx.runner.run_radio(radio.identify(), done)

    def read(self):
        if self._busy_refuse() or not self._unsaved_ok("reading a radio"):
            return
        out = self.ctx.runtime.new_run("read-out")

        def done(res):
            if not res.ok:
                self._fail(res)
                return
            when = datetime.datetime.now().strftime("%H:%M")
            cp, r = cpmod.from_read(self.ctx.engine, out / "device.img", when)
            if cp is None:
                self._fail(r)
                return
            self._set_codeplug(cp)
            for w in res.warnings:
                self._warning_note(w, res)
        self.ctx.runner.run_radio(radio.read(out, self.ctx.engine.short), done)

    def read_names(self):
        if self._busy_refuse():
            return

        def done(res):
            if not res.ok:
                self._fail(res)
                return
            self.keys.show_radio_slots(res.result.get("slots", []))
        self.ctx.runner.run_radio(radio.read_keys(), done)

    def _write_gate(self, keys=False, codeplug=False):
        """The radio bar's own conditions, checked again at the moment a write
        dialog is opened, whichever button or menu opened it."""
        why = None
        if not self.ctx.engine_check.ok:
            why = "The programming engine is missing or the wrong version."
        elif self.ctx.runner.busy:
            why = "A radio operation is already running."
        elif not self.bar.operable():
            why = "No radio is ready (see the radio bar)."
        elif not self.bar.identified():
            why = "Identify the radio first."
        elif keys and not self.bar.keys_supported():
            why = "This radio model isn't supported for keys."
        elif codeplug:
            why = codeplug_model_problem(self.ctx.unit)
        if why:
            QMessageBox.information(self, "TYTcps", why)
            return False
        return True

    def write_codeplug(self):
        self._commit_edit()
        if self.ctx.codeplug is None or not self._write_gate(codeplug=True):
            return
        dlg = WriteCodeplugDialog(self.ctx, self.preview_ctl, self)
        dlg.exec()
        dlg.deleteLater()
        if dlg.goto_request:
            self._goto_event(dlg.goto_request)
            return
        res = dlg.result
        if res is None and dlg.action == "write_again" and dlg.attempt_image:
            # the radio's last write didn't complete: write that image whole
            self.write_image(dlg.attempt_image, (
                "The last codeplug write to this radio didn't finish. This writes that codeplug "
                "again in full."))
        elif res is not None and not res.ok:
            self._do_action(dlg.action, res, attempt=dlg.attempt_image)
        elif res is not None and res.ok and dlg.keys_after:
            self._wait_settled()
            self.write_keys()

    def write_keys(self):
        if not self._write_gate(keys=True):
            return
        name = self.keys.viewed if not self.keys.has_draft() else None
        if not name:
            QMessageBox.information(self, "TYTcps", "Save a key set first (Keys tab).")
            return
        try:
            dlg = WriteKeysDialog(self.ctx, name, self)
        except K.SaveError as e:
            QMessageBox.warning(self, "TYTcps", str(e))
            return
        dlg.exec()
        dlg.deleteLater()
        res = dlg.result
        if res is not None and res.code == "ledger_failed" and getattr(dlg, "record_now", False):
            a207 = (res.error or {}).get("a207") or (self.ctx.unit or {}).get("a207")
            if a207:
                self.record_keys(a207, "recovered", name)
        elif res is not None and not res.ok:
            self._do_action(dlg.action, res)

    def write_image(self, preset, note=None):
        """Write again, whole, the codeplug a write that broke off was writing."""
        self._commit_edit()
        if not self._write_gate(codeplug=True):
            return
        dlg = WriteImageDialog(self.ctx, self, preset, note)
        dlg.exec()
        dlg.deleteLater()
        if dlg.result is not None and not dlg.result.ok:
            self._do_action(dlg.action, dlg.result, attempt=getattr(dlg, "attempt", None) or dlg.path)

    def record_keys(self, a207, tool="manual", keyset=None):
        dlg = RecordKeysDialog(self.ctx, a207, tool, keyset, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        note = " ".join(dlg.note.text().replace("\t", " ").split())
        r = self.ctx.engine.run(K.add_existing(self.ctx.fleet.folder, a207,
                                               dlg.sets.currentText(), note, tool))
        if not r.ok:
            self._fail(r)
        if r.ok:
            self.ctx.mark_keys_unknown(a207, False)
        self.ctx.fleet_changed.emit()

    def _fail(self, res):
        """A failed run outside a dialog: the catalogue message, then its action."""
        msg = messages.explain(res)
        if self.block is not None and res.command.radio:
            self.drawer.reveal(self.block)
        elif not res.command.radio:
            self.drawer.reveal(self.drawer.blocks[-1]) if self.drawer.blocks else None
        self._do_action(messages.show(self, msg), res)

    def _wait_settled(self, timeout=7.0):
        """An action chosen right after a run (Try again, Write again) waits
        for the radio's restart to end before its own checks run."""
        def settled():
            return not self.ctx.runner.busy and self.bar.state not in ("restarting", "busy")
        if settled():
            return
        self.drawer.set_status("Waiting for the radio to restart…")
        loop = QEventLoop()
        timer = QTimer()
        deadline = time.monotonic() + timeout

        def check():
            if settled() or time.monotonic() > deadline:
                loop.quit()
        timer.timeout.connect(check)
        timer.start(100)
        loop.exec()
        timer.stop()

    def _do_action(self, action, res, attempt=None):
        if not action:
            return
        if action in ("retry", "write_again", "write_keys_again"):
            self._wait_settled()
        label = res.command.label
        if action == "retry":
            {"identify": self.identify, "read": self.read, "read-keys": self.read_names,
             "write-codeplug": self.write_codeplug, "write-keys": self.write_keys,
             "write-image": lambda: self.write_image(attempt) if attempt else None
             }.get(label, lambda: None)()
        elif action == "fix_usb":
            self.settings()
        elif action == "diagnostics":
            self.copy_diagnostics()
        elif action == "write_again":
            # After a write that broke off or didn't verify, never run -c over
            # the damaged radio: -c would read it, keep what it didn't name,
            # and verify against that. Write the intended image whole.
            if attempt is not None and Path(attempt).is_file():
                self.write_image(attempt, "The last write didn't finish. This writes the same "
                                          "codeplug again in full.")
            else:
                self.write_codeplug()
        elif action == "write_keys_again":
            self.write_keys()
        elif action == "goto":
            self._goto_event(res.error or {})
        elif action == "open_keys":
            self.tabs.setCurrentWidget(self.keys)
        elif action == "record_now":
            a207 = res.a207 or (self.ctx.unit or {}).get("a207")
            if a207:
                self.record_keys(a207, "recovered")
        elif action == "copy_line":
            QGuiApplication.clipboard().setText((res.error or {}).get("line", ""))

    def _warning_note(self, w, res=None):
        code = w.get("code")
        if code == "reboot_failed":
            self.bar.radio_stuck()
            QMessageBox.warning(self, "TYTcps", "The radio is still in programming mode. Switch "
                                                "it off and on.")
        elif code == "unit_unreadable" or (code == "unit_block_unreadable" and
                                           (res is None or not res.a207)):
            if getattr(self, "_unit_note_for", None) is res and res is not None:
                return          # one message per run
            self._unit_note_for = res
            QMessageBox.warning(self, "TYTcps", "Couldn't identify the radio. Reconnect it and "
                                                "try again.")
        elif code == "privacy_inconsistent":
            QMessageBox.warning(self, "TYTcps", "Channel %s has encryption set but switched off. "
                                                "Set its Privacy again and write to fix it."
                                % w.get("channel", "?"))

    # -- codeplug files --------------------------------------------------------------

    def _set_codeplug(self, cp):
        self.ctx.codeplug = cp
        self.ctx.codeplug_changed.emit()

    def _commit_edit(self):
        """Finish a number still being typed in a CPS form, so Save, Open,
        Read, Write and Quit act on it (or refuse it) instead of losing it."""
        commit_focused()

    def _unsaved_ok(self, doing):
        self._commit_edit()
        cp = self.ctx.codeplug
        if cp is None or not cp.dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("TYTcps")
        if cp.path is not None:
            box.setText("%s has changes that aren't saved." % cp.path.name)
            box.setInformativeText("Saving overwrites %s. (Writing to a radio doesn't save the "
                                   "file.)" % cp.path)
        else:
            box.setText("%s isn't saved." % cp.title)
            box.setInformativeText("Save it before %s?" % doing)
        save = box.addButton(QMessageBox.StandardButton.Save)
        discard = box.addButton(QMessageBox.StandardButton.Discard)
        cancel = box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        r = box.clickedButton()
        if r is save:
            return self.save()
        return r is discard

    def _start_dir(self):
        return self.ctx.setting("files/codeplug_dir", None) or str(paths.documents_folder())

    def open_file(self, path=None):
        if not self._unsaved_ok("opening another file"):
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open codeplug", self._start_dir(),
                                                  "Codeplug files (*.img);;All files (*)")
        if not path:
            return
        p = Path(path)
        if not p.is_file() or p.stat().st_size != cpmod.IMAGE_SIZE:
            QMessageBox.warning(self, "TYTcps", "That isn't a codeplug file for this radio.")
            return
        cp, r = cpmod.open_file(self.ctx.engine, p)
        if cp is None:
            self._fail(r)
            return
        self._set_codeplug(cp)
        for w in r.warnings:
            self._warning_note(w, r)

    def save(self):
        self._commit_edit()
        cp = self.ctx.codeplug
        if cp is None:
            return False
        if cp.path is None:
            return self.save_as()
        return self._save_to(cp.path)

    def save_as(self):
        self._commit_edit()
        cp = self.ctx.codeplug
        if cp is None:
            return False
        suggest = cp.path.name if cp.path else "codeplug-%s.img" % datetime.date.today().isoformat()
        path, _ = QFileDialog.getSaveFileName(self, "Save codeplug", str(Path(self._start_dir()) / suggest),
                                              "Codeplug files (*.img)")
        if not path:
            return False
        if not path.endswith(".img"):
            path += ".img"
        return self._save_to(Path(path))

    def _save_to(self, path):
        cp = self.ctx.codeplug
        if any(f.has_errors() for f in self.forms()) or any(t.model.has_errors() for t in self.tables()):
            QMessageBox.warning(self, "TYTcps", "Fix the problems marked in red before saving.")
            return False
        src = cp.base
        if cp.doc.is_edited():
            run = self.ctx.runtime.new_run("save")
            conf = run / "edited.conf"
            conf.write_text(cp.edited_text(), encoding="utf-8")
            out = run / "out"
            out.mkdir()
            r = self.ctx.engine.run(cpmod.apply(cp.base, conf, out, None, self.ctx.engine.short))
            if not r.ok:
                self._fail(r)
                return False
            src = out / "device.img"
        tmp = path.with_name(".%s.tmp-%d" % (path.name, os.getpid()))
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, path)
        except OSError as e:
            QMessageBox.warning(self, "TYTcps", "Couldn't save %s: %s" % (path, e.strerror))
            if tmp.exists():
                tmp.unlink()
            return False
        tab = self.tabs.currentIndex()
        new, r = cpmod.open_file(self.ctx.engine, path)
        if new is None:
            self._fail(r)
            return False
        self._set_codeplug(new)
        self.tabs.setCurrentIndex(tab)
        return True

    def import_conf(self):
        cp = self.ctx.codeplug
        if cp is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import conf text", self._start_dir(),
                                              "Conf text (*.conf);;All files (*)")
        if not path:
            return
        run = self.ctx.runtime.new_run("import")
        out = run / "out"
        out.mkdir()
        r = self.ctx.engine.run(cpmod.apply(cp.base, path, out, None, self.ctx.engine.short))
        if not r.ok:
            self._fail(r)
            return
        if any(w.get("code") == "no_privacy_columns" for w in r.warnings):
            QMessageBox.information(self, "TYTcps", "This file has no Privacy or Key columns, so "
                                                    "encryption settings stay as they are.")
        new, r2 = cpmod.from_read(self.ctx.engine, out / "device.img", "")
        if new is None:
            self._fail(r2)
            return
        new.title = "Imported %s" % Path(path).name
        self._set_codeplug(new)

    def export_conf(self):
        cp = self.ctx.codeplug
        if cp is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export conf text",
                                              str(Path(self._start_dir()) / "codeplug.conf"),
                                              "Conf text (*.conf)")
        if path:
            Path(path).write_text(cp.edited_text(), encoding="utf-8")

    # -- preview ---------------------------------------------------------------------

    def show_preview(self):
        p = self.preview_ctl.current()
        if p and p.ok:
            PreviewPanel(p, self).exec()

    def goto_error(self):
        p = self.preview_ctl.current()
        if p and p.errors:
            self._goto_event(p.errors[0])

    def _form_tab(self, form):
        for title, ph, w in self.cp_tabs:
            if w is form:
                self.tabs.setCurrentWidget(ph)
                return

    def _goto_event(self, e):
        sec = e.get("section")
        col = e.get("column")
        msg = e.get("message")
        cells = error_cells(self.ctx, self.preview_ctl.current())
        target = [(k, uid, col) for (k, uid, col) in cells if k == sec]
        if sec == "General":
            # Menu Hang Time, Long Press Duration, the emergency settings and
            # the VFOs are General keys in the conf, but the CPS shows them on
            # their own pages.
            from ..backend.conf import scalar_record
            form = {"menu": self.menu_tab, "buttons": self.buttons_tab,
                    "emergency": self.emergency_tab, "vfo": self.vfo_tab}.get(
                scalar_record(col or "")[0], self.general)
            self._form_tab(form)
            form.flag(col, msg)
            return
        if sec in ("EmergencySystem", "DTMFSystem", "DTMFEncode", "DTMFDecode"):
            form = self.emergency_tab if sec == "EmergencySystem" else self.dtmf_tab
            self._form_tab(form)
            num = "".join(ch for ch in str(e.get("id") or "") if ch.isdigit())
            if num:
                form.flag_row(sec, num, col, msg)
            return
        if sec in ("Menu", "Buttons", "OneTouch", "NumberKey"):
            self._form_tab(self.menu_tab if sec == "Menu" else self.buttons_tab)
            return
        if sec in ("ChanDigital", "ChanAnalog", "ScanTiming"):
            num = "".join(ch for ch in str(e.get("id") or "") if ch.isdigit())
            tab = self.scanlists if sec == "ScanTiming" else self.channels
            self._form_tab(tab)
            if num:
                tab.show_details_of(sec, int(num), col, msg)
            return
        for title, ph, w in self.cp_tabs:
            tabs = w.tables() if hasattr(w, "tables") else ([w] if isinstance(w, TableTab) else [])
            for t in tabs:
                if t.kind == sec:
                    self.tabs.setCurrentWidget(ph)
                    if w is self.channels:
                        self.channels.show_kind(sec)
                    if target:
                        t.goto(target[0][1], target[0][2])
                    elif e.get("id"):
                        num = "".join(ch for ch in str(e["id"]) if ch.isdigit())
                        row = self.ctx.codeplug.doc.tables[sec].find(int(num)) if num else None
                        if row:
                            t.goto(row.uid, 14 if e.get("code") == "key_slot_empty" else 0)
                    return

    # -- misc ------------------------------------------------------------------------

    def settings(self):
        SettingsDialog(self.ctx, self).exec()
        self.ctx.fleet_changed.emit()

    def copy_diagnostics(self):
        u = self.ctx.unit or {}
        ec = self.ctx.engine_check
        lines = ["TYTcps %s" % __version__,
                 "Engine: %s" % ("dmrconfig-tyt %s (%s %s)" % (ec.info.get("version"),
                                 ec.info.get("branch"), ec.info.get("commit")) if ec.ok else ec.problem),
                 "Radio: %s, firmware %s, unit %s" % (u.get("model", "-"), u.get("firmware", "-"),
                                                      short_unit(u.get("a207", "")) if u else "-"),
                 "", self.drawer.last_text(3, radio_only=True, raw=True)]
        from .diagnostics import copy_text
        if copy_text(self, "\n".join(lines)):
            self.drawer.set_status("Diagnostics copied")

    def save_diagnostics(self, path=None):
        from .diagnostics import save_dialog
        return save_dialog(self, path)

    def radio_busy(self):
        return self.ctx.runner.busy

    def about(self):
        ec = self.ctx.engine_check
        QMessageBox.about(self, "About TYTcps", (
            "<b>TYTcps %s</b><br>A Linux programmer for the TYT MD-UV390 Plus.<br><br>Engine: "
            "dmrconfig-tyt %s (%s %s), based on dmrconfig by Serge Vakulenko (BSD-3).<br>Free "
            "software under the GNU GPL, version 3 or later.") % (
                __version__, ec.info.get("version", "?"), ec.info.get("branch", "?"),
                ec.info.get("commit", "?")))

    # -- window ----------------------------------------------------------------------

    def changeEvent(self, ev):
        if ev.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            self.keys.mask_all()
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self.ctx.runner.busy:
            QMessageBox.information(self, "TYTcps", "A radio operation is running. Wait for it to "
                                                    "finish before closing.")
            ev.ignore()
            return
        if not self._unsaved_ok("closing"):
            ev.ignore()
            return
        if self.keys.has_draft():
            r = QMessageBox.question(
                self, "TYTcps", "The key set hasn't been saved.",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                ev.ignore()
                return
            if r == QMessageBox.StandardButton.Save:
                self.keys.save_new()
                if self.keys.has_draft():
                    ev.ignore()
                    return
        self.keys.mask_all()
        self.keys._clear_clipboard()
        ev.accept()
