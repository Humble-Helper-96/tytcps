# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared state of one TYTcps window: the engine, the fleet folder, the open
codeplug, and the signals the tabs listen to."""

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from ..backend import keys as keysmod
from ..backend import paths


class Context(QObject):
    fleet_changed = pyqtSignal()       # ledger, roster or key-set files changed
    keyset_changed = pyqtSignal()      # the current key set changed
    codeplug_changed = pyqtSignal()    # another codeplug was opened (or closed)
    doc_edited = pyqtSignal()          # the open codeplug's text changed
    form_errors_changed = pyqtSignal() # a form field's refused input came or went
    radio_changed = pyqtSignal()       # the radio bar's identity changed
    goto_cell = pyqtSignal(str, int, int)   # table kind, row uid, column

    def __init__(self, engine, fleet, runner, runtime, engine_check):
        super().__init__()
        self.engine = engine
        self.fleet = fleet
        self.runner = runner
        self.runtime = runtime
        self.engine_check = engine_check
        self.codeplug = None
        self.applog = None             # backend.applog.AppLog (set by app.py)
        self.crash = None              # crash.CrashHandler (set by app.py)
        self.unit = None               # identity of the attached radio (dict)
        self._unknown_session = set()  # E-K4 marks made this session
        self._known_session = set()    # ...and cleared this session
        self.settings = QSettings(str(paths.settings_file()), QSettings.Format.IniFormat)
        self._current_sha = None
        self._current_slots = None
        self.refresh_keyset()

    # -- units whose key write broke off (E-K4), kept in the roster's flags ---

    @property
    def keys_unknown(self):
        """Roster flags plus what this session knows: a mark that couldn't be
        saved is still shown until TYTcps closes."""
        try:
            saved = self.fleet.keys_unknown()
        except (OSError, ValueError):
            saved = set()
        return (saved | self._unknown_session) - self._known_session

    def mark_keys_unknown(self, a207, unknown):
        """Returns False if the mark couldn't be saved in the fleet folder."""
        a207 = a207.lower()
        if unknown:
            self._unknown_session.add(a207)
            self._known_session.discard(a207)
        else:
            self._known_session.add(a207)
            self._unknown_session.discard(a207)
        try:
            self.fleet.set_keys_unknown(a207, unknown)
            return True
        except (OSError, ValueError):
            return False

    def keys_status(self, a207, ledger=None):
        return self.fleet.keys_status(a207, self.current_sha, ledger, self.keys_unknown)

    # -- the current key set ----------------------------------------------------

    def refresh_keyset(self):
        """Re-read current-keyset; cache its SHA256 and slot types/names."""
        self._current_sha = None
        self._current_slots = None
        p = self.fleet.current_path()
        if p and p.is_file():
            self._current_sha = keysmod.sha256_file(p)

    @property
    def current_name(self):
        return self.fleet.current_name()

    @property
    def current_sha(self):
        return self._current_sha

    @property
    def current_path(self):
        p = self.fleet.current_path()
        return p if p and p.is_file() else None

    def current_slots(self):
        """[(slot, type, name, filled)] of the current set, no key bytes kept.
        Read once per change through `keys show`."""
        if self._current_slots is None and self.current_path:
            try:
                ks = keysmod.load(self.engine, self.current_path)
            except keysmod.SaveError:
                return []
            self._current_slots = [(s.slot, s.type, s.name, s.filled) for s in ks.slots]
            del ks
        return self._current_slots or []

    def setting(self, key, default=None, type=str):
        v = self.settings.value(key, default)
        try:
            return type(v) if v is not None else default
        except (TypeError, ValueError):
            return default
