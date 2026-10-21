# SPDX-License-Identifier: GPL-3.0-or-later
"""The Keys tab. Everything here belongs to the fleet folder.

Keys are shown in CPS grid order, masked by default. A reveal shows one slot
and re-masks after the timeout, on tab change and on window blur. Copy is a
separate, explicit action, and the clipboard is cleared 30 s later if it
still holds the key. Edits make a draft that exists only in memory until it
is saved as a NEW key set file; a saved set is never edited in place.
"""

import copy
import shutil
from pathlib import Path

from PyQt6.QtCore import QMimeData, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QToolBar, QToolButton, QVBoxLayout,
                             QWidget)

from ..backend import keys as K
from ..backend.codeplug import name_display

MASK = "●" * 12
CONTRACT_WARNING = (
    "Every radio needs this key set. A radio with the old key in slot %s can't talk encrypted "
    "with radios on the new one.")
RADIO_BANNER = ("Radios don't send the keys back, only types and names.")


class KeysTab(QWidget):
    write_keys_requested = pyqtSignal()
    show_fleet_requested = pyqtSignal()
    read_names_requested = pyqtSignal()
    changed = pyqtSignal()            # draft state or viewed set changed

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.saved = None             # KeySet of the viewed file
        self.viewed = None            # its file name
        self.draft = None
        self.draft_note = ""
        self.revealed = set()
        self.radio_slots = None       # from -k, shown beside the grid
        self.reveal_timer = QTimer(self)
        self.reveal_timer.setSingleShot(True)
        self.reveal_timer.timeout.connect(self.mask_all)
        self.clip_timer = QTimer(self)
        self.clip_timer.setSingleShot(True)
        self.clip_timer.timeout.connect(self._clear_clipboard)
        self.clip_value = None
        self._loading = False
        self.write_allowed = lambda: False     # set by the main window: the radio bar's gate

        lay = QVBoxLayout(self)
        head = QGridLayout()
        self.h_name = QLabel()
        self.h_sha = QLabel()
        self.h_on = QLabel()
        f = self.h_name.font()
        f.setBold(True)
        self.h_name.setFont(f)
        b_change = QPushButton("Change…")
        b_change.clicked.connect(self.change_current)
        b_fleet = QPushButton("Show in Fleet")
        b_fleet.clicked.connect(self.show_fleet_requested)
        head.addWidget(QLabel("Current key set:"), 0, 0)
        head.addWidget(self.h_name, 0, 1)
        head.addWidget(self.h_sha, 0, 2)
        head.addWidget(b_change, 0, 3)
        head.addWidget(QLabel("On this set:"), 1, 0)
        head.addWidget(self.h_on, 1, 1, 1, 2)
        head.addWidget(b_fleet, 1, 3)
        head.setColumnStretch(2, 1)
        lay.addLayout(head)

        self.viewing = QLabel()
        self.viewing.setStyleSheet("color:#777")
        lay.addWidget(self.viewing)

        plus = QLabel("These keys are for Universal privacy and work only on the MD-UV390 Plus. "
                      "Other MD-UV390s take the codeplug and Basic or Enhanced privacy, but "
                      "their Universal channels sound garbled.")
        plus.setStyleSheet("color:#777")
        plus.setWordWrap(True)
        lay.addWidget(plus)

        self.bar = QFrame()
        self.bar.setStyleSheet("QFrame { color:#1f2d3a; background:#fdebd0; border:1px solid #f5b041; "
                               "border-radius:4px; } QLabel { border:none; color:#1f2d3a; }")
        bl = QHBoxLayout(self.bar)
        self.bar_text = QLabel()
        self.bar_text.setWordWrap(True)
        bl.addWidget(self.bar_text, 1)
        self.b_save = QPushButton("Save as new key set")
        self.b_discard = QPushButton("Discard")
        self.b_save.clicked.connect(self.save_new)
        self.b_discard.clicked.connect(self.discard)
        bl.addWidget(self.b_save)
        bl.addWidget(self.b_discard)
        lay.addWidget(self.bar)

        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("color:#1f2d3a; background:#eaf2f8; border:1px solid #aed6f1; "
                                  "border-radius:4px; padding:6px")
        lay.addWidget(self.banner)

        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.a_gen = tb.addAction("Generate key", self.generate)
        self.a_enter = tb.addAction("Enter key…", self.enter_key)
        self.a_clear = tb.addAction("Clear slot", self.clear_slot)
        tb.addSeparator()
        self.a_rot = tb.addAction("New rotation…", self.rotation)
        self.a_new = tb.addAction("New key set", self.new_set)
        tb.addSeparator()
        self.a_imp = tb.addAction("Import CPS key file…", self.import_file)
        self.a_exp = tb.addAction("Export CPS key file…", self.export_file)
        tb.addSeparator()
        self.a_read = tb.addAction("Read slot names from radio", lambda: self.read_names_requested.emit())
        self.a_write = tb.addAction("Write keys to radio…", lambda: self.write_keys_requested.emit())
        lay.addWidget(tb)

        self.empty = QWidget()
        el = QHBoxLayout(self.empty)
        el.addWidget(QLabel("No key set yet."))
        b1 = QPushButton("New key set")
        b1.clicked.connect(self.new_set)
        b2 = QPushButton("Import CPS key file…")
        b2.clicked.connect(self.import_file)
        el.addWidget(b1)
        el.addWidget(b2)
        el.addStretch(1)
        lay.addWidget(self.empty)

        self.table = QTableWidget(16, 7)
        self.table.setHorizontalHeaderLabels(["Slot", "Type", "Name", "Key", "Length", "Used by",
                                              "On radio"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        for i, w in enumerate((50, 110, 170, 330, 70, 110)):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, 1)
        self.table.itemSelectionChanged.connect(self._actions)

        ctx.keyset_changed.connect(self.reload)
        ctx.fleet_changed.connect(self._header)
        ctx.doc_edited.connect(self._used_by)
        ctx.codeplug_changed.connect(self._used_by)
        self.reload()

    # -- what is shown -----------------------------------------------------------------

    @property
    def shown(self):
        return self.draft or self.saved

    def has_draft(self):
        return self.draft is not None

    def viewed_path(self):
        return self.ctx.fleet.keys_dir / self.viewed if self.viewed and not self.draft else None

    def reload(self, name=None):
        """Show a saved set: `name`, else the current one."""
        self.mask_all()
        name = name or self.ctx.current_name
        self.saved, self.viewed = None, None
        if name and (self.ctx.fleet.keys_dir / name).is_file():
            try:
                self.saved = K.load(self.ctx.engine, self.ctx.fleet.keys_dir / name)
                self.viewed = name
            except K.SaveError as e:
                QMessageBox.warning(self, "TYTcps", "Key set %s can't be read: %s" % (name, e))
        self.radio_slots = None
        self.render()

    def render(self):
        self._loading = True
        ks = self.shown
        self.empty.setVisible(ks is None)
        self.table.setVisible(ks is not None)
        self.table.setColumnHidden(6, self.radio_slots is None)
        if ks is not None:
            for s in ks.slots:
                self._render_slot(s)
        self._loading = False
        self._header()
        self._bar()
        self._used_by()
        self._actions()
        self.changed.emit()

    def _render_slot(self, s):
        r = s.slot - 1
        it = QTableWidgetItem(str(s.slot))
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(r, 0, it)
        cb = QComboBox()
        cb.addItems(["(empty)"] + K.TYPE_NAMES)
        cb.setCurrentText("(empty)" if s.type == "empty" else s.type)
        cb.currentTextChanged.connect(lambda t, slot=s.slot: self._type_changed(slot, t))
        self.table.setCellWidget(r, 1, cb)
        name = QLineEdit(s.name if s.type != "empty" else "")
        name.setMaxLength(K.NAME_MAX)
        name.setEnabled(s.type != "empty")
        name.setPlaceholderText("" if s.type != "empty" else "")
        name.textEdited.connect(lambda t, slot=s.slot: self._name_changed(slot, t))
        self.table.setCellWidget(r, 2, name)
        self.table.setCellWidget(r, 3, self._key_widget(s))
        ln = QTableWidgetItem("%d B" % s.length if s.type != "empty" else "")
        ln.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(r, 4, ln)
        if self.radio_slots is not None:
            rs = self.radio_slots.get(s.slot)
            txt = "%s · %s" % (rs[0], rs[1]) if rs else "?"
            ri = QTableWidgetItem(txt)
            ri.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if rs and (rs[0] != (s.type if s.type != "empty" else rs[0])):
                ri.setForeground(Qt.GlobalColor.darkRed)
            self.table.setItem(r, 6, ri)

    def _key_widget(self, s):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(4, 0, 2, 0)
        problem = s.problem() if s.type != "empty" else None
        if s.type == "empty":
            lab = QLabel("")
        elif not s.key:
            lab = QLabel("<span style='color:#c0392b'>no key</span>")
        elif s.slot in self.revealed:
            lab = QLabel("<tt>%s</tt>" % K.grouped_hex(s.key))
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        else:
            lab = QLabel(MASK)
        if problem:
            lab.setToolTip(problem)
            w.setStyleSheet("QWidget { border:1px solid #c0392b; }")
        l.addWidget(lab, 1)
        if s.filled:
            eye = QToolButton()
            eye.setText("👁")
            eye.setAutoRaise(True)
            eye.setCheckable(True)
            eye.setChecked(s.slot in self.revealed)
            eye.setToolTip("Show this key (CPS grid order). It hides again after %d s."
                           % self.timeout())
            eye.toggled.connect(lambda on, slot=s.slot: self.reveal(slot, on))
            l.addWidget(eye)
        return w

    def timeout(self):
        return int(self.ctx.setting("keys/reveal_seconds", 30, int))

    def reveal(self, slot, on):
        if on:
            self.revealed = {slot}
            self.reveal_timer.start(self.timeout() * 1000)
        else:
            self.revealed.discard(slot)
        ks = self.shown
        if ks:
            for s in ks.slots:
                self.table.setCellWidget(s.slot - 1, 3, self._key_widget(s))

    def mask_all(self):
        if self.revealed:
            self.revealed = set()
            ks = self.shown
            if ks:
                for s in ks.slots:
                    self.table.setCellWidget(s.slot - 1, 3, self._key_widget(s))

    def _header(self):
        name = self.ctx.current_name
        if not name:
            self.h_name.setText("none")
            self.h_sha.setText("")
            self.h_on.setText("-")
        else:
            sha = self.ctx.current_sha
            missing = self.ctx.fleet.current_missing()
            self.h_name.setText(K.display_name(name) + (" (file missing)" if missing else ""))
            self.h_sha.setText("SHA256 %s…%s" % (sha[:4], sha[-4:]) if sha else "")
            units = [u for u in self.ctx.fleet.roster() if not u.hidden]
            ledger = self.ctx.fleet.ledger()
            on = sum(1 for u in units if self.ctx.keys_status(u.a207, ledger).kind == "current")
            self.h_on.setText("%d of %d radio%s" % (on, len(units), "" if len(units) == 1 else "s"))
        if self.draft:
            self.viewing.setText("Draft (not saved)")
        elif self.viewed and self.viewed != name:
            self.viewing.setText("Viewing %s, which is not the current key set." % self.viewed)
        elif self.viewed:
            self.viewing.setText("Viewing %s · SHA256 %s" % (self.viewed, self.saved.sha256))
        else:
            self.viewing.setText("")

    def _bar(self):
        d = self.draft
        self.bar.setVisible(d is not None)
        if d is None:
            return
        text = "<b>Unsaved key changes.</b>"
        if self.draft_note:
            text += " " + self.draft_note
        if d.contract_changed:
            text += "<br>" + CONTRACT_WARNING % ", ".join(str(s) for s in sorted(d.contract_changed))
        probs = d.problems()
        if probs:
            text += "<br><span style='color:#c0392b'>Slot %d: %s</span>" % next(iter(probs.items()))
        self.bar_text.setText(text)
        self.b_save.setEnabled(not probs)

    def _used_by(self, *a):
        cp = self.ctx.codeplug
        for slot in range(1, 17):
            if cp is None:
                it = QTableWidgetItem("-")
            else:
                users = cp.doc.universal_users(slot)
                it = QTableWidgetItem("%d channel%s" % (len(users), "" if len(users) == 1 else "s")
                                      if users else "")
                it.setToolTip("\n".join('%s "%s"' % (r.cells[0], name_display(r.cells[1]))
                                        for r in users))
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(slot - 1, 5, it)

    def _actions(self):
        s = self._selected()
        ks = self.shown
        self.a_gen.setEnabled(s is not None and s.type != "empty")
        self.a_gen.setToolTip("" if s is None or s.type != "empty" else "Choose a type first.")
        self.a_enter.setEnabled(s is not None and s.type != "empty")
        self.a_clear.setEnabled(s is not None and s.type != "empty")
        self.a_rot.setEnabled(ks is not None and bool(ks.filled()))
        self.a_exp.setEnabled(self.saved is not None and self.draft is None)
        self.a_write.setEnabled(self.saved is not None and self.draft is None
                                and self.write_allowed())
        self.a_write.setToolTip("" if self.draft is None else
                                "Save the key set first.")
        self.a_new.setEnabled(self.draft is None)
        self.banner.setVisible(self.radio_slots is not None)
        self.banner.setText(RADIO_BANNER)

    def _selected(self):
        ks = self.shown
        r = self.table.currentRow()
        if ks is None or r < 0:
            return None
        return ks.slots[r]

    # -- editing ------------------------------------------------------------------------

    def _make_draft(self, note=None):
        if self.draft is None:
            base = self.saved or K.KeySet()
            self.draft = copy.deepcopy(base)
            self.draft.file = None
            self.draft.original = None
            self.draft.contract_changed = set()
            self.draft_note = note or ("Started from %s." % self.viewed if self.viewed else "")
        else:
            self.draft.original = None       # no longer a byte-exact import
        return self.draft

    def _type_changed(self, slot, text):
        if self._loading:
            return
        t = "empty" if text == "(empty)" else text
        ks = self.shown
        s = ks.slots[slot - 1]
        if t == s.type:
            return
        if s.key and QMessageBox.question(
                self, "TYTcps", "Changing the type of slot %d clears its key. Change it?" % slot
        ) != QMessageBox.StandardButton.Yes:
            self.render()
            return
        d = self._make_draft()
        ds = d.slots[slot - 1]
        ds.type = t
        ds.key = b""
        if t == "empty":
            ds.name = str(slot)
        elif not ds.name:
            ds.name = str(slot)
        d.contract_changed.add(slot)
        self.render()

    def _name_changed(self, slot, text):
        if self._loading:
            return
        d = self._make_draft()
        d.slots[slot - 1].name = text
        self._bar()
        self._header()
        self.changed.emit()

    def generate(self):
        s = self._selected()
        if s is None or s.type == "empty":
            return
        if s.key and QMessageBox.question(
                self, "TYTcps", "Replace slot %d's key with a new random one?" % s.slot
        ) != QMessageBox.StandardButton.Yes:
            return
        d = self._make_draft()
        d.slots[s.slot - 1].key = K.generate(s.type)
        d.contract_changed.add(s.slot)
        self.render()

    def enter_key(self):
        s = self._selected()
        if s is None or s.type == "empty":
            return
        dlg = EnterKeyDialog(s.slot, s.type, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = self._make_draft()
            d.slots[s.slot - 1].key = dlg.key
            d.contract_changed.add(s.slot)
            dlg.key = None
            self.render()

    def clear_slot(self):
        s = self._selected()
        if s is None or s.type == "empty":
            return
        if QMessageBox.question(self, "TYTcps", "Empty slot %d?" % s.slot) != \
                QMessageBox.StandardButton.Yes:
            return
        d = self._make_draft()
        ds = d.slots[s.slot - 1]
        ds.type, ds.key, ds.name = "empty", b"", str(s.slot)
        d.contract_changed.add(s.slot)
        self.render()

    def new_set(self):
        if self.draft is not None:
            return
        self.draft = K.KeySet()
        self.draft_note = "A new, empty key set."
        self.render()

    def rotation(self):
        ks = self.shown
        if ks is None or not ks.filled():
            return
        dlg = RotationDialog(ks, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        d = self._make_draft("A rotation of %s." % (self.viewed or "the draft"))
        for slot in dlg.chosen():
            ds = d.slots[slot - 1]
            ds.key = K.generate(ds.type)
            d.contract_changed.add(slot)
        self.render()

    def discard(self):
        if self.draft is None:
            return
        if QMessageBox.question(self, "TYTcps", "Discard the unsaved key changes?") != \
                QMessageBox.StandardButton.Yes:
            return
        self.draft = None
        self.draft_note = ""
        self.render()

    def import_file(self):
        if self.draft is not None and not self._confirm_drop_draft():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import CPS key file", str(Path.home()),
                                              "CPS key files (*.dec);;All files (*)")
        if not path:
            return
        try:
            ks = K.import_file(self.ctx.engine, path)
        except K.SaveError as e:
            QMessageBox.warning(self, "TYTcps", str(e))
            return
        self.draft = ks
        self.draft_note = ("Imported from %s (SHA256 %s…%s). Save it to use it."
                           % (Path(path).name, ks.sha256[:4], ks.sha256[-4:]))
        self.render()

    def export_file(self):
        p = self.viewed_path()
        if p is None:
            return
        if QMessageBox.warning(
                self, "TYTcps", "This file contains the keys unencrypted. Anyone with it can "
                                "listen to the fleet's encrypted channels. Export it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) != QMessageBox.StandardButton.Yes:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Export CPS key file", str(Path.home() / p.name),
                                              "CPS key files (*.dec)")
        if not dest:
            return
        try:
            K.write_private(dest, p.read_bytes())
        except OSError as e:
            QMessageBox.warning(self, "TYTcps", "Couldn't export: %s" % e.strerror)

    def save_new(self):
        d = self.draft
        if d is None:
            return
        try:
            name, sha = K.save_new(self.ctx.engine, d, self.ctx.fleet.keys_dir)
        except K.SaveError as e:
            QMessageBox.warning(self, "TYTcps", "The key set wasn't saved: %s" % e)
            return
        make_current = QMessageBox.question(
            self, "TYTcps", "Saved as %s (SHA256 %s…%s).\n\nMake this the current key set?"
            % (name, sha[:4], sha[-4:])) == QMessageBox.StandardButton.Yes
        self.draft = None
        self.draft_note = ""
        if make_current:
            self._set_current(name)
        self.ctx.fleet_changed.emit()
        self.reload(name)

    def _set_current(self, name):
        try:
            self.ctx.fleet.set_current(name)
        except OSError:
            QMessageBox.warning(self, "TYTcps", "The current key set wasn't changed. Check that "
                                                "the fleet folder can be written, then try again.")
            return False
        self.ctx.refresh_keyset()
        self.ctx.keyset_changed.emit()
        return True

    def change_current(self):
        sets = self.ctx.fleet.keysets()
        if not sets:
            QMessageBox.information(self, "TYTcps", "There are no saved key sets yet.")
            return
        dlg = ChooseKeysetDialog(self.ctx, sets, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
            return
        if dlg.choice == self.ctx.current_name:
            self.reload(dlg.choice)
            return
        if self.ctx.current_name and QMessageBox.question(
                self, "TYTcps", "Make %s the current key set?\n\nRadios show as on an old set "
                                "until they're given this one." % dlg.choice
        ) != QMessageBox.StandardButton.Yes:
            return
        self._set_current(dlg.choice)

    def _confirm_drop_draft(self):
        return QMessageBox.question(self, "TYTcps", "Discard the unsaved key changes?") == \
            QMessageBox.StandardButton.Yes

    def show_radio_slots(self, slots):
        """-k result: the radio's own types and names, for a sanity check."""
        self.radio_slots = {int(s["slot"]): (s.get("type", "?"), s.get("name", ""))
                            for s in slots}
        self.render()

    # -- copy ---------------------------------------------------------------------------

    def _menu(self, pos):
        r = self.table.rowAt(pos.y())
        ks = self.shown
        if ks is None or r < 0 or not ks.slots[r].filled:
            return
        m = QMenu(self)
        a = m.addAction("Copy key (clears in 30 s)")
        if m.exec(self.table.viewport().mapToGlobal(pos)) == a:
            self.copy_key(ks.slots[r])

    def copy_key(self, s):
        text = s.key.hex().upper()
        md = QMimeData()
        md.setText(text)
        # Asks clipboard managers (Klipper and others) to keep it out of history.
        md.setData("x-kde-passwordManagerHint", b"secret")
        QGuiApplication.clipboard().setMimeData(md)
        self.clip_value = text
        self.clip_timer.start(30000)

    def _clear_clipboard(self):
        cb = QGuiApplication.clipboard()
        if self.clip_value is not None and cb.text() == self.clip_value:
            cb.clear()
        self.clip_value = None


class EnterKeyDialog(QDialog):
    def __init__(self, slot, type_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter key for slot %d" % slot)
        self.need = K.TYPES[type_name]
        self.key = None
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("%s key, %d bytes, in CPS grid order. Spaces and colons are fine."
                             % (type_name, self.need)))
        self.edit = QLineEdit()
        self.edit.setMinimumWidth(520)
        lay.addWidget(self.edit)
        self.count = QLabel()
        lay.addWidget(self.count)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.edit.textChanged.connect(self._check)
        self._check()

    def _check(self):
        try:
            k = K.parse_hex(self.edit.text())
            err = None
        except ValueError as e:
            k, err = b"", str(e)
        self.count.setText(err or "%d/%d bytes" % (len(k), self.need))
        self.count.setStyleSheet("color:#c0392b" if err else "")
        self.ok.setEnabled(err is None and len(k) == self.need)

    def _accept(self):
        self.key = K.parse_hex(self.edit.text())
        self.edit.clear()
        self.accept()


class RotationDialog(QDialog):
    def __init__(self, ks, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New rotation")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("New random keys for the ticked slots. Types and names stay the "
                             "same."))
        self.boxes = []
        for s in ks.filled():
            cb = QCheckBox('Regenerate slot %d · %s · "%s"' % (s.slot, s.type, s.name))
            cb.setChecked(True)
            cb.slot = s.slot
            self.boxes.append(cb)
            lay.addWidget(cb)
        warn = QLabel(CONTRACT_WARNING % "N" + "<br><br>Radios on different key sets can't talk "
                                               "encrypted, so do the whole fleet in one go.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#1f2d3a; background:#fdebd0; padding:6px")
        lay.addWidget(warn)
        bb = QDialogButtonBox()
        bb.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def chosen(self):
        return [b.slot for b in self.boxes if b.isChecked()]


class ChooseKeysetDialog(QDialog):
    def __init__(self, ctx, sets, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Key sets in the fleet folder")
        self.resize(560, 320)
        self.choice = None
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        import datetime
        cur = ctx.current_name
        for name, mtime in sets:
            sha = ctx.fleet.keyset_sha(name) or ""
            when = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            it = QListWidgetItem("%s   %s   SHA256 %s…%s%s" % (name, when, sha[:4], sha[-4:],
                                                             "   (current)" if name == cur else ""))
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(it)
            if name == cur:
                self.list.setCurrentItem(it)
        lay.addWidget(self.list)
        bb = QDialogButtonBox()
        bb.addButton("Make current", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.itemDoubleClicked.connect(lambda _: self._ok())

    def _ok(self):
        it = self.list.currentItem()
        if it:
            self.choice = it.data(Qt.ItemDataRole.UserRole)
            self.accept()
