# MD-UV390 Plus USB protocol

This note describes how the TYT MD-UV390 Plus exchanges data with a computer
over USB: the transport, the session every program opens, codeplug reads and
writes, the AES ("Universal") key table, the PC Programming Password, and the
restart that ends every session. It closes with what the TYTcps engine does
to stay safe and the questions that are still open.

It was worked out from USB captures of the stock TYT CPS v2.41 (Windows)
programming the radio. Everything TYTcps relies on was then confirmed by
reproducing it from Linux with the TYTcps engine and capturing that traffic
too. Where something has not been tested, this note says so.

Conventions:

- Bytes on the wire are written in transmission order: `91 01`.
- "Image" offsets (`0x020A0`) are into the 851968-byte codeplug image the
  engine reads. ".rdt" offsets are into the file the stock CPS saves.
- "The engine" is `engine/dmrconfig-tyt`, the dmrconfig fork that TYTcps
  drives. Its command line is documented in
  [README-tyt-plus.md](../../engine/dmrconfig-tyt/README-tyt-plus.md); the
  options are shown here as `dmrconfig -r` and so on.

## 1. Transport

The radio presents a standard USB DFU 1.1 interface with the ST
vendor/product ID `0483:df11`. Everything goes over control transfers: DFU
class requests to that interface (bmRequestType `0x21` host to radio, `0xA1`
radio to host). No bulk endpoints are used.

| Request | bRequest | Direction | Used for |
|---|---|---|---|
| DFU_DNLOAD | 1 | host to radio | commands and 1024-byte data blocks |
| DFU_UPLOAD | 2 | radio to host | the answer to the preceding command, and data blocks |
| DFU_GETSTATUS | 3 | radio to host | after every request |
| DFU_CLRSTATUS | 4 | host to radio | clears the error state (stock CPS) |
| DFU_GETSTATE | 5 | radio to host | idle check (engine) |
| DFU_ABORT | 6 | host to radio | return to dfuIDLE (engine) |

### The TYT command convention

TYT layers its own commands on DFU_DNLOAD, told apart by length:

- a **command** is a DNLOAD whose payload is 2 to 5 bytes;
- a **data block** is a DNLOAD of exactly 1024 bytes;
- a **read** is a DFU_UPLOAD issued after the command that selects what to
  read.

| Command | Meaning | Followed by |
|---|---|---|
| `91 01` | enter programming mode; the radio shows "PC Programming Mode" | |
| `91 05` | leave programming mode; the radio restarts (section 6) | |
| `a2 01` | identify: model and band ranges | UPLOAD of 32 bytes |
| `a2 02` | firmware version | UPLOAD of 4 bytes |
| `a2 03` | serial number | UPLOAD of 24 bytes |
| `a2 04` | PC Programming Password | UPLOAD of 8 bytes |
| `a2 07` | unit block | UPLOAD of 16 bytes |
| `da 01` | select the key table for reading | 20 UPLOADs of 1024 bytes |
| `da 02` | select the key table for writing | 20 DNLOADs of 1024 bytes |
| `21` + 4-byte address | set the address pointer (ST DfuSe) | codeplug data blocks |
| `41` + 4-byte address | erase (ST DfuSe) | |

`0xda` is the key-table selector. It is not in upstream dmrconfig, qdmr or
md380tools, and it is the whole of the Plus's key mechanism.

### Status after every request

The stock CPS follows every request, commands and data alike, with a
GETSTATUS/CLRSTATUS exchange. The radio answers it the same way every time:

1. GETSTATUS returns `00 32 00 00 04 00`: status OK, poll timeout 0x32 =
   50 ms, state 4 (dfuDNBUSY).
2. The radio then goes to state 10 (dfuERROR): GETSTATUS returns
   `0e 00 00 00 0a 00`, status 0x0E (errUNKNOWN).
3. The CPS sends CLRSTATUS and carries on. In full, the CPS's sequence
   between transfers is GETSTATUS, CLRSTATUS, GETSTATUS, CLRSTATUS,
   GETSTATUS.

