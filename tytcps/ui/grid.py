# SPDX-License-Identifier: GPL-3.0-or-later
"""The grid that edits one conf table.

Cells hold the conf's own tokens; the grid shows them in the CPS's words
(spaces in names, contacts by name, Yes/No) and turns an edit back into a
token. Immediate format checks run here; the authoritative check is the
engine's offline apply behind the preview, whose errors land on the cell.
"""

from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                             QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStyle,
                             QStyleOptionButton,
                             QStyledItemDelegate, QStyleOptionViewItem, QTableView, QToolBar,
                             QVBoxLayout, QWidget)

from ..backend import values as V
from ..backend.codeplug import name_display, name_token
from ..backend.conf import COLUMNS, LIMITS, LIST_LIMITS, MAX_LINE, format_list, parse_list
from .cpsforms import commit_focused

ACCENT = QColor("#2e86c1")
RED = QColor("#c0392b")
AMBER = QColor("#f5b041")

UserState = Qt.ItemDataRole.UserRole + 1


class Col:
    def __init__(self, title, kind="text", choices=None, width=None, tip="", maxlen=None,
                 ref=None, limit=None):
        self.title = title
        self.kind = kind          # text name freq offset choice yesno ref list key msg num
        self.choices = choices or []
        self.width = width
        self.tip = tip
        self.maxlen = maxlen
        self.ref = ref            # for ref/list: which table it points into
        self.limit = limit


DCDM_COL = COLUMNS["ChanDigital"].index("DCDM")

UNIVERSAL_TIP = "Universal = AES/ARC4 using the key set's slots."
LIST_TIP = "Click Edit… (or double-click the cell) to choose and order the entries."
LIST_BUTTON = "Edit…"
LEGACY_TIP = "Legacy keys stored in the codeplug. Not editable here."

COLS = {
    "Digital": [
        Col("#", "num", width=48), Col("Name", "name", width=140, maxlen=16),
        Col("Receive", "freq", width=90), Col("Transmit", "offset", width=80),
        Col("Power", "choice", V.POWER, 60), Col("Scan", "ref", ref="Scanlist", width=110),
        Col("TOT", "choice", V.TOT, 52, tip="Transmit timeout in seconds; 0 = off"),
        Col("RO", "yesno", width=40, tip="Receive only"),
        Col("Admit", "choice", V.ADMIT_DIGITAL, 64), Col("Color", "choice", V.COLOR, 52),
        Col("Slot", "choice", V.SLOTS, 44), Col("RxGL", "ref", ref="Grouplist", width=120),
        Col("TxContact", "ref", ref="Contact", width=130),
        Col("Privacy", "choice", V.PRIVACY, 86, tip=UNIVERSAL_TIP),
        Col("Key", "key", width=150)],
    "Analog": [
        Col("#", "num", width=48), Col("Name", "name", width=140, maxlen=16),
        Col("Receive", "freq", width=90), Col("Transmit", "offset", width=80),
        Col("Power", "choice", V.POWER, 60), Col("Scan", "ref", ref="Scanlist", width=110),
        Col("TOT", "choice", V.TOT, 52, tip="Transmit timeout in seconds; 0 = off"),
        Col("RO", "yesno", width=40, tip="Receive only"),
        Col("Admit", "choice", V.ADMIT_ANALOG, 64), Col("Sq", "choice", V.SQUELCH, 40),
        Col("RxTone", "tone", width=74), Col("TxTone", "tone", width=74),
        Col("Width", "choice", V.WIDTH, 56)],
    "Zone": [
        Col("#", "num", width=48), Col("Name", "name", width=160, maxlen=16),
        Col("Channels A", "list", ref="channel", width=320, limit=64),
        Col("Channels B", "list", ref="channel", width=320, limit=64)],
    "Scanlist": [
        Col("#", "num", width=48), Col("Name", "name", width=160, maxlen=16),
        Col("PCh1", "chan", width=130, tip="Priority channel 1 (50% of scans)"),
        Col("PCh2", "chan", width=130, tip="Priority channel 2 (25% of scans)"),
        Col("TxCh", "txch", width=130, tip="Designated transmit channel"),
        Col("Channels", "list", ref="channel", width=320, limit=31)],
    "Contact": [
        Col("#", "num", width=56), Col("Name", "name", width=160, maxlen=16),
        Col("Type", "choice", V.CALL_TYPES, 80), Col("ID", "callid", width=100),
        Col("RxTone", "yesno", width=60, tip="Call receive tone")],
    "Grouplist": [
        Col("#", "num", width=48), Col("Name", "name", width=160, maxlen=16),
        Col("Contacts", "list", ref="Contact", width=420, limit=32)],
    "Message": [Col("#", "num", width=48), Col("Text", "msg", width=700, maxlen=144)],
}

