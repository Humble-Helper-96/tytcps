# SPDX-License-Identifier: GPL-3.0-or-later
"""≡ → Save diagnostics…: gather what a bug report needs and save it as one
file (backend/diagnostics.py makes it safe to send)."""

import datetime
import os
import platform
import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from .. import __version__
from ..backend import diagnostics as D
from ..backend import usb
from ..backend.fleet import short_unit
from .firstrun import checks

README = """\
TYTcps diagnostics, saved {when}.

  system.txt     program and engine versions, the system, USB access
  radio.txt      the radio last identified
  log.txt        the end of the log: what each radio operation printed
  crash.txt      errors inside TYTcps itself, if there were any
  codeplug.conf  the open codeplug's settings, passwords removed
  fleet.txt      the radio list and the record of key writes

Radio units and key-set fingerprints are shortened. No key, key file or
codeplug image is in this file: it was checked for the keys of every key set
in the fleet folder before it was saved.
"""


def _os_name():
    try:
        for line in open("/etc/os-release", encoding="utf-8"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def gather(win):
    """{file name: text} for the bundle, from the main window's state."""
    ctx = win.ctx
    home = str(Path.home())

    def tilde(p):
        p = str(p)
        return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p

    ec = ctx.engine_check
    sysl = ["TYTcps %s" % __version__,
            "Python %s, PyQt %s, Qt %s" % (platform.python_version(), PYQT_VERSION_STR, QT_VERSION_STR),
            "System: %s (%s %s), session %s" % (_os_name(), platform.system(), platform.release(),
                                               os.environ.get("XDG_SESSION_TYPE", "?")),
            "Engine: %s" % ("dmrconfig-tyt %s (%s %s), api %s" % (
                ec.info.get("version"), ec.info.get("branch"), ec.info.get("commit"),
                ec.info.get("api")) if ec.ok else "problem: " + ec.problem),
            "Engine path: %s" % tilde(ctx.engine.binary),
            "Fleet folder: %s (%s)" % (tilde(ctx.fleet.folder),
                                      "writable" if os.access(ctx.fleet.folder, os.W_OK) else
                                      "not writable"),
            "", "USB:"]
    devs = usb.scan()
    sysl.append("  %d radio(s) on the bus%s" % (len(devs), "".join(
        ", %03d/%03d %s" % (d.busnum, d.devnum, "writable" if d.writable else "not writable")
        for d in devs)))
    for name, ok, text, fix in checks(ec)[1:]:
        sysl.append("  %s %s: %s" % ("ok" if ok else "PROBLEM", name, tilde(text)))

    u = ctx.unit or {}
    bar = getattr(win, "bar", None)
    radl = ["Radio bar: %s" % (bar.state if bar else "?")]
    if u:
        radl.append("Model %s, firmware %s, unit %s" % (u.get("model", "-"), u.get("firmware", "-"),
                                                        short_unit(u.get("a207", ""))))
        if u.get("a207"):
            ru = ctx.fleet.unit(u["a207"])
            st = ctx.keys_status(u["a207"])
            radl.append("Radio ID %s, keys: %s" % (ru.radio_id if ru and ru.radio_id else "-", st.kind))
    else:
        radl.append("No radio identified.")

    log = ctx.applog.tail() if ctx.applog is not None else ""
    if not log.strip():
        log = win.drawer.last_text(20, raw=True)

    crash = ""
    if ctx.crash is not None:
        crash = "\n\n".join(ctx.crash.traces)
        fault = ctx.crash.fault_log()
        if fault.strip():
            crash += "\n\nfault.log (crashes of earlier sessions):\n" + fault[-20000:]

    cp = ctx.codeplug
    conf = None
    if cp is not None:
        conf = "# %s%s\n%s" % (cp.title, " (unsaved changes)" if cp.dirty else "", cp.edited_text())

    fl = ["Current key set: %s%s" % (ctx.current_name or "none",
                                     (" " + ctx.current_sha) if ctx.current_sha else ""),
          "Key sets: %s" % (", ".join(n for n, _ in ctx.fleet.keysets()) or "none"),
          "", "Radios (unit, Radio ID, label, last seen, last codeplug write, flags):"]
    for r in ctx.fleet.roster():
        fl.append("  %s  %s  %s  %s  %s  %s" % (r.a207, r.radio_id or "-", r.label or "-",
                                                r.last_seen or "-", r.last_write or "-",
                                                ",".join(r.flags) or "-"))
    fl += ["", "Key writes (when, unit, Radio ID, label, key set, file, tool):"]
    for l in ctx.fleet.ledger():
        fl.append("  %s  %s  %s  %s  %s  %s  %s" % (l.when, l.a207, l.radio_id, l.label, l.sha256,
                                                    l.file, l.tool))
    if ctx.fleet.problems:
        fl.append("Unreadable lines: %s" % ", ".join("%s:%d" % p for p in ctx.fleet.problems))

    when = datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")
    return {"README.txt": README.format(when=when), "system.txt": "\n".join(sysl) + "\n",
            "radio.txt": "\n".join(radl) + "\n", "log.txt": log, "crash.txt": crash or None,
            "codeplug.conf": conf, "fleet.txt": "\n".join(fl) + "\n"}


REFUSED = ("The diagnostics weren't saved because they would have contained a key. Please "
           "report this. The log in the fleet folder says which part, without the key.")
UNCHECKED = ("The diagnostics weren't saved because these key files couldn't be read to check "
             "them against: %s. Check that the keys folder in the fleet folder can be read.")


def copy_text(win, text):
    """Copy diagnostics text to the clipboard, checked like the bundle.
    Returns True when copied."""
    from PyQt6.QtGui import QGuiApplication
    try:
        # before and after shortening: a 16-byte key is as long as a unit block
        D.check_text("the copied diagnostics", text, win.ctx.fleet.keys_dir)
        text = D.shorten(D.strip_passwords(text))
        D.check_text("the copied diagnostics", text, win.ctx.fleet.keys_dir)
    except D.Refused as e:
        if win.ctx.applog is not None:
            win.ctx.applog.entry("Diagnostics not copied: key material found", "\n".join(e.problems))
        QMessageBox.critical(win, "TYTcps", REFUSED.replace("saved", "copied"))
        return False
    except D.Unchecked as e:
        QMessageBox.warning(win, "TYTcps", UNCHECKED.replace("saved", "copied") % ", ".join(e.names))
        return False
    QGuiApplication.clipboard().setText(text)
    return True


def save_dialog(win, path=None):
    """Ask where, build, save. Returns the path saved, or None."""
    if path is None:
        name = "tytcps-diagnostics-%s.zip" % datetime.datetime.now().strftime("%Y%m%d-%H%M")
        start = str(Path(win.ctx.setting("files/codeplug_dir", str(Path.home()))) / name)
        path, _ = QFileDialog.getSaveFileName(win, "Save diagnostics", start, "Zip files (*.zip)")
        if not path:
            return None
    log = win.ctx.applog
    try:
        data = D.build(gather(win), win.ctx.fleet.keys_dir)
    except D.Refused as e:
        if log is not None:
            log.entry("Diagnostics not saved: key material found", "\n".join(e.problems))
        QMessageBox.critical(win, "TYTcps", REFUSED)
        return None
    except D.Unchecked as e:
        QMessageBox.warning(win, "TYTcps", UNCHECKED % ", ".join(e.names))
        return None
    except Exception:           # gathering must never take the program down
        text = traceback.format_exc()
        print(text, file=sys.stderr)
        if log is not None:
            log.entry("Diagnostics not made", text)
        QMessageBox.warning(win, "TYTcps", "The diagnostics file couldn't be made. What went "
                                           "wrong is in the log in the fleet folder.")
        return None
    try:
        D.save(path, data)
    except OSError as e:
        QMessageBox.warning(win, "TYTcps", "Couldn't save %s: %s." % (Path(path).name, e.strerror or e))
        return None
    win.drawer.set_status("Diagnostics saved")
    return path
