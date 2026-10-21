# Testing, and adding a CPS field

## The test suites

None of them needs a radio.

- **`make test`** (this repository): the conf round trip, the backend
  against the real engine on fictional codeplugs, and the GUI flows driven
  offscreen against `tests/fake_engine.py`. The fake engine answers like the
  engine (same events, same exit codes) and plays a radio from an image file;
  it can fail any phase on request (`FAKE_SCENARIO`, `FAKE_ERROR_AT`,
  `FAKE_EXIT_AT`). `tests/test_catalogue.py` raises every entry of the error
  catalogue the way it really happens and checks the message and what it says
  happened to the radio.
- **`make test` in `engine/dmrconfig-tyt`**: builds the engine a second time
  against `tests/fakeusb.c`, a stand-in for libusb that plays one MD-UV390
  and logs every request, and checks that refusals (another unit, a radio
  that refuses the key table, a bad password line) send nothing they
  shouldn't.
- **The golden test** (below): needs files saved by the stock CPS, which
  aren't in the repository.

## The CPS corpus and the golden test

The stock CPS is the reference for every field: TYTcps must write exactly the
bytes the CPS writes. The corpus is how that's proven, without reading the
CPS's code field by field.

1. **Make the corpus.** In a Windows VM with the stock CPS MD-UV390 v2.41
   (English), put a codeplug the CPS saved, `stock.rdt`, next to
   `tools/cps-corpus/cps-variants.ahk` and set the channel names at the top
   of the script. Run it with AutoHotkey v2. For every visible control on
   every page, it opens `stock.rdt`, changes that one control, and saves
   `variants/<page>_<control>_<change>.rdt`, logging each before and after to
   `variants/variants.tsv` and every page's controls and list entries to
   `inventory.tsv`. It only uses File > Open, Save As and the Edit menu: no
   radio is involved. A full run makes about 300 files in half an hour.
2. **Check it.** A plain re-save of `stock.rdt` (`S0_stock_resaved`) must be
   identical to it, so no file carries save noise. Each variant should differ
   from stock in the one field it names.
3. **Run the golden test:**

       python3 -I tools/cps-corpus/golden.py tytcps/libexec/dmrconfig-tyt CORPUS

   For each variant, the engine prints the CPS's image as conf, applies that
   conf to the stock image, and the result must equal the CPS's file byte for
   byte (outside the date stamp the CPS writes on every save).

Control IDs and labels come from the CPS's dialog templates; where the corpus
can't reach a control (greyed, or behind another choice), the CPS binary's own
getter and setter for it are the source, and [field-map.md](field-map.md)
says which.

**Codeplug files are private.** A real codeplug holds channel plans, IDs and
the legacy Basic/Enhanced keys in plain form, so neither `stock.rdt` nor the
corpus belongs in a repository. The pre-commit hook refuses `.rdt` and `.img`
files.

## Adding a CPS field

1. **Find it.** Where it lives in the image, its bits, its encoding and its
   range: from a corpus file that changes only it, and from the CPS's getter
   and setter. Add it to [field-map.md](field-map.md).
2. **Engine** (`engine/dmrconfig-tyt/cpsfields.c`, in the fork, not the
   subtree): add one row to the right table (`GENERAL`, `MENU`, `CHANDIG`,
   `VFOF`, …): conf key (the CPS's label), offset, mask, width, kind (`K_BOOL`,
   `K_ENUM`, `K_NUM`, …), flags (`F_INV` for an inverted checkbox, `F_ONE` for
   CPS-only fields whose effect is untested), scale and the CPS's spin limits.
   Printing, parsing and `diff`'s field names all come from that row. A value
   outside the CPS's limits prints as `raw:0x…` and is kept.
3. **Prove it.** The golden test must still pass on every corpus file, with
   the new field's files now included. Add a behaviour check if the field has
   rules (a range, a dependency).
4. **Bring the engine in:** commit in the fork, `git subtree pull` it into
   `engine/dmrconfig-tyt`, and set `tytcps/engine_pin.json` to the new
   version and commit.
5. **GUI** (`tytcps/backend/cpsfields.py`): add an `F(key, label, kind, …)`
   entry where the CPS shows it, with its range and step, and a hover hint in
   plain words: what it does, not how it's stored. Say "Undocumented" if TYT
   never documented it, and mark CPS-only fields `single=True`.
6. **Tests:** `make test`. A new kind of field gets its own test.