# Hints for the columns that have none of their own (shown on the header and
# on each cell).
COLUMN_HINTS = {
    "Name": "Up to 16 characters, shown on the radio.",
    "Receive": "Receive frequency in MHz.",
    "Transmit": "Transmit frequency in MHz, or an offset from Receive such as +5 or -0.6.",
    "Power": "Transmit power.",
    "Scan": "The scan list used when scanning from this channel.",
    "Admit": "When the radio may transmit: always (-), only if the channel is free (Free), or "
             "only if it hears its own color code or tone (Color, Tone).",
    "Color": "DMR color code; must match the repeater's.",
    "Slot": "DMR timeslot this channel transmits on.",
    "RxGL": "Receive group list: the talkgroups this channel listens to.",
    "TxContact": "The talkgroup or radio called when you press PTT.",
    "Privacy": "Encryption on this channel.",
    "Key": "Key slot used for encryption.",
    "Sq": "Squelch level: higher needs a stronger signal to open.",
    "RxTone": "CTCSS/DCS tone needed to open the squelch.",
    "TxTone": "CTCSS/DCS tone sent while transmitting.",
    "Width": "Channel bandwidth in kHz.",
    "Type": "Group (talkgroup), Private (one radio) or All call.",
    "ID": "Talkgroup or DMR ID.",
    "Text": "Up to 144 characters.",
}
for _cols in COLS.values():
    for _c in _cols:
        if not _c.tip and _c.title in COLUMN_HINTS:
            _c.tip = COLUMN_HINTS[_c.title]


def list_label(doc, ref, n):
    if ref == "channel":
        name = doc.name_of("channel", n)
    else:
        name = doc.name_of(ref, n)
    return "%d · %s" % (n, name_display(name) if name else "(missing)")