**The error to state 10 is normal, not a failure.** A program that talks to
the radio must not abort on it. Clearing it is one way through; the engine
takes another: its idle check (GETSTATUS, GETSTATE, ABORT, GETSTATE) sees
dfuDNLOAD_IDLE and issues the DFU-standard ABORT instead of letting the radio
fall into state 10. Both routes reach dfuIDLE before the next request, and
key writes made by the ABORT route passed the over-the-air test. Any legal
route back to idle works; tolerating state 10 is sufficient but not required.

## 2. The session

Every session, whatever it is for, opens with the same preamble and ends with
the same command:

    DNLOAD 91 01                  enter programming mode
    DNLOAD a2 01  -> UPLOAD 32    model and band ranges
    DNLOAD a2 02  -> UPLOAD 4     firmware version
    DNLOAD a2 03  -> UPLOAD 24    serial number
    DNLOAD a2 04  -> UPLOAD 8     PC Programming Password
    DNLOAD a2 07  -> UPLOAD 16    unit block
    ...                           the session's work
    DNLOAD 91 05                  leave programming mode; the radio restarts

The stock CPS sends this preamble, in this order, in every session it opens:
reads, writes and key operations alike. (With a PC Programming Password set,
it first opens a short session that stops after `a2 04`; see section 5.) Each
request gets the status exchange of section 1.

### What the identify blocks hold

**`a2 01`, 32 bytes: model and band ranges.**

- Bytes 0-8: the ASCII model string `MD-UV390` and a NUL, then 0xFF up to
  byte 15. This is the plain model string: the Plus does not announce itself
  as a Plus at the USB layer, and the 10 W Plus identifies the same way.
- Bytes 20-27: four little-endian 16-bit BCD words in units of 100 kHz,
  giving the two band ranges. On the Plus they read 0x4000 and 0x4800
  (400.0-480.0 MHz) and 0x1360 and 0x1740 (136.0-174.0 MHz).
- Bytes 16-19 and 28-31: not identified.
- The whole block is identical on different units of the same model, so it
  is a model constant and says nothing about which radio is attached. A
  64-byte UPLOAD returns the same 32 bytes followed by zeros.

The stock CPS's Basic Information page shows the model as "MD-UV380" while
the radio identifies as `MD-UV390`. They are the same codeplug family; the
CPS displays its own model constant. This is not a wrong-model error.

**`a2 02`, 4 bytes: firmware version.** Byte 0 is an ASCII letter; bytes 1-3
are six BCD digits. The version is shown as `Lddd.ddd`: `53 11 90 38` is
S119.038. This matches what the radio's own menu shows.

**`a2 03`, 24 bytes: serial number.** An ASCII serial number, a NUL, then
0xFF padding. The last 4 bytes (+0x14 to +0x17) are not identified. The
serial differs between units. The CPS's Basic Information page leaves its
Serial Number field blank even though the radio returns one here.

**`a2 04`, 8 bytes: PC Programming Password, in clear.** The same 8 bytes as
image 0x020A0-0x020A7; eight 0xFF bytes when no password is set. See
section 5.

**`a2 07`, 16 bytes: the unit block.** Its meaning is unknown (the CPS's
"Unique Device ID" is a candidate, unconfirmed), but it differs between
units, and it is the only value at the DFU layer that tells two radios of the
same model apart. The engine calls it the unit block and uses it to identify
a radio. It is printed as 32 hex digits; examples in this note use the
obviously fake `00112233445566778899AABBCCDDEEFF`.

Why the unit block matters: two 5 W units examined report the same USB serial
string (iSerial) and a byte-identical `a2 01` block. Nothing visible from
outside a session, and nothing in `a2 01`, says which radio is on the cable.

## 3. Codeplug read and write

The codeplug image is **851968 bytes** (0xD0000), 832 blocks of 1024 bytes,
in two segments: image 0x00000-0x3FFFF and 0x40000-0xCFFFF. The AES key
table is not part of it (section 4).

Reading and writing use the ST DfuSe commands that upstream dmrconfig already
implements for the MD-UV380 family: set the address pointer (`21` + 4-byte
address), erase (`41` + 4-byte address), then move data in 1024-byte blocks,
UPLOAD to read and DNLOAD to write. The stock CPS's write erases and sets the
address before each 64 KB sector. Nothing about the Plus changes this path.
What the Plus adds is the per-channel privacy fields inside the codeplug and
the key table outside it.

### Reads can be silently wrong

