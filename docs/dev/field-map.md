# Stock CPS field map: MD-UV380 / MD-UV390

This document maps every control on the pages of TYT's stock CPS v2.41 for
the MD-UV380 and MD-UV390 (including the Plus) to the 851968-byte codeplug
image that the engine reads and writes. The engine's
`engine/dmrconfig-tyt/cpsfields.c` is built from it. Each field in that file is
one table row, holding the offset, mask, encoding and CPS label given here. Use
this map when you add a field or check one.

## Conventions

- **Offsets** are image offsets (0x00000-0xCFFFF). For a repeated record, the
  section gives the base and the stride, and each row gives `+offset` within
  the record.
- **Masks** are byte masks; bit 0 is 0x01. "byte >> 6" and similar describe how
  the value is extracted.
- **INV** means the bit is stored inverted: 0 means the CPS box is ticked.
- **Default** is what a new file made by the stock CPS holds.
- Multi-byte integers are little-endian unless stated. Names are UTF-16LE.
- The CPS label is copied as the CPS shows it, misspellings included. The
  engine's config key is the CPS label unless a section says otherwise.

## Sources

| Name | What it is |
|---|---|
| **CPS** | The CPS v2.41 program (`CPS-DMR.exe` from TYT's MD-UV390 v2.41 installer), disassembled. Getter and setter addresses are virtual addresses in that program. They are given where they correct another source or are the only evidence. |
| **CPS files** | One-field files. The stock CPS opened a base `.rdt`, changed one control and saved. The corpus has 316 such files covering General Setting, Menu Item, Buttons Definitions (side buttons and Long Press), Scan List, Channel Information (one analog and one digital channel), Digit Emergency System, DTMF Signaling (DTMF-1) and VFO Mode (VFO A). A plain re-save of the base is byte-identical, so every difference in a file belongs to the control that was changed. No file disagreed with this map, and the engine reproduces all 316 byte for byte. The files are not distributed, because each `.rdt` carries the serial number and unit ID of the radio it came from (section 1). |
| **qdmr** | qdmr's code and its layout docs (`doc/code/*.txt`). |
| **md380tools** | `codeplugs/map.xlsx`, `chirp/md380.py` and `applet/src/radio_config.h`. These describe the MD-380 layout. On the UV390 only their bit layouts inside a record carry over to channels and contacts, because the record bases differ. |
| **editcp** | Field names only. It gives no offsets. |
| **dmrconfig** | Upstream dmrconfig's `uv380.c`, from which this engine is forked. |
| **radio** | Written to an MD-UV390 Plus (firmware S119.038) and read back, or with its effect seen on that radio. |

### Status

| Status | Meaning |
|---|---|
| **radio** | Checked on a radio, as above. |
| **CPS file** | Settled by CPS files. Where a page note says CPS files cover the whole page, every visible row on it is settled this way, whatever its Status column says. |
| **CPS code** | Traced in the CPS program's getters and setters, but no CPS file reached the control. This applies to hidden controls, VFO B, DTMF-2 to DTMF-4, the DTMF encode and decode lists, and the emergency systems' own fields. |
| **agreed** | Two or more independent sources agree. |
| **qdmr only** | qdmr is the only source. |
| **unknown** | No source gives a meaning. Preserve the bytes. |

A CPS file or the CPS code shows what the CPS writes. Neither shows what the
firmware does with the value.

Three pages have been tested offline only: Digit Emergency System, DTMF
Signaling and VFO Mode. No write of these pages has been read back from a
radio, and none of their effects has been observed on the air or on screen.

### Tags

- **[CPS-only]**: no tool or document other than the stock CPS knows this
  field, and its effect on the firmware is untested unless stated. The engine
  marks these fields `F_ONE`.
- **[UV390]**: the field is not in the MD-380 layout (md380tools).
- **[Plus]**: the field exists only on the Plus.
- **[10W]**: the field differs on the 10 W radio, or is unchecked there.

### Rules cpsfields.c follows

- **R1. Absent means untouched.** A key, table, row or column that the config
  does not carry leaves its bytes as they are.
- **R2. Write only on change.** A value is written only when it prints
  differently from what the image holds. This keeps raw values that print the
  same, such as:
  - Keypad Lock 0x00 and 0xFF, which both print as Manual;
  - any non-zero value at 0x2097, which prints as Channel;
  - BCD nibbles above 9;
  - 0xFFFF name characters;
  - PC password padding;
  - byte 0x2087.
- **R3. Raw escape.** A value with no CPS word prints as `raw:0xNN` and parses
  back to the same bytes.
- **R4. The CPS's meaning, not its bits.** Checkboxes print `+` or `-` as the
  CPS box shows them, and inversions are handled in the table. Units are the
  CPS's: ms, s, Always, Manual, Continue, Hang.

When you add something to the config text:

- **Table names.** A new table header must not start with an existing table
  name: Digital, Analog, Zone, Scanlist, Contact, Grouplist, Message, Menu,
  Buttons, OneTouch, NumberKey, ScanTiming, ChanDigital, ChanAnalog,
  EmergencySystem, DTMFSystem, DTMFEncode or DTMFDecode. Both the engine and
  TYTcps match headers by prefix.
- **Scalar keys.** A key must not contain ":" and must not reuse an existing
  key (Radio, Name, ID, Last Programmed Date, CPS Software Version, Intro
  Line 1, Intro Line 2 and the keys listed below).
- **Line length.** Keep every line to 254 bytes. The engine reads lines into a
  256-byte buffer.
- **No new columns on Digital, Analog or Scanlist rows.** Older parsers read
  a fixed number of fields and silently ignore extra ones. Put new channel
  fields in ChanDigital or ChanAnalog instead.

---

## 1. Address translation

| Range | Image offset | qdmr address | CPS v2.41 buffer | md380tools | CPS `.rdt` file |
|---|---|---|---|---|---|
| Settings segment | 0x00000-0x3FFFF | same as the image | same as the image (getters read `[buf+0x20xx]`) | `.bin` and chirp: same as the image. `map.xlsx`: `.rdt` offsets | image + 0x225 |
| Channel and contact segment | 0x40000-0xCFFFF | image + 0xD0000 | channel accessors use `base + n*64 + (off - 0x40)` | MD-380 layout (different bases) | image + 0x235 |

**Anchors**

| Anchor | What agrees |
|---|---|
| Radio ID | Image 0x2084 = qdmr `ADDR_SETTINGS` 0x2040 + 0x44 = dmrconfig `OFFSET_SETTINGS` + 68. In an `.rdt` it is at 0x22A9 = 0x2084 + 0x225, and md380tools `editcodeplug()` adds 549 = 0x225. Verified on a radio. |
| Channels | Image 0x40000 = qdmr 0x110000 (radio). |
| Contacts | Image 0x70000 = qdmr 0x140000. |
| Messages | Image 0x2180 = qdmr 0x2180. |
| VFO | Image 0x2EF00 and 0x2EF40 = qdmr's VFO addresses = CPS channel indexes 4029 and 4030. |

dmrconfig's `dfu_read_block` adds 832 blocks (832 x 1024 = 0xD0000) to every
block number of 256 and above. That is where the second-segment rule comes
from.

**`.rdt` layout**

| `.rdt` offset | Contents |
|---|---|
| 0x000-0x124 | DfuSe header |
| 0x125-0x178 | A copy of the radio's identify blocks (section 2). These are not part of the image. |
| 0x179-0x224 | 0xFF |
| 0x225 | Image 0x00000-0x3FFFF |
| 0x40225 | 16 bytes (DFU suffix, "UFD") |
| 0x40235 | Image 0x40000-0xCFFFF |

An `.rdt` therefore carries the radio's serial number (block a2 03) and its
16-byte unit block (a2 07). Remove them before you share a file.

An apparent shift of 0x179 for image 0x0000-0x1FFF is a false match: that area
is all 0xFF.

**md380tools offsets.** `map.xlsx` uses `.rdt` offsets (image + 0x225): for
example, its 22A9 "Radio ID Low Byte" is image 0x2084. `radio_config.h` is a
firmware RAM copy based at image 0x2080: `dmrid` is at +4 = 0x2084, `vox` at
+11 = 0x208B, `backlight` at +21 = 0x2095, `mode` at +23 = 0x2097, and
`radioname` at +48 = 0x20B0.

**Consistency checks**
- An `.rdt` that the stock CPS saved after reading a radio matches that radio's
  image byte for byte below 0x40000.
- Three radios were programmed alike: two 5 W and one 10 W. In 0x2040-0x20EF
  they differ only in Radio ID, and the 10 W radio also differs at 0x20E0
  (MIC Level).
- 0x20F0-0x217F was identical on all three radios and in two saves by the
  stock CPS.

**Memory map**

| Image range | Contents | Records | Section |
|---|---|---|---|
| 0x00000-0x01FFF | all 0xFF | — | — |
| 0x02000-0x0203F | Last Programmed Date, CPS Software Version | — | 2 |
| 0x02040-0x020EF | General Setting | — | 3 |
| 0x020F0-0x020FF | Menu Item | — | 4 |
| 0x02100-0x0213F | Buttons, One Touch Access, Number Key quick contacts | — | 5 |
| 0x02140-0x0217F | reserved, 0xFF | — | — |
| 0x02180-0x059BF | Text messages | 50 x 0x120 | 6 |
| 0x059C0-0x05A6F | Enhanced keys, a gap, Basic keys | 8 x 16, 16 x 2 | 7 |
| 0x05A70-0x05A7F | Digit Emergency System settings | — | 8 |
| 0x05A80-0x05F7F | Emergency systems | 32 x 0x28 | 8 |
| 0x0EC20-0x149DF | RX group lists | 250 x 96 | 10 |
| 0x149E0-0x1885F | Zones | 250 x 64 | 11 |
| 0x18860-0x1EDEF | Scan lists | 250 x 104 | 12 |
| 0x2EF00-0x2EF7F | VFO A, VFO B | 2 x 64 | 15 |
| 0x2F000-0x2F00F | Power-on zone and channel (on no CPS page; see below) | — | — |
| 0x30000-0x300BF | DTMF systems DTMF-1 to DTMF-4 | 4 x 0x30 | 14 |
| 0x300C0-0x302BF | DTMF encode list | 32 x 0x10 | 14 |
| 0x302C0-0x3037F | DTMF decode entries | 8 x 0x18 | 14 |
| 0x31000-0x3EABF | Zone extension records | 250 x 224 | 11 |
| 0x3EC40-0x3ED3F | GPS systems (on no CPS page; see below) | 16 x 0x10 | — |
| 0x40000-0x6EDFF | Channels | 3000 x 64 | 13 |
| 0x70000-0xC7E3F | Contacts | 10000 x 36 | 9 |

This map does not cover the ranges the table leaves out. Preserve them.

**On no CPS page**

| Region | Offset | Encoding | Sources | Status |
|---|---|---|---|---|
| Power-on zone and channel | 0x2F000, 16 bytes | +0x03 zone index + 1; +0x04 channel A; +0x06 channel B; +0x09..+0x0A = 0x0001; +0x0C. The radio updates these bytes itself, so 0x2F004 and 0x2F006 change with use. | qdmr `BootSettingsElement` and md380tools chirp `selectedzone` (0x2F003) agree | agreed. Do not expose these bytes or write them. Leave them out when you compare images, along with 0x2001-0x200B, which every config write rewrites. |
| GPS systems 1-16 (the v2.41 tree has no node for them) | 0x3EC40 + (k-1) x 0x10 | +0x00 revert channel index + 1 (0 = current); +0x02 repeat interval x 30 s (0 = off); +0x04 destination contact index + 1 | qdmr only | qdmr only. Preserve. |

---

## 2. Basic Information

This page is read-only. After a read from a radio, the page showed:
- Model Name "MD-UV380", although the radio identifies as "MD-UV390";
- CPS Software Version "V02.41";
- Serial Number, Hardware Version, MCU Version and Unique Device ID, all blank.

So nothing shows that the identify blocks feed this page.

The identify blocks are stored in the `.rdt` in this order:

| Block | `.rdt` offset | Size |
|---|---|---|
| a2 01 | 0x125 | 32 bytes |
| a2 03 | 0x145 | 24 bytes |
| a2 04 | 0x15D | 8 bytes |
| a2 02 | 0x165 | 4 bytes |
| a2 07 | 0x169 | 16 bytes |

| CPS label | Where | Encoding | Sources | Status |
|---|---|---|---|---|
| Model Name | Not in the image. a2 01 bytes 0-15 (`.rdt` 0x125) | ASCII, then NUL, then 0xFF. The page shows the CPS's own model constant, not these bytes. | dmrconfig-tyt (identify string, used for the `Radio:` line and the model check) | radio (the bytes); unknown (the page) |
| Frequency range (no page label seen) | Not in the image. a2 01 bytes 16-31 (`.rdt` 0x135-0x144) | Bytes 20-27 are 16-bit little-endian BCD words in 100 kHz units: 20-21 = 0x4000 (400.0 MHz), 22-23 = 0x4800 (480.0), 24-25 = 0x1360 (136.0), 26-27 = 0x1740 (174.0). Bytes 16-19 and 28-31 are unidentified. Not checked on the 10 W radio. | The bytes only; editcp has names for these fields but no offsets | single source |
| Serial Number | Not in the image. a2 03 (`.rdt` 0x145-0x158) | ASCII serial, NUL, then 0xFF padding. Different on every unit. The page has this field but showed it blank. | dmrconfig-tyt `dfu-libusb.c`; radio | radio (the bytes); unknown (the page) |
| (no label) a2 03 trailer | `.rdt` 0x159-0x15C (a2 03 +0x14..+0x17) | `00 03 00 00` on every unit examined. A candidate for Hardware Version. | none | unknown |
| Hardware Version | Unmapped. Candidates: a2 04, or the a2 03 trailer | — | blank in the CPS | unknown |
| MCU Version | Unmapped. Candidate: a2 02 | — | blank in the CPS | unknown |
| Unique Device ID | Unmapped. Candidate: a2 07 (16 bytes, different on every unit, `.rdt` 0x169-0x178) | — | blank in the CPS | unknown |
| (no label) a2 04 | `.rdt` 0x15D-0x164 | 8 bytes, all 0xFF on the 5 W Plus | none | unknown |
| Firmware version (no CPS label; the radio's own menu shows it) | Not in the image. a2 02 (`.rdt` 0x165-0x168) | Byte 0 is an ASCII letter, and bytes 1-3 are six BCD digits, shown as Lddd.ddd. `53 11 90 38` = S119.038 (5 W Plus); `53 21 90 43` = S219.043 (10 W Plus). | dmrconfig-tyt `unit_firmware()`; matches the radio's own menu | radio |
| Last Programmed Date | Image 0x2001-0x2007. 0x2000 and 0x200C-0x203F are 0xFF | 7 BCD bytes, big-endian: century, year, month, day, hour, minute, second. Example: `20 26 01 15 09 30 00` = 2026-01-15 09:30:00. After a read, the CPS page shows the time of the read, not these bytes. dmrconfig rewrites the date on every config write. | dmrconfig (`OFFSET_TIMESTMP`) and md380tools chirp (`prog_yr`) agree. qdmr disagrees (see section 17). | radio |
| CPS Software Version | Image 0x2008-0x200B | 4 bytes, one digit in each low nibble, mapped through `0123456789:;<=>?` and shown as Vdd.dd. CPS v2.41 writes `00 02 04 01` = V02.41. dmrconfig writes 0x0D and digits of its own version here, which the CPS shows as, for example, "V=1.01". | dmrconfig and qdmr (+0x08) agree | radio |

---

## 3. General Setting

The `general` record is 0x2040-0x20EF (dmrconfig `OFFSET_SETTINGS`, qdmr
`ADDR_SETTINGS`). The offsets below are absolute.

CPS files cover this page's visible controls (39 control IDs, the three
passwords and Model Select A among them). Each file changed exactly the bits
given here. The Status column records how the sources stood
before the files, plus any check on a radio. "Mirrored" in Sources refers to
dmrconfig's `general_settings_t` defect (section 17).

Config keys are the CPS label with three exceptions:
- `Diable All LEDS` becomes `Disable All LEDs`;
- `??/???` becomes `TX/RX LED`;
- Radio Name, Radio ID and Intro Screen Line 1/2 keep dmrconfig's keys
  `Name:`, `ID:`, `Intro Line 1:` and `Intro Line 2:`.

| CPS label | Offset / mask | Encoding (default) | Sources | Status |
|---|---|---|---|---|
| Save Preamble | 0x2081 0x01 | 1 = ticked. Default ticked. | CPS, qdmr SPR, md380tools (22A6 bit 0); dmrconfig mirrored (bit 7) | agreed |
| Save Mode Receive | 0x2081 0x02 | 1 = ticked. Default ticked. | CPS, qdmr SMR, md380tools; dmrconfig mirrored | agreed |
| Disable All Tone | 0x2081 0x04 INV | 0 = ticked (tones off). Default unticked. | CPS (load negates the bit), qdmr DAT (inverted), md380tools "!Disable All Tones"; dmrconfig mirrored and not inverted | agreed |
| CH Free Indication Tone | 0x2081 0x10 INV | 0 = ticked. Default unticked. | CPS, qdmr CIT (inverted), md380tools | agreed |
| Talk Permit Tone | 0x2081 0xC0 | byte >> 6: 0 None, 1 Digital, 2 Analog, 3 Analog & Digital (bit 6 = digital, bit 7 = analog). Default None. | CPS, qdmr TPD/TPA, md380tools; dmrconfig mirrored (bits 0-1) | radio (None removes the permit tone) |
| Call Alert Tone Duration[s] | 0x208F | s = raw x 5; 0 = Continue. Spin 5..1200 in steps of 5. Default Continue. | CPS, qdmr, md380tools ("s/5, 00 = Continuous"), dmrconfig (byte, no scale) | agreed |
| Scan Digital Hang Time[ms] | 0x2093 | ms = raw x 100. Spin 500..10000 in steps of 500. Default 1000. | all agree | agreed |
| Scan Analog Hang Time[ms] | 0x2094 | ms = raw x 100. Spin 0..10000 in steps of 500. Default 1000. | all agree | agreed |
| Lone Worker Response Time[min] | 0x2090 | minutes, raw 1..255. Default 1. | all agree | agreed |
| Lone Worker Reminder Time[s] | 0x2091 | seconds, raw 1..255. Default 10. | CPS, qdmr; md380tools map says minutes | agreed |
| Password and Lock Enable | 0x2081 0x20 INV | 0 = ticked. Default unticked. Unticked greys out Power On Password. | CPS, qdmr PWE (inverted), md380tools; dmrconfig mirrored | agreed |
| Power On Password | 0x2098-0x209B | 8 BCD digits, most significant first: the high nibble of 0x2098 is digit 1. Default 00000000. In the CPS files the page accepted exactly 8 digits. The getter (0x459730) shows a nibble above 9 as 9. The setter is assumed to work like Radio Program Password's. | CPS, md380tools map (22BD, same order). qdmr reverses the digits; dmrconfig treats the field as a plain uint32. | CPS file |
| CH Voice Announcement | 0x2082 0x02 | 1 = ticked. Default ticked. | CPS, qdmr CVN; dmrconfig `_unused66_0` | agreed [UV390] |
| Voice Announcement | 0x2082 0x04 | 0 English, 1 Chinese. Default English. The CPS's INI lists both (`[VoiceAnnouncement] 0=English 1=Chinese`), but the fill loop at 0x45cc46 stops after one item, so the CPS only offers English. TYTcps offers both; the effect of Chinese is untested. | CPS only. qdmr draws the bit as a fixed 0; dmrconfig's mirrored struct puts keypad_tones here. | CPS file (English) [CPS-only] |
| Radio Name | 0x20B0-0x20CF | 16 UTF-16LE characters, zero-padded. When the page opens, the CPS rewrites each 0xFFFF code unit to 0x0000. Default empty. | CPS, qdmr, md380tools (`radio_config` +48 and the map), dmrconfig `radio_name[16]` | agreed |
| Radio ID | 0x2084-0x2087 | uint32. Empty = `FF FF FF FF`, which the CPS shows as -1 (it formats with %02X four times, parses with %X and prints signed). Otherwise 0..16776415, written as 4 bytes with 0x2087 = 0x00, with no lower clamp. Default 1234. Example: Radio ID 1001 = `E9 03 00 00`. | CPS (setter 0x459140, 4 bytes); qdmr (24 bits plus a 0x00 byte); md380tools `radio_config.h` uint32 (map.xlsx has only 3 bytes); dmrconfig `radio_id[3]` | radio |
| Monitor Type | 0x2080 0x10 | 0 Silent, 1 Open Squelch. Default Open Squelch. | CPS, qdmr MNT, md380tools; dmrconfig mirrored (bit 3) | agreed |
| VOX Sensitivity | 0x208B | raw 1..10, combo "1".."10" (index = raw - 1). Default 3. | CPS, qdmr, dmrconfig, md380tools `radio_config` `vox`; map.xlsx says 0-10 | agreed |
| TX Preamble Duration[ms] | 0x2088 | ms = raw x 60. Spin 0..8640 in steps of 60. Default 600. | all agree | agreed |
| RX Low Battery Interval[s] | 0x208E | s = raw x 5. Spin 0..635 in steps of 5. Default 120. | all agree | agreed |
| Channels Hang Time[ms] | 0x20D0 | ms = raw x 100. Spin 0..7000 in steps of 500. Default 3000. Nothing else in the CPS reads this byte (getter 0x45a7d0). The Chinese label means "channel hang time". | CPS, qdmr (+0x90, x100); md380tools none (0xFF on the MD-380) | agreed [UV390]. The firmware's use is undocumented. |
| PC Programming Password | 0x20A0-0x20A7 | ASCII, at most 8 characters. A shorter password is followed by 0x00 and then 0xFF to the end ("1234" = `31 32 33 34 00 FF FF FF`). Exactly 8 characters: no terminator. Empty = 8 x 0xFF; the CPS checks only the first 2 bytes for FFFF. | CPS (setter 0x459a40, getter 0x459960), qdmr doc ("0x00 terminated, filled with 0xff"), md380tools map, dmrconfig `pc_prog_password[8]` | CPS file |
| Radio Program Password | 0x209C-0x209F | 8 BCD digits, most significant first ("12345678" = `12 34 56 78`). Empty = `FF FF FF FF` (disabled). Setter 0x45a090 right-aligns the entry: the last digit goes in the low nibble of 0x209F, a short entry is left-padded with 0, a non-digit is stored as 9, and input is cut to 8 digits. In the CPS files the page accepted exactly 8 digits. | CPS, md380tools map (22C1, same order). qdmr agrees that FFFFFFFF means disabled but reverses the digits; dmrconfig uint32. | CPS file |
| Back Light Time[s] | 0x2095, whole byte | 0 Always, 1 = 5 s, 2 = 10 s, 3 = 15 s (the CPS stores the combo index). Models other than 2017, MD-UV390, MD-UV380, RDH-X and PK-322DMR drop "Always" and use index = raw - 1. Default Always. | CPS (no mask), md380tools ("s/5, 00 = Always", whole byte). qdmr reads bits 0-1 x 5 s, which matches for 0..3; dmrconfig `backlight_time:2` at bits 6-7 (mirrored). | radio (5 s observed) |
| Set Keypad Lock Time[s] | 0x2096 | Read: 1 = 5 s, 2 = 10 s, 3 = 15 s; any other value, 0 included, = Manual. Write: Manual = 0xFF. Default Manual. | CPS (getter 0x459ec0, setter 0x459ef0), md380tools ("s/5, FF = Manual"), qdmr (x5 s, 0xFF = manual) | agreed |
| Freq/Channel Mode | 0x2097 | 0x00 = Freq; any non-zero value = Channel. The CPS writes 0x00 or 0xFF. Default Channel. | CPS, qdmr; md380tools `mode_ch_mr` agrees only that 0xFF = Channel | agreed |
| Model Select A | 0x2083 0x04 | 0 VFO, 1 MR. Default MR. Greyed (MR) in Channel mode: opening the page in Channel mode makes the CPS set bits 0x84 of 0x2083, so both Model Selects read MR. | CPS (getter 0x459d70, setter 0x459da0), qdmr layout docs `uv390_settings.txt` and `dm1701_settings.txt` (bit 2). qdmr's code uses bit 3 (section 17). | CPS file |
| Model Select B | 0x2083 0x80 | 0 VFO, 1 MR. Default MR (greyed in Channel mode). | CPS, qdmr MSB | agreed |
| Time Zone | 0x20AB 0xF8 | index = byte >> 3: 0 = "UTC -12:00" through 24 = "UTC +12:00", whole hours only. The setter keeps bits 0-2. The CPS resets a value above 24 to 20. Default 20 = UTC +8:00. | CPS, qdmr (`getUInt5(0x6b,3)-12`); dmrconfig inside `_unused104` | agreed [UV390] |
| Diable All LEDS (sic) | 0x2080 0x04 INV | 0 = ticked (all LEDs off). Default unticked. | CPS, qdmr DAL (inverted), md380tools "!Disable All LEDS"; dmrconfig mirrored (bit 5) | agreed |
| Group Call Match | 0x20AB 0x01 | 1 = ticked. Default ticked. | CPS, qdmr GCM | agreed [UV390] |
| Private Call Match | 0x20AB 0x02 | 1 = ticked. Default ticked. | CPS, qdmr PCM | agreed [UV390] |
| Group Call Hang Time[ms] | 0x2089 | ms = raw x 100. Spin 0..7000 in steps of 500. Default 3000. | all agree | agreed |
| Private Call Hang Time[ms] | 0x208A | ms = raw x 100. Spin 0..7000 in steps of 500. Default 4000. | all agree | agreed |
| Intro Screen | 0x2082 0x10 | 0 Char String, 1 Picture. Default Picture. | CPS, qdmr INP, md380tools; dmrconfig mirrored (bit 3) | agreed |
| Intro Screen Line 1 | 0x2040-0x2053 | 10 UTF-16LE characters, zero-padded. The edit box accepts 20 bytes, but the setter (0x45a3f0) converts to 10 wide characters, so a longer entry fails. On load, the getter (0x45a2b0) rewrites 0xFFFF units to 0x0000. Default empty. | CPS, qdmr, md380tools, dmrconfig `intro_line1[10]` | agreed |
| Intro Screen Line 2 | 0x2054-0x2067 | as Line 1 | as Line 1 | agreed |
| Radio ID 1 | 0x20D4-0x20D7 | uint32. Empty = `FF FF FF FF`. Clamped to 16776415. Default 1. | CPS (4 bytes, %X), qdmr `additionalDMRId(0)` | agreed [UV390] |
| Radio ID 2 | 0x20D8-0x20DB | as Radio ID 1. Default 2. | CPS, qdmr | agreed [UV390] |
| Radio ID 3 | 0x20DC-0x20DF | as Radio ID 1. Default 3. | CPS, qdmr | agreed [UV390] |
| MIC Level | 0x20E0 0x38 | raw 0..5, shown "1".."6" (display = raw + 1). The setter keeps the other bits. Default "3" (raw 2). | CPS, qdmr `micGain` (allows 0..6) | agreed [10W] |
| Tx Mode | 0x2080 0xC0 | byte >> 6: 0 Last Call CH, 1 Last Call CH + HandCH, 2 Designed CH, 3 Designed CH + HandCH. Default 3. For other models, the CPS also binds hidden "Analog/Digital Mic AGC" boxes to these bits. | CPS, qdmr TXM; dmrconfig `_unused64_6`; md380tools fixed 1s (MD-380) | agreed [UV390] |
| Front Keyboard Lock | 0x20E2 0x04 INV | 0 = ticked. Default unticked. Nothing else in the CPS reads it (getter 0x45b360). The Chinese label means "front panel lock". | CPS only; qdmr calls the byte reserved (0xFF) | CPS file [CPS-only] |
| Edit Radio ID | 0x20E0 0x40 INV | 0 = ticked. Default unticked. | CPS, qdmr ERI (inverted) | agreed |
| Public Zone | 0x20D2 0x04 | 1 = ticked. Default ticked. Nothing else in the CPS reads it (getter 0x45a840). The Chinese label means "shared zone". | CPS, qdmr PbZ | agreed [UV390]. The firmware's use is undocumented. |
| Power On Voice | 0x20E2 0x20 | 1 = ticked. Default ticked. | CPS only | CPS file [CPS-only]. On a radio with firmware S119.038, ticking it gave no voice at power-on. |
| ??/??? | 0x20EA 0x01 | 1 = ticked. Default ticked. This is control 1219, whose Chinese caption 发射/接收灯 means "TX/RX indicator light". The English INI has no entry for 1219, so the label renders as ??/???. The config key is `TX/RX LED`. The bit does not control the TX LED itself, which follows Diable All LEDS. | CPS only (getter `[0x20ea] & 1`) | CPS file [CPS-only]. On a radio with firmware S119.038, ticking it changed nothing visible: red on TX and green on RX, as before. |

**Hidden controls and unmapped bytes.** None of these is shown on the page.
Preserve them byte for byte. All are CPS code unless the row says otherwise.

| CPS label | Offset / mask | Encoding | Sources |
|---|---|---|---|
| Private Calls (hidden) | 0x2080 0x01 | 1 = ticked | CPS only; qdmr draws a fixed 0 |
| Escalert Tone (hidden) | 0x2081 0x08 INV | 0 = ticked | CPS only; qdmr draws a fixed 1 |
| Scan Priority Alert (hidden) | 0x2082 0x01 | 1 = ticked | CPS only; qdmr draws a fixed 0 |
| (no CPS control) Keypad Tones | 0x2082 0x20 | per qdmr KPT. The General Setting page never touches this bit. | qdmr only. dmrconfig's mirrored `keypad_tones` belongs here. |
| Analog Mic Gain (hidden) | 0x208C | 0..127 | CPS only; qdmr says "unused, 0x00" |
| Digital Mic Gain (hidden) | 0x208D | 0..127 | CPS only |
| Auto Shutdown (hidden) | 0x20E0 0x07 | list index | CPS only; qdmr draws a fixed 111 |
| GPS Report Format (hidden) | 0x20E0 0x80 | — | CPS only; qdmr draws a fixed 1 |
| 菜单控制 "menu control" (hidden) | 0x20E2 0x01 | — | CPS only |
| 双路通话 "dual call" (hidden) | 0x20E2 0x02 INV | — | CPS only |
| 接收亮屏 "RX wakes the screen" (hidden) | 0x20E2 0x08 INV | — | CPS only |
| 发射亮屏 "TX wakes the screen" (hidden) | 0x20E2 0x10 INV | — | CPS only |
| (no control) the rest of the record | 0x2068-0x207F; 0x2080 bits 1, 3, 5; 0x2082 bits 3, 6, 7; 0x2083 bits 0, 1, 3-6; 0x20A8-0x20AA; 0x20AB bit 2 (qdmr: fixed 1); 0x20AC-0x20AF; 0x20D1; 0x20D2 except bit 2; 0x20D3; 0x20E1; 0x20E2 bits 6-7; 0x20E3-0x20E9; 0x20EA bits 1-7; 0x20EB-0x20EF | All ones or 0xFF on every radio examined. Status: unknown. | No source gives a meaning; qdmr writes 1s or 0xFF. 0x2092 is not here: it belongs to Privacy Setting (section 7). |

---

## 4. Menu Item

The `menu` record is 0x20F0-0x20F7; 0x20F8-0x20FF is 0xFF. **Unless a row is
marked INV, a bit value of 1 means the item is shown in the radio's menu (box
ticked).** The config table is `Menu`, with one row per visible box. Each item
name is the CPS label with "_" for spaces, and `Menu_Hang_Time` is the
Utilities box.

