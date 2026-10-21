# dmrconfig-tyt — TYT MD-UV390 Plus fork

A fork of [sergev/dmrconfig](https://github.com/sergev/dmrconfig) 1.1.258,
branch `tyt-plus`, that adds the two things the MD-UV390 **Plus** needs and
upstream has no idea about:

1. the **AES / "Universal" privacy key table**, which lives outside the
   851968-byte codeplug and is reached by the vendor command `0xda`; and
2. the **per-channel privacy fields**, which upstream treats as unused bytes.

It also verifies every read it writes back and every write it makes, and it
has a machine-readable interface (`--json`, documented exit codes) for the
TYTcps program that drives it. Protocol and field map: `docs/dev/protocol.md`
and `docs/dev/field-map.md` in TYTcps.

## Build

    make

Needs `pkg-config`, `libusb-1.0-0-dev`, `libudev-dev`. The `99-dmr.rules`
udev rule (TYTcps ships its own, `tytcps/data/70-tytcps.rules`) gives `plugdev` access to
`0483:df11`. `dmrconfig --version` prints the version and the commit it was
built from (`-dirty` when the tree had uncommitted changes).

## The one thing to understand first

Phase 3 proved that **the key id travels over the air.** A channel's key
number selects the *transmit* key and is signalled on air; the *receiving*
radio looks that number up in **its own** key table, not in its own channel's
configured key.

So the key table is a **fleet-wide contract, slot for slot**:

* one `.dec` file is the single source of truth, and every radio gets the
  identical blob;
* the same key in different slots on two radios will **not** interoperate;
* a channel can look perfectly configured and still hear scrambled audio if a
  peer transmits on a slot this radio was never given.

And the radio **will not read keys back** — `-k` returns correct slot types
and names with all-zero key fields, which is the radio's own answer and not a
display mask. The only verification is over the air. The only record of what a
radio holds is the ledger.

## Commands

### Codeplug

    dmrconfig -r [-o dir]            read twice, to device.img + device.conf
    dmrconfig -w image.img           write an image back
    dmrconfig -c device.conf         apply a text config to the radio
    dmrconfig -c image.img conf [-o dir]
                                     apply a text config to an image file
    dmrconfig image.img              print the config of an image
    dmrconfig diff a.img b.img       which records two images differ in

`-r` reads the radio **twice** and refuses (exit 7, nothing saved) when the
two reads differ; `-o` puts the files in a folder instead of the current one.
`diff` compares two images with the layout knowledge added: every changed byte
is attributed to the record that holds it, with old and new values as the
config prints them, and the bytes that always move are listed separately:

    2 bytes change, in 2 records:
      General settings  1 byte  0x02084  ID 1001 -> 1002
      Channel 2 "TAC_2"  1 byte  0x40042  Key 2 -> 1
    Always changes: 3 bytes at 0x02001-0x0200B (Last Programmed Date and CPS version)
    Volatile: 0 bytes at 0x2F004/0x2F006 (the radio changes these by itself)

Bytes outside any known record are reported as such; that is the signature
of something rewriting what it should not. `diff` exits 0 whenever it ran;
whether the images differ is in its output (`identical` in the JSON result).

### Which radio is this

    dmrconfig identify               model, firmware, serial, a2 07 unit block

No codeplug or key access. **It still restarts the radio**: like every session
it enters programming mode (`91 01`, the radio shows "PC Programming Mode")
and leaves with `91 05`, which restarts it. The
radio is back on USB about 2.7 s after any command exits.

### Key table

    dmrconfig -K fleet.dec           write the key table to the radio
    dmrconfig -k                     read slot types and names
    dmrconfig keys show fleet.dec    list slots, keys in CPS grid order
    dmrconfig keys new out.dec       a new, empty key set (never replaces a file)
    dmrconfig keys set [--no-backup] [--name NAME] fleet.dec SLOT TYPE HEX|-
                                     set one slot in the file; no radio
    dmrconfig keys clear [--no-backup] fleet.dec SLOT
                                     empty one slot in the file; no radio

`keys set` takes the key in **CPS grid order** and reverses it internally:
keys are stored byte-reversed relative to the grid, which is a TYT habit
(qdmr does the same for the legacy keys). Types are `ARC4` (5 bytes),
`AES128` (16) and `AES256` (32). `-` as the key reads it from standard input,
so it never appears on a command line (where `/proc/<pid>/cmdline` shows it).
`--name` sets the slot name, up to 16 characters. The file is replaced
atomically (through a symlink, if it is one) and a timestamped `.bak` is kept
first.

`--no-backup` skips the `.bak`, and is for building a new set: `keys new`,
then one `keys set` per slot. It is refused for a slot that already holds a
key, for a set whose SHA256 is in the ledger (it is on a radio), and for the
current key set named in the fleet folder's `current-keyset` — so it never
destroys a key that exists nowhere else.

`keys new` makes exactly what the CPS makes for an empty set: 16 slots of
type AES256 named "1" to "16" with no key, and the CPS's padding, which is not
all zero (a copy of the slot 12-16 type and name fields at offset 0x4c of
every 1024-byte block from the third on). The radio is sent all 20480 bytes,
so the padding is reproduced, not guessed.

`-K` always sends the whole 20480-byte table. There is no way to write one
slot, and since the radio returns no key material, the key bytes for slots you
are not changing must come from your `.dec`, never from the radio.

### Channel privacy in the text config

The digital channel table has two new columns:

    Digital Name    Receive   Transmit Power Scan TOT RO Admit  Color Slot RxGL TxContact Privacy   Key
        1   TAC_1   451.1250  +0       Mid   -    60  -  Color  1     1    1    2         Universal 1

* `Privacy` — `None`, `Basic`, `Enhanced` or `Universal`.
  `Universal` is the Plus AES type (`+0x02` bits 4-5 = 3), the one that
  selects a slot in the `.dec` table. Upstream dmrconfig and qdmr know only
  None/Basic/Enhanced.
* `Key` — `-`, or 1-16. For `Universal` this is the `.dec` slot number; the
  codeplug stores it zero-based. `Basic` has 16 keys, `Enhanced` 8, both in
  the legacy table at `0x059C0` which this tool does not edit.

Writing a channel also sets `+0x05` bit `0x04`, the "privacy enabled" bit,
for any privacy type, and clears it for `None`.

An **upstream 13-column config is still accepted.** It cannot set or clear
privacy, so the existing privacy bytes are left alone and a note is printed —
clearing them would silently put an encrypted fleet on the air in the clear.

### The stock CPS's other pages (branch cps-fields)

For the MD-UV380/UV390 the config also carries the CPS's General Setting,
Menu Item and Buttons Definitions pages, scan-list timing, and the channel
fields the Digital and Analog tables do not. The field map, with each
offset taken from the CPS v2.41 binary's own getters and setters, is
`docs/dev/field-map.md` in TYTcps; the code is `cpsfields.c`, one table row
per field.

    Save Preamble: +
    Talk Permit Tone: Digital
    Time Zone: UTC +9:00
    Radio ID 1: 1005
    ...

    Menu     Item                Shown
             Text_Message        +
    Buttons  Key            Short                    Long
             Side_Button1   Power_Select             Unassigned
    OneTouch Mode    Call  CallType Message
           1 Digital 1     Text     1
    NumberKey Contact
            0 -
    ScanTiming  Hold[ms] Sample[ms]
             1  500      2000
    ChanDigital Width Sq RxRef TxRef Rekey AS LW VOX TA PCC EAA DCC AI DCDM Leader EmSys InCall MsgFmt
             17 12.5  4  Low   Low   5     -  -  -   +  -   -   -   -  -    MS     -     Follow DMR
    ChanAnalog RxRef TxRef Rekey AS LW VOX TA RxSig TxSig QTRev TurnOff PTTID RevBurst Decode
             4 Low   Low   10    -  -  -   +  Off   Off   180   None    -     +        --------

* **Absent means untouched.** A line, table or row the config does not
  carry leaves its bytes alone, so an older config still works unchanged.
* **Written only on change.** A value is written only when it prints
  differently from what the image holds (Keypad Lock 0x00 and 0xFF both
  print Manual and are kept as they are).
* **raw:0xNN** is printed for a value with no CPS word, or a number outside
  the CPS's own spin limits (Long Press 1000-10000 ms, Menu Hang Time
  0-30 s, ...), and parses back to the same byte. A raw value is
  hexadecimal (the `0x` is optional) and must fit its field; `raw:010` is
  0x10, not octal 8, and `raw:-1` is an error.
