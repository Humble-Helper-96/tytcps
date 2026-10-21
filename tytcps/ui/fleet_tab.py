# SPDX-License-Identifier: GPL-3.0-or-later
"""The Fleet tab: one row per unit in the roster, and which
key set the ledger says each was last given. The ledger is never edited
here; `ledger add-existing` (F8) is the only addition besides -K."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                             QLineEdit, QMenu, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from ..backend import keys as K
from ..backend.fleet import short_unit

GREEN, AMBER, GREY = QColor("#1e8449"), QColor("#b9770e"), QColor("#7f8c8d")


def when(stamp):
    """2026-10-11T19:45:00-0800 -> 2026-10-11 19:45 (the file keeps the full stamp)."""
    if not stamp or len(stamp) < 16 or stamp[10] != "T":
        return stamp or "—"
    return stamp[:10] + " " + stamp[11:16]


class FleetTab(QWidget):
    record_requested = pyqtSignal(str, str)      # a207, tool

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.filter = "all"
        lay = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setWordWrap(True)
        f = self.header.font()
        f.setBold(True)
        self.header.setFont(f)
        lay.addWidget(self.header)
        chips = QHBoxLayout()
        self.group = QButtonGroup(self)
        for i, (key, text) in enumerate((("all", "All"), ("old", "Old set"), ("none", "No record"))):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setProperty("key", key)
            self.group.addButton(b, i)
            chips.addWidget(b)
            if key == "all":
                b.setChecked(True)
        self.show_removed = QCheckBox("Show removed radios")
        chips.addSpacing(16)
        chips.addWidget(self.show_removed)
        chips.addStretch(1)
        lay.addLayout(chips)
        self.group.buttonClicked.connect(self._filter)
        self.show_removed.toggled.connect(self.refresh)
        self.problems = QLabel()
        self.problems.setStyleSheet("color:#b9770e")
        self.problems.setWordWrap(True)
        lay.addWidget(self.problems)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Label", "Radio ID", "Unit", "Keys", "Given",
                                              "Codeplug written", ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, w in enumerate((150, 80, 110, 260, 150, 150, 40)):
            self.table.setColumnWidth(i, w)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(
            lambda pos: self._menu(self.table.rowAt(pos.y()), self.table.viewport().mapToGlobal(pos)))
        lay.addWidget(self.table, 1)
        self.empty = QLabel("No radios yet. Radios appear here once they've been read or written.")
        self.empty.setStyleSheet("color:#777; padding:20px")
        self.empty.setWordWrap(True)
        lay.addWidget(self.empty)
        ctx.fleet_changed.connect(self.refresh)
        ctx.keyset_changed.connect(self.refresh)
        ctx.radio_changed.connect(self.refresh)
        self.refresh()

    def _filter(self, b):
        self.filter = b.property("key")
        self.refresh()

    def refresh(self):
        fl = self.ctx.fleet
        roster = fl.roster()
        ledger = fl.ledger()
        cur_sha = self.ctx.current_sha
        cur = K.display_name(self.ctx.current_name) if self.ctx.current_name else None
        active = [u for u in roster if not u.hidden]
        status = {u.a207: self.ctx.keys_status(u.a207, ledger) for u in roster}
        n_cur = sum(1 for u in active if status[u.a207].kind == "current")
        n_old = sum(1 for u in active if status[u.a207].kind == "old")
        n_none = sum(1 for u in active if status[u.a207].kind == "none")
        n_unk = sum(1 for u in active if status[u.a207].kind == "unknown")
        if cur:
            text = "Current key set %s: %d of %d radio%s. %d on an old set, %d with no record." % (
                cur, n_cur, len(active), "" if len(active) == 1 else "s", n_old, n_none)
            if n_unk:
                text += " %d with unknown keys (a key write didn't finish)." % n_unk
            if active and n_cur == len(active):
                text = "All %d radio%s are on %s." % (len(active), "" if len(active) == 1 else "s", cur)
        else:
            text = "No current key set. %d radio%s." % (len(active), "" if len(active) == 1 else "s")
        self.header.setText(text)
        if fl.problems:
            self.problems.setText("  ".join("Line %d of %s couldn't be read and is skipped." % (n, f)
                                        for f, n in fl.problems))
        self.problems.setVisible(bool(fl.problems))

        shown = [u for u in roster if (self.show_removed.isChecked() or not u.hidden)]
        if self.filter == "old":
            # radios still to do: on an old set, or whose key write broke off
            shown = [u for u in shown if status[u.a207].kind in ("old", "unknown")]
        elif self.filter != "all":
            shown = [u for u in shown if status[u.a207].kind == self.filter]
        self.table.setRowCount(len(shown))
        attached = (self.ctx.unit or {}).get("a207")
        for r, u in enumerate(shown):
            st = status[u.a207]
            label = (u.label or "(no label)") + ("  (removed)" if u.hidden else "")
            cells = [label, u.radio_id or "—", short_unit(u.a207), "", "", when(u.last_write)]
            if st.kind == "unknown":
                cells[3] = "● unknown: a key write didn't finish"
                cells[4] = when(st.line.when) if st.line else ""
                color = QColor("#c0392b")
            elif st.kind == "none":
                cells[3] = "○ no record"
                color = GREY
            else:
                cells[3] = "● %s%s" % (st.line.keyset_name, "" if st.kind == "current" else " (old)")
                cells[4] = when(st.line.when)
                color = GREEN if st.kind == "current" else AMBER
            for c, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, u.a207)
                if c == 4 and st.line is not None:
                    it.setToolTip(st.line.when)
                if c == 5 and u.last_write:
                    it.setToolTip(u.last_write)
                if c == 3:
                    it.setForeground(color)
                    if st.manual:
                        f = it.font()
                        f.setItalic(True)
                        it.setFont(f)
                        it.setToolTip("Recorded by hand.")
                if c == 2:
                    it.setToolTip(u.a207)
                if u.a207 == attached:
                    it.setBackground(QColor("#d6eaf8"))
                    if c != 3:
                        it.setForeground(QColor("#1f2d3a"))
                self.table.setItem(r, c, it)
            b = QToolButton()
            b.setText("⋯")
            b.setAutoRaise(True)
            b.clicked.connect(lambda _, row=r, btn=b: self._menu(row, btn.mapToGlobal(btn.rect().bottomLeft())))
            self.table.setCellWidget(r, 6, b)
        self.table.setVisible(bool(roster))
        self.empty.setVisible(not roster)

    def _menu(self, row, gpos):
        if row < 0:
            return
        it = self.table.item(row, 0)
        if it is None:
            return
        a207 = it.data(Qt.ItemDataRole.UserRole)
        u = self.ctx.fleet.unit(a207)
        if u is None:
            return
        m = QMenu(self)
        a_label = m.addAction("Rename label")
        a_rec = m.addAction("Record keys already on this radio…")
        a_hist = m.addAction("History")
        a_hide = m.addAction("Return to fleet" if u.hidden else "Remove from fleet")
        a = m.exec(gpos)
        if a == a_label:
            text, ok = QInputDialog.getText(self, "Rename label", "Label for unit %s:" % u.short,
                                            text=u.label or "")
            if ok:
                self.rename(a207, text)
        elif a == a_rec:
            self.record_requested.emit(a207, "manual")
        elif a == a_hist:
            HistoryDialog(self.ctx, u, self).exec()
        elif a == a_hide:
            if not u.hidden and QMessageBox.question(
                    self, "TYTcps", "Remove unit %s from the fleet? Its key history is kept, and "
                                    "it reappears if connected again." % u.short
            ) != QMessageBox.StandardButton.Yes:
                return
            self.hide_unit(a207, not u.hidden)

    def rename(self, a207, text):
        try:
            self.ctx.fleet.set_label(a207, text)
        except OSError:
            QMessageBox.warning(self, "TYTcps", "The label wasn't saved. Check that the fleet "
                                                "folder can be written, then try again.")
        self.ctx.fleet_changed.emit()

    def hide_unit(self, a207, hidden):
        try:
            self.ctx.fleet.set_hidden(a207, hidden)
        except OSError:
            QMessageBox.warning(self, "TYTcps", "The radio list wasn't changed. Check that the "
                                                "fleet folder can be written, then try again.")
        self.ctx.fleet_changed.emit()


class HistoryDialog(QDialog):
    def __init__(self, ctx, unit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Key history of unit %s" % unit.short)
        self.resize(780, 300)
        lay = QVBoxLayout(self)
        tree = QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setHeaderLabels(["When", "Radio ID", "Key set", "SHA256", "Tool", "Note"])
        for l in ctx.fleet.history(unit.a207):
            tree.addTopLevelItem(QTreeWidgetItem([l.when, l.radio_id, l.keyset_name,
                                                  "%s…%s" % (l.sha256[:4], l.sha256[-4:]),
                                                  l.tool, l.note or ""]))
        for i, w in enumerate((190, 70, 170, 100, 80)):
            tree.setColumnWidth(i, w)
        lay.addWidget(tree)
        lay.addWidget(QLabel("From the key ledger. Keys can't be read back from a radio, so this "
                             "is the only record of what it has."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class RecordKeysDialog(QDialog):
    """F8: Record keys already on this radio (or, tool=recovered, E-K5)."""

    def __init__(self, ctx, unit_a207, tool="manual", keyset=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record keys already on this radio" if tool == "manual"
                            else "Record the key write")
        lay = QVBoxLayout(self)
        u = ctx.fleet.unit(unit_a207)
        who = "Unit %s" % short_unit(unit_a207)
        if u and u.radio_id:
            who += " · Radio ID %s" % u.radio_id
        if u and u.label:
            who += ' "%s"' % u.label
        lay.addWidget(QLabel(who))
        if tool == "manual":
            warn = QLabel("Only do this if you know this radio has these keys, for example from "
                          "the CPS. This can't be checked.")
        else:
            warn = QLabel("The keys were written but not recorded. This adds the missing record.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#1f2d3a; background:#fdebd0; padding:6px")
        lay.addWidget(warn)
        form = QFormLayout()
        self.sets = QComboBox()
        for name, _ in ctx.fleet.keysets():
            self.sets.addItem(name)
        if keyset:
            self.sets.setCurrentText(keyset)
        elif ctx.current_name:
            self.sets.setCurrentText(ctx.current_name)
        self.note = QLineEdit()
        self.note.setPlaceholderText("e.g. written with the CPS on 2026-10-11")
        form.addRow("Key set:", self.sets)
        form.addRow("Note:", self.note)
        lay.addLayout(form)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("Record", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok.setEnabled(self.sets.count() > 0)
        lay.addWidget(bb)