**Where this comes from**
- The getters and setters are in the CPS program.
- The control-to-member mapping comes from DoDataExchange (0x4790F0) and
  OnInitDialog (0x479630), checked against dialog template 103.
- The CPS's default-codeplug routine (0x477790) calls every menu setter. Its
  values match every box in a new CPS file, which confirms each item's
  polarity.
- **CPS files cover all 42 visible boxes and settle each one.**

**Default-routine bug.** In the slot meant for the Menu Hang Time box (0x20F5
bit 4), the default routine calls the hang-time byte setter: first with 10,
then with 1. So a new CPS file shows Menu Hang Time 1 s, and the CPS never
initialises 0x20F5 bit 4.

**Boxes that depend on the CPS setup file**
- Radio Enable and Radio Disable appear only with setup `dtmffunc` = 1.
- Program Radio appears only when setup `programpsw` is not "0".
- The GPS box depends on setup `gpssystem`. The installer's `setting.ini` has
  `gpssystem=1`, but one installed CPS showed no GPS box, so an installed
  setup can differ from the installer copy.

**On the radio.** With Text Message hidden, the radio's menu keeps the message
inbox but offers no way to write a message.

| CPS label | Offset / mask | Default | Sources and notes |
|---|---|---|---|
| Menu Hang Time[s] | 0x20F0, whole byte | 1 (the bug above) | Seconds, spin 1..30 (wraps); 0 = "Hang" (the menu never times out); 2-character limit. CPS getter 0x4779B0; qdmr (byte 0, 0 = infinite). Config scalar `Menu Hang Time[s]`. |
| Text Message | 0x20F1 0x01 | shown | CPS 0x4779F0, qdmr TXT |
| Call Alert | 0x20F1 0x02 | shown | CPS 0x477A60, qdmr CAL |
| Edit Contact | 0x20F1 0x04 | shown | CPS 0x477AD0, qdmr CED |
| Manual Dial | 0x20F1 0x08 | shown | CPS 0x477B40, qdmr MDL |
| Radio Check | 0x20F1 0x10 | hidden | CPS 0x477BB0, qdmr RCK, md380tools chirp |
| Remote Monitor | 0x20F1 0x20 | hidden | CPS 0x477C20, qdmr RMO, md380tools chirp |
| Radio Enable | 0x20F1 0x40 | hidden | CPS 0x477C90, qdmr REN, md380tools chirp |
| Radio Disable | 0x20F1 0x80 | hidden | CPS 0x477D00, qdmr RDS, md380tools chirp |
| Program Key | 0x20F2 0x01 | shown | [CPS-only] CPS 0x477D70. The Chinese label means "one-key dial", the radio menu for programming quick-dial keys. qdmr's doc draws a fixed 1, while its `clear()` writes 0. |
| New Contact | 0x20F7 0x40 INV | hidden (bit = 1) | [CPS-only] 0 = shown. Getter 0x478CC0 (`not al; shr 6; and 1`), setter 0x478CF0 clears the bit for TRUE; control 1302. qdmr calls byte 7 unused. |
| Group Call | 0x20F7 0x80 INV | hidden (bit = 1) | [CPS-only] 0 = shown. Getter 0x478D30 (`not; shr 7`), setter 0x478D60; control 1301. |
| Missed (Call Log) | 0x20F2 0x08 | shown | CPS 0x477EC0, qdmr CLM |
| Answered | 0x20F2 0x10 | shown | CPS 0x477F30, qdmr CLA |
| Outgoing Radio | 0x20F2 0x20 | shown | CPS 0x477FA0, qdmr CLO |
| Delete all records | 0x20F7 0x08 | shown | [CPS-only] CPS 0x478BE0. The Chinese label means "delete all voice recordings" (recording firmware), not call-log records. |
| Zone | 0x20F5 0x40 | shown | CPS 0x4788D0 (control 1285), qdmr ZNS |
| Edit Zone | 0x20F6 0x01 | shown | CPS 0x478940, qdmr EDZ |
| New Zone List | 0x20F5 0x80 | shown | CPS 0x4789B0, qdmr NWZ |
| Talkaround | 0x20F2 0x40 | shown | CPS 0x478010, qdmr TlA (its `clear()` writes 0) |
| Tone or Alert | 0x20F2 0x80 | shown | CPS 0x478080, qdmr ToA |
| Power | 0x20F3 0x01 | shown | CPS 0x4780F0, qdmr PWR |
| Backlight | 0x20F3 0x02 | shown | CPS 0x478160, qdmr BKL |
| Intro Screen | 0x20F3 0x04 | shown | CPS 0x4781D0, qdmr INS |
| Keyboard Lock | 0x20F3 0x08 | shown | CPS 0x478240, qdmr KPL |
| LED Indicator | 0x20F3 0x10 | shown | CPS 0x4782B0, qdmr LED |
| Squelch | 0x20F3 0x20 | shown | CPS 0x478320, qdmr SQL |
| VOX | 0x20F3 0x80 | hidden | CPS 0x478400, qdmr VOX, md380tools chirp |
| Password and Lock | 0x20F4 0x01 | shown | CPS 0x478470, qdmr PWD (its `clear()` writes 0) |
| Display Mode | 0x20F4 0x02 | shown | CPS 0x4784E0, qdmr DSM |
| Program Radio | 0x20F4 0x04 INV | hidden (bit = 1) | 0 = shown (front-panel programming allowed). CPS 0x478550 (inverted on load and on save at 0x47A6A0), qdmr PRG, md380tools chirp (0xFB allowed, 0xFF disabled) |
| Group Call Match | 0x20F5 0x04 | shown | CPS 0x478630, qdmr UV390 GCM |
| Record Switch | 0x20F4 0x20 | shown | CPS 0x478780, qdmr UV390 RSW. Needs recording firmware. |
| Private Call Match | 0x20F5 0x08 | shown | CPS 0x4786A0, qdmr PCM |
| TX Mode | 0x20F5 0x20 | shown | CPS 0x4787F0, qdmr TXM |
| Monitor | 0x20F6 0x08 | hidden | [CPS-only] CPS 0x478B00. qdmr draws a fixed 1 and its `clear()` writes 0xFF. |
| Select Radio ID | 0x20F7 0x04 | shown | [CPS-only] [UV390] CPS 0x478B70. Chooses among Radio ID 1/2/3. qdmr calls byte 7 unused. |
| Menu Hang Time (Utilities box) | 0x20F5 0x10 | shown | CPS 0x478710 (control 1289), qdmr MHT. 1 = the radio menu has a Menu Hang Time item. |
| Power On Voice | 0x20F7 0x10 | shown | [CPS-only] CPS 0x478C50 (control 1216) |
| Scan | 0x20F2 0x02 | shown | CPS 0x477DE0, qdmr SCN |
| Edit List | 0x20F2 0x04 | shown | CPS 0x477E50, qdmr ESL |
| New Scan List | 0x20F6 0x02 | shown | CPS 0x478860, qdmr NSL |

