# SPDX-License-Identifier: GPL-3.0-or-later
"""The programming engine: the bundled dmrconfig-tyt fork.

TYTcps never touches USB. Every radio operation is one run of the engine,
whose two-read rule, write verification and ledger ARE the product. TYTcps
reads only the engine's --json events and its exit code; the human text on
stderr goes to the log unchanged and is never parsed.

The contract is src/dmrconfig-tyt/README-tyt-plus.md, "For programs".
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent

EXIT_NAMES = {
    0: "ok", 1: "io_error", 2: "usage", 3: "no_radio", 4: "no_permission",
    5: "busy", 6: "unsupported_model", 7: "reads_disagree",
    8: "write_unverified", 9: "transfer_failed", 10: "keyfile_invalid",
    11: "conf_invalid", 12: "key_slot_empty", 13: "ledger_failed",
    14: "unit_unreadable", 15: "multiple_radios", 16: "image_invalid",
    17: "unit_mismatch", 18: "keys_refused", 255: "failed",
}

# Exit codes a crash or a signal gives, for the log.
SIGNAL_EXIT = -1


@dataclass
class Command:
    """One engine run. `args` exclude the program and --json."""
    args: list
    display: str
    radio: bool = False          # opens the radio: one at a time, no cancel
    stdin: bytes = None
    secret: bool = False         # stdout carries key material: never logged
    label: str = "run"
    links: dict = field(default_factory=dict)   # symlinks made in the run folder
    env: dict = field(default_factory=dict)     # environment overrides for this run


class EventStream:
    """stdout bytes -> JSON events, one object per line."""

    def __init__(self):
        self._buf = b""
        self.events = []
        self.bad_lines = 0

    def feed(self, data):
        self._buf += data
        new = []
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            ev = self._parse(line)
            if ev is not None:
                new.append(ev)
        return new

    def finish(self):
        new = []
        if self._buf.strip():
            ev = self._parse(self._buf)
            if ev is not None:
                new.append(ev)
        self._buf = b""
        return new

    def _parse(self, line):
        line = line.strip()
        if not line:
            return None
        try:
            ev = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.bad_lines += 1
            return None
        if not isinstance(ev, dict) or "event" not in ev:
            self.bad_lines += 1
            return None
        self.events.append(ev)
        return ev


@dataclass
class RunResult:
    command: Command
    exit: int
    events: list
    stderr: str
    seconds: float
    run_dir: Path
    bad_lines: int = 0

    def _of(self, kind):
        return [e for e in self.events if e.get("event") == kind]

    @property
    def result(self):
        r = self._of("result")
        return r[-1] if r else None

    @property
    def errors(self):
        return self._of("error")

    @property
    def warnings(self):
        return self._of("warning")

    @property
    def unit(self):
        u = self._of("unit")
        return u[-1] if u else None

    @property
    def last_phase(self):
        p = self._of("phase")
        return p[-1].get("phase") if p else None

    def reached(self, *phases):
        """Whether any of these phases started."""
        return any(e.get("phase") in phases for e in self._of("phase"))

    @property
    def a207(self):
        """The unit this run talked to, from whichever event says so."""
        for e in [self.result or {}, self.error or {}, self.unit or {}]:
            if e.get("a207"):
                return e["a207"].lower()
        return None

    @property
    def ok(self):
        r = self.result
        return self.exit == 0 and r is not None and r.get("ok") is True

    @property
    def code(self):
        if self.errors:
            return self.errors[0].get("code", "failed")
        if self.exit == 0 and self.result is None:
            return "no_result"
        return EXIT_NAMES.get(self.exit, "failed")

    @property
    def error(self):
        """The first error event, or one made from the exit code."""
        if self.errors:
            return self.errors[0]
        if self.exit == 0 and self.result is not None:
            return None
        return {"event": "error", "code": self.code, "exit": self.exit,
                "radio": "unknown",
                "message": "The engine stopped (exit %d) without saying why." % self.exit}

    @property
    def radio_state(self):
        e = self.error
        return e.get("radio", "unknown") if e else None


@dataclass
class EngineCheck:
    ok: bool
    info: dict
    problem: str = ""


class Shortener:
    """Paths for the log: <tmp>, <fleet>, ~."""

    def __init__(self, runtime=None, fleet=None):
        self.pairs = []
        if runtime:
            self.pairs.append((str(runtime), "<tmp>"))
        if fleet:
            self.pairs.append((str(fleet), "<fleet>"))
        self.pairs.append((str(Path.home()), "~"))

    def __call__(self, text):
        text = str(text)
        for prefix, short in self.pairs:
            if text == prefix or text.startswith(prefix + os.sep):
                return short + text[len(prefix):]
        return text


def load_pin():
    with open(PACKAGE / "engine_pin.json") as f:
        return json.load(f)


def locate_engine():
    """The bundled engine. TYTCPS_ENGINE may point elsewhere for development;
    whatever it names still has to pass the version check."""
    env = os.environ.get("TYTCPS_ENGINE")
    if env:
        return Path(env)
    return PACKAGE / "libexec" / "dmrconfig-tyt"


class Engine:
    def __init__(self, binary, fleet, runtime):
        self.binary = Path(binary)
        self.fleet = Path(fleet)
        self.runtime = runtime
        self.short = Shortener(runtime.path, self.fleet)
        self.version = {}
        self.listeners = []          # called with every RunResult, any thread

    # -- version check (F12, E-F1) ------------------------------------------

    def check(self):
        pin = load_pin()
        expect = "dmrconfig-tyt %s (%s %s)" % (pin["version"], pin["branch"], pin["commit"])
        if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
            return EngineCheck(False, {}, "not found at %s; expected %s. Run make in the TYTcps folder."
                               % (self.short(self.binary), expect))
        try:
            p = subprocess.run([str(self.binary), "--version", "--json"], capture_output=True,
                               timeout=10, env=self.env())
        except (OSError, subprocess.SubprocessError) as e:
            return EngineCheck(False, {}, "could not run %s: %s" % (self.short(self.binary), e))
        stream = EventStream()
        stream.feed(p.stdout)
        stream.finish()
        res = [e for e in stream.events if e.get("event") == "result"]
        if p.returncode != 0 or not res:
            return EngineCheck(False, {}, "%s did not answer --version --json, so it is not "
                               "dmrconfig-tyt; expected %s" % (self.short(self.binary), expect))
        info = res[-1]
        self.version = info
        found = "%s %s (%s %s)" % (info.get("program"), info.get("version"),
                                   info.get("branch"), info.get("commit"))
        for k in ("program", "version", "branch", "commit", "api"):
            if info.get(k) != pin[k]:
                return EngineCheck(False, info, "expected %s, found %s" % (expect, found))
        return EngineCheck(True, info, "")

    # -- running -------------------------------------------------------------

    def env(self, cmd=None):
        env = dict(os.environ)
        env["TYT_STATE_DIR"] = str(self.fleet)
        if cmd is not None:
            env.update(cmd.env)
        return env

    def prepare(self, cmd):
        """(argv, run folder) for a command; the folder is new and private."""
        run_dir = self.runtime.new_run(cmd.label)
        for name, target in cmd.links.items():
            os.symlink(target, run_dir / name)
        argv = [str(self.binary), "--json"] + [str(a) for a in cmd.args]
        return argv, run_dir

    def run(self, cmd, timeout=None):
        """Run synchronously. For offline commands and tests; the GUI runs
        radio commands through ui.jobs.Job so the window stays live."""
        argv, run_dir = self.prepare(cmd)
        t0 = time.monotonic()
        p = subprocess.run(argv, cwd=run_dir, env=self.env(cmd), input=cmd.stdin,
                           capture_output=True, timeout=timeout)
        stream = EventStream()
        stream.feed(p.stdout)
        stream.finish()
        res = RunResult(cmd, p.returncode if p.returncode >= 0 else SIGNAL_EXIT,
                        stream.events, p.stderr.decode("utf-8", "replace"),
                        time.monotonic() - t0, run_dir, stream.bad_lines)
        self.notify(res)
        return res

    def notify(self, res):
        for fn in list(self.listeners):
            fn(res)
