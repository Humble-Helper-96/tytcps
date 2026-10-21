# SPDX-License-Identifier: GPL-3.0-or-later
"""What happens when TYTcps itself fails: an exception nothing caught.

The traceback goes to the log file in the fleet folder, and one plain message
says what to do, with a Save diagnostics button. TYTcps never quits by
itself here: the engine runs as its own process, and a write in progress must
be left to finish. The message is shown from the event loop,
never from inside the code that failed. The same error repeating (in a paint
event, say) is logged in full once, then counted, so it can't push the radio
operations out of the log. A hard crash of Qt or Python itself is written to
<fleet>/logs/fault.log by faulthandler.
"""

import faulthandler
import sys
import threading
import time
import traceback

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

SHOW_AGAIN_AFTER = 10.0          # seconds
KEEP_TRACES = 10


class CrashHandler(QObject):
    caught = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.log = None              # backend.applog.AppLog, once the fleet folder is known
        self.window = None           # the main window: radio_busy(), save_diagnostics()
        self.traces = []             # this session's, newest last
        self._seen = {}              # trace text -> how many times
        self._shown_at = None
        self._showing = False
        self._fault_file = None
        self.caught.connect(self._show, Qt.ConnectionType.QueuedConnection)

    def install(self):
        sys.excepthook = self._excepthook
        threading.excepthook = self._thread_hook
        try:
            faulthandler.enable()    # to stderr until the fleet folder is known
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass                     # no usable stderr (started from a launcher)

    def set_log(self, applog):
        self.log = applog
        try:
            applog.dir.mkdir(mode=0o700, exist_ok=True)
            f = open(applog.dir / "fault.log", "a", encoding="utf-8")
        except OSError:
            return
        try:
            faulthandler.enable(file=f)
        except (OSError, RuntimeError, ValueError):
            f.close()
            return
        if self._fault_file is not None:
            self._fault_file.close()
        self._fault_file = f

    def fault_log(self):
        """What faulthandler wrote in earlier sessions, if anything."""
        if self.log is None:
            return ""
        try:
            return (self.log.dir / "fault.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    # -- catching ------------------------------------------------------------------

    def _excepthook(self, etype, value, tb):
        if issubclass(etype, KeyboardInterrupt):
            sys.__excepthook__(etype, value, tb)
            return
        self.record("".join(traceback.format_exception(etype, value, tb)))

    def _thread_hook(self, args):
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread is not None else "?"
        self.record("In thread %s:\n%s" % (name, "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))))

    def record(self, text):
        """Log one unexpected error and show the message (from any thread)."""
        n = self._seen[text] = self._seen.get(text, 0) + 1
        if n == 1:
            try:
                sys.stderr.write(text)
            except Exception:
                pass
            self.traces.append(text)
            del self.traces[:-KEEP_TRACES]
            if self.log is not None:
                self.log.entry("Unexpected error", text)
        elif self.log is not None and n in (2, 10, 100, 1000, 10000):
            last = text.rstrip().splitlines()[-1] if text.strip() else "?"
            self.log.entry("The same error again (%d times so far): %s" % (n, last))
        # Queued: the message waits for the event loop, so it never opens
        # inside a paint event or half-way through whatever raised.
        self.caught.emit(text)

    # -- telling the user ---------------------------------------------------------

    def _show(self, text):
        now = time.monotonic()
        if self._showing or (self._shown_at is not None and now - self._shown_at < SHOW_AGAIN_AFTER):
            return
        if QApplication.instance() is None:
            return
        self._showing = True
        try:
            win = self.window
            busy = False
            try:
                busy = bool(win is not None and win.radio_busy())
            except Exception:
                pass
            box = QMessageBox(win)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("TYTcps")
            box.setText("<b>Something went wrong.</b>")
            info = "Save your work and restart the program."
            if busy:
                info = "A radio operation is still running. Let it finish, then save your work " \
                       "and restart the program."
            info += " To report it, save the diagnostics and send that file."
            box.setInformativeText(info)
            box.setDetailedText(text[-4000:])
            save = None
            if win is not None:
                save = box.addButton("Save diagnostics…", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if save is not None and box.clickedButton() is save:
                win.save_diagnostics()
        except Exception:
            pass                     # the message itself must never take the program down
        finally:
            self._showing = False
            self._shown_at = time.monotonic()