**Hidden boxes and unmapped bits.** Preserve these.

| CPS label | Offset / mask | Encoding | Sources | Status |
|---|---|---|---|---|
| Privacy (no WS_VISIBLE) | 0x20F3 0x40 | 1 = shown | CPS only (control 1275, 0x478390); qdmr draws a fixed 0 | CPS code |
| GPS (hidden on the CPS install examined; the empty slot left of Menu Hang Time) | 0x20F4 0x08 INV | 1 = hides the GPS menu | CPS 0x4785C0 (inverted on load), qdmr UV390 `gpsSettings()` | agreed |
| Clock (hidden for MD-UV380, MD-UV390 and PK-322DMR) | 0x20F6 0x20 | 1 = shown | CPS only (control 1296, 0x478A90); qdmr fixed 1 | CPS code |
| CH Voice Announcement (hidden for MD-UV380 and MD-UV390) | 0x20F6 0x40 | 1 = shown | CPS only (control 1297, 0x478A20); qdmr fixed 1 | CPS code |
| (no CPS control) GPS information | 0x20F4 0x10 | qdmr GPI: hide GPS information (inverted) | qdmr docs only; the CPS never touches it | qdmr only |
| (no control) the rest | 0x20F4 0xC0; 0x20F5 0x03; 0x20F6 0x94; 0x20F7 0x23; 0x20F8-0x20FF | all ones; a CPS round trip preserves them | qdmr writes 1s or 0xFF | unknown |

