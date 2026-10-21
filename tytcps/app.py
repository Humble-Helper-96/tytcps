# SPDX-License-Identifier: GPL-3.0-or-later
"""Start TYTcps: settings, the fleet folder (first run), the engine check."""

import argparse
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from . import __version__
from .backend import paths
from .backend.applog import AppLog
from .backend.engine import PACKAGE, Engine, locate_engine
from .backend.fleet import Fleet
from .crash import CrashHandler
from .ui.context import Context
from .ui.firstrun import FirstRun, import_into_fleet
from .ui.jobs import JobRunner


def parse_args(argv):
    p = argparse.ArgumentParser(prog="tytcps", description="TYTcps %s" % __version__)
    p.add_argument("file", nargs="?", help="codeplug file to open")
    p.add_argument("--fleet", help="fleet folder (default: the one chosen at first run, "
                                   "else ~/.local/share/tytcps)")
    p.add_argument("--log", help="also append the Details log to this file")
    p.add_argument("--version", action="version", version="TYTcps %s" % __version__)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    # argv[0] names the X11 window class: "tytcps" (python3 -m would give
    # "__main__.py"), which the desktop launcher's StartupWMClass matches.
    app = QApplication(["tytcps"])
    app.setApplicationName("TYTcps")
    app.setApplicationVersion(__version__)
    # A Flatpak names its launcher after the app ID.
    app.setDesktopFileName(os.environ.get("FLATPAK_ID", "tytcps"))
    app.setWindowIcon(QIcon(str(PACKAGE / "data" / "tytcps.svg")))
    crash = CrashHandler()
    crash.install()

    settings = QSettings(str(paths.settings_file()), QSettings.Format.IniFormat)
    folder = Path(args.fleet or settings.value("fleet/folder", "") or paths.default_fleet_folder())
    runtime = paths.RuntimeDir()
    try:
        return _run(app, args, settings, folder, runtime, crash)
    finally:
        runtime.cleanup()


def _run(app, args, settings, folder, runtime, crash):
    engine = Engine(locate_engine(), folder, runtime)
    check = engine.check()
    wiz = None

    fleet = Fleet(folder)
    if not fleet.exists():
        wiz = FirstRun(check, folder, None)
        if wiz.exec() != QDialog.DialogCode.Accepted:
            return 0
        folder = wiz.folder
        while True:
            fleet = Fleet(folder)
            try:
                fleet.create()
                break
            except OSError as e:
                QMessageBox.warning(None, "TYTcps", "Can't create the fleet folder %s: %s"
                                    % (folder, e.strerror))
                d = QFileDialog.getExistingDirectory(None, "Choose another fleet folder", str(Path.home()))
                if not d:
                    return 1
                folder = Path(d)
        if folder != paths.default_fleet_folder() and not args.fleet:
            settings.setValue("fleet/folder", str(folder))
        engine = Engine(locate_engine(), folder, runtime)
        check = engine.check()
        if wiz.key_choice == "dec" and wiz.dec_path:
            try:
                name, sha = import_into_fleet(engine, fleet, wiz.dec_path)
            except Exception as e:      # the fleet folder exists; keys can be imported later
                QMessageBox.warning(None, "TYTcps", "The key file wasn't imported: %s" % e)
    applog = AppLog(fleet.folder)
    crash.set_log(applog)
    applog.entry("TYTcps %s started" % __version__, "Engine: %s" % (
        "dmrconfig-tyt %s (%s %s)" % (check.info.get("version"), check.info.get("branch"),
                                      check.info.get("commit")) if check.ok else check.problem))
    from .backend import keys as keysmod
    keysmod.cleanup_partials(fleet.keys_dir)    # key files a killed save left behind
    if not settings.value("files/codeplug_dir", ""):
        settings.setValue("files/codeplug_dir", str(paths.documents_folder()))

    runner = JobRunner(engine)
    ctx = Context(engine, fleet, runner, runtime, check)
    ctx.applog = applog
    ctx.crash = crash
    from .ui.mainwindow import MainWindow
    win = MainWindow(ctx, logfile=args.log)
    crash.window = win
    win.show()
    if not check.ok:
        QMessageBox.critical(win, "TYTcps", "<b>The programming engine is missing or the wrong "
                                            "version.</b><br>TYTcps only works with the "
                                            "dmrconfig-tyt it was built with. Run make in the "
                                            "TYTcps folder.<br><br>%s" % check.problem)
    if wiz is not None and wiz.key_choice == "new":
        win.tabs.setCurrentWidget(win.keys)
        win.keys.new_set()
    if args.file:
        win.open_file(args.file)
    return app.exec()