* Checkboxes are `+`/`-` as the CPS box shows them; inversions are handled
  inside. Units are the CPS's (ms, s).
* The three passwords and Model Select A/B are set like any other line; their
  encodings were settled by files the CPS itself saved: Power
  On and Radio Program Password 8 digits, most significant first; PC
  Programming Password up to 8 characters, then 0x00; `-` is none. A
  password set by mistake can lock the radio: TYTcps asks first.
* The tables are applied after the whole file is read, so their order does
  not matter and the channel tables' erase cannot undo them. A row for a
  channel of the other mode, a missing channel or scan list, or a One Touch
  or number key pointing at a missing contact or message is an error on
  that row. So are the CPS's own cross-field rules: a One Touch call type
  must suit the row's mode (`Call`/`Text` on Digital, `DTMF-n` on Analog,
  `raw:0xN` otherwise), and with DCDM on a channel's TOT must be 15-60 s.
  These are checked on what the config changes: a radio's own state, and
  a row the config leaves alone, still apply, unless the same config
  deletes the contact or message that row points to.
* `diff` names every field (`General settings  Talk Permit Tone Digital ->
  None`), and `menu`, `buttons`, `onetouch` and `numberkey` are records.

Digit Emergency System, DTMF Signaling and VFO Mode follow the same rules.
Their encodings come from 94 files the CPS saved and,
for what those could not reach, the CPS binary's getters and setters:

    Radio Disable Decode: +
    Remote Monitor Duration[s]: 10
    Tx Sync Wakeup TOT[ms]: 150
    EmergencySystem Name  AlarmType AlarmMode       TxInt Impolite Polite HotMic[s] Revert
                  1 System1 Regular Emergency_Alarm -     15       5      10        -
    DTMFSystem FirstDelay[ms] FirstTime[ms] ... SideTone PTTID GroupCode KeyUp KeyDown
             1 400            100           ... +        None  None      -     -
    DTMFEncode Code
             1 1
    DTMFDecode ID Response DecodeType ACK ACKDelay[ms] Revert
             1 -  Active   None       -   Off          Selected
    VFO A Channel Mode: Analog
    VFO A RX Frequency(MHz): 467.55000
    VFO A Step[kHz]: 12.5
    ...