---

## 5. Buttons Definitions

The `button` record is 0x2100-0x213F, and it includes the One Touch Access and
Number Key rows below. 0x2140-0x217F is reserved (0xFF). These extents come
from qdmr's memory table in `uv390_codeplug.hh`, whose `ButtonSettingsElement`
covers only 0x14 bytes. **CPS files cover the four side-button slots and Long
Press Duration.** No file covers the One Touch or Number Key grids.

**Function codes.** Button functions are KeyData codes, named from the CPS's
English INI. The installer's `keydata.ini` [MD-UV390] (keydata3-6) allows the
same set for all four visible slots:

| Code | Function | Code | Function |
|---|---|---|---|
| 0 | Unassigned | 22 | Privacy On/Off |
| 1 | All Alert Tones On/Off | 23 | VOX On/Off |
| 2 | Emergency On | 24 | Zone + |
| 3 | Emergency Off | 26 | Battery Indicator |
| 4 | Power Select | 31 | Lone Work On/Off |
| 5 | Monitor | 34 | Record On/Off(Firmware) |
| 7-12 | One Touch Access 1-6 | 35 | Record Playback(Firmware) |
| 13 | Repeater/Talkaround | 36 | Delete All Record(Firmware) |
| 14 | Scan On/Off | 38 | 1750Hz |
| 21 | Squelch Level | 47 | Switch Up/Down Screen |
| | | 48 | Right Key |
| | | 49 | Left Key |
| | | 55 | Zone - |

An installed CPS whose window title read "CPS MD-UV380" listed exactly these 28
functions, in code order.

**How the combo works.** The getter returns the dropdown position, which is
the number of allowed codes at or below the stored code. A code of 0, or 70
(0x46) and above, shows as Unassigned. A stored code outside the allowed set
selects the wrong item. Codes 0x50-0x56 are md380tools custom-firmware
functions. The engine prints any code outside the set as `raw:0xNN`.

Config tables: `Buttons` (keys `Side_Button1` and `Side_Button2`; function
names are the labels with "_" for spaces), `OneTouch` and `NumberKey`. Long
Press Duration is the scalar `Long Press Duration[ms]`.

| CPS label | Offset / mask | Encoding (default) | Sources | Status |
|---|---|---|---|---|
| Long Press Duration[ms] | 0x2111 | ms = raw x 250. Spin 1000..10000 in steps of 250 (raw 4..40). Default 1000. | CPS (getter 0x416610, setter 0x416640), qdmr (byte 0x11, x250); md380tools `radio_config.h` says "4 ms units" | agreed |
| Side Button1 Short Press (upper side key; md380tools "Top Side Button") | 0x2102 | KeyData code. Default Unassigned. | CPS slot 2 (combo 1354), qdmr byte 0x02 and its ButtonAction enum, md380tools `md380_codeplug.py`, map and chirp | radio (Monitor, code 5, works as Monitor) |
| Side Button1 Long Press | 0x2103 | KeyData code (keydata4). Default Unassigned. | CPS slot 3 (combo 1355), qdmr, md380tools | agreed |
| Side Button2 Short Press (lower side key) | 0x2104 | KeyData code (keydata5). Default Unassigned. | CPS slot 4 (combo 1357), qdmr, md380tools "Bottom Side Button Short" | agreed |
| Side Button2 Long Press | 0x2105 | KeyData code (keydata6). Default Unassigned. | CPS slot 5 (combo 1358), qdmr, md380tools | agreed |
| One Touch Access: Mode (rows 1-6) | Row n at 0x2110 + 4n (0x2114, 0x2118, …), +0 mask 0x30 | (byte >> 4) & 3: 0 None, 1 Digital, 2 Analog. Bits 7-6 are preserved (11 in every image examined). On a Mode change, the CPS resets the row: Digital gets call type 1, message 1, contact 1; Analog gets call type 8 (DTMF-1), encode 1, contact 1. | CPS (getter 0x416680, setter 0x4166B0, fix-up loop for n = 1..6), qdmr `OneTouchSettingElement` (bits 5-4; never encoded for the UV390) | agreed |
| One Touch Access: Call Type | +0 mask 0x0F | Digital: 0 Call, 1 Text Message (the UV390 CPS offers only these two). Analog: stored 8-11 = DTMF-1..4 (stored = combo index + 8; label index = stored - 4). | CPS (getter 0x416700, setter 0x416730, combo fill 0x4189D3), qdmr (CALL 0, MESSAGE 1, DTMF1-4 = 8..11) | agreed |
| One Touch Access: Message/Encode | +1 | Digital Text Message: message number 1..50 (0 = none, shown blank). Analog: DTMF encode entry number (1-based), shown as, for example, "2 Encode". | CPS (0x416770, 0x4167A0, renderer 0x41A400), qdmr `messageIndex` | agreed |
| One Touch Access: Call | +2..+3, uint16 | Contact number, 1-based (1..10000). 0 or out of range = none (shown blank). When a contact is deleted, the CPS sets every row that points to it to Mode None with contact 0, and decrements higher numbers (0x431300). | CPS (0x4167D0, 0x416820), qdmr `contactIndex` | agreed |
| Number Key Quick Contact Access (Number Key0 to Number Key9) | Key k at 0x212C + 2k (to 0x213F), uint16 | Contact number, 1-based. 0 or out of range = None. When a contact is deleted, a matching number becomes 0 and higher numbers are decremented (loop at 0x43139C). Default all None. | CPS only (getter 0x416890, setter 0x4168E0). qdmr includes the range but does not map it. | CPS code |

