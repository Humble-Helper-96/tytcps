# SPDX-License-Identifier: GPL-3.0-or-later
"""The codeplug tabs: General, Channels, Zones, Scan lists, Contacts, Group
lists, Messages. They edit the open file."""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (QButtonGroup, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..backend import cpsfields as CF
from ..backend.codeplug import name_display, name_token
from .cpsforms import DetailsPanel
from .grid import TableTab

EMPTY_TEXT = "Read a radio or open a codeplug file."
DATE_TIP = ("Updated by every codeplug write.")


class Placeholder(QStackedWidget):
    """A tab body that says what to do when no codeplug is open."""

    def __init__(self, body, parent=None):
        super().__init__(parent)
        msg = QLabel(EMPTY_TEXT)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color:#777; font-size:12pt")
        self.addWidget(msg)
        self.addWidget(body)
        self.body = body

    def set_open(self, is_open):
        self.setCurrentIndex(1 if is_open else 0)


class GeneralTab(QWidget):
    """The conf's scalar lines as a form."""

    FIELDS = [
        ("ID", "Radio ID", 8, "The DMR ID in this file. Each radio's ID is set when you write to "
                              "it."),
        ("Name", "Radio Name", 16, "The radio's name, also set per radio when writing."),
        ("Intro Line 1", "Intro line 1", 10, "Shown when the radio powers up."),
        ("Intro Line 2", "Intro line 2", 10, "Shown when the radio powers up."),
    ]
    READONLY = [("Radio", "Radio"), ("Last Programmed Date", "Last programmed date"),
                ("CPS Software Version", "CPS software version")]

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.edits = {}
        self.ro = {}
        self.id_error = None
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        for key, label, maxlen, tip in self.FIELDS:
            e = QLineEdit()
            e.setMaxLength(maxlen)
            e.setMinimumWidth(220)
            e.setToolTip(tip)
            if key == "ID":
                e.setValidator(QIntValidator(1, 16777215, e))
            e.textEdited.connect(lambda text, k=key: self._edited(k, text))
            form.addRow(label + ":", e)
            self.edits[key] = e
        for key, label in self.READONLY:
            l = QLabel()
            l.setToolTip(DATE_TIP if key != "Radio" else "")
            l.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label + ":", l)
            self.ro[key] = l
        note = QLabel("Radio ID and Radio Name here are the file's. Each radio's are set in the "
                      "Write codeplug dialog.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777")
        form.addRow(note)

    def _edited(self, key, text):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        if doc is None:
            return
        if key == "ID":
            # Decimal only, 1-16777215: the engine reads 'ID:' with
            # strtoul(..., 0), so '02102' would be taken as octal.
            t = text.strip()
            n = int(t, 10) if t.isdigit() and t.isascii() else 0
            self.id_error = None if 1 <= n <= 16777215 and t == str(n) else \
                "Radio ID must be a whole number from 1 to 16777215, without leading zeros."
            if self.id_error is None:
                doc.set_scalar(key, str(n))
        else:
            doc.set_scalar(key, name_token(text))
        self._mark()
        self.ctx.doc_edited.emit()

    def _mark(self):
        doc = self.ctx.codeplug.doc
        for key, e in self.edits.items():
            s = doc.scalars.get(key)
            if key == "ID" and self.id_error:
                e.setStyleSheet("border: 2px solid #c0392b;")
                e.setToolTip(self.id_error)
            else:
                e.setStyleSheet("border-left: 3px solid #2e86c1;" if s and s.edited else "")

    def load(self):
        cp = self.ctx.codeplug
        if not cp:
            return
        doc = cp.doc
        self.id_error = None
        for key, e in self.edits.items():
            v = doc.scalar(key, "")
            e.setText(v if key == "ID" else name_display(v))
        for key, l in self.ro.items():
            l.setText(doc.scalar(key, "-"))
        self._mark()

    def has_errors(self):
        return bool(self.id_error)