A read can return corrupt data with no USB error at all. Whole 1024-byte
transfers have come back as 0x00 where the radio holds 0xFF, and an
immediately repeated read was correct. 1024 bytes is exactly one transfer, so
whole transfers are lost or garbled. A single read is therefore never trusted,
either as a backup or as the base for a write. The engine reads twice and
requires the reads to agree (section 7).

### Bytes that change on their own

When comparing two images, leave out:

- **0x02001-0x0200B**: the Last Programmed Date (six BCD bytes at 0x02002:
  year, month, day, hour, minute, second; the year as two digits) and the CPS
  version field after it. The CPS and the engine both rewrite these on every
  codeplug write.
- **0x2F004 and 0x2F006**: these change by themselves with normal use of the
  radio (a power cycle, operating it). Most likely a last-used zone or channel
  setting; not confirmed. They are not evidence of a write.

### The CPS's .rdt file

The stock CPS saves a codeplug as an `.rdt` file of 852533 bytes, 565
(0x235) more than the image. It is not one header plus the image; the image
is split around a DFU suffix:

| .rdt offset | Contents |
|---|---|
| 0x000-0x124 | DfuSe header |
| 0x125-0x224 | copy of the radio's identify blocks (not part of the image) |
| 0x225 | image 0x00000-0x3FFFF |
| 0x40225 | 16-byte DFU suffix |
| 0x40235 | image 0x40000-0xCFFFF |

So `rdt offset = image offset + 0x225` below image 0x40000, and
`+ 0x235` from 0x40000 on. Block matching also "finds" a 0x179 shift for image
0x00000-0x01FFF; that area is all 0xFF, so the match means nothing, and the
0x225 shift holds there too. md380tools' `map.xlsx` uses .rdt offsets
(image + 0x225).

The identify copy keeps the blocks in a different order from the preamble:

| Block | .rdt offset | Size |
|---|---|---|
| `a2 01` (model string first) | 0x125 | 32 bytes |
| `a2 03` | 0x145 | 24 bytes |
| `a2 04` | 0x15D | 8 bytes |
| `a2 02` | 0x165 | 4 bytes |
| `a2 07` | 0x169 | 16 bytes |

.rdt 0x179-0x224 is 0xFF.

Note that a codeplug image, and so an `.rdt`, holds the legacy Basic and
Enhanced privacy keys in clear (the legacy table at image 0x059C0) and the PC
Programming Password. Treat codeplug files as private. They never hold the
AES key table.

## 4. The key table

The Plus's AES ("Universal") privacy keys live in a **20480-byte key table
outside the codeplug**, reached only through `da 01` and `da 02`.

### Writing: `da 02`

    DNLOAD 91 01
    the a2 preamble (section 2)
    DNLOAD da 02                  select the key table for writing
    20 x DNLOAD of 1024 bytes     the table, block 0 to block 19, in order
    DNLOAD 91 05

- `da 02` is sent once, and the 20 blocks stream sequentially from offset 0.
- **There is no set-address and no erase.** The codeplug path's `21` and
  `41` commands do not appear.
- wValue is 0 on every DNLOAD; nothing numbers the blocks. Block order is
  transmission order.
- There is no checksum, no trailer and no obfuscation. The payload is the
  CPS's `.dec` key file byte for byte, padding included. This was checked
  over the whole file in two independent captures.
- Every request gets the status exchange of section 1.
- A complete key-write session is 33 DNLOAD/UPLOAD transfers. The engine's
  session matches the CPS's exactly: the same commands, the same lengths, the
  same order, wValue 0 throughout, and a payload identical to the file.

There is no way to write one slot. A write always sends all 20480 bytes, so
the key bytes for every slot not being changed must come from the local key
file. They cannot come from the radio, because the radio does not return
them.

A key write does not touch the codeplug, and a codeplug write does not carry
the key table. After repeated key writes, a two-read of the codeplug showed
no change at all apart from the date stamp of a separate codeplug write and
the volatile bytes.

### Reading: `da 01`

    DNLOAD da 01                  select the key table for reading
    20 x UPLOAD of 1024 bytes

The radio returns a well-formed 20480-byte table with **correct slot types
and names and all-zero key fields in every slot**. This is the radio's own
answer, seen on the wire, not something the CPS hides: the "*******" in the
CPS's Privacy Setting grid after "Read Privacy" masks nothing, and a file the
CPS saves after a read holds only types and names.