A new CPS file has every One Touch row at 0xD1 (Digital, Text Message),
message 1, contact 1.

**Hidden controls.** Preserve these.

| CPS label | Offset | Encoding | Sources |
|---|---|---|---|
| Top Button short/long (hidden) | 0x2100 / 0x2101 | KeyData codes. keydata1/2 allow nothing on the MD-UV390. Hidden for MD-UV380, MD-UV390, RDH-X and PK-322DMR (OnInitDialog 0x41AF4E-0x41B0FC). | CPS only (combos 1351/1352); qdmr "unused, 0" |
| Side Button3 short/long, P1-P4 short/long (hidden) | 0x2106-0x210F (pairs: SB3, P1, P2, P3, P4) | KeyData codes. keydata7-16 allow nothing on the MD-UV390. | CPS only (combos 1375-1388). qdmr's DM1701 layout agrees; its UV390 code calls these bytes unused. |
| Emergency Short Press Duration[ms] (hidden) | 0x2110 | ms = raw x 50. Spin 50..750 in steps of 50. 0x2112-0x2113 are unused (`FF FF`). | CPS only (getter 0x4165A0, setter 0x4165D0; controls 1366/1367 are not visible); qdmr "unknown, set 0x01" |

---

## 6. Text Message

| CPS label | Offset | Encoding | Sources | Status |
|---|---|---|---|---|
| Message 1-50 | 0x2180 + (n-1) x 0x120 | UTF-16LE, up to 144 characters, zero-padded. An empty record is all 0x00. dmrconfig also treats a first character of 0x0000 or 0xFFFF as empty. | dmrconfig (`OFFSET_MSG`), qdmr (`MessageBankElement`), md380tools chirp (0x2180, 288 bytes x 50) | agreed |

dmrconfig's `Message` table zeroes all 50 records when it reads its first row.
That matches the CPS's empty filler.

---

## 7. Privacy Setting

No CPS file covers this page.

| CPS label | Offset | Encoding | Sources | Status |
|---|---|---|---|---|
| Privacy Type (a combo on this page; the byte sits inside the general record) | 0x2092, whole byte | Combo index = byte. The list comes from the INI key "PrivacyType"; its order is not traced. 0x00 on every radio examined. | CPS only (getter 0x459610, setter 0x459630, called from 0x482743 and 0x482a74). qdmr says "unused, set 0x00"; dmrconfig `_unused82`. | CPS code. Preserve it, and do not reset it to 0x00. |
| Key Value (Enhanced), Key 1-8 (editcp naming; CPS label unseen) | 0x59C0 + (n-1) x 0x10, 16 bytes each | 16 raw bytes, stored byte-reversed relative to how they are displayed (qdmr; md380tools `md380_tool.py`: "displayed as big-endian, stored as little"). | qdmr (`EncryptionElement`, `ADDR_PRIVACY_KEYS`), md380tools chirp (0x59C0) | agreed (the offset); never written in a test |
| (gap) | 0x5A40-0x5A4F | 16 x 0xFF | qdmr layout and the images agree; md380tools chirp puts the Basic keys here | agreed |
| Key Value (Basic), Key 1-16 (editcp naming) | 0x5A50 + (n-1) x 2 (0x59C0 + 0x90), to 0x5A6F | 16-bit value. Byte order disputed: qdmr says little-endian, md380tools chirp says big-endian ("not tested"). | qdmr only for the offset; the images agree (0xFF at 0x5A40-0x5A4F, data from 0x5A50) | qdmr only |
| Universal key slots 1-16 (type ARC4/AES128/AES256, name, key) [Plus] | Not in the image | A separate 20480-byte table, written whole by vendor DFU command 0xDA. The radio returns slot types and names (`dmrconfig -k`) but never key material. The `.dec` file holds the table: 16 records of 100 bytes, then the CPS's padding. Each record has +0x00 type (uint32: 1 = ARC4, 5 bytes; 3 = AES128, 16 bytes; 4 = AES256, 32 bytes), +0x04 name (UTF-16LE, 32 bytes) and +0x24 key bytes, stored byte-reversed relative to the CPS grid. See `engine/dmrconfig-tyt/README-tyt-plus.md`, "Key table". | dmrconfig-tyt `-K`/`-k`; radio | radio |

A channel's Privacy No. selects Basic keys 1-16 or Enhanced keys 1-8 (4 under
one CPS model flag) in this table. For Universal, it selects a slot number in
the key table.

---

## 8. Digit Emergency System

The page's settings are at 0x5A70-0x5A7F. Systems 1-32 are at 0x5A80 +
(n-1) x 0x28, ending at 0x5F7F.

- **CPS files** cover the page's own settings.
- **The CPS code** covers each system's fields, which the CPS greys out until a
  system is picked.
- **qdmr** has the positions, but its scales, its revert encoding and its
  `#define` base addresses are wrong (section 17).

Channels pick a system through channel +0x0A (0 None, n = System n). The
config carries the settings as scalars and the systems as table
`EmergencySystem`. The engine refuses gaps in the numbering (delete from the
last system) and refuses to delete a system that a channel or VFO still uses.

| CPS label | Offset / mask | Encoding (default) | Sources | Status |
|---|---|---|---|---|
| Radio Disable Decode | 0x5A70 0x01 | 1 = ticked | CPS files; qdmr agrees | CPS file |
| Remote Monitor Decode | 0x5A70 0x02 | 1 = ticked | CPS files; qdmr | CPS file |
| Emergency Remote Monitor Decode | 0x5A70 0x04 | 1 = ticked. Bits 3-7 were 1 in every image examined; preserve them. The md380tools factory image holds 0xF8 (all three off). | CPS files; qdmr | CPS file |
| Remote Monitor Duration[s] | 0x5A71 | Whole seconds, 10..120 in steps of 10. Factory image: 0x0A = 10 s. | CPS files. qdmr reads raw x 10 s, which is wrong. | CPS file |
| Tx Sync Wakeup TOT[ms] | 0x5A72 | ms = raw x 25, 125..375 (raw 5..15). Factory image: 0x06 = 150 ms. | CPS files; qdmr (x25 ms) | CPS file |
| Tx Wakeup Message Limit | 0x5A73 | 1..4, combo "1".."4" | CPS files; qdmr | CPS file |
| (none) | 0x5A74-0x5A7F | 0xFF | — | unknown |
| System Name (System n) | +0x00 | 16 UTF-16LE characters. An empty system has a zero name and +0x20..+0x27 all 0xFF. The CPS counts systems up to the first one without a name. | CPS code; qdmr | CPS code |
| Alarm Type | +0x20 0x03 | 0 Disabled, 1 Regular, 2 Silent, 3 Silent w/Voice | CPS code; qdmr | CPS code |
| Alarm Mode | +0x20 0x30 | 0 Emergency Alarm, 1 Emergency Alarm w/Call, 2 Emergency Alarm w/Voice To Follow | CPS code; qdmr | CPS code |
| Tx Interrupt | +0x20 0x80 | 1 = ticked | CPS code; qdmr draws this bit as fixed | CPS code |
| (none) | +0x20 bits 2, 3, 6 | No CPS control. A system the CPS adds gets 1s here. | qdmr doc table | unknown (preserve) |
| Impolite Retries | +0x21 | 1..15 | CPS code; qdmr | CPS code |
| Polite Retries | +0x22 | 0..14; 15 = Infinite | CPS code; qdmr | CPS code |
| Hot Mic Duration[s] | +0x23 | Whole seconds, 10..120 in steps of 10 | CPS code. qdmr reads raw x 10 s, which is wrong. | CPS code |
| Revert Channel | +0x24, uint16 | 0 = None, n = channel n, 0xFFFE = Selected | CPS files (Selected = 0xFFFE); CPS code. qdmr disagrees (section 17). | CPS file |
| (none) | +0x26..+0x27 | `FF FF` | — | unknown (preserve) |

**Adding a system.** When the CPS adds a system on erased bytes, it writes
exactly the factory record, `4D 0F 05 0A 00 00 FF FF` at +0x20..+0x27:
- Regular, Emergency Alarm, Tx Interrupt off;
- Impolite 15, Polite 5;
- Hot Mic 10 s;
- Revert None.

The md380tools factory images hold the same record for System1.

---

## 9. Digital Contact

The `contact` record has base 0x70000 (qdmr 0x140000), stride 36 and 10000
records.

| CPS label | Offset / mask | Encoding | Sources | Status |
|---|---|---|---|---|
| Call ID | +0x00..+0x02 | uint24, 1..16777215. An empty record has 0xFFFFFF. An All Call contact uses 16777215. | dmrconfig, qdmr, md380tools (MD-380 base) | agreed |
| Call Type | +0x03 0x03 | 0 empty, 1 Group Call, 2 Private Call, 3 All Call. dmrconfig declares a 5-bit field; qdmr and md380tools fix bits 2-4 at 0. | all agree | agreed |
| Call Receive Tone | +0x03 0x20 | No/Yes. Bits 6-7 are always 11, so an empty record has 0xC0 at +0x03 (`FF FF FF C0`, which is what the CPS writes). | dmrconfig, qdmr `ringTone`, md380tools CallRxTone | radio |
| Contact Name | +0x04 | 16 UTF-16LE characters. dmrconfig's config writes "_" for a space. | all agree | agreed |

---

## 10. Digital RX Group Call

Base 0x0EC20, stride 96, 250 records.

| CPS label | Offset | Encoding | Sources | Status |
|---|---|---|---|---|
| Group List Name | +0x00 | 16 UTF-16LE characters. An empty record is all 0x00. | dmrconfig, qdmr, md380tools (map 0xEE45 - 0x225; chirp 0xEC20) | agreed |
| Contacts Member | +0x20, 32 x uint16 | Contact number (1-based); 0 ends the list; at most 32 | all agree | agreed |

---

## 11. Zone Information

Zones: base 0x149E0, stride 64, 250 records. Zone n's extension record is at
0x31000 + (n-1) x 224.

