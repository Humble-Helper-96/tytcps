# SPDX-License-Identifier: GPL-3.0-or-later
"""The radio bar.

It watches sysfs once a second for 0483:df11: no USB I/O. Identifying a
radio opens a programming session, which puts the radio in "PC Programming
Mode" and restarts it, so identification is a button and never automatic.
Every Read, Write and key operation reports the radio's unit block too, so
the bar fills itself in after any of them.

After every radio run the radio leaves the bus and comes back about 2.7 s
later on a new device number (O3). The bar shows *Radio restarting…* until
that new number appears, with 5 s as the limit; the identity found by the
run carries across that restart. Any other disappearance clears it.
"""

import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QToolButton,
                             QVBoxLayout)

from ..backend import keys as keysmod
from ..backend import usb
from ..backend.fleet import short_unit
from ..backend.radio import RESTART_TIMEOUT

KEY_MODELS = ("MD-UV390", "MD-UV380")
# The CPS pages and the engine's offline edits are this layout's: an image
# file carries no model, so a codeplug is written only to a radio that
# identifies as one of these.
CODEPLUG_MODELS = KEY_MODELS


def codeplug_model_problem(unit):
    """Why a codeplug can't be written to this identified radio, or None."""
    model = (unit or {}).get("model")
    if model in CODEPLUG_MODELS:
        return None
    return ("TYTcps only writes codeplugs to MD-UV390 and MD-UV380 radios. This radio is a "
            "\"%s\"." % (model or "?"))


