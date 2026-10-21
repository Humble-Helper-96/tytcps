# Model notes

What is known about the radios near the MD-UV390 Plus, what isn't, and how an
owner can help. Only the MD-UV390 Plus has been tested with TYTcps; the rest
comes from the engine's model table (dmrconfig), qdmr, md380tools and owners'
reports, and says so.

| Model | Identifies as | Codeplug | TYTcps | Keys (Universal / AES) | Known | Unknown |
|---|---|---|---|---|---|---|
| **MD-UV390 Plus** 5 W | `MD-UV390` | 851968 bytes | **supported, tested** | yes | everything in this program; firmware S119.038 | - |
| **MD-UV390 Plus** 10 W | `MD-UV390` | 851968 bytes | **supported, tested** | yes | same layout as the 5 W; firmware S219.043 | whether Power High is the full 10 W (needs a wattmeter) |
| MD-UV390 (not Plus), Retevis RT3S | `MD-UV390` | 851968 bytes, same layout (dmrconfig, qdmr) | should work, untested | **no**: Universal channels sound garbled (owner's report) | codeplug and Basic/Enhanced privacy work (owner's report) | what it does when sent a key table: refuse it (TYTcps then says "didn't accept the key table") or take it silently; its firmware version strings |
| MD-UV380 | `MD-UV380` | 851968 bytes, same layout (dmrconfig) | should work, untested | unknown | the UV390 without the IP67 case | everything specific to it |
| MD-UV380/390 with GPS | `MD-UV380` / `MD-UV390` | 851968 bytes | should work, untested | unknown | the GPS settings exist in the codeplug; TYTcps keeps them as they are | which firmware shows the GPS menu (the stock CPS hides it for the Plus) |
| MD-2017, Retevis RT82 | `2017` | 851968 bytes, different layout | not supported | - | dmrconfig and qdmr support it | - |
| MD-9600 | `MD9600` | 851968 bytes, different layout | not supported | - | dmrconfig supports it | - |
| Baofeng DM-1701, Retevis RT84 | `DM-1701` | different | not supported | - | dmrconfig and qdmr support it | - |
| MD-380, MD-390, Retevis RT3/RT8 | `DR780`, `MD390` | 262144 bytes | not supported | - | dmrconfig, qdmr and md380tools support them | - |

Why the same size isn't enough: the MD-2017 and MD-9600 save images of the
same 851968 bytes as the UV390 but lay them out differently, and an image file
doesn't say which radio it came from. So TYTcps checks the model the radio
reports before every codeplug write, and writes only to `MD-UV390` and
`MD-UV380`.

Why a non-Plus UV390 can't be refused up front: over USB it reports the same
model string as the Plus, and nothing found so far (identify blocks, firmware
string) tells them apart. TYTcps therefore offers keys to any `MD-UV390` /
`MD-UV380`, and says on the Keys tab and after every key write that only the
Plus uses them.

## How to help

If you have one of the "should work, untested" radios:

1. In TYTcps, Identify, then Read (both only read the radio).
2. ≡ → Save diagnostics… and keep the file. It holds the model, firmware and
   unit information and the codeplug settings, never keys or passwords.
3. Note the model and firmware version shown in the radio's own menu, and
   whether it is a Plus.
4. Send both. Please don't write keys to a radio you aren't sure is a Plus
   just to find out; if you do, say whether TYTcps reported "didn't accept
   the key table".