| CPS label | Offset | Encoding | Sources | Status |
|---|---|---|---|---|
| Zone Name | zone +0x00 | 16 UTF-16LE characters. An empty zone is 0x00 in both the zone record and its extension record. | dmrconfig, qdmr, md380tools | agreed |
| Channel members, list A 1-16 (CPS label unverified) | zone +0x20, 16 x uint16 | Channel number (1-based); 0 ends the list. The stored order is the order the radio steps through. | dmrconfig, qdmr, md380tools | agreed |
| Channel members, list A 17-64 | extension +0x00, 48 x uint16 | as above | dmrconfig `ext_a`, qdmr `ZoneExtElement`; md380tools none | agreed [UV390] |
| Channel members, list B 1-64 | extension +0x60, 64 x uint16 | as above | dmrconfig `member_b`, qdmr | agreed [UV390] |

---

## 12. Scan List

Base 0x18860, stride 104, 250 records. CPS files cover this page's six
controls. Hold and Sample are carried in the config table `ScanTiming`
(`Hold[ms]`, `Sample[ms]`).

| CPS label | Offset | Encoding (default) | Sources | Status |
|---|---|---|---|---|
| Scan List Name | +0x00 | 16 UTF-16LE characters. An empty record has a zero name, PCh1, PCh2 and TxCh = 0xFFFF, `F1 14 08 FF` at +0x26..+0x29, and no members. | dmrconfig, qdmr, md380tools | agreed |
| Priority Channel 1 | +0x20, uint16 | 0xFFFF = None, 0x0000 = Selected, n = channel n | dmrconfig, qdmr, md380tools | agreed |
| Priority Channel 2 | +0x22, uint16 | as Priority Channel 1 | all agree | agreed |
| Tx Designated Channel | +0x24, uint16 | 0xFFFF = Last Active Channel, 0x0000 = Selected, n = channel n | dmrconfig ("Last"), md380tools ("Last Heard"); qdmr calls 0xFFFF "none" | agreed |
| Signaling Hold Time[ms] | +0x27 | ms = raw x 25. Default 500 (0x14). | dmrconfig `sign_hold_time`, qdmr (x25), md380tools | agreed |
| Priority Sample Time[ms] | +0x28 | ms = raw x 250. Default 2000 (0x08). | dmrconfig, qdmr (x250), md380tools | agreed |
| (none) | +0x26 | Constant 0xF1 | dmrconfig, qdmr and every image examined; the md380tools map says "?FF" | agreed (preserve) |
| (none) | +0x29 | Constant 0xFF | all agree | agreed (preserve) |
| Channel Member | +0x2A, 31 x uint16 | Channel number (1-based); 0 ends the list | all agree | agreed |

---

## 13. Channel Information

The `channel` record is at 0x40000 + (n-1) x 0x40 for n = 1..3000 (qdmr
0x110000 + …, `.rdt` 0x40235 + …). The VFO records use the same layout
(section 15).

- **CPS program:** the accessors are at 0x41bcf0-0x41ff60, the DDX at
  0x420b40, the dialog is resource 112, and the new-channel default routine
  is at 0x41b8b0.
- **Empty channel:** a record is empty when name[0] is 0x0000 or 0xFFFF.
- **CPS files** cover 20 controls on an analog channel and 21 on a digital
  channel. When the CPS turns an analog channel into a digital one, every other
  byte of the record stays as it was.

The **Config** column names the dmrconfig table column (`Digital`/`Analog`) or
the engine's extension column (`ChanDigital`/`ChanAnalog`).

**Digital/Analog Data**

| CPS label | Offset / mask | Encoding (default) | Sources | Status | Config |
|---|---|---|---|---|---|
| Channel Mode | +0x00 0x03 | 1 Analog, 2 Digital. The INI also lists 0 Auto, which channels do not use. 0 and 3 are invalid. A new CPS channel is Analog. | dmrconfig, qdmr, md380tools, CPS | agreed | which table |
| Band Width | +0x00 0x0C | (byte >> 2) & 3: 0 = 12.5, 1 = 20, 2 = 25 kHz; 3 is invalid. Default 12.5. The CPS edits it on digital channels too. | dmrconfig, qdmr, CPS. md380tools' single bit (bit 3) is consistent with 2. | agreed | Analog `Width`; ChanDigital `Width` |
| Scan List | +0x0B | 0 None, n = list n (1..250) | all agree | agreed | `Scan` |
| Squelch | +0x0F | Level 0..9 (combo index = byte). Default 1. | dmrconfig, qdmr UV390, CPS. md380tools' Tight/Normal at +0x00 0x20 is MD-380 only. | radio (a squelch change read back from a radio appeared at +0x0F) | Analog `Sq`; ChanDigital `Sq` |
| RX Ref Frequency | +0x03 0x03 | 0 Low, 1 Medium, 2 High. Default Low. | all agree | agreed | `RxRef` |
| TX Ref Frequency | +0x04 0x03 | 0 Low, 1 Medium, 2 High | all agree | agreed | `TxRef` |
| TOT[s] | +0x08 0x3F (the CPS reads the whole byte; bits 0xC0 are 0) | Analog, or digital with DCDM off: 0 = Infinite, n = 15n s for n = 1..37. Digital with DCDM Switch on: only n = 1..4 (15/30/45/60 s); the combo index is n - 1 and the CPS writes index + 1 (loader 0x423012-0x4230a2, handler 0x425b60, refill on a DCDM toggle at 0x427b9e). A setup-INI key `qcom` = 1 would cap the list at 180 s; the shipped INI has none. Default 4 (60 s). | all agree | agreed | `TOT` (seconds) |
| TOT Rekey Delay[s] | +0x09 | 0..255 s. Default 0. | all agree | agreed | `Rekey` |
| Power | +0x1E 0x03 | 0 Low, 2 Middle, 3 High. Raw 1 is invalid: getter 0x41d720 shows it as High. Setter 0x41d7e0 writes 0 for index 0, otherwise index + 1. Default High. Bits 0x0C are fixed 11; bits 0xF0 are the Universal key's high nibble. | dmrconfig, qdmr UV390 `power()` (0/2/3), CPS | CPS file (High = 3); radio (Low and Middle) [10W: whether High means 10 W is unchecked] | `Power` |
| Channel Name | +0x20..+0x3F | 16 UTF-16LE characters, 0x0000-padded | all agree | radio | `Name` |
| RX Frequency(MHz) | +0x10, uint32 | 8-digit BCD, little-endian, in 10 Hz units; 0xFFFFFFFF = invalid. Example: 145.50000 MHz = `00 00 55 14`. | all agree | radio | `Receive` |
| TX Frequency(MHz) | +0x14, uint32 | As RX. Stores the absolute frequency. | all agree | agreed | `Transmit` (absolute, or as a ± offset) |
| Admit Criteria | +0x04 0xC0 | byte >> 6: 0 Always, 1 Channel Free, 2 Correct CTCSS/CDCSS (analog only), 3 Color Code (digital only). On load, the CPS resets an out-of-mode value to 0: raw 3 on analog (0x421f30), raw 2 on digital (0x422051). Default Always. | dmrconfig, qdmr, CPS. md380tools reads bits 7 and 6 as independent flags. | agreed | `Admit` |
| Auto Scan | +0x00 0x10 | 1 = ticked. Default 0. | all agree | agreed | `AS` |
| Rx Only | +0x01 0x02 | 1 = ticked | all agree | agreed | `RO` |
| Lone Worker | +0x00 0x80 | 1 = ticked | dmrconfig, md380tools, qdmr doc (LWK, bit 7), CPS | agreed | `LW` |
| VOX | +0x04 0x10 | 1 = ticked | all agree | agreed | `VOX` |
| Allow Talkaround | +0x01 0x01 | 1 = allowed (not inverted). Default 0 (default init 0x41b948). Greyed when RX = TX. | CPS getter 0x41c220, qdmr UV390 override, md380tools (chirp, map). qdmr's TyT base class and `uv390_channel.txt` say inverted. | CPS file | `TA` |

**Digital Data**

| CPS label | Offset / mask | Encoding (default) | Sources | Status | Config |
|---|---|---|---|---|---|
| Private Call Confirmed | +0x02 0x40 | 1 = ticked | all agree | agreed | `PCC` |
| Emergency Alarm Ack | +0x03 0x08 | 1 = ticked | dmrconfig, qdmr code, md380tools, CPS. qdmr's `uv390_channel.txt` says bit 5. | agreed | `EAA` |
| Data Call Confirmed | +0x02 0x80 | 1 = ticked | all agree | agreed | `DCC` |
| Allow Interrupt | +0x1F 0x04 INV | 0 = ticked. Default unticked. | qdmr UV390, CPS (getter `(~b >> 2) & 1`); dmrconfig `_unused11` writes 1 | agreed [UV390] | `AI` |
| DCDM Switch | +0x1F 0x08 INV | 0 = on. Default off. | dmrconfig `dcdm_switch_dis`, qdmr, CPS | agreed [UV390] | `DCDM` |
| Leader/MS | +0x1F 0x10 | 0 Leader, 1 MS. Default MS. Has an effect only with DCDM on. | dmrconfig, qdmr (same bit, inverted name), CPS | agreed [UV390] | `Leader` |
| Emergency System | +0x0A | 0 None, n = System n (1..32) | all agree | agreed | `EmSys` |
| Contact Name | +0x06, uint16 | 0 None, n = contact n | all agree | agreed | `TxContact` |
| Group List | +0x0C | 0 None, n = list n | all agree | agreed | `RxGL` |
| Color Code | +0x01 0xF0 | 0..15. Default 1. | all agree | agreed | `Color` |
| Repeater Slot | +0x01 0x0C | 0x04 = Slot 1, 0x08 = Slot 2. Getter 0x41c4a0: 0x04 set gives Slot 1, otherwise 0x08 set gives Slot 2, otherwise Slot 1. | all agree | agreed | `Slot` |
| In Call Criteria | +0x05 0x30 | 0 Always, 1 Follow Admit Criteria, 2 Tx Interrupt. Raw 3 has no CPS entry. | dmrconfig, qdmr UV390, CPS | agreed [UV390] | `InCall` |
| Privacy Switch (checkbox) | +0x05 0x04 | 1 = privacy on, for any type. The CPS sets it for Basic, Enhanced and Universal and clears it for None. On models other than the Plus, bits 0x0C are the hidden Signaling Squelch combo. | qdmr UV390 `privacySwitch`, CPS | radio [Plus] | implied by `Privacy` |
| Privacy Switch type (unlabelled combo) | +0x02 0x30 | 0 None, 1 Basic, 2 Enhanced, 3 Universal. Depending on a global model flag, the CPS removes either Universal or both Basic and Enhanced. | dmrconfig-tyt, CPS (0x41c9f0); qdmr knows only 0-2 | radio [Plus: Universal]. With this field changed from Universal to Basic (one byte), the channel could no longer talk with radios still on Universal, in either direction; changing it back restored it. | `Privacy` |
| Privacy No. | +0x02 0x0F | Key index - 1. Basic 1-16; Enhanced 1-8 (4 under one CPS model flag). Universal also takes the high nibble in the next row. | all agree | radio | `Key` |
| Privacy No. (Universal high nibble) | +0x1E 0xF0 | Type 3 only: index = (+0x1E & 0xF0) + (+0x02 & 0x0F), range 0-254, shown 1-255. The CPS setter 0x41c820 writes both nibbles, so the high nibble is 0 for keys 1-16. For other types the nibble is ignored. | CPS only (getter 0x41c730). dmrconfig (`_unused10` = 0b111111) and qdmr (bits 2-7 = 1) treat it as a constant. | CPS code [Plus] [CPS-only] | none; the engine writes 0 for keys 1-16 |
| Message Format | +0x1F 0x40 | 0 DMR Format, 1 M Format. Default DMR. | CPS only (getter 0x41fef0, combo 0x828). dmrconfig (`_unused12`) and qdmr (`setBit(31,6)`) write a constant 1. md380tools' CompUDP is a different bit. | CPS file [CPS-only] | `MsgFmt` |