class ConfModel(QAbstractTableModel):
    edited = pyqtSignal()

    def __init__(self, ctx, kind, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.cols = COLS[kind]
        self.engine_errors = {}       # (uid, col) -> message from the preview
        self._dcdm = None             # _dcdm_on() for the length of one has_errors()

    @property
    def doc(self):
        cp = self.ctx.codeplug
        return cp.doc if cp else None

    def rows(self):
        return self.doc.rows(self.kind) if self.doc else []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows())

    def columnCount(self, parent=QModelIndex()):
        return len(self.cols)

    def headerData(self, section, orient, role=Qt.ItemDataRole.DisplayRole):
        if orient == Qt.Orientation.Horizontal:
            c = self.cols[section]
            if role == Qt.ItemDataRole.DisplayRole:
                return c.title
            if role == Qt.ItemDataRole.ToolTipRole:
                return c.tip or None
        return None

    def row_at(self, r):
        rows = self.rows()
        return rows[r] if 0 <= r < len(rows) else None

    def index_of(self, row, col=0):
        rows = self.rows()
        return self.index(rows.index(row), col) if row in rows else QModelIndex()

    def flags(self, index):
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        c = self.cols[index.column()]
        if c.kind == "num":
            return f
        if c.kind == "key":
            row = self.row_at(index.row())
            if row and row.cells[13] == "None":
                return f
        if c.kind in ("list",):
            return f
        return f | Qt.ItemFlag.ItemIsEditable

    # -- display ------------------------------------------------------------------

    def display(self, row, c, col):
        tok = row.cells[col]
        doc = self.doc
        k = c.kind
        if k == "name":
            return name_display(tok)
        if k == "yesno":
            return "Yes" if tok == "+" else "No" if self.kind == "Contact" else ""
        if k == "ref":
            if tok == "-" or not tok.isdigit():
                return "-" if tok == "-" else tok
            name = doc.name_of(c.ref, int(tok))
            return "%s · %s" % (tok, name_display(name) if name is not None else "(missing)")
        if k in ("chan", "txch"):
            if tok.isdigit():
                name = doc.name_of("channel", int(tok))
                return "%s · %s" % (tok, name_display(name) if name is not None else "(missing)")
            return tok
        if k == "key":
            return self.key_display(row)
        if k == "list":
            return tok
        if k == "msg":
            return tok
        return tok

    def key_display(self, row):
        priv, key = row.cells[13], row.cells[14]
        if priv in ("", "None") or key in ("", "-"):
            return "-" if priv != "" else ""
        if priv == "Universal" and key.isdigit():
            for slot, typ, name, filled in self.ctx.current_slots():
                if slot == int(key):
                    if not filled:
                        return "%s · (empty)" % key
                    return "%s · %s · %s" % (key, typ, name)
        return key

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        row = self.row_at(index.row())
        if row is None:
            return None
        col = index.column()
        c = self.cols[col]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.display(row, c, col)
        if role == Qt.ItemDataRole.EditRole:
            return row.cells[col]
        if role == Qt.ItemDataRole.ToolTipRole:
            p = self.problem(row, col)
            if p:
                return p[1]
            if c.kind == "list":
                nums = _nums(row.cells[col]) or []
                names = "\n".join(list_label(self.doc, c.ref, n) for n in nums)
                return (names + "\n\n" if names else "") + LIST_TIP
            if c.kind == "key" and row.cells[13] in ("Basic", "Enhanced"):
                return LEGACY_TIP
            return c.tip or None
        if role == UserState:
            p = self.problem(row, col)
            edited = col in row.edited_columns() if not row.is_new else True
            return (p[0] if p else None, edited, row.edited)
        if role == Qt.ItemDataRole.ForegroundRole and c.kind == "key" and row.cells[13] == "None":
            return QColor("#999")
        if role == Qt.ItemDataRole.TextAlignmentRole and c.kind == "num":
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    # -- checks -------------------------------------------------------------------

    def problem(self, row, col):
        """('error'|'warning', message) for a cell, or None."""
        e = self.engine_errors.get((row.uid, col))
        if e:
            return ("error", e)
        c = self.cols[col]
        tok = row.cells[col]
        msg = None
        warning = None
        if c.kind == "name":
            touched = row.is_new or col in row.edited_columns()
            if tok == "-" and not touched and not (self.kind == "Zone" and col != 1):
                # The radio's own name is '-', which the engine reads as an
                # empty name: any write would delete this record.
                msg = ("A name of '-' counts as no name, and writing would delete this record. "
                       "Rename it.")
            else:
                msg = V.check_name(name_display(tok), c.maxlen or 16, required=touched)
        elif c.kind == "freq":
            msg = V.check_receive(tok)
        elif c.kind == "offset":
            msg = V.check_transmit(tok, row.cells[2])
        elif c.kind == "tone":
            msg = V.check_tone(tok)
        elif c.kind == "callid":
            msg = None if tok.isdigit() and 1 <= int(tok) <= V.MAX_ID else \
                "Call ID must be 1-%d." % V.MAX_ID
        elif c.kind == "msg":
            msg = V.check_text(tok) if (row.is_new or col in row.edited_columns()) else None
            if "_" in tok:
                warning = ("'_' is written as a space.")
        elif c.kind in ("ref",):
            if tok.isdigit() and self.doc.name_of(c.ref, int(tok)) is None:
                msg = "%s %s doesn't exist." % ({"Contact": "Contact", "Grouplist": "Group list",
                                                 "Scanlist": "Scan list"}[c.ref], tok)
        elif c.kind in ("chan", "txch"):
            if tok.isdigit() and self.doc.channel(int(tok)) is None:
                msg = "Channel %s doesn't exist." % tok
        elif c.kind == "list":
            nums = _nums(tok)
            if nums is None:
                msg = "This list can't be read."
            else:
                missing = [n for n in nums if (self.doc.channel(n) if c.ref == "channel"
                                               else self.doc.tables[c.ref].find(n)) is None]
                if missing:
                    msg = "Not in the codeplug: %s." % ", ".join(map(str, missing))
                elif c.limit and len(nums) > c.limit:
                    msg = "At most %d entries." % c.limit
        elif c.kind == "key":
            if row.cells[13] == "Universal" and row.cells[14].isdigit():
                for slot, typ, name, filled in self.ctx.current_slots():
                    if slot == int(row.cells[14]) and not filled:
                        warning = ("Key slot %s is empty in the current key set." % slot)
        if msg is None and self.kind == "Digital" and c.title == "TOT" and \
                tok not in ("15", "30", "45", "60"):
            # A channel number that held this DCDM and TOT in the image is
            # kept as it is, as the engine keeps it: it compares each
            # channel with the record the image had at that number.
            on, was = self._dcdm_state()
            n = row.number
            if n in on and not (n in was and was[n] == tok):
                msg = ("With DCDM on (channel details), the CPS allows only TOT 15, 30, 45 or "
                       "60 s.")
        if msg is None:
            # Every row, edited or not: the engine cuts a longer line on any
            # write, and reads its tail as another row.
            for line_col, n in self.long_lines(row):
                if line_col == col:
                    msg = ("Too long: this entry is %d bytes and the limit is %d. Shorten it."
                           % (n, MAX_LINE))
        if msg:
            return ("error", msg)
        return ("warning", warning) if warning else None

    def long_lines(self, row):
        """[(column to report on, bytes)] for each of the row's conf lines
        over MAX_LINE. A zone is two lines: 'a' (Channels A), 'b' (B)."""
        lines = self.doc._render_row(self.doc.tables[self.kind], row)
        out = []
        for i, line in enumerate(lines):
            n = len(line.encode("utf-8", "surrogatepass"))
            if n > MAX_LINE:
                if self.kind == "Zone":
                    out.append((2 if i == 0 else 3, n))
                else:
                    out.append((self.long_col(), n))
        return out

    def long_col(self):
        """The cell a too-long row is reported on: the text or list column."""
        for i, c in enumerate(self.cols):
            if c.kind in ("msg", "list"):
                return i
        return 1

    def _dcdm_state(self):
        """({channel numbers with DCDM on now}, {number: TOT} for the channels
        that had DCDM on in the image, at their original numbers)."""
        if self._dcdm is not None:
            return self._dcdm
        doc = self.doc
        on = {r.number for r in doc.rows("ChanDigital") if r.cells[DCDM_COL] == "+"}
        cd, dg = doc.tables["ChanDigital"], doc.tables["Digital"]
        was_on = {r.orig_number for r in cd.rows + cd.deleted
                  if r.orig is not None and r.orig[DCDM_COL] == "+"}
        was = {r.orig_number: r.orig[6] for r in dg.rows + dg.deleted
               if r.orig is not None and r.orig_number in was_on}
        return on, was

    def has_errors(self):
        self._dcdm = self._dcdm_state() if self.kind == "Digital" else None
        try:
            for row in self.rows():
                for col in range(len(self.cols)):
                    p = self.problem(row, col)
                    if p and p[0] == "error":
                        return True
            return False
        finally:
            self._dcdm = None

    # -- editing ------------------------------------------------------------------

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole:
            return False
        row = self.row_at(index.row())
        col = index.column()
        c = self.cols[col]
        tok = self.token(c, value)
        if tok is None or tok == row.cells[col]:
            return False
        row.cells[col] = tok
        if self.kind == "Digital" and col == 13:
            # Privacy None has no key; any other type needs one.
            if tok == "None":
                row.cells[14] = "-"
            elif row.cells[14] in ("-", ""):
                row.cells[14] = "1"
            elif tok == "Enhanced" and row.cells[14].isdigit() and int(row.cells[14]) > 8:
                row.cells[14] = "1"
        self.engine_errors = {k: v for k, v in self.engine_errors.items() if k[0] != row.uid}
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), len(self.cols) - 1))
        self.edited.emit()
        return True

    def token(self, c, value):
        v = str(value).strip() if value is not None else ""
        if c.kind == "name":
            return name_token(v)
        if c.kind == "yesno":
            return "+" if v in ("+", "Yes", "yes", "1", "True") else "-"
        if c.kind in ("freq", "offset", "callid"):
            return v.replace(",", ".") if v else None
        if c.kind == "msg":
            return " ".join(str(value).split()) if value is not None else None
        if c.kind == "tone":
            if not v:
                return "-"
            return v.upper() if v[:1] in ("d", "D") else v
        return v or None

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def repaint_all(self):
        """Another table changed: names and references shown here may have."""
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1, len(self.cols) - 1))

    def set_engine_errors(self, errs):
        self.engine_errors = errs
        if self.rowCount():
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self.rowCount() - 1, len(self.cols) - 1))