class RadioBar(QFrame):
    identify_clicked = pyqtSignal()
    read_clicked = pyqtSignal()
    write_codeplug_clicked = pyqtSignal()
    write_keys_clicked = pyqtSignal()
    fix_clicked = pyqtSignal()
    state_changed = pyqtSignal()

    def __init__(self, ctx, menu, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("radiobar")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.devices = []
        self.state = "none"
        self.identity_dev = None
        self.restart_from = None
        self.restart_deadline = None
        self.busy_text = ""
        self.retrying = False
        self.stuck_dev = None         # device left in programming mode (reboot_failed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 6, 6, 6)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.line1 = QLabel()
        self.line1.setTextFormat(Qt.TextFormat.RichText)
        f = self.line1.font()
        f.setPointSizeF(f.pointSizeF() * 1.08)
        f.setBold(True)
        self.line1.setFont(f)
        self.line2 = QLabel()
        self.line2.setTextFormat(Qt.TextFormat.RichText)
        text.addWidget(self.line1)
        text.addWidget(self.line2)
        # Every radio operation shows a bar, not only text: a read is ~6.5 s
        # and the text alone is easy to miss (6.6 bench). Busy without a
        # percentage yet (connecting) shows a moving bar.
        self.progress = QProgressBar()
        self.progress.setMaximumHeight(10)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        text.addWidget(self.progress)
        outer.addLayout(text, 1)

        self.b_fix = QPushButton("Fix…")
        self.b_fix.clicked.connect(self.fix_clicked)
        outer.addWidget(self.b_fix)
        self.b_identify = QPushButton("Identify")
        self.b_identify.setToolTip("Find out which radio this is. The radio shows PC Programming "
                                   "Mode and then restarts.")
        self.b_read = QPushButton("Read")
        self.b_write = QPushButton("Write codeplug…")
        self.b_keys = QPushButton("Write keys…")
        for b, sig in ((self.b_identify, self.identify_clicked), (self.b_read, self.read_clicked),
                       (self.b_write, self.write_codeplug_clicked),
                       (self.b_keys, self.write_keys_clicked)):
            b.clicked.connect(sig)
            outer.addWidget(b)
        self.b_menu = QToolButton()
        self.b_menu.setText("≡")
        self.b_menu.setToolTip("Menu")
        self.b_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.b_menu.setMenu(menu)
        self.b_menu.setStyleSheet("QToolButton { font-size: 16pt; padding: 0 8px; } "
                                  "QToolButton::menu-indicator { image: none; }")
        outer.addWidget(self.b_menu)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1000)
        ctx.fleet_changed.connect(self.render)
        ctx.keyset_changed.connect(self.render)
        self.poll()

    # -- what the bar knows ------------------------------------------------------

    @property
    def unit(self):
        return self.ctx.unit

    def identified(self):
        return self.state == "identified" and self.unit is not None

    def operable(self):
        """One writable radio, nothing running, not restarting."""
        return self.state in ("connected", "identified") and self.ctx.engine_check.ok

    def keys_supported(self):
        u = self.unit
        return bool(u) and u.get("privacy_capable", True) and u.get("model") in KEY_MODELS

    def roster_unit(self):
        u = self.unit
        return self.ctx.fleet.unit(u["a207"]) if u and u.get("a207") else None

    # -- events from runs ----------------------------------------------------------

    def job_started(self, text):
        self.busy_text = text
        self.set_fraction(None)
        self.restart_from = self.devices[0].key if len(self.devices) == 1 else None
        self.poll()

    def job_progress(self, text):
        self.busy_text = text
        self.render()

    def unit_seen(self, ev):
        """A `unit` event or identify result: who is attached."""
        if not ev.get("a207"):
            return
        prev = self.ctx.unit or {}
        u = dict(prev) if prev.get("a207") == ev["a207"] else {}
        for k in ("model", "a207", "serial", "firmware", "privacy_capable"):
            if k in ev and ev[k] is not None:
                u[k] = ev[k]
        self.ctx.unit = u
        # The run saw this unit on the device it started on. If the restart
        # that follows every run has already been seen, the radio is on its
        # new device number by now.
        if (self.ctx.runner.busy or self.restart_deadline is not None) and self.restart_from:
            self.identity_dev = self.restart_from
        else:
            self.identity_dev = self.devices[0].key if len(self.devices) == 1 else None
        self.ctx.radio_changed.emit()

    def set_fraction(self, done_total):
        """(done, total) of the current transfer, or None for 'working'."""
        if done_total and done_total[1]:
            self.progress.setRange(0, done_total[1])
            self.progress.setValue(done_total[0])
        else:
            self.progress.setRange(0, 0)

    def job_finished(self, radio_was_opened=True):
        self.busy_text = ""
        if radio_was_opened:
            self.restart_deadline = time.monotonic() + RESTART_TIMEOUT
        self.poll()

    def radio_stuck(self):
        """reboot_failed: the radio is still in programming mode on the same
        device number. Hold every radio button until it leaves the bus (the
        operator switches it off and on)."""
        self.restart_deadline = None
        self.stuck_dev = self.devices[0].key if len(self.devices) == 1 else None
        self.poll()

    def set_retrying(self, on):
        self.retrying = on
        self.render()

    # -- polling ------------------------------------------------------------------------

    def poll(self):
        self.devices = usb.scan()
        old = self.state
        now = time.monotonic()
        if self.stuck_dev is not None and not any(d.key == self.stuck_dev for d in self.devices):
            self.stuck_dev = None
            self._forget()
        if self.ctx.runner.busy:
            self.state = "busy"
        elif self.stuck_dev is not None:
            self.state = "stuck"
        elif self.restart_deadline is not None:
            back = [d for d in self.devices if d.key != self.restart_from]
            if len(self.devices) == 1 and back:
                # The restart finished: same radio, new device number.
                self.identity_dev = self.devices[0].key
                self.restart_deadline = None
                self.state = self._settled()
            elif now > self.restart_deadline:
                self.restart_deadline = None
                self.state = self._settled()
            else:
                self.state = "restarting"
        else:
            self.state = self._settled()
        if old != self.state:
            self.state_changed.emit()
        self.render()

    def _settled(self):
        if not self.devices:
            self._forget()
            return "none"
        if len(self.devices) > 1:
            self._forget()
            return "multiple"
        d = self.devices[0]
        if not d.writable:
            return "no_permission"
        if self.ctx.unit and self.identity_dev == d.key:
            return "identified"
        self._forget()
        return "connected"

    def _forget(self):
        if self.ctx.unit is not None:
            self.ctx.unit = None
            self.identity_dev = None
            self.ctx.radio_changed.emit()

    # -- drawing -------------------------------------------------------------------------

    def render(self):
        self.progress.setVisible(self.state == "busy")
        s = self.state
        dot = "<span style='color:%s'>%s</span> "
        hint = ""
        keys = ""
        if s == "none":
            l1 = dot % ("#888", "○") + "No radio connected."
            hint = "Connect the programming cable and turn the radio on."
        elif s == "no_permission":
            l1 = dot % ("#d68910", "⚠") + "Radio found, but this user can't open it."
            hint = "Settings → USB access shows the fix."
        elif s == "multiple":
            l1 = dot % ("#d68910", "⚠") + "Two radios are connected. Connect one at a time."
            hint = ("They can't be told apart over USB.")
        elif s == "busy":
            l1 = dot % ("#2e86c1", "◌") + (self.busy_text or "Working…")
            hint = "Don't disconnect the radio."
        elif s == "restarting":
            l1 = dot % ("#2e86c1", "◌") + ("Radio restarting, retrying…" if self.retrying
                                           else "Radio restarting…")
            hint = "The radio restarts after every operation and is back in about 3 seconds."
        elif s == "stuck":
            l1 = dot % ("#c0392b", "⚠") + "The radio is still in programming mode."
            hint = "It didn't restart after the last operation. Switch it off and on."
        elif s == "connected":
            l1 = dot % ("#27ae60", "●") + "Radio connected"
            hint = "Press Identify or Read. Either one restarts the radio."
        else:
            l1, keys = self._identified_lines()
        if not self.ctx.engine_check.ok:
            hint = "The programming engine is missing or the wrong version (see Settings)."
        self.line1.setText(l1)
        self.line2.setText(keys or "<span style='color:#777'>%s</span>" % hint)
        self.line1.setToolTip("")
        if s == "identified":
            self.line1.setToolTip("Radio ID and label from the last time this radio was read or "
                                  "written.")
        self.line2.setToolTip(self._keys_tooltip() if s == "identified" else "")
        self.b_identify.setVisible(s in ("connected", "identified"))
        self.b_fix.setVisible(s == "no_permission")

    def _identified_lines(self):
        u = self.unit
        ru = self.roster_unit()
        if u.get("model") not in KEY_MODELS:
            return ("<span style='color:#27ae60'>●</span> %s (not supported)" %
                    _esc(u.get("model") or "?"), self._keys_line())
        parts = [u.get("model") or "Radio", "Unit %s" % short_unit(u["a207"])]
        if ru and ru.radio_id:
            rid = "Radio ID %s" % ru.radio_id
            if ru.label:
                rid += ' "%s"' % _esc(ru.label)
            parts.append(rid)
        else:
            parts.append("new radio")
        l1 = "<span style='color:#27ae60'>●</span> " + " · ".join(_esc(p) for p in parts)
        return l1, self._keys_line()

    def _keys_line(self):
        u = self.unit
        if not self.keys_supported():
            return "<span style='color:#777'>Keys: not supported on this model</span>"
        st = self.ctx.keys_status(u["a207"])
        if st.kind == "unknown":
            return ("<span style='color:#c0392b'><b>Keys: unknown</b> (a key write didn't "
                    "finish). Write keys again before use.</span>")
        cur = keysmod.display_name(self.ctx.current_name) if self.ctx.current_name else None
        if st.kind == "none":
            return "<span style='color:#777'>Keys: no record</span>"
        name = _esc(st.line.keyset_name)
        if st.kind == "current":
            if st.manual:
                return "<span style='color:#1e8449'><i>Keys: recorded by hand: %s</i></span>" % name
            return "<span style='color:#1e8449'>Keys: %s (current)</span>" % name
        if cur:
            return ("<span style='color:#b9770e'>Keys: %s (old set, current is %s)</span>"
                    % (name, _esc(cur)))
        return "<span style='color:#b9770e'>Keys: %s (no current key set chosen)</span>" % name

    def _keys_tooltip(self):
        u = self.unit
        if not u:
            return ""
        st = self.ctx.keys_status(u["a207"])
        if st.kind == "unknown":
            return ("A key write to this radio didn't finish. Write keys again.")
        if st.kind == "none":
            return ("No key write is recorded for this radio. If it has keys from the CPS and you "
                    "know which, use Fleet → Record keys already on this radio.")
        return "Last given %s (%s)." % (st.line.when, "recorded by hand" if st.manual else "written")

    def set_buttons(self, read, write, keys, why_write="", why_keys=""):
        can = self.operable()
        self.b_identify.setEnabled(can)
        self.b_read.setEnabled(can and read)
        self.b_write.setEnabled(can and self.identified() and write)
        self.b_keys.setEnabled(can and self.identified() and keys and self.keys_supported())
        self.b_write.setToolTip(why_write if not self.b_write.isEnabled() else "")
        self.b_keys.setToolTip(why_keys if not self.b_keys.isEnabled() else "")


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