The types and names that do come back have one use: they show that a table
landed, at the level of slot types. After two slots' types were swapped and
then restored, a `da 01` read showed the restored layout. A read can never
confirm key bytes.

### The .dec key file

The CPS's key file (`.dec`) is exactly the 20480 bytes sent to the radio:
20 blocks of 1024. The first 1600 bytes (0x640) are 16 records of 100 bytes
(0x64), slot 1 first:

| Offset in record | Size | Field |
|---|---|---|
| +0x00 | 4 | type, uint32 little-endian |
| +0x04 | 32 | name, UTF-16LE, zero-padded (16 characters; "1" to "16" by default) |
| +0x24 | up to 64 | key bytes, zero-padded to the end of the record |
| +0x64 | | next record |

| Type | Cipher | Key length |
|---|---|---|
| 1 | ARC4 | 5 bytes |
| 3 | AES-128 | 16 bytes |
| 4 | AES-256 | 32 bytes |

The type codes were matched against the CPS's "Type" column.

The rest of the file is padding and carries no key material, but it is not
all zero: from the third 1024-byte block on, each block holds a copy of the
type and name fields of slots 12-16 at block offset 0x4C. It is sent
verbatim, so a tool that creates a key file reproduces the CPS's padding
rather than guessing it. An empty set as the CPS makes it is 16 slots of type
AES-256, named "1" to "16", with no key.

The slot number is purely a position in this file. Swapping two slots in the
CPS changed exactly 66 bytes, all inside the first two records; no other byte
of the table moved and no command changed. There is no per-slot address or
command.

**Byte order.** A key is stored **byte-reversed** relative to how the CPS
shows it in its Privacy Setting grid: the last byte displayed is the first
byte stored at +0x24. A tool that takes a key typed in the CPS's order must
reverse it. qdmr uses the same reversed convention for the legacy TYT privacy
keys, so this is a TYT habit, not a one-off. When copying a key out of the
CPS, copy the cell rather than reading it off the screen: the grid
scroll-clips the cell, so the first visible character is not necessarily the
first character of the key.

### The slot contract

**The key slot number travels over the air.** On a Universal channel, the
channel's key number selects the transmit key and is signalled on air. The
receiving radio looks that number up in **its own** key table, not in its own
channel's configured key. A channel selects a slot; the cipher type is a
property of the slot, stored in the table, not of the channel.

So the key table is a fleet-wide contract, slot for slot:

- every radio that must talk to the others gets the identical table, from one
  key file;
- the same key in different slots on two radios does not interoperate;
- a channel can look perfectly configured and still produce scrambled audio
  if a peer transmits on a slot this radio was never given.

In the codeplug, a channel's privacy type is a field of its 64-byte record
(Universal is the Plus's AES type; Basic and Enhanced are the legacy types
with their keys in the codeplug), and a Universal channel stores its slot
number zero-based. The offsets are in the field map
([cpsfields.c](../../engine/dmrconfig-tyt/cpsfields.c) and the engine's
README).

### Keys can only be verified over the air

- `da 01` returns no key bytes.
- The keys are not in the codeplug: both units' images and a CPS `.rdt` were
  searched for the known keys, forwards and byte-reversed, with no match, and
  key writes moved no byte of the image.

There is no read path that could confirm a key, so the only proof that a key
was written correctly is traffic: transmit on a Universal channel using that
slot from one radio and hear clear audio on another. Because nothing can be
read back, the engine records the SHA256 of every table it sends, per unit,
in a ledger. That ledger is the only record of which key set a radio holds.

### Firmware

AES works on firmware **S119.038**: a 5 W Plus on S119.038 passed AES-256
traffic with another 5 W Plus, in both directions, after a key write. A requirement of
"firmware S219.043 and CPS 2.41" for AES appears in user reports; as a
minimum firmware it is wrong. S219.043 is what a 10 W Plus reports
([models.md](../models.md)). Do not reflash a working radio for AES.

## 5. Passwords

### PC Programming Password: not enforced by the radio

The PC Programming Password is an ordinary codeplug field at image
0x020A0-0x020A7: up to 8 ASCII characters, then 0x00, then 0xFF fill; eight
0xFF bytes when none is set.