def _nums(text):
    try:
        return parse_list(text)
    except ValueError:
        return None


class Delegate(QStyledItemDelegate):
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model

    def createEditor(self, parent, option, index):
        m = self.model
        c = m.cols[index.column()]
        row = m.row_at(index.row())
        doc = m.doc
        if c.kind in ("choice", "yesno", "ref", "chan", "txch", "key", "tone"):
            cb = QComboBox(parent)
            items = self.options(c, row, doc)
            for label, tok, enabled in items:
                cb.addItem(label, tok)
                if not enabled:
                    it = cb.model().item(cb.count() - 1)
                    it.setEnabled(False)
            if c.kind == "tone":
                cb.setEditable(True)
                cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            return cb
        ed = QLineEdit(parent)
        if c.maxlen:
            ed.setMaxLength(c.maxlen)
        return ed

    def options(self, c, row, doc):
        if c.kind == "choice":
            return [(x, x, True) for x in c.choices]
        if c.kind == "yesno":
            return [("No", "-", True), ("Yes", "+", True)]
        if c.kind == "tone":
            return [(x, x, True) for x in V.TONES]
        if c.kind == "ref":
            out = [("-", "-", True)]
            for r in doc.rows(c.ref):
                out.append(("%d · %s" % (r.number, name_display(r.cells[1])), str(r.number), True))
            return out
        if c.kind in ("chan", "txch"):
            out = [("-", "-", True), ("Sel", "Sel", True)] if c.kind == "chan" else \
                [("Last", "Last", True), ("Sel", "Sel", True)]
            for r in sorted(doc.channel_rows(), key=lambda r: r.number):
                out.append(("%d · %s" % (r.number, name_display(r.cells[1])), str(r.number), True))
            return out
        if c.kind == "key":
            priv = row.cells[13]
            if priv == "Universal":
                slots = self.model.ctx.current_slots()
                if not slots:
                    return [(str(n), str(n), True) for n in range(1, 17)]
                return [("%d · %s · %s" % (s, t, n) if f else "%d · (empty)" % s, str(s), f)
                        for s, t, n, f in slots]
            if priv == "Enhanced":
                return [(str(n), str(n), True) for n in range(1, 9)]
            return [(str(n), str(n), True) for n in range(1, 17)]
        return []

    def setEditorData(self, editor, index):
        m = self.model
        row = m.row_at(index.row())
        col = index.column()
        c = m.cols[col]
        tok = row.cells[col]
        if isinstance(editor, QComboBox):
            i = editor.findData(tok)
            if i < 0 and c.kind == "tone":
                editor.setEditText(tok)
            else:
                editor.setCurrentIndex(max(i, 0))
            return
        editor.setText(m.display(row, c, col) if c.kind == "name" else tok)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            c = self.model.cols[index.column()]
            if c.kind == "tone" and editor.currentText() != editor.itemText(editor.currentIndex()):
                model.setData(index, editor.currentText())
            else:
                model.setData(index, editor.currentData())
            return
        model.setData(index, editor.text())

    def paint(self, painter, option, index):
        c = self.model.cols[index.column()]
        if c.kind == "list":
            self._paint_chips(painter, option, index)
        else:
            super().paint(painter, option, index)
        state = index.data(UserState)
        if not state:
            return
        level, edited, row_edited = state
        painter.save()
        r = option.rect
        if index.column() == 0 and row_edited:
            painter.fillRect(QRect(r.left(), r.top(), 4, r.height()), ACCENT)
        elif edited and index.column() != 0:
            painter.fillRect(QRect(r.left(), r.top(), 2, r.height()), ACCENT)
        if level:
            pen = QPen(RED if level == "error" else AMBER)
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(r.adjusted(1, 1, -2, -2))
        painter.restore()

    @staticmethod
    def button_rect(cell, fm):
        """Where a list cell's Edit… button is: its right end, like a combo's arrow."""
        w = fm.horizontalAdvance(LIST_BUTTON) + 16
        return QRect(cell.right() - w - 3, cell.top() + 3, w, cell.height() - 6)

    def _paint_chips(self, painter, option, index):
        """A channel or contact list as chips, in stored order (7.5), with an
        Edit… button so a first-time user can see the cell opens a picker."""
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        fm = opt.fontMetrics
        b = QStyleOptionButton()
        b.rect = self.button_rect(opt.rect, fm)
        b.text = LIST_BUTTON
        b.state = QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Raised
        style.drawControl(QStyle.ControlElement.CE_PushButton, b, painter, opt.widget)
        if text in ("", "-"):
            painter.save()
            painter.setPen(QColor("#888"))
            painter.drawText(opt.rect.adjusted(8, 0, -(b.rect.width() + 8), 0),
                             int(Qt.AlignmentFlag.AlignVCenter), "none: click Edit… to add")
            painter.restore()
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = opt.rect.adjusted(4, 4, -(b.rect.width() + 10), -4)
        x = r.left()
        h = min(r.height(), fm.height() + 4)
        y = r.top() + (r.height() - h) // 2
        parts = text.split(",")
        for i, part in enumerate(parts):
            w = fm.horizontalAdvance(part) + 12
            if x + w > r.right() - (fm.horizontalAdvance("…") + 6 if i < len(parts) - 1 else 0):
                painter.setPen(opt.palette.text().color())
                painter.drawText(QRect(x, y, r.right() - x, h), int(Qt.AlignmentFlag.AlignVCenter), "…")
                break
            rect = QRect(x, y, w, h)
            painter.setPen(QPen(QColor("#9fb3c8")))
            painter.setBrush(QColor("#e8f0f8"))
            painter.drawRoundedRect(rect, 6, 6)
            painter.setPen(QColor("#1f2d3a"))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), part)
            x += w + 4
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), 24))

    def editorEvent(self, event, model, option, index):
        # One click on a list cell's Edit… button opens its picker.
        if self.model.cols[index.column()].kind == "list" and \
                event.type() == QEvent.Type.MouseButtonRelease and \
                event.button() == Qt.MouseButton.LeftButton and \
                self.button_rect(option.rect, option.fontMetrics).contains(
                    event.position().toPoint()):
            view = option.widget
            if hasattr(view, "open_picker"):
                view.open_picker.emit(index)
                return True
        return super().editorEvent(event, model, option, index)