* The DTMF tables always have all their rows (4 systems, 32 encodes, 8
  decodes). DTMF digits are `0-9 A-D * #`, at most 30, `-` for none; the
  image keeps them as a length byte and nibbles, low first, and as the CPS
  only the new digits' nibbles are written. Encode 1 is never empty.
* Emergency systems print only those that exist. A row for the next free
  number adds one (from erased bytes this gives exactly what the CPS's Add
  writes); a row of `-` in every column deletes one, from the last, and is
  refused while a channel or VFO still uses it. Revert is `-`, `Selected`
  or a channel. A channel's or VFO's emergency system must exist.
* `VFO A ...` / `VFO B ...` carry every field of the CPS's VFO page, analog
  and digital, with the CPS's labels; offsets are the channel record's.
  `Privacy: None` clears the key and the switch bit as the CPS's Privacy
  Switch does; a VFO made Universal gets the CPS's 0 in the +0x1E high
  nibble (a Universal key is 8 bits), and with `-F` its key slot must hold
  a key, as the channels'. Admit Criteria follows the VFO's mode (Correct
  CTCSS/CDCSS analog, Color Code digital) and DCDM on needs TOT 15-60 s.
* References are checked against the image the config started from: a
  VFO's contact, group list, scan list or emergency system, and a revert
  channel, may not point at a record this config deletes. A value printed
  exactly as the image holds it is kept without being parsed, so a VFO
  frequency outside the bands still reads back.