class ChannelsTab(QWidget):
    """Digital and Analog grids behind a segmented switch."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        seg = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.b_dig = QToolButton()
        self.b_ana = QToolButton()
        for i, b in enumerate((self.b_dig, self.b_ana)):
            b.setCheckable(True)
            b.setMinimumWidth(130)
            self.group.addButton(b, i)
            seg.addWidget(b)
        seg.addStretch(1)
        self.b_dig.setChecked(True)
        lay.addLayout(seg)
        self.stack = QStackedWidget()
        self.digital = TableTab(ctx, "Digital")
        self.analog = TableTab(ctx, "Analog")
        self.stack.addWidget(self.digital)
        self.stack.addWidget(self.analog)
        lay.addWidget(self.stack, 3)
        self.dstack = QStackedWidget()
        self.dpanel = DetailsPanel(ctx, "Channel details (digital)", "ChanDigital", CF.CHAN_DIGITAL, 3)
        self.apanel = DetailsPanel(ctx, "Channel details (analog)", "ChanAnalog", CF.CHAN_ANALOG, 3)
        self.dstack.addWidget(self.dpanel)
        self.dstack.addWidget(self.apanel)
        lay.addWidget(self.dstack, 2)
        self.group.idClicked.connect(self.stack.setCurrentIndex)
        self.group.idClicked.connect(self.dstack.setCurrentIndex)
        for t, panel in ((self.digital, self.dpanel), (self.analog, self.apanel)):
            t.view.selectionModel().currentRowChanged.connect(
                lambda cur, prev, t=t, panel=panel: self._details(t, panel))
            t.model.modelReset.connect(lambda t=t, panel=panel: self._details(t, panel))
        ctx.doc_edited.connect(self.refresh_details)
        for t in (self.digital, self.analog):
            t.model.modelReset.connect(self.counts)
            t.model.rowsInserted.connect(self.counts)
        ctx.doc_edited.connect(self.counts)

    def counts(self):
        cp = self.ctx.codeplug
        nd = len(cp.doc.rows("Digital")) if cp else 0
        na = len(cp.doc.rows("Analog")) if cp else 0
        self.b_dig.setText("Digital (%d)" % nd)
        self.b_ana.setText("Analog (%d)" % na)

    def tables(self):
        return [self.digital, self.analog]

    def detail_kinds(self):
        return ["ChanDigital", "ChanAnalog"]

    def panels(self):
        return [self.dpanel, self.apanel]

    def show_details_of(self, kind, number, column=None, message=None):
        """Select channel `number` in its grid and point at a details field."""
        t = self.digital if kind == "ChanDigital" else self.analog
        panel = self.dpanel if kind == "ChanDigital" else self.apanel
        self.show_kind("Digital" if kind == "ChanDigital" else "Analog")
        row = self.ctx.codeplug.doc.tables[t.kind].find(number) if self.ctx.codeplug else None
        if row is not None:
            t.goto(row.uid, 0)
            panel.flag(column, message)

    def _details(self, t, panel):
        row = t.model.row_at(t.view.currentIndex().row()) if t.view.currentIndex().isValid() else None
        panel.show_record(row.number if row else None)

    def refresh_details(self):
        self._details(self.digital, self.dpanel)
        self._details(self.analog, self.apanel)

    def show_kind(self, kind):
        i = 0 if kind == "Digital" else 1
        self.stack.setCurrentIndex(i)
        self.dstack.setCurrentIndex(i)
        self.group.button(i).setChecked(True)


class ScanListsTab(QWidget):
    """The Scan lists grid, with each list's timing below it."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.grid = TableTab(ctx, "Scanlist")
        self.kind = "Scanlist"
        self.model = self.grid.model
        self.panel = DetailsPanel(ctx, "Scan list timing", "ScanTiming", CF.SCAN_TIMING, 2)
        lay.addWidget(self.grid, 3)
        lay.addWidget(self.panel, 1)
        v = self.grid.view
        v.selectionModel().currentRowChanged.connect(lambda *a: self._details())
        self.model.modelReset.connect(self._details)
        ctx.doc_edited.connect(self._details)

    def _details(self):
        v = self.grid.view
        row = self.model.row_at(v.currentIndex().row()) if v.currentIndex().isValid() else None
        self.panel.show_record(row.number if row else None)

    def tables(self):
        return [self.grid]

    def detail_kinds(self):
        return ["ScanTiming"]

    def panels(self):
        return [self.panel]

    def show_details_of(self, kind, number, column=None, message=None):
        row = self.grid.model.doc.tables["Scanlist"].find(number) if self.grid.model.doc else None
        if row is not None:
            self.grid.goto(row.uid, 0)
            self.panel.flag(column, message)

    def goto(self, uid, col):
        return self.grid.goto(uid, col)
