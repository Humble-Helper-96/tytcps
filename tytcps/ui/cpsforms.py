# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock CPS's pages as forms: General Setting, Menu Item, Buttons
Definitions, Digit Emergency System, DTMF Signaling, VFO Mode, and the channel
and scan-list details the grids don't show.

Every widget edits one conf value (a General scalar, or one cell of a Menu,
Buttons, OneTouch, NumberKey, ScanTiming, ChanDigital, ChanAnalog,
EmergencySystem or DTMF row).
The engine owns the bytes and writes a value only when it changes. A value
the engine prints as raw:0xNN has no CPS meaning: it is shown as it is and
kept unless the operator picks a real value.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator, QValidator
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QCheckBox, QComboBox,
                             QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
                             QSpinBox, QTableWidget, QTabWidget, QVBoxLayout, QWidget)

from ..backend import cpsfields as CF
from ..backend import values as V
from ..backend.codeplug import name_display, name_token

EDITED = "border-left: 3px solid #2e86c1;"


class Binding:
    """Where a widget's value lives: a scalar, or a cell of a keyed row."""

    def __init__(self, ctx, scalar=None, table=None, key=None, col=None):
        self.ctx = ctx
        self.scalar = scalar
        self.table = table
        self.key = key
        self.col = col

    @property
    def doc(self):
        return self.ctx.codeplug.doc if self.ctx.codeplug else None

    def row(self):
        doc = self.doc
        if doc is None or self.table is None:
            return None
        for r in doc.rows(self.table):
            if r.cells[0] == str(self.key):
                return r
        return None

    def get(self):
        doc = self.doc
        if doc is None:
            return None
        if self.scalar:
            s = doc.scalars.get(self.scalar)
            return s.value if s else None
        r = self.row()
        return r.cells[self.col] if r else None

    def edited(self):
        doc = self.doc
        if doc is None:
            return False
        if self.scalar:
            s = doc.scalars.get(self.scalar)
            return bool(s and s.edited)
        r = self.row()
        return bool(r and (r.is_new or self.col in r.edited_columns()))

    def present(self):
        return self.get() is not None

    def set(self, token):
        doc = self.doc
        if doc is None or token is None or token == self.get():
            return
        if self.scalar:
            doc.set_scalar(self.scalar, token)
        else:
            r = self.row()
            if r is None:
                return
            r.cells[self.col] = token
        self.ctx.doc_edited.emit()


class CpsSpinBox(QSpinBox):
    """A spin box that reports only the operator's own changes (arrows, wheel,
    or a typed number once editing finishes), and that can show a value it
    can't hold - raw:0xNN, or a number outside the CPS's range - as text,
    instead of a clamped or stale number, until the operator sets one.

    While a value is kept, the box's hidden value is its minimum (so an arrow
    steps from a known place) and the zero word is off (it would show in
    place of the kept text). A typed entry that isn't a whole acceptable
    number when editing finishes writes nothing and puts the display back."""

    user_value = pyqtSignal(int)

    def __init__(self, special="", parent=None):
        super().__init__(parent)
        self.special = special
        self.kept = None            # the text shown while a value is kept
        self.restore = None         # kept text to put back after a bad entry
        self.typed = None           # what the operator typed, until it is finished
        self.setKeyboardTracking(False)
        if special:
            self.setSpecialValueText(special)
        self.editingFinished.connect(self._finished)
        self.lineEdit().textEdited.connect(self._typed)

    def show_kept(self, text):
        self.blockSignals(True)
        self.kept = text
        self.restore = None
        self.typed = None
        self.setValue(self.minimum())
        self.setSpecialValueText("")        # redraws, from textFromValue: the kept text
        self.blockSignals(False)

    def show_value(self, v):
        self.blockSignals(True)
        self.kept = None
        self.restore = None
        self.typed = None
        self.setValue(v)
        self.setSpecialValueText(self.special)      # redraws
        self.blockSignals(False)

    def textFromValue(self, v):
        return self.kept if self.kept is not None else super().textFromValue(v)

    def validate(self, text, pos):
        if self.kept is not None and text == self.kept:
            return (QValidator.State.Acceptable, text, pos)
        return super().validate(text, pos)

    def valueFromText(self, text):
        if self.kept is not None and text == self.kept:
            return self.value()
        return super().valueFromText(text)

    def _typed(self, text):
        if self.kept is not None:
            self.restore = self.kept
            self.kept = None
        self.typed = text

    def stepEnabled(self):
        if self.restore is not None:                # typed over a kept value
            return QAbstractSpinBox.StepEnabledFlag.StepUpEnabled | \
                QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return super().stepEnabled()

    def stepBy(self, n):
        self.typed = None
        if self.restore is not None:                # typed over a kept value
            text = self.lineEdit().text()
            if QSpinBox.validate(self, text, 0)[0] != QValidator.State.Acceptable:
                # As Qt does on any box: an arrow over text that isn't a
                # number puts the value back and writes nothing.
                self.show_kept(self.restore)
                return
            self.interpretText()                    # step from the typed number
            self.restore = None
            self.setSpecialValueText(self.special)
        elif self.kept is not None:
            self.show_value(self.minimum())         # an untouched kept box: from the bottom
        super().stepBy(n)
        self.user_value.emit(self.value())

    def commit(self):
        """Finish a typed entry now (before Save, Open, Write or Quit)."""
        if self.typed is not None:
            self.interpretText()
            self._finished()

    def _finished(self):
        typed, self.typed = self.typed, None
        if typed is None:
            return                                  # nothing typed: nothing to write
        if QSpinBox.validate(self, typed, 0)[0] != QValidator.State.Acceptable:
            if self.restore is not None:
                self.show_kept(self.restore)
            else:
                self.show_value(self.value())
            return
        v = self.value()
        self.show_value(v)
        self.user_value.emit(v)