* `diff` names the records `emergency`, `emsystem`, `dtmfsystem`,
  `dtmfencode`, `dtmfdecode` and `vfo`.

Also on this branch: `ID:` is decimal (strtoul(..., 0) read `02102` as octal
1090), takes the CPS's 0-16776415 and writes 4 bytes (0x2087 = 0); the ID
an image already holds always applies. A channel number may be in the
Digital or the Analog table, not both. A new digital channel, or one made
digital, gets the CPS's Message Format DMR. A digital row no longer forces Width and tones, nor an analog row
colour code, slot, group list and contact, so values the CPS set survive;
a channel made Universal gets the CPS's 0 in the +0x1E high nibble instead
of 0xF (which the CPS shows as Privacy No. 241+); scan lists keep their
hold and sample time across the bank erase.

An image file carries no model: every 851968-byte file is read as an
MD-UV380, and offline print and apply treat it so, although an MD-2017,
MD-9600 or RT84 saves images of the same size. These pages are for the
MD-UV380/UV390 only; TYTcps writes codeplugs only to radios that identify
as one.

### Writing only to the radio you mean

    dmrconfig --expect-unit A207 -K fleet.dec
    dmrconfig --expect-unit A207 -c device.conf
    dmrconfig --expect-unit A207 -w image.img

`A207` is the unit block in hex, as `identify` prints it. The write goes
ahead only if the radio on the cable is that unit: right after connecting,
before anything is read, erased or sent, a different unit is refused (exit
17, `unit_mismatch`) and so is a radio whose unit block cannot be read (exit
14). Either way nothing is written and a TYT radio gets its normal restart
(91 05). Radios of other families have no unit block, so a write to them
with this option is always refused (exit 14).

This is for a program that identified a radio and writes to it later. The
radio leaves the bus after every session and comes back about 2.7 s later on
a new device number, and another radio plugged in during that gap looks
exactly the same from outside; only the unit block tells them apart. TYTcps
passes the unit its Write dialog was opened for on every write. The option
is a usage error on any other command.

### Checking key references

    dmrconfig -F fleet.dec -c device.conf

With `-F`, any channel set to `Universal` slot *N* is refused when slot *N* is
empty in that fleet file (exit 12). Without `-F` the check is skipped and a
note says so.

### Recording keys a radio already holds

    dmrconfig ledger add-existing --unit A207 --keyset fleet.dec [--note TEXT]
                                  [--tool manual|recovered]

Adds a ledger line for keys this tool did not write — the CPS wrote them, or a
`-K` whose ledger append failed (`--tool recovered`). Touches no radio; the
operator vouches for it. `--unit` is the a2 07 block in hex, as `identify`
prints it.

## The fleet folder

The ledger, the radio roster and the pre-write images live in one folder:
`$TYT_STATE_DIR` when set (TYTcps always sets it), otherwise
`$XDG_DATA_HOME/tytcps`, i.e. `~/.local/share/tytcps`. There is no hard-coded
path. The fork creates the folder (mode 0700) only to write the ledger; the
roster and pre-write images are skipped, with a note, when it does not exist,
since creating it is TYTcps's first-run dialog's job.

A fleet that kept its ledger somewhere else before this version must point
`TYT_STATE_DIR` there, or the next ledger line starts a new file.

### The ledger

`-K` appends one line to `ledger.tsv`:

    when  a207  serial  dmr_id  label  dec_sha256  dec_file  tool  note

No key material is recorded — only the SHA256 of the table that was sent.
Since keys cannot be read back, **this file is the only record of which key
set each radio holds.** `dmr_id` and `label` come from the roster, `-` when it
does not know the unit. `tool` is the fork's version, or `manual`/`recovered`
for `ledger add-existing`.