It was tested by setting a test password with the stock CPS and capturing
every CPS read and write, then reading and writing the same radio from Linux:

- **The radio hands the password to anyone who asks.** `a2 04`, part of every
  session's preamble, returns those 8 bytes in clear. A plain codeplug read
  returns them too, at 0x020A0.
- **Only the CPS enforces it.** With a password set, the CPS opens a short
  session (`91 01`, `a2 01` to `a2 04`) and stops after `a2 04`. It asks the
  user, compares the answer with what the radio returned, and only then opens
  a fresh session, identical in its commands to one on a radio without a
  password. Nothing the user types is ever sent to the radio, and no extra
  command appears.
- **The radio does not check it.** With the password set, the engine's
  two-read agreed and returned the password field like any other byte, and
  the CPS's own writes to that radio sent nothing the radio could have
  checked. A radio with a PC Programming Password reads and writes from Linux
  like any other. The CPS sets and clears the password on S119.038.

So the PC Programming Password is no protection against anyone with a cable;
it only stops the stock CPS being used without it. The engine has no password
option because none is needed. Anything that logs raw UPLOAD data, such as a
verbose USB trace, logs the password; treat such logs accordingly.

### Power On and Radio Program passwords

These are also codeplug fields, not part of the USB protocol: Power On
Password at image 0x02098 and Radio Program Password at 0x0209C, each 8 BCD
digits in 4 bytes, most significant first. Their encodings are in the field
map ([cpsfields.c](../../engine/dmrconfig-tyt/cpsfields.c)). A password set by
mistake can lock the radio, which is why TYTcps asks before writing one.

## 6. The restart, and one radio at a time

**Every session restarts the radio.** `91 05` leaves programming mode and
restarts the radio, even after a session that only read the identify blocks.
The radio drops off USB and comes back about 3 seconds later (about 2.7 s
measured) with a new USB device number. A program that starts a new session
too soon finds no radio; allow a few seconds between sessions. If the restart
command fails, the radio stays in "PC Programming Mode" until it is switched
off and on (the engine reports this as the warning `reboot_failed`).

**One radio at a time.** The 5 W units examined share a USB serial string
and an identical `a2 01` block, so two attached radios cannot be told apart
from outside a session. The restart makes this worse: a different radio
plugged in during the 3-second gap looks exactly like the one that left. Only
the `a2 07` unit block, read inside a session, tells them apart. The engine
refuses to run with more than one `0483:df11` device attached (exit 15), and
`--expect-unit` checks the unit block at the start of every write session.

## 7. What the engine does for safety

**Two reads.** `dmrconfig -r` reads the codeplug twice and saves nothing
unless the reads agree (exit 7). `-c` (apply a text config to the radio) also
reads twice and requires agreement before applying, because it writes the
result back: one corrupt read written back would program garbage into the
radio. `-w` (write an image) reads twice for its pre-write image; reads that
disagree there only cost that image, since `-w` does not depend on what the
radio holds. A short UPLOAD of a codeplug block is an error, not stale data.

**Verify after write.** `-c` and `-w` read the radio back after writing and
compare it with the image that was meant to be written. A single
disagreeing read is retried once, because a corrupt read looks exactly like a
bad write and must not be reported as one. Exit 8 means the write genuinely
did not land. The volatile bytes 0x2F004 and 0x2F006 are named and counted,
not treated as failures.

**Pre-write images.** `-c` and `-w` keep the codeplug as the radio held it
just before the write, from the verified reads they make anyway, and keep the
newest five per unit. An image is saved only once the write is certain to go
ahead.

**Writing only to the radio you mean.**

    dmrconfig --expect-unit 00112233445566778899AABBCCDDEEFF -w image.img

Right after connecting, before anything is read, erased or sent, the engine
reads the unit block. A different unit is refused (exit 17,
`unit_mismatch`); so is a radio whose unit block cannot be read (exit 14).
Either way nothing is written and the radio gets its normal restart. Radios
of other families have no unit block, so a write to them with this option is
always refused. TYTcps passes the unit its write dialog was opened for on
every write.