def commit_focused():
    """Finish a value still being typed in a CPS form (the focused box: a
    number, tenths or a frequency), so an action about to change or reload
    the codeplug acts on it."""
    w = QApplication.focusWidget()
    while w is not None and not isinstance(w, (CpsSpinBox, FieldWidget)):
        w = w.parentWidget()
    if w is not None:
        w.commit()


class FieldWidget(QWidget):
    """One field's editor; keeps the binding's token and shows raw values."""

    def __init__(self, f, binding, parent=None):
        super().__init__(parent)
        self.f = f
        self.b = binding
        self._loading = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        k = f.kind
        self._asking = False
        if k == "bool":
            self.w = QCheckBox()
            self.w.toggled.connect(self._bool_changed)
        elif k == "pin8":
            # Passwords, as the CPS shows them (plain). Taken when editing
            # finishes, after a confirmation that names the lockout risk.
            self.w = QLineEdit()
            self.w.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,8}"), self.w))
            self.w.setMaxLength(8)
            self.w.setMaximumWidth(140)
            self.w.editingFinished.connect(self._secret_done)
        elif k == "enum":
            self.w = QComboBox()
            if f.labels:
                for tok, text in zip(f.choices, f.labels):
                    self.w.addItem(text, tok)
            else:
                self.w.addItems(list(f.choices))
            self.n_items = self.w.count()
            self.w.currentIndexChanged.connect(lambda i: self._user(self.w.itemData(i) or self.w.itemText(i)))
        elif k in ("tone", "ref"):
            # Choices from the codeplug's own records (ref) or the radio's
            # tone list: filled by load().
            self.w = QComboBox()
            self.n_items = 0
            if k == "tone":
                for t in V.TONES:
                    self.w.addItem("None" if t == "-" else t, t)
                self.n_items = self.w.count()
            self.w.currentIndexChanged.connect(lambda i: self._user(self.w.itemData(i)))
        elif k in ("dtmf", "name", "freq"):
            self.w = QLineEdit()
            if k == "dtmf":
                self.w.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9A-Da-d*#]{0,30}"),
                                                                self.w))
                self.w.setMaxLength(30)
                self.w.setMinimumWidth(180)
            elif k == "name":
                self.w.setMaxLength(16)
                self.w.setMinimumWidth(140)
            else:
                self.w.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,3}(\.[0-9]{0,5})?"),
                                                                self.w))
                self.w.setMaximumWidth(120)
                # A frequency is written when it is finished, not on every
                # keystroke (a half-typed 467 is a valid frequency too).
                self.w.editingFinished.connect(self._freq_finished)
            self.w.textEdited.connect(self._text_edited)
        elif k == "tenths":
            self.w = QDoubleSpinBox()
            self.w.setDecimals(1)
            self.w.setRange(f.lo / 10, f.hi / 10)
            self.w.setSingleStep(0.1)
            self.w.setKeyboardTracking(False)
            self.w.valueChanged.connect(lambda v: self._user("%.1f" % v))
            self.w.setMinimumWidth(110)
        elif k == "num":
            self.w = CpsSpinBox((f.zero or "").replace("_", " "))
            lo = 0 if f.zero else f.lo
            self.w.setRange(lo, f.hi)
            self.w.setSingleStep(f.step)
            self.w.user_value.connect(self._num_changed)
            self.w.setMinimumWidth(110)
        elif k == "id":
            self.w = QLineEdit()
            self.w.setValidator(QRegularExpressionValidator(QRegularExpression(r"-|[0-9]{0,8}"), self.w))
            self.w.setMaximumWidth(140)
            self.w.textEdited.connect(self._id_changed)
        elif k == "decode":
            self.w = QWidget()
            bl = QHBoxLayout(self.w)
            bl.setContentsMargins(0, 0, 0, 0)
            self.boxes = []
            for n in range(8):
                cb = QCheckBox(str(n + 1))
                cb.toggled.connect(self._decode_changed)
                self.boxes.append(cb)
                bl.addWidget(cb)
        else:   # ro
            self.w = QLabel()
            self.w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.w)
        self.note = QLabel()
        self.note.setStyleSheet("color:#b9770e")
        lay.addWidget(self.note)
        lay.addStretch(1)
        tip = f.tip
        if f.single:
            tip = (tip + "\n\n" if tip else "") + CF.SINGLE_TIP
        if k == "ro":
            tip = (tip + "\n\n" if tip else "") + CF.RO_TIP
        self.setToolTip(tip)
        self.error = None

    def _user(self, token):
        if not self._loading:
            self.b.set(token)
            self.mark()

    def _confirmed(self):
        """Ask before a value that could lock the radio (the field's confirm text)."""
        self._asking = True
        try:
            r = QMessageBox.question(self, "TYTcps", "%s\n\n%s\n\nSet it?" % (self.f.label, self.f.confirm),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        finally:
            self._asking = False
        return r == QMessageBox.StandardButton.Yes

    def _bool_changed(self, on):
        if self._loading:
            return
        if on and self.f.confirm and not self._confirmed():
            self.load()                         # back to what the file holds
            return
        self._user("+" if on else "-")

    def _secret_done(self):
        if self._loading or self._asking:
            return
        t = self.w.text().strip()
        tok = t if t else "-"
        if tok == self.b.get():
            self._set_error(None)
            return
        if not (len(t) == 8 and t.isdigit()) and \
                (t or self.f.key == "Power On Password"):
            # The CPS takes exactly 8 digits (the Power On Password can't be empty).
            self._set_error("%s must be 8 digits%s." % (
                self.f.label, "" if self.f.key == "Power On Password" else ", or empty for none"))
            return
        if tok != "-" and self.f.confirm and not self._confirmed():
            self.load()
            return
        self._set_error(None)
        self._user(tok)

    def _text_edited(self, text):
        """DTMF digits, a name or a frequency: written as typed, once valid."""
        t = text.strip()
        k = self.f.kind
        err = None
        if k == "dtmf":
            tok = t.upper() if t else "-"
            if not t and self.f.required:
                err = "%s can't be empty." % self.f.label
        elif k == "name":
            tok = name_token(t)
            if not t and self.f.required:
                err = "%s can't be empty." % self.f.label
            elif t == "-":
                # In the conf a name of - deletes the system.
                err = "%s can't be just -." % self.f.label
        else:
            tok, err = self._freq_token(t)
            self._set_error(err)            # shown while typing, written when finished
            return
        self._set_error(err)
        if err is None:
            self._user(tok)

    def _freq_token(self, t):
        try:
            mhz = float(t)
        except ValueError:
            mhz = None
        if mhz is None or not V.band_ok(mhz):
            return None, "%s must be in %s." % (self.f.label, V.BANDS)
        return "%.5f" % mhz, None

    def _freq_finished(self):
        if self._loading:
            return
        tok, err = self._freq_token(self.w.text().strip())
        self._set_error(err)
        if err is None:
            self._user(tok)

    def commit(self):
        """Finish what is being typed in this field now (Save, Open, Write)."""
        k = self.f.kind
        if k == "num":
            self.w.commit()
        elif k == "tenths":
            self.w.interpretText()
        elif k == "freq" and self.w.text().strip() != (self.b.get() or ""):
            self._freq_finished()

    def _when_ok(self):
        w = self.f.when
        if not w:
            return True
        doc = self.b.doc
        if doc is None:
            return False
        for key, val in (w if isinstance(w[0], tuple) else (w,)):
            cur = doc.scalar(key, "")
            if (cur == val[1:]) if val.startswith("!") else (cur != val):
                return False
        return True

    def _num_changed(self, v):
        if self._loading:
            return
        if v == 0 and self.f.zero:
            self._set_error(None)
            self._user(self.f.zero)
        elif v % self.f.unit:
            # The radio stores this field in steps of `unit`; the engine
            # would refuse any other value.
            self._set_error("%s must be a multiple of %d." % (self.f.label, self.f.unit))
        else:
            self._set_error(None)
            self._user(str(v))

    def _id_changed(self, text):
        t = text.strip()
        ok = t == "-" or (t.isdigit() and t == str(int(t)) and 1 <= int(t) <= V.MAX_RADIO_ID)
        self._set_error(None if ok else "Radio ID 1-%d without leading zeros, or - for none."
                        % V.MAX_RADIO_ID)
        if ok:
            self._user(t)
        self.mark()

    def _set_error(self, error):
        """A value the form won't write. Write and Save stay blocked while it
        is shown; the forms re-check when it comes or goes."""
        changed = error != self.error
        self.error = error
        self.mark()
        if changed:
            self.b.ctx.form_errors_changed.emit()

    def _decode_changed(self, *a):
        if self._loading:
            return
        self._user("".join(str(n + 1) if cb.isChecked() else "-" for n, cb in enumerate(self.boxes)))

    def load(self):
        tok = self.b.get()
        self._loading = True
        # As the CPS: Model Select only in Freq mode, the Power On Password
        # only with Password and Lock Enable on.
        self.setEnabled(tok is not None and self._when_ok())
        self.note.setText("")
        had_error, self.error = self.error, None
        k = self.f.kind
        try:
            if k == "ref":
                # The records to choose from, as the codeplug has them now.
                self.w.clear()
                for data, text in ref_items(self.b.doc, self.f.ref):
                    self.w.addItem(text, data)
                self.n_items = self.w.count()
            if k == "enum" and self.f.choices_by:
                key, table = self.f.choices_by
                choices = table.get(self.b.doc.scalar(key, "") if self.b.doc else "", self.f.choices)
                self.w.clear()
                self.w.addItems(list(choices))
                self.n_items = self.w.count()
            if k in ("enum", "tone", "ref"):
                # A kept raw value belongs to the record it came from.
                while self.w.count() > self.n_items:
                    self.w.removeItem(self.w.count() - 1)
            if tok is None:
                if k == "num":
                    self.w.show_kept("")
                return
            raw = tok.lower().startswith("raw:")
            if raw:
                self.note.setText("%s (no CPS meaning; kept)" % tok)
            if k == "bool":
                self.w.setChecked(tok == "+")
            elif k in ("tone", "ref"):
                i = self.w.findData(tok)
                if i < 0:
                    self.w.addItem(tok + " (kept)", tok)
                    i = self.w.findData(tok)
                self.w.setCurrentIndex(i)
            elif k == "dtmf":
                self.w.setText("" if tok == "-" else tok)
            elif k == "name":
                self.w.setText(name_display(tok))
            elif k == "freq":
                self.w.setText(tok)
            elif k == "tenths":
                try:
                    self.w.setValue(float(tok))
                except ValueError:
                    self.note.setText("%s (kept)" % tok)
            elif k == "enum":
                i = self.w.findText(tok)
                if i < 0:
                    if self.w.findData(tok) < 0:
                        self.w.addItem(tok + (" (kept)" if raw else ""), tok)
                    i = self.w.findData(tok)
                self.w.setCurrentIndex(i)
            elif k == "num":
                if self.f.zero and tok == self.f.zero:
                    self.w.show_value(0)
                elif tok.isdigit() and self.w.minimum() <= int(tok) <= self.w.maximum() \
                        and int(tok) % self.f.unit == 0 and not (int(tok) == 0 and self.f.zero):
                    self.w.show_value(int(tok))
                else:
                    # Shown as it is, not clamped into the box's range.
                    self.w.show_kept(tok)
                    if not raw:
                        self.note.setText("outside the CPS range, kept")
            elif k == "id":
                self.w.setText(tok)
            elif k == "pin8":
                self.w.setText("" if tok == "-" else tok)
            elif k == "decode":
                for n, cb in enumerate(self.boxes):
                    cb.setChecked(len(tok) == 8 and tok[n] == str(n + 1))
            else:
                self.w.setText(tok)
        finally:
            self._loading = False
            self.mark()
            if had_error:
                # The refused input went with its record or file.
                self.b.ctx.form_errors_changed.emit()

    def mark(self):
        if self.error:
            self.w.setStyleSheet("border: 2px solid #c0392b;")
            self.w.setToolTip(self.error)
        else:
            self.w.setStyleSheet(EDITED if self.b.edited() else "")
            self.w.setToolTip("")

    def flag(self, message):
        """Show an engine error on this field; the next edit or load clears it."""
        self.w.setStyleSheet("border: 2px solid #c0392b;")
        self.w.setToolTip(message or "")
        self.w.setFocus()


class NameWidget(QLineEdit):
    """Radio Name, Radio ID and the intro lines: the conf's existing keys."""

    def __init__(self, ctx, key, maxlen, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.key = key
        self.setMaxLength(maxlen)
        self.setMinimumWidth(160)
        self.error = None
        self.hint = CF.HINTS.get(key, "")
        self.setToolTip(self.hint)
        if key == "ID":
            self.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]{0,8}"), self))
        self.textEdited.connect(self._edited)

    def _edited(self, text):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        if doc is None:
            return
        if self.key == "ID":
            # The CPS's range; the ID the file already holds is always kept.
            t = text.strip()
            n = int(t, 10) if t.isdigit() and t.isascii() else -1
            s = doc.scalars.get("ID")
            ok = t == str(n) and (0 <= n <= V.MAX_RADIO_ID or (s is not None and t == s.orig))
            was = self.error
            self.error = None if ok else \
                "Radio ID must be a whole number from 0 to %d, without leading zeros." % V.MAX_RADIO_ID
            if ok:
                doc.set_scalar("ID", str(n))
            elif was != self.error:
                self.ctx.form_errors_changed.emit()
        else:
            doc.set_scalar(self.key, name_token(text))
        self.mark()
        self.ctx.doc_edited.emit()

    def load(self):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        if self.error:
            self.error = None
            self.ctx.form_errors_changed.emit()
        if doc is None:
            return
        v = doc.scalar(self.key, "")
        self.setText(v if self.key == "ID" else name_display(v))
        self.mark()

    def mark(self):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        s = doc.scalars.get(self.key) if doc else None
        if self.error:
            self.setStyleSheet("border: 2px solid #c0392b;")
            self.setToolTip(self.error)
        else:
            self.setStyleSheet(EDITED if s and s.edited else "")
            self.setToolTip(self.hint)


def _label(text, w):
    """A field's label, with the field's hint: hovering the name explains it too."""
    lab = QLabel(text)
    lab.setToolTip(w.toolTip())
    return lab


def _scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(widget)
    sa.setFrameShape(QScrollArea.Shape.NoFrame)
    return sa


class GeneralSettingTab(QWidget):
    """General Setting, laid out as the CPS does: three columns of groups."""

    NAMES = {"Name": 16, "ID": 8, "Intro Line 1": 10, "Intro Line 2": 10}

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.widgets = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        vbox = QVBoxLayout(body)
        cols = QHBoxLayout()
        vbox.addLayout(cols)
        column = QVBoxLayout()
        for group in CF.GENERAL:
            if group is None:
                column.addStretch(1)
                cols.addLayout(column, 1)
                column = QVBoxLayout()
                continue
            title, fields = group
            box = QGroupBox(title) if title else QWidget()
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            for f in fields:
                if f.key in self.NAMES:
                    w = NameWidget(ctx, f.key, self.NAMES[f.key])
                else:
                    w = FieldWidget(f, Binding(ctx, scalar=f.key))
                self.widgets.append(w)
                form.addRow(_label(f.label + ":", w), w)
            column.addWidget(box)
        column.addStretch(1)
        cols.addLayout(column, 1)
        ro = QWidget()
        rf = QFormLayout(ro)
        self.ro = {}
        for key, label in (("Radio", "Radio"), ("Last Programmed Date", "Last programmed date"),
                           ("CPS Software Version", "CPS software version")):
            l = QLabel()
            l.setToolTip("Updated by every codeplug write."
                         if key != "Radio" else "")
            rf.addRow(label + ":", l)
            self.ro[key] = l
        vbox.addWidget(ro)
        note = QLabel("Writing keeps each radio's own Radio ID and Radio Name. Change them here "
                      "only to change them on the radio you write to.")
        note.setStyleSheet("color:#777")
        note.setWordWrap(True)
        vbox.addWidget(note)
        vbox.addStretch(1)
        outer.addWidget(_scroll(body))
        ctx.doc_edited.connect(self._refresh_dependent)

    def _refresh_dependent(self):
        """Fields enabled by another one (Model Select by Freq mode, the Power
        On Password by Password and Lock Enable) follow it at once."""
        for w in self.widgets:
            if isinstance(w, FieldWidget) and w.f.when:
                w.setEnabled(w.b.get() is not None and w._when_ok())

    def load(self):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        for w in self.widgets:
            w.load()
        for key, l in self.ro.items():
            l.setText(doc.scalar(key, "-") if doc else "")

    def has_errors(self):
        return any(getattr(w, "error", None) for w in self.widgets)

    def flag(self, column, message):
        for w in self.widgets:
            if isinstance(w, FieldWidget) and w.f.key == column:
                w.flag(message)


class MenuTab(QWidget):
    """Menu Item: which items the radio's own menu shows."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.widgets = []
        outer = QVBoxLayout(self)
        body = QWidget()
        lay = QGridLayout(body)
        top = QFormLayout()
        hang = FieldWidget(CF.MENU_HANG, Binding(ctx, scalar=CF.MENU_HANG.key))
        self.widgets.append(hang)
        top.addRow(_label(CF.MENU_HANG.label + ":", hang), hang)
        tm = self._box(CF.MENU_TEXT)
        top.addRow("", tm)
        lay.addLayout(top, 0, 0, 1, 2)
        positions = {"Contacts": (1, 0), "Call Log": (2, 0), "Zone": (3, 0),
                     "Utilities": (1, 1), "Scan": (3, 1)}
        for title, items in CF.MENU:
            box = QGroupBox(title)
            g = QGridLayout(box)
            for i, item in enumerate(items):
                g.addWidget(self._box(item), i // 2, i % 2)
            r, c = positions[title]
            lay.addWidget(box, r, c, 2 if title == "Utilities" else 1, 1, Qt.AlignmentFlag.AlignTop)
        lay.setRowStretch(5, 1)
        outer.addWidget(_scroll(body))

    def _box(self, item):
        key, label, single = item
        f = CF.F(key, label, "bool", single=single, tip=CF.MENU_TIP % label)
        w = FieldWidget(f, Binding(self.ctx, table="Menu", key=key, col=1))
        w.w.setText(label)
        self.widgets.append(w)
        return w

    def load(self):
        for w in self.widgets:
            w.load()

    def has_errors(self):
        return any(w.error for w in self.widgets)

    def flag(self, column, message):
        for w in self.widgets:
            if w.f.key == column:
                w.flag(message)


class ButtonsTab(QWidget):
    """Buttons Definitions: long press, side buttons, One Touch Access,
    Number Key quick contacts."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.widgets = []
        outer = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        top = QFormLayout()
        lp = FieldWidget(CF.LONG_PRESS, Binding(ctx, scalar=CF.LONG_PRESS.key))
        self.widgets.append(lp)
        top.addRow(_label(CF.LONG_PRESS.label + ":", lp), lp)
        lay.addLayout(top)

        box = QGroupBox("Radio Buttons")
        g = QGridLayout(box)
        g.addWidget(QLabel("Short Press"), 0, 1)
        g.addWidget(QLabel("Long Press"), 0, 2)
        for r, (key, label) in enumerate(CF.BUTTONS, start=1):
            g.addWidget(QLabel(label), r, 0)
            for c, col in ((1, 1), (2, 2)):
                f = CF.F(key, label, "enum", CF.BUTTON_FUNCTIONS,
                         tip=CF.BUTTON_TIP % ("short" if col == 1 else "long"))
                w = FieldWidget(f, Binding(ctx, table="Buttons", key=key, col=col))
                for i in range(w.w.count()):
                    w.w.setItemData(i, w.w.itemText(i))
                    w.w.setItemText(i, w.w.itemText(i).replace("_", " "))
                self.widgets.append(w)
                g.addWidget(w, r, c)
        lay.addWidget(box)

        box = QGroupBox("One Touch Access")
        self.ot = QTableWidget(6, 4)
        self.ot.setHorizontalHeaderLabels(["Mode", "Call", "Call Type", "Message/Encode"])
        self.ot.verticalHeader().setDefaultSectionSize(30)
        self.ot.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        bl = QVBoxLayout(box)
        bl.addWidget(self.ot)
        self.ot.setMinimumHeight(220)
        lay.addWidget(box)

        box = QGroupBox("Number Key Quick Contact Access")
        self.nk = QTableWidget(10, 1)
        self.nk.setHorizontalHeaderLabels(["Contact"])
        self.nk.setVerticalHeaderLabels(["Number Key%d" % k for k in range(10)])
        self.nk.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.nk.setMinimumHeight(330)
        bl = QVBoxLayout(box)
        bl.addWidget(self.nk)
        lay.addWidget(box)
        lay.addStretch(1)
        outer.addWidget(_scroll(body))

    def _contacts(self):
        doc = self.ctx.codeplug.doc
        return [("-", "None")] + [(r.cells[0], "%s · %s" % (r.cells[0], name_display(r.cells[1])))
                                  for r in doc.rows("Contact")]

    def _messages(self):
        doc = self.ctx.codeplug.doc
        return [("-", "None")] + [(r.cells[0], "%s · %s" % (r.cells[0], r.cells[1][:24]))
                                  for r in doc.rows("Message")]

    def _combo(self, items, binding, tok, enabled=True):
        cb = QComboBox()
        for data, text in items:
            cb.addItem(text, data)
        if tok is not None and cb.findData(tok) < 0:
            cb.addItem(tok + " (kept)", tok)
        cb.setCurrentIndex(max(0, cb.findData(tok)))
        cb.setStyleSheet(EDITED if binding.edited() else "")

        def changed(i):
            if binding.table == "OneTouch" and binding.col == 1:
                # The CPS resets the row when its Mode changes (map 2.4).
                if self.ctx.codeplug.doc.onetouch_mode(binding.key, cb.itemData(i)):
                    self.ctx.doc_edited.emit()
            else:
                binding.set(cb.itemData(i))
            cb.setStyleSheet(EDITED if binding.edited() else "")
            if binding.col in (1, 3):        # mode or call type changes the others
                QTimer.singleShot(0, self.load)
        cb.currentIndexChanged.connect(changed)
        cb.setEnabled(tok is not None and enabled)
        return cb

    def load(self):
        for w in self.widgets:
            w.load()
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        if doc is None:
            return
        contacts, messages = self._contacts(), self._messages()
        for n in range(6):
            b = [Binding(self.ctx, table="OneTouch", key=n + 1, col=c) for c in range(1, 5)]
            mode = b[0].get()
            self.ot.setCellWidget(n, 0, self._combo([(m, m) for m in ("None", "Digital", "Analog")],
                                                    b[0], mode))
            # With Mode None the row does nothing; its other cells are kept
            # as they are, as the CPS keeps them, until a mode is chosen.
            on = mode in ("Digital", "Analog")
            self.ot.setCellWidget(n, 1, self._combo(contacts, b[1], b[1].get(), on))
            types = [("Call", "Call"), ("Text", "Text Message")] if mode == "Digital" else \
                [("DTMF-%d" % k, "DTMF-%d" % k) for k in range(1, 5)] if mode == "Analog" else []
            self.ot.setCellWidget(n, 2, self._combo(types, b[2], b[2].get(), on))
            if mode == "Analog":
                enc = [("-", "None")] + [(str(k), "%d Encode" % k) for k in range(1, 33)]
                self.ot.setCellWidget(n, 3, self._combo(enc, b[3], b[3].get(), on))
            else:
                self.ot.setCellWidget(n, 3, self._combo(messages, b[3], b[3].get(), on))
        for k in range(10):
            b = Binding(self.ctx, table="NumberKey", key=k, col=1)
            self.nk.setCellWidget(k, 0, self._combo(contacts, b, b.get()))

    def has_errors(self):
        return any(w.error for w in self.widgets)

    def flag(self, column, message):
        for w in self.widgets:
            if w.f.key == column:
                w.flag(message)


class DetailsPanel(QGroupBox):
    """Fields of the selected record that its grid doesn't show (the
    ChanDigital/ChanAnalog/ScanTiming rows), as a form."""

    def __init__(self, ctx, title, table, fields, columns=2, parent=None):
        super().__init__(title, parent)
        self.ctx = ctx
        self.table = table
        self.fields = fields
        self.number = None
        self.widgets = []
        grid = QGridLayout(self)
        self.empty = QLabel("Select a row to see its details.")
        self.empty.setStyleSheet("color:#777")
        grid.addWidget(self.empty, 0, 0, 1, columns * 2)
        per = (len(fields) + columns - 1) // columns
        for i, f in enumerate(fields):
            w = FieldWidget(f, Binding(ctx, table=table, key=None, col=i + 1))
            self.widgets.append(w)
            r, c = 1 + i % per, (i // per) * 2
            lab = _label(f.label + ":", w)
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            w.label = lab
            grid.addWidget(lab, r, c)
            grid.addWidget(w, r, c + 1)

    def show_record(self, number):
        self.number = number
        for w in self.widgets:
            w.b.key = number
            w.load()
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        has = doc is not None and number is not None and any(
            r.cells[0] == str(number) for r in doc.rows(self.table))
        self.empty.setVisible(not has)
        self.empty.setText("Select a row to see its details." if number is None else
                           "No details for this record yet.")
        for w in self.widgets:
            w.setVisible(has)
            w.label.setVisible(has)

    def has_errors(self):
        return any(w.error for w in self.widgets)

    def flag(self, column, message):
        """Point at the field an engine error names (until it is edited)."""
        for w in self.widgets:
            if w.f.key == column:
                w.flag(message)


# ---------------------------------------------------------------------------
# Digit Emergency System, DTMF Signaling and VFO Mode (7.6).
# ---------------------------------------------------------------------------

def ref_items(doc, ref):
    """[(conf token, what the combo shows)] for a field that picks a record."""
    if doc is None:
        return []

    def named(kind, none="None"):
        out = [("-", none)] if none else []
        return out + [(r.cells[0], "%s · %s" % (r.cells[0], name_display(r.cells[1])))
                      for r in doc.rows(kind)]

    def channels():
        return [(str(r.number), "%d · %s" % (r.number, name_display(r.cells[1])))
                for r in sorted(doc.channel_rows(), key=lambda r: r.number)]
    if ref == "revert":
        return [("-", "None"), ("Selected", "Selected")] + channels()
    if ref == "decode_revert":
        return [("Selected", "Selected")] + channels()
    if ref == "encodes":
        return [("-", "None")] + [(r.cells[0], "Encode %s" % r.cells[0]) for r in doc.rows("DTMFEncode")
                                  if r.cells[1] != "-"]
    if ref == "scanlists":
        return named("Scanlist")
    if ref == "emsystems":
        return named("EmergencySystem")
    if ref == "contacts":
        return named("Contact")
    if ref == "grouplists":
        return named("Grouplist")
    return []


def _fill_form(form, widgets, fields, ctx, **binding):
    """One FieldWidget per field into a QFormLayout; the binding's column
    is the field's position + 1 for a table row, else its scalar key."""
    for i, f in enumerate(fields):
        if "table" in binding:
            b = Binding(ctx, table=binding["table"], key=binding["key"], col=i + 1)
        else:
            b = Binding(ctx, scalar=f.key)
        w = FieldWidget(f, b)
        widgets.append(w)
        form.addRow(_label(f.label + ":", w), w)


class _PageTab(QWidget):
    """What the CPS pages below share: load, errors, flags, and fields that
    follow another one (When)."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.widgets = []
        ctx.doc_edited.connect(self._refresh_dependent)

    def _refresh_dependent(self):
        for w in self.widgets:
            if w.f.when:
                w.setEnabled(w.b.get() is not None and w._when_ok())

    def load(self):
        for w in self.widgets:
            w.load()

    def has_errors(self):
        return any(w.error for w in self.widgets)

    def flag(self, column, message):
        """An engine error on a scalar (the column is its conf key)."""
        for w in self.widgets:
            if w.b.scalar and w.f.key == column:
                w.flag(message)

    def flag_row(self, table, key, column, message):
        for w in self.widgets:
            if w.b.table == table and str(w.b.key) == str(key) and w.f.key == column:
                w.flag(message)
                return True
        return False


class EmergencyTab(_PageTab):
    """Digit Emergency System: the page's settings and its systems."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        body = QWidget()
        lay = QVBoxLayout(body)
        top = QHBoxLayout()
        for part in (CF.EMERGENCY[:3], CF.EMERGENCY[3:]):
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            _fill_form(form, self.widgets, part, ctx)
            top.addLayout(form)
        top.addStretch(1)
        lay.addLayout(top)
        self.fixed = list(self.widgets)

        box = QGroupBox("Emergency System")
        bl = QVBoxLayout(box)
        self.grid = QTableWidget(0, len(CF.EMSYS))
        self.grid.setHorizontalHeaderLabels([f.label for f in CF.EMSYS])
        self.grid.verticalHeader().setDefaultSectionSize(30)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.grid.setMinimumHeight(260)
        for i, f in enumerate(CF.EMSYS):
            self.grid.horizontalHeaderItem(i).setToolTip(f.tip)
        bl.addWidget(self.grid)
        buttons = QHBoxLayout()
        self.b_add = QPushButton("Add system")
        self.b_add.setToolTip("Adds a system after the last one, with the CPS's defaults.")
        self.b_add.clicked.connect(self._add)
        self.b_del = QPushButton("Delete last system")
        self.b_del.setToolTip("Systems are numbered without gaps, so only the last one can go.")
        self.b_del.clicked.connect(self._delete)
        buttons.addWidget(self.b_add)
        buttons.addWidget(self.b_del)
        buttons.addStretch(1)
        bl.addLayout(buttons)
        lay.addWidget(box)
        lay.addStretch(1)
        outer.addWidget(_scroll(body))

    def load(self):
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        rows = sorted(doc.rows("EmergencySystem"), key=lambda r: r.number) if doc else []
        self.widgets = list(self.fixed)
        self.grid.setRowCount(len(rows))
        self.grid.setVerticalHeaderLabels([r.cells[0] for r in rows])
        for n, r in enumerate(rows):
            for i, f in enumerate(CF.EMSYS):
                w = FieldWidget(f, Binding(self.ctx, table="EmergencySystem", key=r.number, col=i + 1))
                self.widgets.append(w)
                self.grid.setCellWidget(n, i, w)
        self.b_add.setEnabled(doc is not None and len(rows) < 32)
        self.b_del.setEnabled(doc is not None and len(rows) > 1)
        super().load()

    def _add(self):
        doc = self.ctx.codeplug.doc
        if doc.add_row("EmergencySystem") is not None:
            self.ctx.doc_edited.emit()
            QTimer.singleShot(0, self.load)

    def _delete(self):
        doc = self.ctx.codeplug.doc
        rows = sorted(doc.rows("EmergencySystem"), key=lambda r: r.number)
        if not rows:
            return
        why = doc.can_delete("EmergencySystem", [rows[-1]])
        if why:
            QMessageBox.information(self, "TYTcps", why)
            return
        doc.delete_rows("EmergencySystem", [rows[-1]])
        self.ctx.doc_edited.emit()
        QTimer.singleShot(0, self.load)


class DtmfTab(_PageTab):
    """DTMF Signaling: systems DTMF-1..4, the encode list, decode 1-8."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        pages = QTabWidget()

        systems = QTabWidget()
        for n in range(1, 5):
            page = QWidget()
            cols = QHBoxLayout(page)
            left, right = QFormLayout(), QFormLayout()
            for form in (left, right):
                form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            # The CPS's order: side tone, PTT ID, group code, the codes and
            # the decode times on the left; the digit timings on the right.
            for i in (8, 9, 10, 11, 12, 6, 7, 0, 1, 2, 3, 4, 5):
                f = CF.DTMF_SYSTEM[i]
                w = FieldWidget(f, Binding(ctx, table="DTMFSystem", key=n, col=i + 1))
                self.widgets.append(w)
                (right if i < 6 else left).addRow(_label(f.label + ":", w), w)
            cols.addLayout(left)
            cols.addLayout(right)
            cols.addStretch(1)
            systems.addTab(_scroll(page), "DTMF-%d" % n)
        pages.addTab(systems, "System")

        enc = QTableWidget(32, 1)
        enc.setHorizontalHeaderLabels(["Encode"])
        enc.setVerticalHeaderLabels([str(n) for n in range(1, 33)])
        enc.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        enc.verticalHeader().setDefaultSectionSize(30)
        for n in range(1, 33):
            f = CF.F(CF.DTMF_ENCODE.key, "Encode %d" % n, "dtmf", tip=CF.DTMF_ENCODE.tip,
                     required=(n == 1))
            w = FieldWidget(f, Binding(ctx, table="DTMFEncode", key=n, col=1))
            self.widgets.append(w)
            enc.setCellWidget(n - 1, 0, w)
        pages.addTab(enc, "Encode")

        decodes = QTabWidget()
        for n in range(1, 9):
            page = QWidget()
            form = QFormLayout(page)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            _fill_form(form, self.widgets, CF.DTMF_DECODE, ctx, table="DTMFDecode", key=n)
            decodes.addTab(_scroll(page), "Decode %d" % n)
        pages.addTab(decodes, "Decode")
        outer.addWidget(pages)


class VfoTab(_PageTab):
    """VFO Mode: VFO A and VFO B, laid out as the CPS's VFO page."""

    def _refresh_dependent(self):
        """A Channel Mode change: an Admit Criteria the new mode doesn't
        offer goes back to Always (the CPS resets it when it loads the VFO),
        and the lists that depend on the mode follow."""
        doc = self.ctx.codeplug.doc if self.ctx.codeplug else None
        if doc is not None:
            for v in ("A", "B"):
                mode = doc.scalars.get("VFO %s Channel Mode" % v)
                admit = "VFO %s Admit Criteria" % v
                if mode is None or not mode.edited or admit not in doc.scalars:
                    continue
                bad = {"Analog": "Color Code", "Digital": "Correct CTCSS/CDCSS"}.get(mode.value)
                if doc.scalar(admit) == bad:
                    doc.set_scalar(admit, "Always")
        # Rebuilt after this signal, not inside it: the edit may have come
        # from one of these combos.
        QTimer.singleShot(0, self._reload_choices)
        super()._refresh_dependent()

    def _reload_choices(self):
        for w in self.widgets:
            if w.f.choices_by:
                w.load()

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        outer = QVBoxLayout(self)
        vfos = QTabWidget()
        for v in ("A", "B"):
            page = QWidget()
            grid = QGridLayout(page)
            groups = CF.vfo_fields(v)
            places = {"Digital/Analog Data": (0, 0, 1, 1), "Digital Data": (0, 1, 1, 1),
                      "Analog Data": (1, 0, 1, 2)}
            for title, fields in groups:
                box = QGroupBox(title)
                cols = QHBoxLayout(box)
                per = 9 if title == "Digital/Analog Data" else (5 if title == "Analog Data" else 15)
                for start in range(0, len(fields), per):
                    form = QFormLayout()
                    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
                    _fill_form(form, self.widgets, fields[start:start + per], ctx)
                    cols.addLayout(form)
                cols.addStretch(1)
                grid.addWidget(box, *places[title], Qt.AlignmentFlag.AlignTop)
            grid.setRowStretch(2, 1)
            vfos.addTab(_scroll(page), "VFO " + v)
        outer.addWidget(vfos)
