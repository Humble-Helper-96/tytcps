# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview: a dry run of the edited text against the open
file, 500 ms after the last edit, guarding against WRONG INTENT. The engine
guards against corruption either way.

No write without a current preview: the result is kept with the SHA256 of
the exact text it ran on, and Write codeplug is enabled only while that text
is still what would be written and the run found no problem.
"""

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..backend import codeplug as cpmod
from ..backend.conf import COLUMNS


class PreviewController(QObject):
    changed = pyqtSignal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.preview = None
        self.running = False
        self.again = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.run)
        ctx.doc_edited.connect(self.schedule)
        ctx.keyset_changed.connect(self.invalidate)
        ctx.codeplug_changed.connect(self.invalidate)

    def invalidate(self):
        self.preview = None
        self.schedule()

    def schedule(self):
        self.timer.start()
        self.changed.emit()

    def text(self):
        cp = self.ctx.codeplug
        return cp.edited_text() if cp else None

    def run(self):
        cp = self.ctx.codeplug
        if cp is None:
            self.preview = None
            self.changed.emit()
            return
        if self.running:
            self.again = True
            return
        text = cp.edited_text()
        sha = cpmod.sha256_text(text)
        if self.preview and self.preview.conf_sha == sha:
            self.changed.emit()
            return
        self.running = True
        edited = cp.doc.edited_records()
        base = cp.base
        keyset = self.ctx.current_path
        engine = self.ctx.engine
        self.changed.emit()

        def work():
            return cpmod.run_preview(engine, base, text, edited, keyset)

        def done(result, exc):
            self.running = False
            if self.ctx.codeplug is cp:
                if exc is not None:
                    self.preview = cpmod.Preview(sha, False, errors=[{"code": "failed", "message": str(exc)}],
                                                 message=str(exc))
                else:
                    self.preview = result[0]
            if self.again:
                self.again = False
                self.run()
            self.changed.emit()
        self.ctx.runner.run_offline(work, done)

    # -- state -------------------------------------------------------------------------

    def current(self):
        """The preview, if it ran on exactly the text as it is now."""
        t = self.text()
        if t is None or self.preview is None:
            return None
        return self.preview if self.preview.conf_sha == cpmod.sha256_text(t) else None

    def state(self):
        cp = self.ctx.codeplug
        if cp is None or not cp.doc.is_edited():
            p = self.current()
            if p is None or p.ok and p.changed == 0:
                return "hidden"
        p = self.current()
        if p is None or self.running:
            return "running"
        if not p.ok:
            return "error"
        if p.unexplained_bytes:
            return "unexplained"
        return "clean"


def error_cells(ctx, preview):
    """{(kind, row uid, col): message} for the preview's located errors (F9)."""
    out = {}
    cp = ctx.codeplug
    if not cp or not preview or preview.ok:
        return out
    for e in preview.errors or []:
        sec = e.get("section")
        if sec not in COLUMNS:
            continue
        rid = str(e.get("id", ""))
        num = "".join(ch for ch in rid if ch.isdigit())
        if not num:
            continue
        row = cp.doc.tables[sec].find(int(num))
        if row is None:
            continue
        colname = e.get("column") or "#"
        cols = COLUMNS[sec]
        if sec == "Zone" and colname == "Channels":
            col = 3 if rid.lower().endswith("b") else 2
        elif colname in cols:
            col = cols.index(colname)
        else:
            col = 0
        out[(sec, row.uid, col)] = e.get("message", "")
    return out


def first_error_text(preview):
    for e in preview.errors or []:
        sec = e.get("section")
        names = {"Digital": "Channels row", "Analog": "Channels row", "Zone": "Zones row",
                 "Scanlist": "Scan lists row", "Contact": "Contacts row",
                 "Grouplist": "Group lists row", "Message": "Messages row", "General": "General",
                 "ChanDigital": "Channel details", "ChanAnalog": "Channel details",
                 "ScanTiming": "Scan list timing", "Menu": "Menu", "Buttons": "Buttons",
                 "OneTouch": "One Touch Access", "NumberKey": "Number Key",
                 "EmergencySystem": "Emergency system", "DTMFSystem": "DTMF system",
                 "DTMFEncode": "DTMF encode", "DTMFDecode": "DTMF decode"}
        if sec:
            where = names.get(sec, sec)
            if sec != "General":
                where += " %s" % e.get("id", e.get("row", "?"))
            if e.get("column"):
                where += " " + e["column"]
            return where, e.get("message", "")
        return "", e.get("message", "")
    return "", preview.message


