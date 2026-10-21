# SPDX-License-Identifier: GPL-3.0-or-later
"""Write codeplug (7.7), Write keys (7.9), Write the codeplug again, and the shared
progress view. None of these can be cancelled once the radio is open, and
the window will not close while one runs (7.13)."""

import datetime
import os
import shutil
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QIntValidator
from PyQt6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QProgressBar, QPushButton, QStackedWidget, QVBoxLayout,
                             QWidget)

from ..backend import codeplug as cpmod
from ..backend import keys as K
from ..backend import radio
from ..backend import values as V
from ..backend.codeplug import name_display, name_token
from ..backend.fleet import short_unit
from . import messages
from .preview import PreviewPanel, headline
from .radiobar import codeplug_model_problem


def unit_line(ctx, last_seen=True):
    u = ctx.unit or {}
    ru = ctx.fleet.unit(u["a207"]) if u.get("a207") else None
    s = "%s · Unit %s" % (u.get("model", "Radio"), short_unit(u.get("a207", "")))
    if ru and ru.radio_id:
        s += " · %sRadio ID %s" % ("last seen as " if last_seen else "", ru.radio_id)
        if ru.label:
            s += ' "%s"' % ru.label
    else:
        s += " · new radio"
    return s


def _warn(text, level="warn"):
    l = QLabel(text)
    l.setWordWrap(True)
    l.setTextFormat(Qt.TextFormat.RichText)
    l.setStyleSheet({"warn": "color:#1f2d3a; background:#fdebd0; border-left:4px solid #f5b041; padding:6px",
                     "error": "color:#1f2d3a; background:#fadbd8; border-left:4px solid #c0392b; padding:6px",
                     "info": "color:#1f2d3a; background:#eaf2f8; border-left:4px solid #2e86c1; padding:6px"}[level])
    return l


class Steps(QWidget):
    """`Read 1 · Read 2 · Compare · Erase · Write · Verify`, ticking off."""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps            # [(label, [phases])]
        self.done = set()
        self.current = None
        lay = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.render()

    def phase(self, ph):
        for i, (label, phases) in enumerate(self.steps):
            if ph in phases:
                for j in range(i):
                    self.done.add(j)
                self.current = i
                self.bar.setRange(0, 0)
        self.render()

    def progress(self, done, total):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def finish(self, ok):
        if ok:
            self.done = set(range(len(self.steps)))
            self.current = None
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if ok else 0)
        self.render()

    def render(self):
        parts = []
        for i, (label, _) in enumerate(self.steps):
            if i in self.done:
                parts.append("<span style='color:#1e8449'>✔ %s</span>" % label)
            elif i == self.current:
                parts.append("<b>▶ %s</b>" % label)
            else:
                parts.append("<span style='color:#999'>%s</span>" % label)
        self.label.setText(" · ".join(parts))


WARNING_TEXT = {
    "reboot_failed": ("The radio is still in programming mode. Switch it off and on before using "
                      "it.", "error"),
    "prewrite_failed": ("No backup of the radio's previous codeplug was kept for this write.",
                        "warn"),
    "prewrite_skipped": ("No backup of the radio's previous codeplug was kept for this write.",
                         "warn"),
    "unit_unreadable": ("Couldn't identify the radio, so the radio list wasn't updated.", "warn"),
    "roster_failed": ("The radio list (radios.tsv) couldn't be updated.", "warn"),
    "privacy_inconsistent": ("A channel has encryption set but switched off. Set its Privacy "
                             "again and write.", "warn"),
}


def warning_widgets(res):
    out = []
    for w in res.warnings:
        code = w.get("code")
        if code in ("no_key_check", "no_privacy_columns"):
            continue
        if code == "unit_block_unreadable" and res.a207:
            continue        # one identification block missed; the unit was still identified
        if code == "unit_unreadable" and res.code == "unit_unreadable":
            continue        # the failure itself says so
        text, level = WARNING_TEXT.get(code, (w.get("message") or code, "warn"))
        out.append(_warn("⚠ " + _esc(text), level))
    return out


