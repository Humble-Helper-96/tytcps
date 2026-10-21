# SPDX-License-Identifier: GPL-3.0-or-later
"""First run and Settings (7.11)."""

import datetime
import os
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
                             QWidget, QWizard, QWizardPage)

from ..backend import keys as K
from ..backend import paths
from ..backend import usb
from ..backend.engine import PACKAGE

RULE_NAME = "70-tytcps.rules"


def bundled_rule():
    for p in (PACKAGE / "data" / RULE_NAME, PACKAGE.parent / "data" / RULE_NAME):
        if p.is_file():
            return p
    return None


def install_rule_commands(rule):
    return ["pkexec install -m 644 %s /etc/udev/rules.d/%s" % (rule, RULE_NAME),
            "pkexec udevadm control --reload",
            "pkexec udevadm trigger --subsystem-match=usb --attr-match=idVendor=0483"]


def install_rule(parent):
    """The only root action TYTcps has, and never automatic (7.11)."""
    rule = bundled_rule()
    if rule is None:
        QMessageBox.warning(parent, "TYTcps", "The USB rule file isn't in this installation.")
        return False
    for cmd in install_rule_commands(rule):
        try:
            r = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            QMessageBox.warning(parent, "TYTcps", "Couldn't run %s: %s" % (cmd.split()[1], e))
            return False
        if r.returncode != 0:
            QMessageBox.warning(parent, "TYTcps", "%s failed: %s" % (cmd, (r.stderr or "").strip()))
            return False
    QMessageBox.information(parent, "TYTcps", "The USB rule is installed. Unplug the radio and "
                            "plug it back in.")
    return True


def rule_line():
    """The rule itself, from the bundled file."""
    rule = bundled_rule()
    if rule is not None:
        for line in rule.read_text().splitlines():
            if line.strip() and not line.startswith("#"):
                return line.strip()
    return ('SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="df11", '
            'MODE="0660", GROUP="plugdev", TAG+="uaccess"')


def rule_file_unreachable():
    """A Flatpak's files aren't at a path the computer can see, and an
    AppImage's are on a mount that root can't read, so from either the rule
    goes in by its text and the Install button (pkexec) is hidden."""
    return paths.in_flatpak() or bool(os.environ.get("APPIMAGE"))


def terminal_rule_commands():
    """What to type in a terminal."""
    if rule_file_unreachable():
        cmds = ["echo '%s' | sudo tee /etc/udev/rules.d/%s" % (rule_line(), RULE_NAME)]
        cmds += [c.replace("pkexec ", "sudo ") for c in install_rule_commands("-")[1:]]
        return cmds
    rule = bundled_rule() or "data/%s" % RULE_NAME
    return [c.replace("pkexec ", "sudo ") for c in install_rule_commands(rule)]