**Analog Data**

| CPS label | Offset / mask | Encoding (default) | Sources | Status | Config |
|---|---|---|---|---|---|
| CTCSS/DCS Dec | +0x18, uint16 | 0xFFFF = None. CTCSS: 4 BCD digits in 0.1 Hz (0x0670 = 67.0 Hz). DCS: top nibble 0x8 = N, 0xC = I, and the low 3 BCD digits are the code (0x8023 = D023N, 0xC023 = D023I). | all agree | agreed | `RxTone` |
| CTCSS/DCS Enc | +0x1A, uint16 | As Dec | all agree | agreed | `TxTone` |
| Rx Signaling System | +0x1C | 0 Off, 1-4 = DTMF-1..4. Decode 1-8 are enabled only when this is not Off. | all agree | agreed | `RxSig` |
| Tx Signaling System | +0x1D | 0 Off, 1-4 = DTMF-1..4 | all agree | agreed | `TxSig` |
| QT Reverse | +0x05 0x03 | 0 = 180, 1 = 120, 2 = 240, 3 = Silent. Greyed until a CTCSS tone is set. Default 180. | CPS only (combo 0x81c, getter 0x41ecf0). dmrconfig `_unused7a` writes both bits 0; qdmr's `clear()` clears only 0x01. md380tools (MD-380) uses +0x04 0x08, which the CPS keeps as a hidden legacy combo. | CPS file [UV390] [CPS-only] | `QTRev` |
| Non-QT/DQT Turn-off Freq | +0x05 0xC0 | 0 = 259.2 Hz, 1 = 55.2 Hz, 3 = None. The CPS also reads 2 as None, and writes None as 3. Default None. | dmrconfig, qdmr UV390 KillTone, CPS (0x41ee00) | agreed | `TurnOff` |
| Display PTT ID | +0x03 0x80 INV | 0 = ticked. Default unticked. | dmrconfig, qdmr, md380tools "!PTT_ID", CPS | agreed | `PTTID` |
| Reverse Burst/Turn-off Code | +0x04 0x04 | 1 = ticked (not inverted). Default ticked. Greyed until a tone is set. | CPS only (getter 0x41d360). The md380tools map says "!RevBurst" (inverted); dmrconfig and qdmr write a constant 1. | CPS file [CPS-only] | `RevBurst` |
| Decode 1 … Decode 8 | +0x0E, bit n-1 (0x01 … 0x80) | 1 = ticked | qdmr `dtmfDecode(0x0e)`, CPS (DDX 0x813-0x81a). md380tools (MD-380) puts them at +0x0D, which is GPS System on this model. dmrconfig `_unused9` writes 0. | agreed [UV390] | `Decode` (for example `12------`) |

**Hidden controls and constant bits.** Preserve these.

| CPS label | Offset / mask | Encoding | Sources | Status |
|---|---|---|---|---|
| Compressed UDP Data Header (hidden at runtime) | +0x03 0x40 INV | 0 = compressed | CPS (inverted before DDX 0x81f; default init writes 1), md380tools chirp. The md380tools map ("CompUDP", not inverted) disagrees; dmrconfig and qdmr write a constant 1. | agreed. On the Plus, Message Format replaces it in the dialog. |
| Emergency Alarm Indication (hidden in the template) | +0x03 0x04 | 1 = ticked | CPS only (DDX 0x7e5); dmrconfig writes 0 | CPS code |
| Emergency Call Indication (hidden in the template) | +0x03 0x10 | 1 = ticked | CPS only (DDX 0x7e7) | CPS code |
| QT Reverse, legacy (hidden combo 0x7ec) | +0x04 0x08 | 0 = 180, 1 = 120 | md380tools map, CPS (0x41d4a0); dmrconfig and qdmr write 0 | agreed |
| Signaling Squelch (hidden combo 0x80c) | +0x05 0x0C | 0 None, 1 And, 2 Or | CPS only (0x41ead0) | CPS code. It overlaps the Privacy Switch bit, so never expose it on the Plus. |
| GPS System (hidden at runtime) | +0x0D | 0 None, 1-16 | qdmr, CPS (combo 0x7f2). md380tools calls the byte Decode (MD-380); dmrconfig writes 0. | agreed |
| Send GPS Info / Receive GPS Info (hidden) | +0x1F 0x01 / 0x02, INV | 1 = off | qdmr, CPS (DDX 0x82a/0x82b); dmrconfig writes 1 | agreed |
| (no control) | +0x03 0x20 | Unknown, and the CPS has no accessor for it. dmrconfig and qdmr write 1 on new channels. The bit differs between radios on otherwise identical channels and changes after edits on the radio's keypad, so the radio probably writes it. | none | unknown |
| (no control) fixed bits | +0x00 0x60, +0x04 0x20, +0x08 0xC0, +0x1E 0x0C, +0x1F 0xA0 | Observed constants: 11, 1, 00, 11 and 1/1. The CPS default init touches none of them. | dmrconfig writes them all. qdmr writes +0x04 0x20, +0x1E 0x0C and +0x1F 0xA0, but not +0x00 0x60 and not +0x08 0x80 (it clears only 0x40). | unknown |

---

## 14. DTMF Signaling

The block starts at 0x30000. qdmr calls 0x2F010-0x31000 "reserved", and no
other tool maps it.

- **CPS files** cover the controls of DTMF-1.
- **The CPS code** covers DTMF-2 to DTMF-4, the encode list and the decode
  entries.

Config tables: `DTMFSystem`, `DTMFEncode` and `DTMFDecode`.

**DTMF strings.** A string is a length byte, then the digits two to a byte,
low nibble first: 0-9 = 0x0-0x9, A-D = 0xA-0xD, * = 0xE, # = 0xF. A string
holds at most 30 digits, and the CPS shows nothing for a length above 30.
Example, on erased bytes: "1" = `01 F1`.

The CPS's encoder (0x4443a0) writes the length byte and only the nibbles of
the new digits; nibbles past the new length keep their old values. On a
character it cannot encode, it stops writing digits but still stores the full
length. Typing "TEST" therefore stores length 4 and no digits, which reads
back from erased bytes as "####".

**Systems DTMF-1 to DTMF-4**: 0x30000 + (s-1) x 0x30. Channels select one
through +0x1C/+0x1D. Analog One Touch rows select one through call types 8-11.

| CPS label | Offset / mask | Encoding | Config column |
|---|---|---|---|
| First Digit Delay[ms] | +0x00 | ms = raw x 10, 100..2550 | `FirstDelay[ms]` |
| First Digit Time[ms] | +0x01 | ms = raw x 10, 30..2550 | `FirstTime[ms]` |
| Digit Duration Time[ms] | +0x02 | ms = raw x 10, 30..2550 | `Duration[ms]` |
| Digit Interval Time[ms] | +0x03 | ms = raw x 10, 30..2550 | `Interval[ms]` |
| *# Digit Time[ms] | +0x04 | ms = raw x 10, 0..2550 | `StarHash[ms]` |
| D Key Assignment[ms] | +0x05 | 0 = "D Key"; otherwise ms = raw x 10, 10..2550. The CPS's spin starts at 10 ms, but its up arrow from D Key stores 0 again: a file saved after that click showed no change. | `DKey[ms]` |
| Next Sequence Decode[s] | +0x06 | s = raw x 0.1, 0.2..25.5 | `NextSeq[s]` |
| Auto Reset Time[s] | +0x07 | Seconds, 1..255 | `AutoReset[s]` |
| DTMF Side Tone | +0x08 0x01 | 1 = ticked | `SideTone` |
| (none) | +0x08 0x02 | No CPS control; 1 in every image examined. Preserve. | — |
| PTT ID | +0x08 0x0C | 0 None, 1 Pre Only, 2 Post Only, 3 Pre & Post | `PTTID` |
| Group Code | +0x08 0xF0 | 0 None, 1 A, 2 B, 3 C, 4 D, 5 *, 6 # | `GroupCode` |
| (none) | +0x09..+0x0F | 0xFF. Preserve. | — |
| KeyUp Encode | +0x10, 16 bytes | DTMF string | `KeyUp` |
| KeyDown Encode | +0x20, 16 bytes | DTMF string | `KeyDown` |

Every image examined had no DTMF set up and held the same values in all four
systems:
- +0x00..+0x04 `28 0A 0A 0A 0A` (400, 100, 100, 100 and 100 ms);
- +0x05 0x00 (D Key);
- +0x06 0x14 (2.0 s);
- +0x07 0x0A (10 s);
- +0x08 0x03.

The md380tools factory image has 0x0A at +0x05 and 0x02 at +0x06.

**Encode list 1-32**: 0x300C0 + (k-1) x 0x10. Each entry is one DTMF string.
An empty entry is a length byte of 0x00, then 15 x 0xFF. The CPS always keeps
a code in encode 1 (the factory code is "1", `01 F1`), and the engine refuses
to empty it.

**Decode 1-8**: 0x302C0 + (k-1) x 0x18. Channels enable each entry through the
Decode 1-8 bits at +0x0E.

| CPS label | Offset | Encoding | Config column |
|---|---|---|---|
| DTMF ID | +0x00, 16 bytes | DTMF string | `ID` |
| Response Type | +0x10 | 1 = Kill, 3 = Active. Other values have no CPS word. | `Response` |
| Decode Type | +0x11 | 0 None, 1 Sel Call | `DecodeType` |
| ACK | +0x12 | 0 = none, n = encode entry n (1..32) | `ACK` |
| ACK Delay Time[ms] | +0x13 | 0 = Off; otherwise ms = raw x 50, 50..12750 | `ACKDelay[ms]` |
| Revert CH | +0x14, uint16 | 0 = Selected, n = channel n | `Revert` |
| (none) | +0x16..+0x17 | `FF FF`. Preserve. | — |

The images examined hold `03 00 00 00 00 00 FF FF` at +0x10..+0x17 in every
entry: Active, None, no ACK, Off, Selected.

---

## 15. VFO Mode

VFO A is at 0x2EF00 and VFO B at 0x2EF40, 64 bytes each (CPS channel indexes
4029 and 4030). The page has VFO A and VFO B tabs, with the same three groups
as Channel Information. The CPS edits these records with the channel
accessors, so every field has the offset and encoding given in section 13.
The exceptions are listed below.

- **CPS files** cover VFO A.
- **The CPS code** covers VFO B.
- qdmr is the only other tool that knows these records
  (`ADDR_VFO_CHANNEL_A`).

The config carries each field as a scalar, `VFO A <CPS label>` or
`VFO B <CPS label>`.

