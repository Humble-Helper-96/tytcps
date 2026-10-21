# Third-party software

## Bundled

**dmrconfig** by Serge Vakulenko (KK6ABQ), BSD 3-Clause License.
`engine/dmrconfig-tyt` is a fork of dmrconfig and keeps its license and
copyright notices; see `engine/dmrconfig-tyt/LICENSE`. The fork's additions
(the key table, the CPS pages, the ledger, `--json`, the safety checks) are
under the same BSD 3-Clause License.

## Linked by the engine

**libusb-1.0**, GNU Lesser General Public License 2.1 or later. The engine's
Makefile links it statically when the static library is installed, and
dynamically otherwise. The engine's full source and Makefile are part of this
repository, so it can always be rebuilt against another libusb.

**libudev** (systemd), GNU Lesser General Public License 2.1 or later, linked
dynamically.

## Used, not bundled

- **Python** (Python Software Foundation License).
- **PyQt6** (Riverbank Computing, GPL v3) and **Qt 6** (The Qt Company,
  LGPL v3), installed from your distribution. TYTcps is GPL v3 or later, which
  PyQt6's GPL license requires.
- **AutoHotkey v2** (GPL v2) runs `tools/cps-corpus/cps-variants.ahk` when
  building a test corpus; it isn't needed to use TYTcps.

## Consulted as references (no code copied)

The codeplug field map was cross-checked against **qdmr** (Hannes Matuschek,
GPL v3), **md380tools** (Travis Goodspeed and contributors) and **editcp**
(Dale Farnsworth), and against the stock TYT CPS's behaviour. Facts were
taken from them, not code.