class RadioRunDialog(QDialog):
    """Base: a form page, then a progress page that can't be cancelled.

    A dialog belongs to the unit it showed. Its Write button is live only
    while the radio bar still has that same unit identified and nothing else
    is running, and the write itself names that unit (--expect-unit): the
    engine refuses any other radio before it reads, erases or sends anything.
    """

    finished_run = pyqtSignal(object)

    def __init__(self, ctx, title, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(title)
        self.setMinimumWidth(640)
        self.running = False
        self.result = None
        self.action = None
        self.job = None
        self.phase = None
        self.other_unit = None
        self.closed = False
        self.a207 = (ctx.unit or {}).get("a207")
        self.lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        self.form = QWidget()
        self.form_lay = QVBoxLayout(self.form)
        self.form_lay.setContentsMargins(0, 0, 0, 0)
        self.prog = QWidget()
        self.prog_lay = QVBoxLayout(self.prog)
        self.prog_lay.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.form)
        self.stack.addWidget(self.prog)
        self.lay.addWidget(self.stack)
        self.gate_note = _warn("", "error")
        self.gate_note.setVisible(False)
        self.lay.addWidget(self.gate_note)
        self.bb = QDialogButtonBox()
        self.lay.addWidget(self.bb)
        self.gate_timer = QTimer(self)
        self.gate_timer.timeout.connect(self.refresh_gate)
        self.gate_timer.start(300)
        ctx.radio_changed.connect(self.refresh_gate)

    # -- is this dialog still about the attached radio? --------------------------

    def gate_problem(self):
        """Why Write can't run now, or None."""
        if self.running or self.result is not None:
            return None
        bar = getattr(self.ctx, "bar", None)
        if not self.ctx.engine_check.ok:
            return "The programming engine is missing or the wrong version."
        if self.ctx.runner.busy:
            return "Another radio operation is running. Wait for it to finish."
        if bar is None or not bar.identified():
            return ("The radio is no longer identified. Close this dialog and press Identify.")
        u = self.ctx.unit or {}
        if not self.a207 or u.get("a207") != self.a207:
            return ("A different radio is connected now. Close this dialog and open it again.")
        return None

    def refresh_gate(self):
        p = self.gate_problem()
        self.gate_note.setText("✖ " + _esc(p) if p else "")
        self.gate_note.setVisible(bool(p))
        self.update_write_button(p is None)

    def update_write_button(self, gate_ok):
        pass

    # -- the run ---------------------------------------------------------------

    def start_run(self, cmd, steps):
        problem = self.gate_problem()
        if problem:
            QMessageBox.information(self, "TYTcps", problem)
            return False
        self.steps = Steps(steps)
        self.prog_lay.addWidget(self.steps)
        self.outcome = QVBoxLayout()
        self.prog_lay.addLayout(self.outcome)
        self.prog_lay.addStretch(1)
        self.stack.setCurrentWidget(self.prog)
        self.bb.clear()
        self.close_btn = self.bb.addButton(QDialogButtonBox.StandardButton.Close)
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        self.running = True
        self.gate_note.setVisible(False)
        self.ctx.runner.radio_event.connect(self._event)
        self.job = self.ctx.runner.run_radio(cmd, self._done)
        if self.job is None:            # something else started first
            self.running = False
            self.ctx.runner.radio_event.disconnect(self._event)
            self.close_btn.setEnabled(True)
            self.outcome.addWidget(_warn("Another radio operation is running. Nothing was "
                                         "written.", "error"))
            return False
        return True

    def _event(self, ev):
        kind = ev.get("event")
        if kind == "phase":
            self.phase = ev.get("phase")
            self.steps.phase(self.phase)
        elif kind == "progress":
            self.steps.progress(ev.get("done", 0), ev.get("total", 0))
        elif kind == "unit":
            got = (ev.get("a207") or "").lower()
            if got != (self.a207 or ""):
                self.other_unit = got or "unreadable"

    def _done(self, res):
        self.running = False
        self.result = res
        try:
            self.ctx.runner.radio_event.disconnect(self._event)
        except TypeError:
            pass
        self.steps.finish(res.ok)
        self.close_btn.setEnabled(True)
        # The engine refuses another radio before writing (unit_mismatch);
        # this only fires if one was written all the same.
        wrote = res.ok or res.radio_state not in (None, "unchanged")
        if self.other_unit and self.other_unit != "unreadable" and wrote:
            self.outcome.addWidget(_warn(
                "⚠ <b>This was a different radio</b>: unit %s, not %s. The ledger and the "
                "radio list show the unit that was written."
                % (short_unit(self.other_unit), short_unit(self.a207)), "error"))
        try:
            self.show_outcome(res)
        finally:
            # Recorded even if the message can't be shown: the recovery
            # image and "keys unknown" are what keep a damaged radio safe.
            self.record_state(res)
        # The main window refreshed when the run ended, before this
        # dialog recorded its outcome (keys unknown, recovery image).
        self.ctx.fleet_changed.emit()
        self.ctx.radio_changed.emit()
        for w in warning_widgets(res):
            self.outcome.addWidget(w)
        self.finished_run.emit(res)

    def record_state(self, res):
        """Persist what this run did to the radio (subclasses)."""

    def record_codeplug(self, res, image):
        """A codeplug write that broke off or didn't verify leaves the image it
        was writing as the unit's recovery; a verified write clears it."""
        a207 = res.a207
        if not a207:
            return
        try:
            if res.ok or res.radio_state == "codeplug_written":
                self.ctx.fleet.set_codeplug_incomplete(a207, None)
            elif res.radio_state in ("codeplug_incomplete", "codeplug_differs",
                                     "codeplug_unverified") or \
                    (res.radio_state != "unchanged" and res.reached("erase", "write", "verify")):
                if image is not None and Path(image).is_file():
                    self.ctx.fleet.set_codeplug_incomplete(a207, image)
        except (OSError, ValueError) as e:
            self.outcome.addWidget(_warn("⚠ Couldn't save this radio's recovery state in the "
                                         "fleet folder (%s)." % _esc(e), "error"))

    def show_outcome(self, res):
        if res.ok:
            return
        msg = messages.explain(res)
        text = "<b>%s</b><br>%s" % (_esc(msg.title), _esc(msg.body))
        if msg.state:
            text += "<br><br><b><i>%s</i></b>" % _esc(msg.state)
        self.outcome.addWidget(_warn(text, "error"))
        self.failure = msg
        row = QHBoxLayout()
        for name in msg.buttons:
            if name in ("record_now", "copy_line", "goto", "open_keys"):
                continue
            b = QPushButton(messages.BUTTON_TEXT.get(name, name))
            b.clicked.connect(lambda _, n=name: self._action(n))
            row.addWidget(b)
        row.addStretch(1)
        self.outcome.addLayout(row)

    def _action(self, name):
        self.action = name
        self.accept()

    def done(self, r):
        self.closed = True
        self.gate_timer.stop()
        try:
            self.ctx.radio_changed.disconnect(self.refresh_gate)
        except TypeError:
            pass
        super().done(r)

    def reject(self):
        if self.running:
            QMessageBox.information(self, "TYTcps", "A radio operation is running. Wait for it to "
                                                    "finish before closing.")
            return
        super().reject()

    def closeEvent(self, ev):
        if self.running:
            ev.ignore()
            self.reject()
            return
        super().closeEvent(ev)


