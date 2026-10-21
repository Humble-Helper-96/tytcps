# SPDX-License-Identifier: GPL-3.0-or-later
"""The Details drawer: one block per engine run, its stderr,
and its exit. The engine's human text is shown here unchanged and nowhere
parsed. Key hex never appears: stdout (where `keys show` puts keys) is
never logged, and keys reach `keys set` on stdin."""

import re
import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontDatabase
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QToolButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

A207 = re.compile(r"\b([0-9a-fA-F]{4})[0-9a-fA-F]{24}([0-9a-fA-F]{4})\b")


def truncate_units(text):
    return A207.sub(lambda m: "%s…%s" % (m.group(1), m.group(2)), text)


class RunBlock:
    def __init__(self, item, display, radio):
        self.item = item
        self.display = display
        self.radio = radio
        self.lines = []
        self.partial = ""
        self.exit = None
        self.seconds = None
        self.when = time.strftime("%H:%M:%S")

    def text(self):
        out = ["$ " + self.display] + self.lines + ([self.partial] if self.partial else [])
        if self.exit is not None:
            out.append("exit %d · %.1f s" % (self.exit, self.seconds))
        return "\n".join(out)


class Drawer(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, parent=None, logfile=None, applog=None):
        super().__init__(parent)
        self.blocks = []
        self.logfile = logfile
        self.applog = applog          # <fleet>/logs/tytcps.log
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(8, 2, 8, 2)
        self.toggle = QToolButton()
        self.toggle.setText("Details (log)")
        self.toggle.setCheckable(True)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setAutoRaise(True)
        self.toggle.toggled.connect(self._toggled)
        head.addWidget(self.toggle)
        head.addStretch(1)
        self.copy = QToolButton()
        self.copy.setText("Copy diagnostics")
        self.copy.setAutoRaise(True)
        head.addWidget(self.copy)
        head.addSpacing(12)
        self.status = QLabel("Status: Ready")
        head.addWidget(self.status)
        lay.addLayout(head)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(1)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.tree.setFont(mono)
        self.tree.setUniformRowHeights(True)
        self.tree.setVisible(False)
        self.tree.setMinimumHeight(160)
        lay.addWidget(self.tree)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def _toggled(self, on):
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.tree.setVisible(on)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Expanding if on else QSizePolicy.Policy.Maximum)
        self.toggled.emit(on)

    def set_status(self, text):
        self.status.setText("Status: " + text)

    def open(self):
        self.toggle.setChecked(True)

    # -- blocks --------------------------------------------------------------

    def start(self, cmd):
        item = QTreeWidgetItem(["$ " + cmd.display])
        f = item.font(0)
        f.setBold(True)
        item.setFont(0, f)
        if not cmd.radio:
            item.setForeground(0, QBrush(QColor("#777")))
        self.tree.addTopLevelItem(item)
        block = RunBlock(item, cmd.display, cmd.radio)
        self.blocks.append(block)
        if cmd.radio:
            item.setExpanded(True)
            self.tree.scrollToItem(item)
        return block

    def append(self, block, text):
        text = block.partial + text
        parts = text.split("\n")
        block.partial = parts.pop()
        for line in parts:
            block.lines.append(line)
            QTreeWidgetItem(block.item, [line])
        if block.radio:
            self.tree.scrollToItem(block.item.child(block.item.childCount() - 1)
                                   if block.item.childCount() else block.item)

    def finish(self, block, res):
        if block.partial:
            block.lines.append(block.partial)
            QTreeWidgetItem(block.item, [block.partial])
            block.partial = ""
        if res.bad_lines:
            note = "(%d line%s of the engine's output couldn't be read)" % (
                res.bad_lines, "" if res.bad_lines == 1 else "s")
            block.lines.append(note)
            QTreeWidgetItem(block.item, [note])
        block.exit = res.exit
        block.seconds = res.seconds
        end = QTreeWidgetItem(block.item, ["exit %d · %.1f s" % (res.exit, res.seconds)])
        block.item.setText(0, "$ %s    (exit %d · %.1f s)" % (block.display, res.exit, res.seconds))
        if res.exit != 0:
            end.setForeground(0, QBrush(QColor("#c0392b")))
            block.item.setForeground(0, QBrush(QColor("#c0392b")))
        # Radio runs and failures; previews would bury them.
        if self.applog is not None and (block.radio or res.exit != 0):
            self.applog.entry("run", block.text())
        if self.logfile:
            try:
                with open(self.logfile, "a", encoding="utf-8") as f:
                    f.write("[%s]\n%s\n\n" % (block.when, block.text()))
            except OSError:
                pass

    def add_completed(self, res):
        """A run made synchronously (offline): log it whole."""
        block = self.start(res.command)
        if res.stderr:
            self.append(block, res.stderr if res.stderr.endswith("\n") else res.stderr + "\n")
        self.finish(block, res)
        if not res.command.radio:
            block.item.setExpanded(False)
        return block

    def reveal(self, block):
        """Open the drawer at a failing run (7.12)."""
        self.open()
        block.item.setExpanded(True)
        self.tree.scrollToItem(block.item, QTreeWidget.ScrollHint.PositionAtTop)
        self.tree.setCurrentItem(block.item)

    def last_text(self, n=3, radio_only=False, raw=False):
        """The last n runs' text, units shortened unless raw (diagnostics
        scan the raw text for keys first: shortening could hide one)."""
        blocks = [b for b in self.blocks if b.radio or not radio_only]
        text = "\n\n".join(b.text() for b in blocks[-n:])
        return text if raw else truncate_units(text)
