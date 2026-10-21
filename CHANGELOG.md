# Changelog

## 0.3.0 (2026-10-20)

Engine dmrconfig-tyt 1.1.280 (JSON api 3).

- **Packages:** a Flatpak and an AppImage, for Ubuntu 22.04 and Linux Mint
  21 or newer ([install](docs/install.md)). Settings shows the one command
  that gives the radio's USB port to your user.
- The USB rule is now `70-tytcps.rules`: under its old number the
  "logged-in user" part of the rule never took effect.
- **Writing keeps each radio's own Radio ID and Name.** One saved file writes
  to every radio; change a radio's ID or name on the General tab if you mean
  to. The Radio ID and Name boxes are gone from the Write window.
- **Simpler menu:** no "New from radio" (the Read button does it) and no
  "Write codeplug file as-is". A write that breaks off still offers to write
  the same codeplug again in full, with the radio's own ID and name.
- **More CPS pages:** Digit Emergency System (with adding and deleting
  systems), DTMF Signaling (systems, encode list, decode entries) and VFO
  Mode (VFO A and B). All 316 files the stock CPS saved in the test corpus
  come out byte for byte.
- **Other radios:** a "Which radios" policy in the README and
  [model notes](docs/models.md). A radio that refuses the key table gets a
  plain message ("it may not be an MD-UV390 Plus") and nothing is written;
  the Keys tab and every key write say only the Plus uses AES keys.
- **Writes go only to the radio you identified.** Another radio on the cable
  is refused before anything is read or sent.
- **Crash handler, log and Save diagnostics:** a plain message, a log in the
  fleet folder, and a diagnostics file checked for keys before it's saved.
- **The PC Programming Password field is gone:** the radio hands the password
  to anyone and doesn't enforce it.
- Voice Announcement offers Chinese as well as English; Channels Hang Time,
  Public Zone and Front Keyboard Lock are marked "Undocumented".
- Documentation: [user guide](docs/guide.md), [FAQ](docs/faq.md) and
  [developer docs](docs/dev/README.md).

## 0.2.0 (2026-10-18)

Engine dmrconfig-tyt 1.1.270.

- The stock CPS's General Setting, Menu Item and Buttons Definitions pages
  (side buttons, One Touch Access, Number Key quick contacts), and the
  channel and scan-list fields the grids don't show, as forms laid out like
  the CPS, with a hover hint on every field.
- The CPS's own files are the reference: a corpus of files the CPS saved
  with one field changed each, and a golden test that the engine writes each
  one byte for byte.
- Passwords and Model Select settable, with a warning before anything that
  could lock the radio.

## 0.1.0 (2026-10-12)

The first version of the program.

- Radio bar: Identify, Read (two reads that must agree), Write codeplug and
  Write keys, with progress and the radio's restart tracked.
- Codeplug grids for channels, zones, scan lists, contacts, group lists and
  messages, with live checks and the engine's errors on the cell.
- A preview of every change before it can be written, byte by byte, by
  record and field.
- Keys tab: import a CPS `.dec` byte for byte, generate or type keys, masked
  display, drafts saved only as new key sets, key rotation.
- Fleet tab and ledger: which key set went to which radio, and when.
- Every write verified; every failure says what happened to the radio.
- A pre-commit check that refuses key material.