WRITE_STEPS = [("Read 1", ["connect", "read1"]), ("Read 2", ["read2"]),
               ("Compare", ["compare", "parse", "check", "prewrite"]), ("Erase", ["erase"]),
               ("Write", ["write"]), ("Verify", ["verify", "verify_retry"])]
# Where an image keeps the Radio ID and Name (fieldmap.md: 0x2084 uint32;
# the name is 16 UTF-16 characters at 0x20B0).
ID_BYTES = (0x2084, 0x2088)
NAME_BYTES = (0x20B0, 0x20D0)

KEY_STEPS = [("Connect", ["connect"]), ("Send 20 blocks", ["keys"]), ("Done", [])]


class WriteCodeplugDialog(RadioRunDialog):
    def gate_problem(self):
        p = super().gate_problem()
        if p is None and not self.running and self.result is None:
            p = codeplug_model_problem(self.ctx.unit)
        return p

    def __init__(self, ctx, preview_ctl, parent=None):
        super().__init__(ctx, "Write codeplug to this radio", parent)
        self.preview_ctl = preview_ctl
        self.preview = None
        self.previewing = False
        self.again = False
        self.goto_request = None
        self.keys_after = False
        self.write_ready = False
        self.attempt_image = None
        cp = ctx.codeplug
        f = self.form_lay
        top = QFormLayout()
        top.addRow("Radio:", QLabel(unit_line(ctx)))
        top.addRow("Codeplug:", QLabel(cp.title + (" (unsaved changes included)" if cp.dirty else "")))
        # The radio keeps its own Radio ID and Name; only an ID or Name
        # changed on the General tab is written (Codeplug.write_text).
        changed = [("Radio ID %s" % cp.doc.scalar("ID")) if cp.identity_edited("ID") else None,
                   ('Radio Name "%s"' % name_display(cp.doc.scalar("Name", "-")))
                   if cp.identity_edited("Name") else None]
        changed = [c for c in changed if c]
        top.addRow("Radio ID and Name:", QLabel(
            "Set to %s, as changed on the General tab." % " and ".join(changed) if changed else
            "The radio keeps its own."))
        f.addLayout(top)
        chg = QHBoxLayout()
        self.changes = QLabel()
        self.changes.setTextFormat(Qt.TextFormat.RichText)
        self.b_show = QPushButton("Show")
        self.b_show.clicked.connect(self._show)
        chg.addWidget(QLabel("Changes compared with the file:"))
        chg.addWidget(self.changes, 1)
        chg.addWidget(self.b_show)
        f.addLayout(chg)
        self.warnings = QVBoxLayout()
        f.addLayout(self.warnings)
        self.b_write = self.bb.addButton("Write codeplug", QDialogButtonBox.ButtonRole.AcceptRole)
        self.bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.bb.accepted.connect(self._write)
        self.bb.rejected.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._run_preview)
        self._changed()

    def _roster_unit(self):
        u = self.ctx.unit or {}
        return self.ctx.fleet.unit(u["a207"]) if u.get("a207") else None

    def write_text(self):
        return self.ctx.codeplug.write_text()

    def update_write_button(self, gate_ok):
        self.gate_ok = gate_ok
        if hasattr(self, "b_write") and not self.running and self.result is None:
            self.b_write.setEnabled(bool(gate_ok and self.write_ready))

    def _changed(self):
        self.preview = None
        self.write_ready = False
        self.b_write.setEnabled(False)
        self.changes.setText("Checking…")
        self.timer.start()
        self._warnings()

    def _run_preview(self):
        if self.previewing:
            self.again = True
            return
        cp = self.ctx.codeplug
        text = self.write_text()
        edited = cp.doc.edited_records() | ({("general", 0)} if text != cp.edited_text() else set())
        base, keyset, engine = cp.base, self.ctx.current_path, self.ctx.engine
        self.previewing = True

        def done(result, exc):
            if self.closed:
                return          # the dialog was closed while this ran
            self.previewing = False
            if self.again:
                self.again = False
                self._run_preview()
                return
            if exc is not None:
                self.preview = cpmod.Preview(cpmod.sha256_text(text), False,
                                             errors=[{"message": str(exc)}], message=str(exc))
            else:
                self.preview = result[0]
            self._render_preview()
        self.ctx.runner.run_offline(lambda: cpmod.run_preview(engine, base, text, edited, keyset), done)

    def _render_preview(self):
        p = self.preview
        if p is None:
            return
        if p.ok:
            self.changes.setText(headline(p))
        else:
            e = (p.errors or [{}])[0]
            self.changes.setText("<span style='color:#c0392b'>✖ %s</span>" % _esc(e.get("message", p.message)))
        self.b_show.setEnabled(p.ok)
        self._warnings()

    def _warnings(self):
        while self.warnings.count():
            w = self.warnings.takeAt(0).widget()
            if w:
                w.deleteLater()
        cp = self.ctx.codeplug
        ru = self._roster_unit()
        blocking = False
        if cp.identity_edited("ID"):
            rid = cp.doc.scalar("ID")
            if ru and ru.radio_id and rid != ru.radio_id:
                self.warnings.addWidget(_warn("⚠ This radio is %s. Writing will change it to %s, "
                                              "as set on the General tab." % (ru.radio_id, rid)))
            for other in self.ctx.fleet.roster():
                if other.radio_id == rid and (ru is None or other.a207 != ru.a207) and not other.hidden:
                    self.warnings.addWidget(_warn(
                        '⚠ Radio ID %s is already used by Unit %s%s. Two radios with the same ID '
                        "will conflict on the network."
                        % (rid, other.short, (' "%s"' % other.label) if other.label else "")))
        recovery = self.ctx.fleet.codeplug_incomplete(self.a207) if self.a207 else None
        if recovery is not None:
            blocking = True
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(_warn("✖ The last codeplug write to this radio didn't finish. Write that "
                               "codeplug again in full first.", "error"), 1)
            b = QPushButton("Write that codeplug")
            b.clicked.connect(lambda: self._recover(recovery))
            bl.addWidget(b)
            self.warnings.addWidget(box)
        underscored = [r for r in self.ctx.codeplug.doc.rows("Message") if "_" in r.cells[1]]
        if underscored:
            self.warnings.addWidget(_warn(
                "⚠ Message%s %s contain%s '_', which the engine writes as a space." % (
                    "s" if len(underscored) > 1 else "",
                    ", ".join(r.cells[0] for r in underscored),
                    "" if len(underscored) > 1 else "s")))
        p = self.preview
        if p is not None and not p.ok:
            blocking = True
            for e in p.errors or []:
                if e.get("code") == "key_slot_empty":
                    box = QWidget()
                    bl = QHBoxLayout(box)
                    bl.setContentsMargins(0, 0, 0, 0)
                    bl.addWidget(_warn("✖ Channel '%s' uses key slot %s, which is empty in the "
                                       "current key set." % (e.get("name"), e.get("slot")),
                                       "error"), 1)
                    b = QPushButton("Go to channel")
                    b.clicked.connect(lambda _, ev=e: self._goto(ev))
                    bl.addWidget(b)
                    self.warnings.addWidget(box)
        if self.ctx.current_path is None:
            self.warnings.addWidget(_warn("⚠ No key set is loaded, so encrypted channels can't be "
                                          "checked against it."))
        u = self.ctx.unit or {}
        if u.get("a207"):
            st = self.ctx.keys_status(u["a207"])
            if self.ctx.current_sha and st.kind != "current":
                box = QWidget()
                bl = QHBoxLayout(box)
                bl.setContentsMargins(0, 0, 0, 0)
                text = {"old": "⚠ This radio has an old key set. Encrypted channels won't work "
                               "with the fleet until you write the current keys.",
                        "unknown": "⚠ A key write to this radio didn't finish. Write the current "
                                   "keys before using it."}.get(
                    st.kind, "⚠ There's no record of this radio's keys. Encrypted channels may "
                             "not work with the fleet until you write the current keys.")
                bl.addWidget(_warn(text), 1)
                self.cb_keys = QCheckBox("Write keys after this")
                self.cb_keys.setChecked(self.keys_after)
                self.cb_keys.toggled.connect(lambda on: setattr(self, "keys_after", on))
                bl.addWidget(self.cb_keys)
                self.warnings.addWidget(box)
        if p is not None and p.ok and p.unexplained_bytes:
            self.warnings.addWidget(_warn("⚠ %d bytes change in records you didn't edit. Check "
                                          "the list before writing." % p.unexplained_bytes))
        current = p is not None and p.conf_sha == cpmod.sha256_text(self.write_text())
        self.write_ready = bool(current and p.ok and not blocking)
        self.update_write_button(self.gate_problem() is None)

    def _goto(self, ev):
        self.goto_request = ev
        self.reject()

    def _recover(self, image):
        self.attempt_image = image
        self.action = "write_again"
        self.reject()

    def record_state(self, res):
        if not res.ok and self.attempt_image is not None:
            self._keep_radio_identity(res)
        self.record_codeplug(res, self.attempt_image)

    def _keep_radio_identity(self, res):
        """The recovery image is the file with this write's changes; its
        Radio ID and Name are the file's. Unless they were changed on the
        General tab, put back the radio's own, from the copy the engine kept
        of the radio just before this write."""
        cp = self.ctx.codeplug
        a207 = res.a207 or self.a207
        pre = self.ctx.fleet.folder / "prewrite"
        if not a207 or not pre.is_dir():
            return
        mine = [p for p in pre.glob("%s-*.img" % a207)
                if p.stat().st_mtime >= getattr(self, "started", 0) - 2]
        if not mine:
            return
        before = max(mine, key=lambda p: p.stat().st_mtime).read_bytes()
        img = bytearray(Path(self.attempt_image).read_bytes())
        if len(before) != len(img):
            return
        for key, (lo, hi) in (("ID", ID_BYTES), ("Name", NAME_BYTES)):
            if not cp.identity_edited(key):
                img[lo:hi] = before[lo:hi]
        Path(self.attempt_image).write_bytes(bytes(img))

    def _show(self):
        if self.preview and self.preview.ok:
            PreviewPanel(self.preview, self, "Changes this write makes, compared with the file").exec()

    def _write(self):
        if self.gate_problem():
            self.refresh_gate()
            return
        p = self.preview
        text = self.write_text()
        if p is None or not p.ok or p.conf_sha != cpmod.sha256_text(text) or not self.write_ready:
            return
        run_dir = self.ctx.runtime.new_run("write-conf")
        conf = run_dir / "write.conf"
        conf.write_text(text, encoding="utf-8")
        # The whole image this write is meant to leave, for a recovery that
        # writes it as-is if this write breaks off (never -c over a damaged
        # radio).
        self.attempt_image = run_dir / "intended.img"
        shutil.copyfile(p.image, self.attempt_image)
        self.started = time.time()
        self.start_run(radio.write_conf(conf, self.ctx.current_path, self.ctx.engine.short,
                                        unit=self.a207), WRITE_STEPS)

    def show_outcome(self, res):
        if res.ok:
            r = res.result
            text = "✔ <b>Written and verified.</b> The radio holds this codeplug."
            if r.get("volatile"):
                text += " (%d bytes the radio changes by itself were ignored.)" % r["volatile"]
            self.outcome.addWidget(_warn(text, "info"))
            return
        super().show_outcome(res)