Before the radio is touched, `-K` checks the ledger can be opened, locked
and appended to, and that the key file's name can be recorded (refusing with
nothing written if not), and it appends the line the moment the last block
is in, before restarting the radio. A ledger that ends
in a partial line is repaired before appending; a failed append is cut back,
never left half-written. Lines written before the `note` column existed have
eight fields; a nine-column header line is appended once, as a comment, when
such a ledger gets its first new line.

### The roster, radios.tsv

    a207  radio_id  label  last_seen  last_write  flags

One line per unit, keyed on the `a2 07` vendor block, filled in by the fork
on every `identify`, `-r`, `-c`, `-w`, `-k` and `-K`: `radio_id` is the
Radio ID read from or written to the codeplug, `last_write` the time of the
last verified codeplug write. `label` and `flags` are the operator's (TYTcps's
Fleet tab) and are carried through verbatim, as are any columns after them.
Updates replace the file atomically under a lock (`radios.tsv.lock`).

The roster is **not a write guard**. Any radio can be written, keys included.
`units.tsv`, which used to refuse unlisted radios, is no longer
read. The `a2 07` block still matters: both 5W units report the same USB
iSerial and a byte-identical `a2 01` identify block, so it is
the only thing at the DFU layer that tells radios apart. A key write whose
`a2 07` cannot be read is refused (exit 14), since its ledger line would not
say which radio it was.

### Pre-write images

`-c` and `-w` keep the codeplug as the radio held it just before the write,
from the verified reads they do anyway, as
`prewrite/<a207>-<YYYYMMDDTHHMMSSZ>-NN.img` (UTC). The newest five per unit
are kept; an image identical to the newest one is not saved again, and none
is kept for a radio whose a2 07 unit block could not be read. The image is saved
only once the write is certain to go ahead — a run refused for a bad config
or a mismatched file writes nothing and keeps nothing. This is what to
restore with `-w` when a write turns out to be the wrong one; it is how a
test radio was recovered from a corrupted write.

## Fidelity: what this fork changed about ordinary writes

`-w image.img` was already byte-exact. The text config path was
not, so four things changed. On this fleet's codeplug they take the
`-c` round trip from 10049 differing bytes to zero, outside the date stamp:

| what | why |
|---|---|
| channels keep their pre-erase bytes | A config names about a third of a channel record. Upstream erases the bank and resets the rest to built-in defaults, which rewrote the privacy bytes and 27 others. This fork snapshots the bank, and restores a record when the old one was a valid channel *of the same mode*, before applying the config fields. |
| digital channels keep their squelch | Only the analog table has a Squelch column; upstream forced digital channels to 1. |
| zone and scanlist channel lists keep their order | Upstream sorted before printing, so a read-modify-write reshuffled every zone. |
| empty contacts are filled `ff ff ff c0` | What the CPS writes, and what `contact_t` documents (type 0, the two `_unused` bits set). Upstream wrote `ff ff ff ff`, which moved 9990 bytes of an untouched codeplug. |

The Last Programmed Date at `0x02002` (6 BCD bytes) and the CPS-version field
after it are still rewritten on every `-c`, deliberately, as the CPS does.
Upstream stamps its own version there, which prints as `V=1.01`. Exclude
`0x02001`-`0x0200B` when comparing images across a config write, along with
the volatile bytes `0x2F004` and `0x2F006` (`diff` does this for you).

Also fixed: the digital table's trailing `# contact name` comment used to be
absorbed by the two new columns, because `radio_parse_config()` only strips a
comment that starts in column one. The digital parser now cuts a `#` that
starts a whitespace-delimited token.

## Reads and writes are verified

A dmrconfig read can **silently** return corrupt data: whole 1024-byte DFU
transfers come back wrong and the tool still exits 0
(seen on the bench, more than once). So:

* **`-r` reads twice** and requires the reads to agree.
* **`-c` reads twice and requires the two reads to agree** before applying
  the config, because it writes the result back: that is how a corrupt read
  programmed 1135 bytes of garbage into a test radio.
* **`-w` reads twice** too, for the pre-write image; reads that disagree only
  cost that image, since `-w` does not depend on what the radio holds.
