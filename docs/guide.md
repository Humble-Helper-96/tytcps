# TYTcps user guide

TYTcps programs TYT MD-UV390 Plus radios from Linux: the codeplug (channels,
zones, contacts, every page of the stock CPS) and the AES key table. This
guide walks through using it. The [README](../README.md) has the short
version and the install commands; the [FAQ](faq.md) answers the questions
people run into.

## Before you start

- **One radio on the cable at a time.** Radios of the same model can share a
  USB serial number, so two connected radios can't be told apart.
- **Close other programming software,** and shut down (not pause) any
  virtual machine that passes USB through. A paused VM still holds the radio.
- **Every operation restarts the radio.** Identify, Read, Write codeplug and
  Write keys all put it into "PC Programming Mode" and restart it at the
  end. It's back on USB about 3 seconds later. That's normal, and it's why
  nothing ever happens to the radio unless you press a button.
- **Which radios:** the MD-UV390 Plus (5 W and 10 W) is supported and
  tested. See [Which radios](../README.md#which-radios) for the rest.

## Install

Install the Flatpak or the AppImage: see [Installing TYTcps](install.md).
To run it from the source instead, follow
[Install and run](../README.md#install-and-run).

**USB access.** Linux needs a udev rule before your user may open the
radio's programming port (USB `0483:df11`). The first-run dialog and
≡ → Settings check for it and show the commands that put it in place.
Unplug and replug the radio afterwards.

## First run

TYTcps creates its **fleet folder**, `~/.local/share/tytcps`, readable only
by you. It holds your key sets, the ledger (which keys went to which radio),
the list of radios it has seen, and its log. Then it offers to import a key
file from the stock CPS (`.dec`). An imported file is kept byte for byte,
so its fingerprint stays the one the radios programmed from it hold.

*(Planned: opening a codeplug saved by the stock CPS, `.rdt`.)*

## The radio bar

Along the top: what's on the cable, and four buttons.

- **Identify** asks the radio which unit it is: model, firmware, its unit
  number (TYTcps tells radios apart by it), Radio ID, and what the ledger
  says about its keys. Writes need an identified radio.
- **Read** reads the codeplug, twice: the two reads must agree, or nothing is
  trusted (a read can come back silently corrupted). About 6.5 seconds. The
  result opens as an unsaved codeplug.
- **Write codeplug…** and **Write keys…** open their windows (below).

While anything runs, the bar shows the step and a progress bar.

## Read, save, open, write

This is the whole codeplug workflow:

1. Connect a radio, press **Read**.
2. ≡ → **Save as…** to keep it as a file (`.img`).
3. Later: ≡ → **Open…** that file.
4. Change what you need (next section).
5. **Write codeplug…** → **Write codeplug**. Progress goes read, read,
   compare, erase, write, verify. Wait for **✔ Written and verified**.
   Don't unplug during a write; there's no cancel.
6. For the next radio: plug it in, **Identify**, **Write codeplug…** again.

**Each radio keeps its own Radio ID and Radio Name.** A write sends
everything else in the file, so one file serves the whole fleet. To change a
radio's ID or name, change it on the **General** tab before writing: the
Write window then says so.

Writing doesn't save the file; ≡ → **Save** does.

## Editing

The tabs are the stock CPS's pages: General, Menu, Buttons, Channels,
Zones, Scan lists, Contacts, Group lists, Messages, Emergency, DTMF and VFO,
plus Keys and Fleet.

- **Hover over any field** for what it does. Fields marked as written the
  same way as the CPS but with an untested effect say so; fields TYT never
  documented say "Undocumented".
- **The strip at the bottom** shows what your edits change, half a second
  after you stop typing. **Show** lists every changed byte by record and
  field. Write codeplug stays disabled until that check has run on exactly
  what will be written.
- **Red** marks a value the radio won't take, with the reason. Fix it
  before writing.
- **"(kept)"** next to a value means the codeplug holds something the stock
  CPS has no word for. It's left exactly as it is unless you pick a real
  value.
- A tab title with **•** has unsaved changes; a red dot has a problem.

## Keys

The Keys tab holds the AES keys for Universal privacy, in 16 slots.

**The fleet contract.** When a radio transmits encrypted, it sends the key's
*slot number*, not the key. The receiving radio looks that number up in its
own table. So every radio must hold the same key in the same slot: the same
key in a different slot won't work. TYTcps always writes all 16 slots and
warns whenever a key or a type changes.

- **Import** a `.dec` file from the stock CPS, **generate** keys (from the
  system's random generator, the right length for the type), or type them in
  the CPS's order. Keys are masked; the eye shows one slot for 30 seconds.
- Edits are a **draft** in memory until **Save as new key set**. A saved set
  is never changed in place: a new version is a new file.
- **New rotation…** generates new keys for every filled slot at once, for
  replacing a key set across the fleet.
- **Write keys…** sends all 16 slots to the identified radio and adds a
  line to the ledger.

**Keys can't be read back.** The radio returns slot types and names, but the
key bytes always come back as zeros. So after every key write, test each
slot you use over the air against a radio on the same key set, in both
directions, before relying on it.

**Only the Plus uses these keys.** An MD-UV390 that isn't a Plus takes the
codeplug and Basic or Enhanced privacy, but its Universal channels sound
garbled. If a radio refuses the key table, TYTcps says so and nothing is
written.

## The ledger and the Fleet tab

Because keys can't be read back, TYTcps keeps a **ledger**: every key write
records the date, the radio (unit, serial, Radio ID, label), and which key
set went to it, by fingerprint (SHA256), never the keys. It's the only record
of which keys a radio holds.

The **Fleet** tab lists every radio TYTcps has seen and what the ledger says
it holds. During a rotation, the **Old set** filter shows the radios still
to do; do the whole fleet in one go, because radios on different key sets
can't talk encrypted. **Record keys already on this radio** adds a ledger
line for keys written another way (the stock CPS): TYTcps can't check it, so
only use it when you know.

## When something goes wrong

Every failure message says what happened to the radio. In short:

| Message | The radio | What to do |
|---|---|---|
| Two reads didn't match | unchanged | Unplug and replug, try again; another USB port or cable if it repeats |
| The write didn't take | **not fit for use** | Write again; if that fails too, open a codeplug file you know is good and write it |
| Connection dropped while writing | **codeplug incomplete** | Don't unplug it again. **Write again** writes the same codeplug in full |
| Connection dropped while sending keys | **keys unknown** | Write the keys again before using the radio |
| Keys written, record not saved | holds the new keys | **Don't** write again. Fix the disk or permission problem, then **Record now** |
| This radio didn't accept the key table | unchanged | It may not be a Plus (see Keys) |
| In use by another program | unchanged | Shut the virtual machine down fully, close other programming software |
| A different radio is connected | unchanged | Identify the radio that's on the cable, then open the window again |

**Putting a radio back as it was:** open the file you saved from it (Read,
then Save as, before changing anything) and write it. The engine also keeps
what each radio held just before each of its last five writes, in
`~/.local/share/tytcps/prewrite/`; from a shell, `dmrconfig-tyt -w` writes
such a file back whole (below).

To report a problem: ≡ → **Save diagnostics…** and send the file. It holds
versions, the USB checks, the end of the log and the open codeplug's
settings with passwords removed, is checked against every key in your fleet
folder before it's saved, and never contains a key file or a codeplug image.

## Files and privacy

| What | Where |
|---|---|
| Fleet folder | `~/.local/share/tytcps/`, readable only by you |
| Key sets | `keys/` in the fleet folder, CPS `.dec` format |
| Ledger | `ledger.tsv` in the fleet folder: fingerprints, never keys |
| Radio list | `radios.tsv` in the fleet folder |
| Before-write copies | `prewrite/` in the fleet folder, newest five per radio |
| Log | `logs/tytcps.log` in the fleet folder |
| Settings | `~/.config/tytcps/settings.ini`, no secrets |

**Codeplug files are private too.** They hold no AES keys, but like the
stock CPS's files they do hold the older Basic and Enhanced privacy keys,
in plain form. Don't post a codeplug file publicly.

## From a shell

Everything the windows do can be done with the bundled engine,
`tytcps/libexec/dmrconfig-tyt`. Set the fleet folder first, or ledger lines
go elsewhere:

    export TYT_STATE_DIR=~/.local/share/tytcps
    E=tytcps/libexec/dmrconfig-tyt

| Task | Command |
|---|---|
| Which radio is this | `$E identify` |
| Read (two reads must agree) | `$E -r -o DIR` → `DIR/device.img`, `DIR/device.conf` |
| A codeplug as text | `$E file.img > file.conf` |
| Try a change without a radio | `$E -c -o OUT base.img edited.conf`, then `$E diff base.img OUT/device.img` |
| Write a codeplug (text) | `$E --expect-unit UNIT -F $TYT_STATE_DIR/keys/SET.dec -c edited.conf` |
| Write an image whole | `$E --expect-unit UNIT -w file.img` |
| Write keys (adds the ledger line) | `cd $TYT_STATE_DIR && $E --expect-unit UNIT -K keys/SET.dec` |
| Read slot types and names | `$E -k` (key bytes always read back as zeros) |

`UNIT` is the unit number `identify` prints. With `--expect-unit`, a write to
any other radio is refused before anything is read or sent. Lines a text
file leaves out are left as the radio has them: delete the `ID:` and `Name:`
lines to keep the radio's own, as TYTcps does. The full
reference, including `--json` and the exit codes, is
[engine/dmrconfig-tyt/README-tyt-plus.md](../engine/dmrconfig-tyt/README-tyt-plus.md).
Don't use the upstream `dmrconfig -c` on these radios: it writes a single,
unchecked read back into the radio.