class WriteKeysDialog(RadioRunDialog):
    def __init__(self, ctx, keyset_name, parent=None):
        super().__init__(ctx, "Write keys to this radio", parent)
        self.keyset_name = keyset_name
        path = ctx.fleet.keys_dir / keyset_name
        self.keyset = K.load(ctx.engine, path)
        self.sha = self.keyset.sha256
        u = ctx.unit or {}
        ru = ctx.fleet.unit(u["a207"]) if u.get("a207") else None
        current = keyset_name == ctx.current_name
        form = QFormLayout()
        form.addRow("Radio:", QLabel(unit_line(ctx)))
        form.addRow("Key set:", QLabel("%s%s · SHA256 %s…%s" % (
            K.display_name(keyset_name), " (current)" if current else "", self.sha[:4], self.sha[-4:])))
        sl = QLabel(self.keyset.summary())
        sl.setWordWrap(True)
        form.addRow("Slots:", sl)
        self.form_lay.addLayout(form)
        note = QLabel("This replaces all 16 slots on the radio. Slots you leave empty here become "
                      "empty on the radio.")
        note.setWordWrap(True)
        self.form_lay.addWidget(note)
        when = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
        line = "%s  %s  %s  %s  %s…%s  %s" % (
            when, short_unit(u.get("a207", "")), ru.radio_id if ru and ru.radio_id else "-",
            ru.label if ru and ru.label else "-", self.sha[:4], self.sha[-4:], keyset_name)
        self.form_lay.addWidget(QLabel("Ledger line to add:"))
        ll = QLabel("<tt>%s</tt>" % _esc(line))
        ll.setTextFormat(Qt.TextFormat.RichText)
        self.form_lay.addWidget(ll)
        if not current:
            self.form_lay.addWidget(_warn("⚠ This isn't the current key set. This radio won't be "
                                          "able to talk encrypted with radios on the current set."))
        if not (ru and ru.radio_id):
            self.form_lay.addWidget(_warn("⚠ This radio's ID isn't known yet. Read or write its "
                                          "codeplug once to fill it in."))
        del self.keyset
        self.b_write = self.bb.addButton("Write keys", QDialogButtonBox.ButtonRole.AcceptRole)
        self.bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.refresh_gate()
        self.bb.accepted.connect(self._write)
        self.bb.rejected.connect(self.reject)

    def update_write_button(self, gate_ok):
        if hasattr(self, "b_write") and not self.running and self.result is None:
            self.b_write.setEnabled(gate_ok)

    def _write(self):
        # Marked unknown BEFORE the transfer, so a TYTcps that dies during it
        # (power loss, logout) leaves the mark; resolved when the run ends.
        if self.gate_problem():
            self.refresh_gate()
            return
        self.was_unknown = self.a207 in self.ctx.keys_unknown
        if not self.ctx.mark_keys_unknown(self.a207, True):
            if not self.was_unknown:
                self.ctx.mark_keys_unknown(self.a207, False)
            QMessageBox.warning(self, "TYTcps", "Can't save to the fleet folder (radios.tsv). "
                                                "Check disk space and permissions, then try "
                                                "again. Nothing was written.")
            return
        if not self.start_run(radio.write_keys(self.ctx.fleet.folder, self.keyset_name,
                                               unit=self.a207), KEY_STEPS):
            self.ctx.mark_keys_unknown(self.a207, self.was_unknown)

    def record_state(self, res):
        e = res.error or {}
        state = e.get("radio") if not res.ok else None
        target = res.a207 or self.a207
        written = res.ok or state == "keys_written"
        broken = not written and (state == "keys_unknown" or
                                  (state != "unchanged" and res.reached("keys")))
        ok = True
        if target != self.a207 or not (written or broken):
            # This dialog's unit was not written: its mark goes back to what
            # it was. A radio that was refused or not reached keeps its own.
            ok = self.ctx.mark_keys_unknown(self.a207, self.was_unknown)
        if written:
            ok = self.ctx.mark_keys_unknown(target, False) and ok
        elif broken:
            ok = self.ctx.mark_keys_unknown(target, True) and ok
        if not ok:
            self.outcome.addWidget(_warn(
                "⚠ Couldn't save this radio's key state in the fleet folder.", "error"))

    def show_outcome(self, res):
        if res.ok:
            u = self.ctx.unit or {}
            ru = self.ctx.fleet.unit(u["a207"]) if u.get("a207") else None
            who = (ru.label or ("Radio ID %s" % ru.radio_id if ru.radio_id else None)) if ru else None
            self.outcome.addWidget(_warn("✔ <b>Keys sent: %s → %s.</b> Recorded in the ledger." % (
                _esc(K.display_name(self.keyset_name)), _esc(who or "Unit " + short_unit(u.get("a207", "")))),
                "info"))
            self.outcome.addWidget(_warn(
                "Keys can't be read back from the radio. Before using it, test each key slot you "
                "use with another radio on the same key set. If this radio isn't an MD-UV390 "
                "Plus, its Universal channels will sound garbled: only the Plus uses these keys.",
                "warn"))
            return
        super().show_outcome(res)
        if res.code == "ledger_failed":
            line = (res.error or {}).get("line", "")
            row = QHBoxLayout()
            b1 = QPushButton("Record now")
            b2 = QPushButton("Copy line")
            b1.clicked.connect(lambda: setattr(self, "record_now", True) or self.accept())
            b2.clicked.connect(lambda: QGuiApplication.clipboard().setText(line))
            row.addWidget(b1)
            row.addWidget(b2)
            row.addStretch(1)
            self.outcome.addLayout(row)