class PreviewStrip(QFrame):
    show_clicked = pyqtSignal()
    goto_clicked = pyqtSignal()

    def __init__(self, ctl, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 6, 4)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.label, 1)
        self.b_show = QPushButton("Show")
        self.b_goto = QPushButton("Go to")
        lay.addWidget(self.b_show)
        lay.addWidget(self.b_goto)
        self.b_show.clicked.connect(self.show_clicked)
        self.b_goto.clicked.connect(self.goto_clicked)
        ctl.changed.connect(self.render)
        self.render()

    def render(self):
        st = self.ctl.state()
        p = self.ctl.current()
        self.setVisible(st != "hidden")
        self.b_show.setVisible(st in ("clean", "unexplained"))
        self.b_goto.setVisible(st == "error")
        if st == "running":
            self.label.setText("Checking your changes…")
        elif st == "error":
            where, msg = first_error_text(p)
            n = len(p.errors or [])
            self.label.setText("<span style='color:#c0392b'>✖ %d problem%s · %s</span>"
                               % (n, "" if n == 1 else "s", _esc(where or msg)))
            self.label.setToolTip(msg)
        elif st == "unexplained":
            self.label.setText("<span style='color:#b9770e'>⚠ %d bytes change, %d of them outside "
                               "the rows you edited</span>" % (p.changed, p.unexplained_bytes))
            self.label.setToolTip("Check the list before writing.")
        elif st == "clean":
            self.label.setText(headline(p))
            self.label.setToolTip("")


def headline(p):
    if p.changed == 0:
        return "No bytes change compared with the file."
    recs = p.records
    text = "%d byte%s" % (p.changed, " changes" if p.changed == 1 else "s change")
    if len(recs) == 1:
        r = recs[0]
        fields = ", ".join(f["field"] for f in r.get("fields", []))
        label = cpmod.record_label(r)
        label = label[:1].lower() + label[1:]
        text += " · %s%s" % (_esc(label), (" (%s)" % _esc(fields)) if fields else "")
    else:
        text += " · in %d records" % len(recs)
    return text


class PreviewPanel(QDialog):
    """One line per changed record, the date stamp listed apart (7.6)."""

    def __init__(self, preview, parent=None, title="Changes compared with the file"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(headline(preview) if preview.ok else "The preview found a problem."))
        tree = QTreeWidget()
        tree.setHeaderLabels(["Record", "Bytes", "Where", "What changes"])
        tree.setRootIsDecorated(False)
        unexplained = {id(r) for r in preview.unexplained or []}
        for r in preview.records:
            ranges = ", ".join(_range(a, b) for a, b in r.get("ranges", []))
            it = QTreeWidgetItem([cpmod.record_label(r), str(r.get("bytes", "")), ranges,
                                  cpmod.record_fields(r)])
            if id(r) in unexplained:
                it.setText(0, "⚠ " + it.text(0))
                it.setToolTip(0, "Not one of the rows you edited.")
            tree.addTopLevelItem(it)
        un = (preview.diff or {}).get("unattributed") or {}
        if un.get("bytes"):
            tree.addTopLevelItem(QTreeWidgetItem(
                ["⚠ Outside any known record", str(un["bytes"]),
                 ", ".join(_range(a, b) for a, b in un.get("ranges", [])), ""]))
        ds = (preview.diff or {}).get("datestamp") or {}
        tree.addTopLevelItem(QTreeWidgetItem(
            ["Always changes", str(ds.get("bytes", 0)), "0x02001-0x0200B",
             "Last programmed date and version"]))
        for i, w in enumerate((240, 60, 170)):
            tree.setColumnWidth(i, w)
        lay.addWidget(tree)
        note = QLabel("The date stamp changes on every write and isn't counted.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def _range(a, b):
    return "0x%05X" % a if a == b else "0x%05X-0x%05X" % (a, b)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