class GridView(QTableView):
    open_picker = pyqtSignal(QModelIndex)

    def edit(self, index, trigger=QAbstractItemView.EditTrigger.AllEditTriggers, event=None):
        # Qt calls the three-argument virtual, often with no event; the
        # one-argument overload returns nothing, so always pass all three.
        m = self.model()
        if index.isValid() and m.cols[index.column()].kind == "list" and trigger in (
                QAbstractItemView.EditTrigger.DoubleClicked,
                QAbstractItemView.EditTrigger.EditKeyPressed,
                QAbstractItemView.EditTrigger.AnyKeyPressed):
            self.open_picker.emit(index)
            return False
        return bool(super().edit(index, trigger, event))


class Picker(QDialog):
    """Two lists, available ↔ in this list, that keep order (7.5)."""

    def __init__(self, title, available, chosen, limit=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 440)
        self.limit = limit
        self.labels = dict(available)
        lay = QVBoxLayout(self)
        note = QLabel("The radio uses the entries in this order.")
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        self.left = QListWidget()
        self.left.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.right = QListWidget()
        self.right.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.right.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for n, label in available:
            if n not in chosen:
                self._add(self.left, n)
        for n in chosen:
            self._add(self.right, n)
        lcol = QVBoxLayout()
        lcol.addWidget(QLabel("Available"))
        lcol.addWidget(self.left)
        mid = QVBoxLayout()
        mid.addStretch(1)
        b_add = QPushButton("Add →")
        b_rem = QPushButton("← Remove")
        b_up = QPushButton("Move up")
        b_down = QPushButton("Move down")
        for b in (b_add, b_rem, b_up, b_down):
            mid.addWidget(b)
        mid.addStretch(1)
        rcol = QVBoxLayout()
        self.count = QLabel()
        rcol.addWidget(self.count)
        rcol.addWidget(self.right)
        row.addLayout(lcol, 1)
        row.addLayout(mid)
        row.addLayout(rcol, 1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        lay.addWidget(bb)
        b_add.clicked.connect(self.add)
        b_rem.clicked.connect(self.remove)
        b_up.clicked.connect(lambda: self.move(-1))
        b_down.clicked.connect(lambda: self.move(1))
        self.left.itemDoubleClicked.connect(lambda _: self.add())
        self.right.itemDoubleClicked.connect(lambda _: self.remove())
        self.right.model().rowsMoved.connect(self.update_count)
        self.update_count()

    def _add(self, w, n, at=None):
        it = QListWidgetItem(self.labels.get(n, str(n)))
        it.setData(Qt.ItemDataRole.UserRole, n)
        if at is None:
            w.addItem(it)
        else:
            w.insertItem(at, it)

    def add(self):
        for it in self.left.selectedItems():
            n = it.data(Qt.ItemDataRole.UserRole)
            self.left.takeItem(self.left.row(it))
            self._add(self.right, n)
        self.update_count()

    def remove(self):
        for it in self.right.selectedItems():
            n = it.data(Qt.ItemDataRole.UserRole)
            self.right.takeItem(self.right.row(it))
            # back into numeric place on the left
            pos = 0
            while pos < self.left.count() and self.left.item(pos).data(Qt.ItemDataRole.UserRole) < n:
                pos += 1
            self._add(self.left, n, pos)
        self.update_count()

    def move(self, d):
        rows = sorted(self.right.row(it) for it in self.right.selectedItems())
        if not rows:
            return
        if d < 0 and rows[0] == 0 or d > 0 and rows[-1] == self.right.count() - 1:
            return
        for r in (rows if d < 0 else reversed(rows)):
            it = self.right.takeItem(r)
            self.right.insertItem(r + d, it)
            it.setSelected(True)

    def update_count(self, *a):
        n = self.right.count()
        over = self.limit and n > self.limit
        self.count.setText("In this list: %d%s" % (n, (" of at most %d" % self.limit) if self.limit else ""))
        self.count.setStyleSheet("color:#c0392b" if over else "")
        self.ok.setEnabled(not over)

    def chosen(self):
        return [self.right.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.right.count())]