class WriteImageDialog(RadioRunDialog):
    """After a codeplug write that didn't finish: write the codeplug it was
    writing again, whole (-w), never -c over a damaged radio."""

    def gate_problem(self):
        p = super().gate_problem()
        if p is None and not self.running and self.result is None:
            p = codeplug_model_problem(self.ctx.unit)
        return p

    def __init__(self, ctx, parent, preset, preset_note=None):
        super().__init__(ctx, "Write the codeplug again", parent)
        self.path = Path(preset)
        self.form_lay.addWidget(QLabel("Radio: " + unit_line(ctx)))
        self.form_lay.addWidget(_warn(preset_note or "The last write to this radio didn't finish. "
                                      "This writes the same codeplug again in full.", "info"))
        self.b_write = self.bb.addButton("Write again", QDialogButtonBox.ButtonRole.AcceptRole)
        self.bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.bb.accepted.connect(self._write)
        self.bb.rejected.connect(self.reject)
        self.refresh_gate()

    def update_write_button(self, gate_ok):
        if hasattr(self, "b_write") and not self.running and self.result is None:
            self.b_write.setEnabled(bool(gate_ok and self.path.is_file()))

    def _write(self):
        if not self.path.is_file() or self.gate_problem():
            self.refresh_gate()
            return
        if self.path.stat().st_size != cpmod.IMAGE_SIZE:
            QMessageBox.warning(self, "TYTcps", "That file isn't a codeplug for this radio "
                                "(%d bytes, expected 851968)." % self.path.stat().st_size)
            return
        # -w reads a copy, so a recovery still has the file if this breaks off too.
        run_dir = self.ctx.runtime.new_run("write-image")
        self.attempt = run_dir / "image.img"
        shutil.copyfile(self.path, self.attempt)
        cmd = radio.write_image(self.attempt, self.ctx.engine.short, unit=self.a207)
        sha = cpmod.hashlib.sha256(self.attempt.read_bytes()).hexdigest()
        cmd.display += "    (copy of %s, SHA256 %s…%s)" % (self.ctx.engine.short(self.path),
                                                      sha[:8], sha[-8:])
        self.start_run(cmd, WRITE_STEPS)

    def record_state(self, res):
        self.record_codeplug(res, getattr(self, "attempt", None))

    def show_outcome(self, res):
        if res.ok:
            r = res.result
            text = "✔ <b>Written and verified.</b> The radio holds this codeplug."
            if r.get("volatile"):
                text += " (%d bytes the radio changes by itself were ignored.)" % r["volatile"]
            self.outcome.addWidget(_warn(text, "info"))
            return
        super().show_outcome(res)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