* **`-c` and `-w` read the radio back afterwards** and compare it against the
  image that was meant to be written. A single disagreeing read is retried
  once, because a corrupt read looks exactly like a bad write and must not be
  reported as one. Exit 8 if the write genuinely did not land.
* A short UPLOAD of a codeplug block is an error, not stale data.
* `0x2F004` and `0x2F006` change by themselves with normal radio use, so on
  an attached MD-UV390 the verify names and counts them rather than failing on
  them.

`-K` cannot be verified this way at all: the radio returns no key material.
That is what the ledger and the over-the-air test are for.

## For programs: `--json`, exit codes

Added in Phase 6.0 for TYTcps. A program driving
this tool reads the events and the exit code and never parses the human text,
which stays on stderr unchanged, for a log.

### `--json`

Valid on every command, anywhere on the line. stdout then carries exactly one
JSON object per line and nothing else; anything the tool would otherwise print
to stdout (tables, `-t` traces) goes to stderr. Strings are strict UTF-8.

| event | fields | when |
|---|---|---|
| `phase` | `phase` | a step starts: `connect`, `read1`, `read2`, `compare`, `parse`, `check`, `prewrite`, `erase`, `write`, `verify`, `verify_retry`, `keys`, `keys_read`, `save` |
| `progress` | `phase`, `done`, `total` | during transfers, about every 2% |
| `unit` | `model`, `a207`, `serial`, `firmware`, `privacy_capable`; key sessions add `known`, `radio_id`, `label` | right after the radio is opened |
| `prewrite` | `path`, `reused` | the pre-write image was saved (or an identical one kept) |
| `warning` | `code`, `message`, + fields | non-fatal: `no_privacy_columns`, `no_key_check`, `privacy_inconsistent`, `unit_unreadable`, `unit_block_unreadable`, `roster_failed`, `prewrite_failed`, `prewrite_skipped`, `reboot_failed` (the radio is still in programming mode: switch it off and on) |
| `error` | `code`, `exit`, `phase`, `radio`, `message`, + fields | a failure |
| `result` | `command`, `ok`, + per command | success; the last line |

`radio` in an error says what happened to the radio:

| `radio` | meaning |
|---|---|
| `unchanged` | nothing was written |
| `codeplug_incomplete` | erase or write started and did not finish |
| `codeplug_unverified` | written; the verify read did not finish |
| `codeplug_differs` | written; read-back differs on two reads |
| `codeplug_written` | written and verified (trouble came after) |
| `keys_unknown` | the key transfer started and did not finish |
| `keys_written` | keys written (trouble came after: the ledger) |
| `contacts_incomplete` / `contacts_written` | `-u`, the contacts database |

After `-K` has opened the radio, every error event also carries `a207`,
`sha256` and `file`, so a transfer that breaks off (`keys_unknown`) can be
recorded against the unit.

`unit_mismatch` (exit 17, `--expect-unit`) carries `expected`, the unit the
write was meant for, and `a207`, the one found; `radio` is always
`unchanged` and `phase` is `connect`. It comes before the key file is in
play, so on `-K` it has no `sha256` or `file`, as with `unsupported_model`
and `unit_unreadable` there.

