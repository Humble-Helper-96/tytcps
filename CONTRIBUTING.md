# Contributing to TYTcps

Thanks for helping. A few rules keep radios and keys safe; please read them
before your first change.

## Getting started

    make            # builds the bundled engine
    make test       # everything offline: no radio is ever touched
    make hooks      # installs the pre-commit check (do this first)

How the pieces fit is in [docs/dev/README.md](docs/dev/README.md).

## Never commit private material

- **No key material, ever.** `make hooks` installs `tools/check-key-material.py`
  as the pre-commit hook. It refuses a commit carrying any key it can find in
  your key files, in any form (raw, hex, either byte order, any 8-byte
  fragment), and refuses `.dec`, `.img`, `.rdt`, capture, ledger and roster
  files outright. Point it at key files kept elsewhere with
  `git config --add tytcps.keyfile '/path/*.dec'`.
- **No real codeplugs.** A codeplug holds channel plans, radio IDs and the
  older Basic/Enhanced keys in plain form. Tests use the fictional codeplug in
  `tests/fixtures/demo.conf`.
- **No engine traces made with `-t -t`** in issues or commits: they contain
  codeplug data.

## Changing the engine

The engine is developed in the dmrconfig-tyt fork (branch `tyt-plus`) and
brought in as a subtree. Make the change there, with its test, then:

    git subtree pull --prefix=engine/dmrconfig-tyt <fork> tyt-plus --squash

and set `tytcps/engine_pin.json` to the new version, branch, commit and JSON
api. TYTcps refuses an engine that doesn't match its pin.

Rules the engine keeps:

- **Absent means untouched.** A conf line, table or row that isn't there
  leaves those bytes alone. Older confs must keep working.
- **Written only on change.** A value is written only when it prints
  differently from what the image holds; a value the stock CPS has no word for
  prints as `raw:0x…` and survives.
- **The stock CPS is the reference.** A field is written exactly as the CPS
  writes it, proven by the golden test ([docs/dev/testing.md](docs/dev/testing.md)).
- **Every failure says what happened to the radio** (`unchanged`,
  `codeplug_incomplete`, `keys_unknown`, …), and a new failure gets its own
  exit code, documented in `README-tyt-plus.md`.
- **Two reads before trusting an image; every write verified.**

## Changing the GUI

- **Plain words.** App text says what happened and what to do, in sentence
  case, without internals ("This radio didn't accept the key table", not
  "da 02 stalled"). Hover hints say what a field does, not how it's stored.
- **Every write goes to the radio its window was opened for**, and nothing
  talks to the radio unless the user pressed a button.
- **The conf text is edited, never the image.** Untouched lines go back to
  the engine exactly as it printed them.

## Tests

- Every fix comes with a test that fails without it.
- GUI tests run offscreen against `tests/fake_engine.py`; extend the fake
  engine rather than mocking inside a test.
- Every entry of the error catalogue is covered in `tests/test_catalogue.py`.
- No test may open USB or need a radio.

## Reporting a problem

Use ≡ → **Save diagnostics…** in TYTcps and attach the file: it never holds
keys, passwords or a codeplug image. Say which radio model and firmware (from
the radio's own menu) and what you did.

## License

By contributing you agree that your work is released under the license of
the part you change: GPL-3.0-or-later for TYTcps, BSD-3-Clause for the engine
(`engine/dmrconfig-tyt`).
