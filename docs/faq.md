# TYTcps FAQ

Questions people run into, most of them things that surprised us while
building TYTcps. The [user guide](guide.md) covers normal use.

### Is it legal to use encryption?

Encryption isn't permitted on amateur radio frequencies in most countries.
You're responsible for where you use it.

### Why does the radio restart every time I do anything?

That's how these radios work. Every programming session, even just
identifying the radio, puts it into "PC Programming Mode" and restarts it
at the end. It's back on USB about 3 seconds later. It's also why TYTcps
never talks to the radio by itself: identifying it is a button, not
something that happens in the background.

### Why can't TYTcps show me the keys on my radio?

The radio won't give them back. Asked for its key table, it returns the
slot types and names with every key byte set to zero. The stock CPS can't
read them either. That's why TYTcps keeps a ledger of which key set went to
which radio, and why every key write ends with a reminder to test on the
air.

### I put the right key in a different slot and the radio can't decode. Why?

The key's *slot number* travels over the air, not the key. The receiving
radio looks that number up in its own table. Every radio has to hold the same
key in the same slot. A channel picks a slot; the key's type (AES-256,
AES-128, ARC4) belongs to the slot, not the channel.

### Why does TYTcps read the radio twice?

Because a single read can come back corrupted without any error. TYTcps only
trusts two reads that agree, and after every write it reads the radio back
and compares it byte for byte.

### Why won't it work with two radios plugged in?

Radios of the same model can report the same USB serial number, so nothing
can tell which is which. Connect one at a time.

### TYTcps says the radio is in use by another program.

Usually a virtual machine with USB passthrough has it, often one running the
Windows CPS. Shut the VM down fully: a paused VM still holds the radio. Close
any other programming software too.

### Do I need a particular firmware for AES?

Forums say S219.043 or later. That's wrong, or true only for some models:
AES works on the 5 W Plus with S119.038. Don't flash firmware just for this.

### Will it work with a radio that isn't a Plus?

An MD-UV390 that isn't a Plus looks exactly like a Plus over USB. Owners
report that it takes codeplugs and Basic or Enhanced privacy, but its
Universal (AES) channels sound garbled. See [Which radios](../README.md#which-radios)
and [model notes](models.md).

### When I write a file from one radio to another, which Radio ID does it get?

Its own. A write keeps each radio's Radio ID and Radio Name and sends
everything else, so one file serves the whole fleet. Change a radio's ID or
name on the General tab if you mean to.

### The stock CPS shows a new "last programmed" date after I only read the radio.

The CPS shows the time of the read there without writing anything. It isn't a
sign the radio was changed.

### Can I use the original dmrconfig instead?

Not for writing to these radios. Its `-c` reads the radio once and writes
that read back with your changes, unchecked; a bad read gets programmed into
the radio. That's how one of our test radios got a damaged codeplug. The
engine bundled with TYTcps reads twice, compares, and verifies every write.

### Does the PC Programming Password protect my radio?

No. The radio hands the password to any program that asks, and doesn't check
it on the cable: only the stock CPS asks you for it. TYTcps doesn't set it. A
radio that has one keeps it.

### Some settings don't seem to do anything.

A few fields exist in the stock CPS but have no effect on the firmware we
tested (S119.038): Power On Voice and TX/RX LED, for example. Their hover
hint says "the firmware may ignore it". Three fields TYT never documented
(Channels Hang Time, Public Zone, Front Keyboard Lock) are marked
"Undocumented". Unticking Text Message in the Menu page only hides writing a
new message; the inbox stays.

### Why does Voice Announcement offer Chinese when the stock CPS doesn't?

The CPS's own list has English and Chinese, but it only ever shows the first
entry. TYTcps offers both; what the radio does with Chinese hasn't been
tested.

### What's in a codeplug file? Can I share it?

Channels, contacts and every setting. No AES keys, but, like the stock CPS's
files, the older Basic and Enhanced privacy keys in plain form. Keep codeplug
files private.

### A value shows "raw:0x…" or "(kept)". What does that mean?

The codeplug holds a value the stock CPS has no word for, often in a radio
that was never fully programmed. TYTcps shows it and leaves it exactly as it
is, unless you pick a real value.

### Something went wrong. How do I report it?

≡ → **Save diagnostics…** and send that file. It never contains a key file
or a codeplug image, passwords are removed, and it's checked against every
key in your fleet folder before it's saved.