class TableTab(QWidget):
    """Toolbar + grid for one conf table."""

    def __init__(self, ctx, kind, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.model = ConfModel(ctx, kind, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        tb = QToolBar()
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.a_add = tb.addAction("Add", self.add)
        self.a_dup = tb.addAction("Duplicate", self.duplicate)
        self.a_del = tb.addAction("Delete", self.delete)
        tb.addSeparator()
        self.a_up = tb.addAction("Move up", lambda: self.move(-1))
        self.a_down = tb.addAction("Move down", lambda: self.move(1))
        self.a_up.setToolTip("Swap this record's number with the one above. References to it "
                             "follow.")
        self.a_down.setToolTip(self.a_up.toolTip().replace("above", "below"))
        lay.addWidget(tb)
        self.view = GridView()
        self.view.setModel(self.model)
        self.delegate = Delegate(self.model, self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                  QAbstractItemView.EditTrigger.EditKeyPressed |
                                  QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.view.verticalHeader().setVisible(False)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.setAlternatingRowColors(True)
        self.view.open_picker.connect(self.pick)
        for i, c in enumerate(self.model.cols):
            if c.width:
                self.view.setColumnWidth(i, c.width)
        lay.addWidget(self.view)
        self.problem_label = QLabel()
        self.problem_label.setStyleSheet("color:#c0392b; padding:2px 6px")
        self.problem_label.setWordWrap(True)
        lay.addWidget(self.problem_label)
        self.model.edited.connect(self._edited)
        self.view.selectionModel().selectionChanged.connect(self._show_problem)
        self.model.modelReset.connect(self._show_problem)

    def _edited(self):
        self.ctx.doc_edited.emit()
        self._show_problem()

    def _show_problem(self, *a):
        idx = self.view.currentIndex()
        msgs = []
        if idx.isValid():
            row = self.model.row_at(idx.row())
            if row:
                for col in range(len(self.model.cols)):
                    p = self.model.problem(row, col)
                    if p:
                        msgs.append(p[1])
        if not msgs:
            for row in self.model.rows():
                for col in range(len(self.model.cols)):
                    p = self.model.problem(row, col)
                    if p and p[0] == "error":
                        msgs.append("Row %s: %s" % (row.cells[0], p[1]))
                        break
                if len(msgs) >= 2:
                    break
        self.problem_label.setText("  ".join(msgs))
        self.problem_label.setVisible(bool(msgs))

    def selected_rows(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        if not rows and self.view.currentIndex().isValid():
            rows = [self.view.currentIndex().row()]
        return [self.model.row_at(r) for r in rows if self.model.row_at(r)]

    def _after_structure_change(self, select=None):
        self.model.refresh()
        self.ctx.doc_edited.emit()
        if select is not None:
            idx = self.model.index_of(select)
            if idx.isValid():
                self.view.setCurrentIndex(idx)
                self.view.scrollTo(idx)

    def add(self):
        commit_focused()        # a number still typed in the details goes to its record first
        doc = self.model.doc
        if doc is None:
            return
        cur = self.selected_rows()
        row = doc.add_row(self.kind, after=cur[-1] if cur else None)
        if row is None:
            QMessageBox.information(self, "TYTcps", "This table is full (%d)." % LIMITS[self.kind])
            return
        self._add_details(doc, row, None)
        _sort(doc.rows(self.kind))
        self._after_structure_change(row)

    def duplicate(self):
        commit_focused()
        doc = self.model.doc
        rows = self.selected_rows()
        if not doc or not rows:
            return
        new = None
        for r in rows:
            new = doc.duplicate_row(r)
            if new is None:
                break
            self._add_details(doc, new, r)
        _sort(doc.rows(self.kind))
        self._after_structure_change(new)

    def _add_details(self, doc, row, source):
        """The CPS fields a new record's grid row doesn't carry: copied from
        the record it duplicates, or what the engine gives a new record."""
        from ..backend import cpsfields as CF
        detail = {"Digital": ("ChanDigital", CF.NEW_DIGITAL), "Analog": ("ChanAnalog", CF.NEW_ANALOG),
                  "Scanlist": ("ScanTiming", ["500", "2000"])}.get(self.kind)
        if detail is None:
            return
        table, cells = detail
        if source is not None:
            src = doc.tables[table].find(source.number)
            if src is not None:
                cells = src.cells[1:]
        doc.add_detail_row(table, row.number, cells)

    def delete(self):
        commit_focused()
        doc = self.model.doc
        rows = self.selected_rows()
        if not doc or not rows:
            return
        why = doc.can_delete(self.kind, rows)
        if why:
            QMessageBox.information(self, "TYTcps", why)
            return
        users = []
        for r in rows:
            for ref_row, col in doc.references(self.kind, r.number):
                users.append(_describe(ref_row))
            users += doc.scalar_references(self.kind, r.number)
        if users:
            what = {"Digital": "channel", "Analog": "channel", "Scanlist": "scan list",
                    "Grouplist": "group list", "Contact": "contact",
                    "Message": "message"}.get(self.kind, "row")
            text = ("The %s%s you're deleting %s used by: %s.\n\nDelete, and take %s out of "
                    "those?" % (what, "s" if len(rows) > 1 else "",
                                "are" if len(rows) > 1 else "is",
                                ", ".join(sorted(set(users))), "them" if len(rows) > 1 else "it"))
            if QMessageBox.question(self, "TYTcps", text) != QMessageBox.StandardButton.Yes:
                return
        doc.delete_rows(self.kind, rows)
        self._after_structure_change()

    def move(self, d):
        commit_focused()
        doc = self.model.doc
        rows = self.selected_rows()
        if not doc or len(rows) != 1:
            return
        lst = doc.rows(self.kind)
        i = lst.index(rows[0])
        j = i + d
        if j < 0 or j >= len(lst):
            return
        doc.swap_numbers(self.kind, lst[i], lst[j])
        self._after_structure_change(rows[0])

    def pick(self, index):
        m = self.model
        row = m.row_at(index.row())
        col = index.column()
        c = m.cols[col]
        doc = m.doc
        if c.ref == "channel":
            avail = [(r.number, "%d · %s" % (r.number, name_display(r.cells[1])))
                     for r in sorted(doc.channel_rows(), key=lambda r: r.number)]
        else:
            avail = [(r.number, "%d · %s" % (r.number, name_display(r.cells[1])))
                     for r in doc.rows(c.ref)]
        chosen = _nums(row.cells[col]) or []
        dlg = Picker("%s %s: %s" % ({"Zone": "Zone", "Scanlist": "Scan list",
                                      "Grouplist": "Group list"}[self.kind], row.cells[0], c.title),
                     avail, chosen, c.limit, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            m.setData(index, format_list(dlg.chosen()))

    def goto(self, uid, col):
        for i, r in enumerate(self.model.rows()):
            if r.uid == uid:
                idx = self.model.index(i, col)
                self.view.setCurrentIndex(idx)
                self.view.scrollTo(idx)
                self.view.setFocus()
                return True
        return False


def _sort(rows):
    rows.sort(key=lambda r: r.number)


def _describe(row):
    if row.kind == "OneTouch":
        return "One Touch Access %s" % row.cells[0]
    if row.kind == "NumberKey":
        return "Number Key %s" % row.cells[0]
    if row.kind == "EmergencySystem":
        return 'emergency system %s "%s" (revert channel)' % (row.cells[0], name_display(row.cells[1]))
    if row.kind == "DTMFDecode":
        return "DTMF decode %s (revert channel)" % row.cells[0]
    names = {"Zone": "zone", "Scanlist": "scan list", "Digital": "channel", "Analog": "channel",
             "Grouplist": "group list"}
    return '%s %s "%s"' % (names.get(row.kind, row.kind), row.cells[0], name_display(row.cells[1]))
