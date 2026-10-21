# SPDX-License-Identifier: GPL-3.0-or-later
"""The log file in the fleet folder: <fleet>/logs/tytcps.log.

It holds what the Details drawer shows for every engine run (the engine's
stderr, never its stdout, so never key material), the start of each session,
and anything that went wrong inside TYTcps itself. It is what a bug report
needs, and Save diagnostics puts its end in the bundle. Rotated at 1 MB to
tytcps.log.1. A log that can't be written is skipped: logging never gets in
the way of a radio operation.
"""

import datetime
import os
import threading
from pathlib import Path

NAME = "tytcps.log"
MAX_BYTES = 1024 * 1024


def stamp():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S%z")


class AppLog:
    def __init__(self, fleet_folder):
        self.dir = Path(fleet_folder) / "logs"
        self.path = self.dir / NAME
        self.old = self.dir / (NAME + ".1")
        self._lock = threading.Lock()
        self.failed = False          # the last write didn't happen

    def write(self, text):
        """Append text; False if it couldn't be written (never raises)."""
        if not text.endswith("\n"):
            text += "\n"
        try:
            with self._lock:
                self.dir.mkdir(mode=0o700, exist_ok=True)
                try:
                    if self.path.stat().st_size >= MAX_BYTES:
                        os.replace(self.path, self.old)
                except FileNotFoundError:
                    pass
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8", errors="replace") as f:
                    f.write(text)
        except (OSError, ValueError):
            self.failed = True
            return False
        self.failed = False
        return True

    def entry(self, title, body=""):
        """[when] title, then the body, then a blank line."""
        text = "[%s] %s\n" % (stamp(), title)
        if body:
            text += body if body.endswith("\n") else body + "\n"
        return self.write(text + "\n")

    def tail(self, max_bytes=200_000):
        """The end of the log, reaching into the rotated file when short."""
        out = b""
        for p in (self.old, self.path):
            try:
                out += p.read_bytes()
            except OSError:
                pass
        out = out[-max_bytes:]
        return out.decode("utf-8", "replace")
