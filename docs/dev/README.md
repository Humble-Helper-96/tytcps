# TYTcps for developers

## How it fits together

TYTcps is two programs:

- **The engine**, `engine/dmrconfig-tyt`: a C fork of
  [dmrconfig](https://github.com/sergev/dmrconfig), bundled as a git subtree
  and built into `tytcps/libexec/`. It does everything that touches a radio
  or a codeplug's bytes: identify, read (twice), write (verified), the key
  table, the ledger, the codeplug as text ("conf") and back, and `diff`. Its
  reference is `engine/dmrconfig-tyt/README-tyt-plus.md`.
- **The GUI**, `tytcps/`: Python and PyQt6. It never opens USB and never
  edits image bytes. It edits the engine's conf text and runs the engine once
  per operation.

The GUI talks to the engine only through command lines and `--json` output:
one JSON event per line (`phase`, `progress`, `warning`, `error`, `result`),
plus an exit code that names the failure. `tytcps/engine_pin.json` names the
exact engine version, branch, commit and JSON api the GUI was built for, and
TYTcps refuses to start with any other.

Main pieces of the GUI:

| Module | What it does |
|---|---|
| `backend/conf.py` | Parses the conf text into scalars and tables and renders it back, with every untouched line verbatim |
| `backend/codeplug.py` | An open codeplug: its base image, the conf, the preview (an offline engine apply and `diff`) |
| `backend/cpsfields.py` | The stock CPS's pages field by field: label, kind, range, hover hint |
| `backend/engine.py`, `ui/jobs.py` | Running the engine and reading its events |
| `backend/radio.py`, `backend/keys.py`, `backend/fleet.py` | Command lines for radio and key operations; the fleet folder |
| `ui/` | The windows: radio bar, grids, CPS forms, write dialogs, Keys and Fleet tabs |

## Rules the code keeps

- **Absent means untouched.** A conf line, table or row that isn't there
  leaves those bytes as the image has them. That's how a write keeps each
  radio's own Radio ID and Name (the GUI leaves those lines out), and how an
  older conf keeps working.
- **Written only on change.** The engine writes a field only when its value
  prints differently, so a value the CPS has no word for survives as
  `raw:0x…`.
- **Two reads, verified writes.** Nothing is written from a single read; every
  write is read back and compared.
- **No key material in the repository.** `tools/check-key-material.py` is
  the pre-commit hook (`make hooks`); see [CONTRIBUTING](../../CONTRIBUTING.md).

## Reference

- [protocol.md](protocol.md): how the radio talks over USB, the key table
  and the `.dec` file.
- [field-map.md](field-map.md): every stock-CPS field's place in the
  codeplug image.
- [testing.md](testing.md): the test suites, the CPS corpus and the golden
  test, and how to add a CPS field.
