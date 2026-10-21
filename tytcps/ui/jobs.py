# SPDX-License-Identifier: GPL-3.0-or-later
"""Running the engine from the GUI.

Radio commands run as a QProcess so their events (phase, progress, unit)
arrive live. Only one runs at a time, and it cannot be cancelled: killing a
write mid-flash leaves an unknown codeplug. Offline commands
(preview, open, key-set saves) run on a worker thread alongside it.
"""

import time

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment, QRunnable, QThreadPool, QTimer, pyqtSignal

from ..backend.engine import EXIT_NAMES, EventStream, RunResult, SIGNAL_EXIT


class Job(QObject):
    got_event = pyqtSignal(dict)        # not "event": that is QObject.event()
    stderr = pyqtSignal(str)
    finished = pyqtSignal(object)            # RunResult

    def __init__(self, engine, cmd, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.cmd = cmd
        self.stream = EventStream()
        self._err = []
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._out)
        self.proc.readyReadStandardError.connect(self._errread)
        self.proc.finished.connect(self._done)
        self.proc.errorOccurred.connect(self._failed)
        self.t0 = 0.0
        self.run_dir = None
        self._finished = False

    def start(self):
        argv, self.run_dir = self.engine.prepare(self.cmd)
        env = QProcessEnvironment()
        for k, v in self.engine.env(self.cmd).items():
            env.insert(k, v)
        self.proc.setProcessEnvironment(env)
        self.proc.setWorkingDirectory(str(self.run_dir))
        self.proc.setProgram(argv[0])
        self.proc.setArguments(argv[1:])
        self.t0 = time.monotonic()
        self.proc.start()
        if self.cmd.stdin is not None:
            self.proc.write(self.cmd.stdin)
        self.proc.closeWriteChannel()

    def _out(self):
        for ev in self.stream.feed(bytes(self.proc.readAllStandardOutput())):
            self.got_event.emit(ev)

    def _errread(self):
        text = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
        self._err.append(text)
        self.stderr.emit(text)

    def _failed(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            self._finish(127)

    def _done(self, code, status):
        self._out()
        self._errread()
        for ev in self.stream.finish():
            self.got_event.emit(ev)
        if status == QProcess.ExitStatus.CrashExit:
            code = SIGNAL_EXIT
        self._finish(code)

    def _finish(self, code):
        if self._finished:
            return
        self._finished = True
        res = RunResult(self.cmd, code, self.stream.events, "".join(self._err),
                        time.monotonic() - self.t0, self.run_dir, self.stream.bad_lines)
        self.finished.emit(res)


class _Bridge(QObject):
    done = pyqtSignal(object, object)


class _Worker(QRunnable):
    def __init__(self, fn, bridge):
        super().__init__()
        self.fn = fn
        self.bridge = bridge

    def run(self):
        try:
            r = self.fn()
        except Exception as e:          # handed to the caller, never swallowed
            self.bridge.done.emit(None, e)
            return
        self.bridge.done.emit(r, None)


class JobRunner(QObject):
    """One radio job at a time; offline work on a thread pool."""

    radio_started = pyqtSignal(object)        # Command
    radio_event = pyqtSignal(dict)
    radio_stderr = pyqtSignal(str)
    radio_finished = pyqtSignal(object)       # RunResult, after any retry
    retrying = pyqtSignal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.job = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._bridges = set()
        self.last_radio_end = 0.0
        self.retry_pending = False

    @property
    def busy(self):
        """A radio run is going, or one is waiting to be retried (E-R2)."""
        return self.job is not None or self.retry_pending

    def run_radio(self, cmd, on_done=None, _retry=True):
        """Start a radio run. Returns the Job, or None if one is already
        running (callers check `busy` first; this is the backstop)."""
        if self.job is not None or (self.retry_pending and _retry):
            return None
        self.retry_pending = False
        job = Job(self.engine, cmd, self)
        self.job = job
        job.got_event.connect(self.radio_event)
        job.stderr.connect(self.radio_stderr)

        def finished(res):
            self.job = None
            job.deleteLater()
            recent = time.monotonic() - self.last_radio_end < 10.0
            self.last_radio_end = time.monotonic()
            # E-R2: "no radio" right after a previous run is usually the
            # radio still restarting. Wait 5 s and try once more, for
            # identify and reads only: a write is never re-run unasked, since
            # by then a different radio could be on the cable.
            if _retry and res.code == "no_radio" and recent and not cmd.label.startswith("write"):
                self.retry_pending = True
                self.radio_finished.emit(res)
                self.retrying.emit()
                QTimer.singleShot(5000, lambda: self.run_radio(cmd, on_done, _retry=False))
                return
            self.radio_finished.emit(res)
            if on_done:
                on_done(res)

        job.finished.connect(finished)
        self.radio_started.emit(cmd)
        job.start()
        return job

    def run_offline(self, fn, on_done):
        """fn() on a worker thread; on_done(result, exception) on this one."""
        bridge = _Bridge()
        self._bridges.add(bridge)

        def done(r, e):
            self._bridges.discard(bridge)
            on_done(r, e)
        bridge.done.connect(done)
        self.pool.start(_Worker(fn, bridge))


def exit_name(code):
    return EXIT_NAMES.get(code, "exit %d" % code)