**Key writes.** `-K` always sends the whole 20480-byte table from the key
file and never takes key bytes from the radio. The file must be a valid
20480-byte `.dec` (exit 10 otherwise). A key write whose unit block cannot be
read is refused (exit 14), since its ledger line could not say which radio it
went to. Before touching the radio, the engine checks that the ledger can be
opened, locked and appended to; it appends the line (unit, SHA256 of the
table, file name, time; never key material) the moment the last block is in,
before the restart. If the keys went in but the ledger line could not be
written, it exits 13 and reports the line to record by hand. `-K` cannot be
verified by reading back; the result says `verify: on_air_only`.

**Key references.** With `-F keys.dec`, a config that puts a Universal
channel on a slot that is empty in that key file is refused (exit 12).

**Keys never echoed.** Key-table blocks are never printed, at any trace
level. `keys set` takes a key in the CPS grid's order and reverses it
internally, and `-` reads the key from standard input so it never appears on
a command line.

### Exit codes

| Exit | Code | Meaning |
|---|---|---|
| 0 | | success |
| 1 | `io_error` | a file could not be read or written, the ledger included before a key write (nothing written) |
| 2 | `usage` | bad command line |
| 3 | `no_radio` | nothing on the bus |
| 4 | `no_permission` | radio present, this user cannot open it (udev rule, group) |
| 5 | `busy` | claimed by another program, often a virtual machine with USB passthrough (a paused one still holds it) |
| 6 | `unsupported_model` | the radio's model is not supported for this |
| 7 | `reads_disagree` | two reads differed; nothing was written |
| 8 | `write_unverified` | written; read-back differs on two reads |
| 9 | `transfer_failed` | a USB transfer failed; `phase` and `radio` in the error say where and what |
| 10 | `keyfile_invalid` | not a 20480-byte CPS `.dec`, or a bad slot, type, key or name |
| 11 | `conf_invalid` | config error, with its location |
| 12 | `key_slot_empty` | the only errors are Universal channels on empty slots (`-F`) |
| 13 | `ledger_failed` | the keys WERE written but the ledger line could not be; the error carries the line to record |
| 14 | `unit_unreadable` | a key write, or a write with `--expect-unit`, could not read the `a2 07` unit block; nothing written |
| 15 | `multiple_radios` | more than one `0483:df11` attached |
| 16 | `image_invalid` | not a codeplug image this tool knows, or not for the attached radio |
| 17 | `unit_mismatch` | `--expect-unit` named another unit than the one on the cable; nothing written |
| 18 | `keys_refused` | the radio refused the key-table command (`da 02`) itself, before any key was sent; its keys are as they were (a radio that is not an MD-UV390 Plus may do this) |
| 255 | `failed` | upstream code paths for other radio families |

`dmrconfig --version --json` reports `api`, the version of this contract: 3
since exit 18, 2 since `--expect-unit` and exit 17, 1 before. The `--json`
event stream is documented in the engine's README.

## 8. Open questions

- **`a2 07`.** What the unit block means. It is used only to tell units
  apart; whether it is the CPS's "Unique Device ID" is unconfirmed.
- **Unidentified identify bytes.** `a2 01` bytes 16-19 and 28-31, and the
  last 4 bytes of `a2 03`. The CPS's Basic Information page has Hardware
  Version and MCU Version fields that have not been mapped to anything the
  radio returns.
- **Type against key length.** Whether the radio checks a slot's type field
  against its key length, or simply stores 100-byte records. The CPS never
  sends a mismatched pair, and neither has anything else.
- **A non-Plus MD-UV390 and the key table.** What a radio that is not a Plus
  does when sent `da 02` is unknown: refuse it (the engine then exits 18) or
  take it silently. One owner reports that a non-Plus MD-UV390 takes
  codeplugs and Basic and Enhanced privacy normally, but that its Universal
  channels sound garbled. Nothing found so far at the USB layer (identify
  blocks, firmware string) tells a Plus from a non-Plus.
- **Where the key table lives.** Only that it is outside the 851968 bytes the
  codeplug read covers, and reachable only through `da 01`/`da 02`.
- **The volatile bytes.** What 0x2F004 and 0x2F006 hold.

If you can answer any of these, or have a radio that behaves differently,
please open an issue with the model, the firmware version from the radio's
own menu, and what you saw. Never include key bytes, key files or codeplug
images in a report.