Configuration errors (`conf_invalid`, `key_slot_empty`) carry their location:
`file`, `line`, `section` (`Digital`, `Analog`, `Zone`, `Scanlist`,
`Contact`, `Grouplist`, `Message`, or `General` for the scalar lines), `row`
(data row within the table), `id` (the row's own number as written, `7` or
`1a`), `column` (the header's name, `#` for the number) and, for parse errors,
`text`. `message` is the parser's own sentence. Problems found after parsing
(a channel on a missing scan list, a Universal channel on an empty slot) are
reported one `error` event each, then the run exits.

Results: `identify` (`model`, `firmware`, `serial`, `a207`, `known`,
`radio_id`, `label`, `last_seen`), `read` (`image`, `conf`, `sha256`,
`radio_id`, `name`, `a207`), `write_conf` / `write_image` (`verified`,
`volatile`, `prewrite`, `radio_id`, `a207`), `apply` (offline `-c`:
`image`, `sha256`, `radio_id`), `print` (`conf`: the whole config text),
`diff` (`identical`, `changed`, `records` with `kind`, `index`, `name`,
`bytes`, `ranges` as inclusive `[first, last]` offsets, and `fields` with
`field`/`old`/`new`; `unattributed`, `datestamp`, `volatile`),
`write_keys` (`sha256`, `a207`, `ledger`, `line`, `slots` without keys,
`verify: on_air_only`), `read_keys` (`slots`), `keys_show` (`slots` with
`key` in CPS grid order — never log it), `keys_new` / `keys_set` /
`keys_clear` (`file`, `sha256`), `ledger_add_existing` (`line`), `version`
(`version`, `branch`, `commit`, `api`).

### Exit codes

| exit | code | meaning |
|---|---|---|
| 0 | | success |
| 1 | `io_error` | a file could not be read or written, the ledger included before a key write (nothing written) |
| 2 | `usage` | bad command line |
| 3 | `no_radio` | nothing on the bus |
| 4 | `no_permission` | radio present, this user cannot open it (udev rule, group) |
| 5 | `busy` | claimed by another program, often a VM with USB passthrough (a paused VM still holds it) |
| 6 | `unsupported_model` | the radio's model is not supported for this |
| 7 | `reads_disagree` | two reads differed; nothing was written |
| 8 | `write_unverified` | written; read-back differs on two reads |
| 9 | `transfer_failed` | a USB transfer failed; `phase` and `radio` say where and what |
| 10 | `keyfile_invalid` | not a 20480-byte CPS `.dec`, or a bad slot, type, key or name |
| 11 | `conf_invalid` | config error, with its location |
| 12 | `key_slot_empty` | the only errors are Universal channels on empty slots (`-F`) |
| 13 | `ledger_failed` | the keys WERE written but the ledger line could not be; `line` is the line to record (`ledger add-existing --tool recovered`) |
| 14 | `unit_unreadable` | a key write, or a write with `--expect-unit`, could not read the a2 07 unit block; nothing written |
| 15 | `multiple_radios` | more than one 0483:df11 attached |
| 16 | `image_invalid` | not a codeplug image this tool knows, or not for the attached radio |
| 17 | `unit_mismatch` | `--expect-unit` named another unit than the one on the cable; nothing written |
| 18 | `keys_refused` | the radio refused the key-table command (da 02) itself, before any key was sent; its keys are as they were (a radio that isn't an MD-UV390 Plus may do this) |
| 255 | `failed` | upstream code paths for other radio families |

`--version --json` gives `api`, the version of this contract: 3 since exit
18 (1.1.278), 2 since `--expect-unit` and exit 17 (1.1.271), 1 before.

## Tests

    make test

Links the engine's objects a second time against `tests/fakeusb.c`, a
stand-in for libusb that plays one MD-UV390 and logs every request, and runs
`tests/test_expect_unit.py` against it: the `--expect-unit` refusals must
leave the log free of any codeplug read, erase, write or key transfer. It
also checks that a bad password line is refused without being repeated
back: no error message or `text` field ever shows a password line or value,
so a near-miss of a real password can't end up in a log or a bug report.
No radio is touched.

## Known limits

* `MD-UV390` and `MD-UV380` only for key operations; other identify strings
  are refused rather than guessed at. The 10W Plus identifies as `MD-UV390`
  and has the same layout. The unit-block reads at the start of a
  codeplug session are made only for these models; other TYT radios get
  upstream's session unchanged.
* What a non-Plus MD-UV390 identifies as is unknown.
* The radio may or may not validate the slot type against the key length;
  nothing has ever sent it a mismatched pair.
* `a2 04` and `a2 07` semantics are still unidentified. `a2 07` differs per
  unit and is used as the unit key; `a2 02` is the firmware version, a letter
  and six BCD digits (`53 11 90 38` = S119.038).
* `-t -t` dumps codeplug block data. Key-table blocks are never printed, at
  any trace level.