def show_rule_commands(parent):
    text = "\n".join(terminal_rule_commands())
    box = QMessageBox(parent)
    box.setWindowTitle("USB access rule")
    box.setText("Run these in a terminal:")
    box.setInformativeText("<pre>%s</pre>" % text)
    copy = box.addButton("Copy", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() == copy:
        QGuiApplication.clipboard().setText(text)


def checks(engine_check):
    """[(name, ok, text, fix)] for the first-run and Settings pages."""
    out = []
    if engine_check.ok:
        v = engine_check.info
        out.append(("Programming engine", True, "dmrconfig-tyt %s (%s %s)" % (
            v.get("version"), v.get("branch"), v.get("commit")), None))
    else:
        out.append(("Programming engine", False, "The programming engine is missing or the wrong "
                                                 "version: %s." % engine_check.problem, "E-F1"))
    rule = usb.find_rule()
    if rule:
        out.append(("USB access rule", True, "udev rule found (%s)" % rule.path, None))
    else:
        out.append(("USB access rule", False, "Your user needs permission to use the programming "
                                              "cable.", "E-U1"))
    if rule and rule.group and not (rule.world or rule.uaccess):
        if rule.group in usb.session_groups():
            out.append(("Group membership", True, "you are in %s" % rule.group, None))
        elif rule.group in usb.user_groups():
            out.append(("Group membership", False, "You were added to %s, but this login "
                        "doesn't have it yet. Log out and back in." % rule.group, "E-U2"))
        else:
            out.append(("Group membership", False, "Your account isn't in the \"%s\" group yet. "
                        "Add it with: sudo usermod -aG %s %s, then log out and back in." % (
                            rule.group, rule.group, os.environ.get("USER", "$USER")), "E-U2"))
    elif rule:
        out.append(("Group membership", True, "not needed: the rule gives the logged-in user "
                    "access", None))
    return out


class FirstRun(QWizard):
    def __init__(self, engine_check, default_folder, engine_factory, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to TYTcps")
        self.setMinimumSize(640, 460)
        self.engine_factory = engine_factory
        self.folder = Path(default_folder)
        self.dec_path = None
        self.key_choice = "later"
        self.engine_check = engine_check

        p1 = QWizardPage()
        p1.setTitle("Welcome")
        l1 = QVBoxLayout(p1)
        t = QLabel("TYTcps programs TYT MD-UV390 Plus radios on Linux.<br><br>Privacy keys can't "
                   "be read back from these radios, so TYTcps keeps a record of which key set "
                   "each radio was given.")
        t.setWordWrap(True)
        l1.addWidget(t)
        self.addPage(p1)

        p2 = QWizardPage()
        p2.setTitle("Checks")
        l2 = QVBoxLayout(p2)
        failed = False
        for name, ok, text, fix in checks(engine_check):
            row = QHBoxLayout()
            mark = QLabel("✔" if ok else "✖")
            mark.setStyleSheet("color:%s; font-size:14pt" % ("#1e8449" if ok else "#c0392b"))
            row.addWidget(mark)
            lab = QLabel("<b>%s</b>: %s" % (name, text))
            lab.setWordWrap(True)
            row.addWidget(lab, 1)
            if fix == "E-U1":
                if not rule_file_unreachable():
                    b = QPushButton("Install rule…")
                    b.clicked.connect(lambda: install_rule(self))
                    row.addWidget(b)
                b2 = QPushButton("Show command")
                b2.clicked.connect(lambda: show_rule_commands(self))
                row.addWidget(b2)
            l2.addLayout(row)
            failed = failed or not ok
        if failed:
            s = QLabel("You can use TYTcps without a radio until these are fixed.")
            s.setStyleSheet("color:#b9770e")
            l2.addWidget(s)
        l2.addStretch(1)
        self.addPage(p2)

        p3 = QWizardPage()
        p3.setTitle("Fleet folder")
        l3 = QVBoxLayout(p3)
        row = QHBoxLayout()
        self.folder_label = QLabel(str(self.folder))
        b = QPushButton("Change…")
        b.clicked.connect(self._change_folder)
        row.addWidget(QLabel("Fleet folder:"))
        row.addWidget(self.folder_label, 1)
        row.addWidget(b)
        l3.addLayout(row)
        t3 = QLabel("Key sets, the key ledger and the radio list are kept here, readable only by "
                    "you.")
        t3.setWordWrap(True)
        l3.addWidget(t3)
        l3.addStretch(1)
        self.addPage(p3)

        p4 = QWizardPage()
        p4.setTitle("Keys (optional)")
        l4 = QVBoxLayout(p4)
        self.r_dec = QRadioButton("I have a CPS key file (.dec)")
        self.r_new = QRadioButton("Create a new key set now")
        self.r_later = QRadioButton("Later")
        self.r_later.setChecked(True)
        grp = QButtonGroup(p4)
        for r in (self.r_dec, self.r_new, self.r_later):
            grp.addButton(r)
        row = QHBoxLayout()
        row.addWidget(self.r_dec)
        self.dec_label = QLabel("")
        bd = QPushButton("Choose…")
        bd.clicked.connect(self._choose_dec)
        row.addWidget(self.dec_label, 1)
        row.addWidget(bd)
        l4.addLayout(row)
        n = QLabel("It becomes the current key set. The file is copied unchanged.")
        n.setWordWrap(True)
        n.setStyleSheet("color:#777; margin-left:24px")
        l4.addWidget(n)
        l4.addWidget(self.r_new)
        l4.addWidget(self.r_later)
        l4.addStretch(1)
        self.addPage(p4)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Finish")

    def _change_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Fleet folder", str(self.folder.parent))
        if d:
            p = Path(d)
            if p.exists() and any(p.iterdir()) and not (p / "ledger.tsv").exists():
                p = p / "tytcps"
            self.folder = p
            self.folder_label.setText(str(p))

    def _choose_dec(self):
        p, _ = QFileDialog.getOpenFileName(self, "CPS key file", str(Path.home()),
                                           "CPS key files (*.dec);;All files (*)")
        if p:
            self.dec_path = Path(p)
            self.dec_label.setText(self.dec_path.name)
            self.r_dec.setChecked(True)

    def accept(self):
        if self.r_dec.isChecked() and self.dec_path is None:
            QMessageBox.information(self, "TYTcps", "Choose the key file, or pick Later.")
            return
        self.key_choice = "dec" if self.r_dec.isChecked() else "new" if self.r_new.isChecked() else "later"
        super().accept()


def import_into_fleet(engine, fleet, dec_path):
    """Flow 1 step 4: a CPS .dec saved as fleet-<today>.dec and made current."""
    ks = K.import_file(engine, dec_path)
    name, sha = K.save_new(engine, ks, fleet.keys_dir)
    fleet.set_current(name)
    return name, sha


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Settings")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel(str(ctx.fleet.folder)), 1)
        b = QPushButton("Open folder")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ctx.fleet.folder))))
        row.addWidget(b)
        form.addRow("Fleet folder:", row)
        row2 = QHBoxLayout()
        self.cp_dir = QLabel(ctx.setting("files/codeplug_dir", ""))
        b2 = QPushButton("Change…")
        b2.clicked.connect(self._cp_dir)
        row2.addWidget(self.cp_dir, 1)
        row2.addWidget(b2)
        form.addRow("Codeplug files:", row2)
        self.timeout = QComboBox()
        for s in (10, 30, 60):
            self.timeout.addItem("%d s" % s, s)
        cur = ctx.setting("keys/reveal_seconds", 30, int)
        self.timeout.setCurrentIndex(max(0, self.timeout.findData(cur)))
        self.timeout.currentIndexChanged.connect(
            lambda: ctx.settings.setValue("keys/reveal_seconds", self.timeout.currentData()))
        form.addRow("Key reveal timeout:", self.timeout)
        ec = ctx.engine_check
        eng = QLabel(("dmrconfig-tyt %s (%s %s)" % (ec.info.get("version"), ec.info.get("branch"),
                                                    ec.info.get("commit")) if ec.ok
                      else "<span style='color:#c0392b'>%s</span>" % ec.problem)
                     + "<br><span style='color:#777'>%s</span>" % ctx.engine.binary)
        eng.setWordWrap(True)
        form.addRow("Programming engine:", eng)
        lay.addLayout(form)

        lay.addWidget(QLabel("<b>USB access</b>"))
        for name, ok, text, fix in checks(ec)[1:]:
            l = QLabel("%s %s: %s" % ("✔" if ok else "✖", name, text))
            l.setWordWrap(True)
            lay.addWidget(l)
        rr = QHBoxLayout()
        bi = QPushButton("Install rule…")
        bi.clicked.connect(lambda: install_rule(self))
        bs = QPushButton("Show command")
        bs.clicked.connect(lambda: show_rule_commands(self))
        bi.setVisible(not rule_file_unreachable())
        rr.addWidget(bi)
        rr.addWidget(bs)
        rr.addStretch(1)
        lay.addLayout(rr)

        lay.addWidget(QLabel("<b>Old key sets</b> (not current). They're never deleted "
                             "automatically."))
        self.retired = QListWidget()
        lay.addWidget(self.retired)
        bdel = QPushButton("Delete…")
        bdel.clicked.connect(self._delete)
        lay.addWidget(bdel, 0, Qt.AlignmentFlag.AlignLeft)
        self._fill_retired()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _cp_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Default folder for codeplug files",
                                             self.cp_dir.text() or str(Path.home()))
        if d:
            self.ctx.settings.setValue("files/codeplug_dir", d)
            self.cp_dir.setText(d)

    def _fill_retired(self):
        self.retired.clear()
        ledger = self.ctx.fleet.ledger()
        cur = self.ctx.current_name
        for name, mtime in self.ctx.fleet.keysets():
            if name == cur:
                continue
            sha = self.ctx.fleet.keyset_sha(name)
            last = [l.when for l in ledger if l.sha256 == sha]
            it = QListWidgetItem("%s   last written to a radio: %s" % (name, last[-1] if last else "never"))
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.retired.addItem(it)

    def _delete(self):
        it = self.retired.currentItem()
        if not it:
            return
        name = it.data(Qt.ItemDataRole.UserRole)
        if QMessageBox.warning(
                self, "TYTcps", "Delete %s? Radios that have this key set keep it. This can't be "
                                "undone." % name,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            (self.ctx.fleet.keys_dir / name).unlink()
        except OSError as e:
            QMessageBox.warning(self, "TYTcps", "Couldn't delete it: %s" % e.strerror)
        self._fill_retired()
        self.ctx.fleet_changed.emit()