| CPS label | Offset | Encoding | Status |
|---|---|---|---|
| Step (combo "2.5K" … "50K") | +0x20 | An index into 2.5, 5, 6.25, 8.33, 10, 12.5, 20, 25, 30 and 50 kHz. For example, 0x05 = 12.5 kHz. qdmr's formula, step = (n+1) x 2.5 kHz, is wrong. | CPS file |
| (none) | +0x21; +0x22..+0x3F | 0xFF; 0x00 (observed). There is no channel name. | unknown (preserve) |
| Privacy Switch | +0x05 0x04 with +0x02 | Switching privacy off is the same as Privacy None: the CPS clears the type and the key at +0x02 and clears +0x05 bit 2. | CPS file |
| Privacy No. | +0x02 0x0F (+0x1E 0xF0 for Universal) | As for channels. The VFO records seen so far hold 0xF in the +0x1E high nibble, so making a VFO Universal must write 0 there for keys 1-16, as the CPS setter 0x41c820 does. Otherwise the CPS shows Privacy No. 241 or higher. | CPS code |

The CPS's limits apply to the VFOs as they do to channels:
- Admit Criteria offers Correct CTCSS/CDCSS on analog only and Color Code on
  digital only.
- With DCDM on, TOT is 15 to 60 s.
- TOT offers Infinite and 15..555 s.
- Frequencies are 136-174 or 400-480 MHz.

---

## 16. Open questions

1. **What the firmware does with fields no document explains.** Untested:
   - Voice Announcement = Chinese;
   - Front Keyboard Lock;
   - Public Zone;
   - Channels Hang Time;
   - Message Format = M;
   - the recording items (Delete all records, Record Switch).

   On S119.038, Power On Voice and TX/RX LED showed no visible effect when
   ticked. What TX/RX LED controls is still unknown.
2. **PC Programming Password.** Does the radio refuse cable programming once a
   password is set? Untested.
3. **Power on the 10 W radio.** Does High (raw 3) give 10 W? RF output has not
   been measured at any level; that needs a wattmeter.
4. **Privacy Type (0x2092).** The order of the CPS's list (INI key
   "PrivacyType") is not traced, and no CPS file covers the Privacy Setting
   page.
5. **Legacy keys.** The Basic key byte order (qdmr: little-endian; md380tools:
   big-endian) and the Enhanced key byte reversal have never been checked
   against a CPS file.
6. **Channel +0x03 bit 0x20.** The CPS has no accessor for it. It is probably
   written by the radio, and its meaning is unknown.
7. **Basic Information.** Unknowns:
   - which identify block feeds Hardware Version, MCU Version and Unique
     Device ID;
   - why the page shows them blank;
   - what bytes 16-19 and 28-31 of a2 01 mean;
   - what the 10 W radio's frequency-range bytes hold.

   `.rdt` diffs cannot settle these, because the radio reports identify data
   itself.
8. **One Touch Access and Number Key.** These are mapped from the CPS code and
   qdmr only. No CPS file covers them.
9. **Universal keys above 16.** What the radio does with a Universal channel
   whose +0x1E high nibble is not 0 is untested.
10. **The three offline-only pages.** Nothing written on Digit Emergency
    System, DTMF Signaling or VFO Mode has yet been read back from a radio or
    observed on the air.
11. **Hidden controls and unmapped bits.** The CPS hides some controls for
    this model:
    - General: Private Calls, Escalert Tone, Scan Priority Alert, the mic
      gains, Auto Shutdown, GPS Report Format and the 0x20E2 bits;
    - Menu: Privacy, Clock, CH Voice Announcement;
    - Channel: the hidden channel controls.

    Their firmware meaning is unknown, as is the meaning of every byte listed
    under "the rest of the record". Preserve them all.

---

## 17. Hazards in other tools

Each item says what the tool gets wrong and which reading is right.

**qdmr**

| Area | What qdmr does | Right reading |
|---|---|---|
| Emergency base | `#define ADDR_EMERGENCY_SETTINGS 0x5A50` and `ADDR_EMERGENCY_SYSTEMS 0x5A60` contradict qdmr's own memory-map table (0x5A70/0x5A80). Code that uses the defines, such as `clearEmergencySystems()` on a UV390, overwrites all 16 Basic privacy keys (0x5A50-0x5A6F), the real emergency settings (0x5A70) and the first 8 bytes of System 1's name. | The table is right: radios, CPS saves and the md380tools factory images all put the block at 0x5A70. |
| Emergency durations | Remote Monitor Duration and Hot Mic Duration read as raw x 10 s | Whole seconds |
| Emergency revert | 0 = Disabled, 0xFFFF = Selected. `isValid()` drops any system whose revert is 0. | 0 = None, 0xFFFE = Selected |
| Emergency system `clear()` | Writes Alarm Type into name byte +0x00 (0x4C, "L") instead of +0x20 | A bug |
| Emergency +0x20 bit 7 | Drawn as a fixed bit | Tx Interrupt |
| Model Select A | Code (`DM1701Codeplug::channelModeA()`) uses 0x2083 bit 3, against its own layout docs (bit 2). The likely cause is a CPS remap (0x43b6d0/0x43a800) for another 80-byte-channel model, which moves 0x2083 bits 2-5 to bits 3-6; the CPS does not apply it to the UV390. Writing bit 3 flips an unrelated bit. | Bit 2 (CPS file) |
| Power On / Radio Program Password | `getBCD8_le`: reversed digit order | BCD, most significant digit first (CPS file) |
| Last Programmed Date | Reads the year as little-endian BCD4, so `20 25` decodes as 2520 | Big-endian (radio) |
| Voice Announcement | 0x2082 bit 2 drawn as a fixed 0 | English/Chinese bit |
| Keypad Lock raw 0 | 0 s | Manual |
| Privacy Type 0x2092 | "unused, set 0x00" | A live combo index. Preserve it. |
| Menu byte 0x20F7, Program Key, Monitor | Fixed values or "unused". `clear()` writes 0xFF to 0x20F7. That hides New Contact and Group Call, which happens to match the CPS default, but shows Select Radio ID, Delete all records and Power On Voice. `clear()` also writes 0 to Program Key, Talkaround and Password and Lock, and shows Monitor. | The CPS bits in section 4 |
| Channel Lone Worker | `{0x0000, 8}` makes the getter and setter no-ops | +0x00 bit 7 |
| Allow Talkaround | Inverted in the TyT base class and `uv390_channel.txt` (the UV390 override is right) | Not inverted (CPS file) |
| Emergency Alarm Ack | `uv390_channel.txt` says bit 5 (the code is right) | +0x03 bit 3 |
| Power | Doc says 0/1/2 (the code's 0/2/3 is right) | 0 Low, 2 Middle, 3 High |
| Band Width | The API writes only 0 or 2, so 20 kHz is lost | 0/1/2 = 12.5/20/25 kHz |
| Privacy type | Knows only 0-2 | 3 = Universal [Plus] |
| +0x1E high nibble, +0x1F bit 6 | Written as constant 1s, so new channels get a Universal high nibble of 0xF and M Format | 0 for keys 1-16; DMR Format by default |
| Leader/MS, QT Reverse | `clear()` writes Leader; clears only QT Reverse bit 0x01 | The CPS defaults: MS; 180 (both bits 0) |
| Fixed channel bits | Does not write +0x00 0x60 or +0x08 0x80 | Preserve them |
| One Touch | Mapped but never encoded for the UV390 | Section 5 |
| Emergency Short Press, SB3/P1-P4 | "unknown, set 0x01"; "unused" | Hidden CPS fields; preserve them |
| VFO step | step = (n+1) x 2.5 kHz | List index (section 15) |
| Scan list TxCh 0xFFFF | Called "none" (naming only) | Last Active Channel |
| Boot settings `clear()` | Writes 0xFF at 0x2F00C, where radios hold 0x00 | Do not write this region |

**md380tools** (MD-380 layout)

| Area | What md380tools says | Right reading |
|---|---|---|
| Offsets in `map.xlsx` | `.rdt` offsets | Image = `.rdt` - 0x225 (section 1) |
| Long Press | `radio_config.h`: "4 ms units" | x 250 ms |
| Lone Worker Reminder | Minutes | Seconds |
| VOX Sensitivity | `map.xlsx`: 0-10 | 1-10 |
| Radio ID | `map.xlsx`: 3 bytes | 4 bytes, 0x2087 = 0 |
| Freq/Channel Mode | Calls 0 "MR" | 0 = Freq |
| Admit Criteria | Two independent flags | 2-bit enum |
| Squelch | Tight/Normal at +0x00 0x20 | Level 0-9 at +0x0F |
| Decode 1-8 | +0x0D | +0x0E (+0x0D is GPS System) |
| QT Reverse | +0x04 0x08 | +0x05 bits 0-1 (+0x04 0x08 is a hidden legacy combo) |
| Reverse Burst | Inverted | Not inverted (CPS file) |
| Compressed UDP | `map.xlsx` not inverted; chirp inverted | Inverted |
| Basic keys | chirp: 0x5A40, big-endian | 0x5A50 (byte order open) |
| Scan list +0x26 | "?FF" | 0xF1 |

**dmrconfig** (upstream `uv380.c`, unless this engine's changes are noted)

| Area | What dmrconfig does | Right reading |
|---|---|---|
| `general_settings_t` | Declares bytes 0x2080-0x2082 and 0x2095 most-significant bit first, but GCC allocates bitfields least-significant bit first, so every named bit in those bytes is mirrored (bit n is really bit 7-n). It also calls live data unused: 0x2080 bits 6-7 (Tx Mode), 0x2083 (Model Select), 0x2092 (Privacy Type) and 0x20AB (Time Zone, Call Match). The struct ends at 0x20CF. | This engine keeps the struct, but `cpsfields.c` replaces it for every byte mapped here. |
| Radio ID | `radio_id[3]` writes 3 bytes, never touches 0x2087 and has no range check | 4 bytes, 0..16776415 (the engine writes the CPS's form) |
| Back Light Time | `backlight_time:2` at bits 6-7 | Whole byte |
| Power | `POWER_NAME` prints raw 1 as Low | The CPS shows raw 1 as High |
| Squelch | Prints values above 9 as 1 | Keep raw (`raw:0xNN`) |
| Channel write | A config write erases the whole channel bank and rebuilds each channel from its table plus `erase_channel` defaults. Everything the tables do not carry is lost, including the privacy bytes. `erase_channel` writes 0xF to the +0x1E high nibble (a Universal channel then shows Privacy No. 241 or higher in the CPS) and M Format at +0x1F bit 6. Digital channels are forced to squelch 1, 12.5 kHz and no tones; analog channels to Color Code 1, Slot 1, no group list and no contact. | This engine restores each record of the same mode before applying a row. It writes the CPS's 0 high nibble and DMR Format on new digital channels, and stops forcing fields the row does not carry. |
| Scan lists | Erased together with the channels, which resets Signaling Hold Time and Priority Sample Time to 500 and 2000 ms | This engine snapshots and restores them. |
| Zone and scan-list members | Sorted on print, so a read-modify-write reshuffles them | The stored order is the order the radio steps through. The engine prints it as stored. |
| Empty contacts | Written as `FF FF FF FF` | `FF FF FF C0`, as the CPS writes |
| CPS Software Version | Stamped with 0x0D and dmrconfig's version (the CPS shows "V=1.01") | Deliberate in this engine; exclude 0x2001-0x200B when comparing images |
