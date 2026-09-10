# ROM image handbook

This handbook covers the ROM-specific parts of Atari File Forge. It is intended
for ROM collectors, developers, repairers and anyone preparing images for a
programmer. The main [README](../README.md) remains the complete application
guide. This document goes deeper into TOS ROM interpretation, maintenance and
hardware preparation.

Return to the [documentation index](README.md) for installation, media-format,
file-editor, firmware and release references.

## Safety first

A ROM image is executable machine data. It does not contain a GEMDOS
filing system, so names shown by the application are decoded structures and
evidence, not files that can be mounted or extracted.

Before changing a ROM:

1. Keep the original dump outside Atari File Forge.
2. Create a named checkpoint in **Edit -> Checkpoints**.
3. Record the machine, socket, ROM board, chip type and any link settings under
   **Tools -> ROM Workbench -> Project**.
4. Save and compare checksums before programming a device.
5. Test in an emulator or a spare programmable device before replacing a
   known-good ROM.

A recognised release or a valid header proves only that a structure was
decoded. It does not prove that the code is safe for a particular machine,
ROM socket, accelerator configuration, expansion board or physical device.

## Supported ROM input

The normal image picker recognises `.rom`, `.img`, `.rom0` through `.rom3`,
and `.bin` files that contain a recognisable TOS header. Use **Raw format
override -> Atari ROM** when a headerless binary or unusually named dump is
misidentified.

The application supports:

- 192 KiB TOS ROMs (TOS 1.00 to 1.04, mapped at `$FC0000`);
- 256 KiB TOS ROMs (TOS 1.06 to 2.06, mapped at `$E00000`);
- 512 KiB TOS ROMs (TOS 3.06 and 4.0x, mapped at `$E00000`);
- 1 MiB EmuTOS builds, and every other EmuTOS size;
- 128 KiB cartridge ROMs (`$ABCDEF42` at `$FA0000`);
- images divided into configurable logical banks, 64 KiB by default;
- a partial final bank, preserved without padding and reported by Image Health;
- two-chip and four-chip byte-interleaved source sets;
- custom byte images where no standard header can be proved.

Logical bank size must be at least 256 bytes and aligned to 256 bytes. The bank
view does not rewrite, pad or reorder bytes merely because its layout settings
change.

EmuTOS 1.4 is committed under `firmware/emutos` and is the only firmware the
project redistributes. Atari's own TOS releases are not, and the built-in
identity catalogue therefore lists EmuTOS only.

## Opening one image or a physical chip set

### One image

1. Choose **Open image** in an empty pane.
2. Select the ROM or BIN.
3. Confirm the platform and byte layout in the ROM summary.
4. Use the raw Atari ROM override if automatic detection is inappropriate.
5. After opening, choose **Tools -> ROM layout** if the logical bank size,
   erased byte, target family or layout needs correction.

### Two or four physical files

Select two or four equal-sized component files together. The open dialog asks
how they relate:

- **Concatenate** places each selected component after the previous component.
  Use this for files that represent consecutive banks, such as the three
  even-chip halves of a 192 KiB ST ROM read separately.
- **Byte interleave** reconstructs logical CPU byte order from byte-wide
  physical chips. Every ST-family board is a 16-bit bus fed by pairs of
  byte-wide chips, so two lanes (even and odd bytes) is the normal case. Four
  lanes exist for boards that split each byte lane across two devices.

Component order matters. Keep the file selection order consistent with the
physical sockets. The saved ZIP records that order and contains reconstructed
files in `ROM-components`.

## Reading the ROM pane

![ROM bank inventory showing address, identity, purpose and utilisation](../app/static/help/rom-pane.png)

The pane is a bank inventory. At normal width it has four columns. In a narrow
or multi-pane layout, each bank becomes a two-column information card.

| Field | Meaning |
| --- | --- |
| Bank | Zero-based logical bank number using the current bank size. |
| File address | Byte offset in the complete saved image. It is not a CPU address. |
| Mapped address | The CPU window for the chosen target. A 192 KiB TOS maps to `$FC0000-$FEFFFF`; 256 KiB and 512 KiB images map from `$E00000`; a cartridge maps to `$FA0000`. |
| Identity | Release and country from the header, such as `TOS 1.04 UK` or `EmuTOS 1.4 US`, a cartridge application name, or a clear `Empty bank` or raw-data description. A bank after the first is labelled as a continuation of the whole image. |
| Version and copyright | The release, version word, country, video standard, machine and build date decoded from the header. |
| Purpose | TOS, EmuTOS, cartridge, continuation, raw or erased. |
| Processor | 68000 for TOS 1.x and 2.x, 68030 for TOS 3.06 and 4.0x. This follows the release, not a header flag. |
| Entry points | Proven reset, TRAP handler, dispatch table and VDI or AES entries in mapped address form. |
| Programmed | Bytes that differ from the configured erased value. |
| Percentage | Programmed bytes divided by actual bank length. This is not filesystem free space. |
| Duplicate result | Other banks with byte-identical content, or `Unique bank contents`. |
| SHA-256 | A shortened fingerprint. Point at it for the complete value. |

The guidance strip provides the shortest route to the next level:

- select the information icon to decode the bank;
- double-click the row to open its first byte in the hex editor;
- use **Tools -> ROM Workbench** for code, revision and hardware work;
- use **Tools -> ROM layout** to change interpretation without rewriting data.

## Decoded bank information

![Decoded ROM information with fingerprints, header and entry-point evidence](../app/static/help/rom-decoder.png)

The information dialog deliberately begins on its heading. Opening it does not
select or expand the first entry. Tab moves to the first interactive control.

### Fingerprints and byte statistics

The bank report includes:

- its exact byte range in the complete image;
- SHA-256 and CRC-32 fingerprints;
- Shannon entropy from 0 to 8 bits per byte;
- the number of distinct byte values;
- counts of configured erased bytes, zero bytes and `&FF` bytes;
- the first and last non-erased offset;
- printable-byte count;
- byte-identical logical banks.

These values are diagnostics. High entropy can suggest compressed, encrypted or
dense code, but it is not a copy-protection detector. Printable strings can
suggest messages, resource text or build data, but string boundaries are not
files.

### TOS header

A TOS ROM begins with a `BRA.S` to the reset code, and the reset vector at
`$04` must name the same byte. That agreement is what the decoder requires
before it calls an image a TOS ROM; a file that merely starts with `$60` is
reported as raw data.

For a valid header the decoder reports:

| Offset | Field | Reported as |
| --- | --- | --- |
| `$00` | `BRA.S` to the reset code | Reset entry |
| `$02` | OS version word | Release (`$0104` is TOS 1.04, `$0206` is TOS 2.06, `$0306` is TOS 3.06, `$0404` is TOS 4.04) |
| `$04` | Reset vector | Reset entry, cross-checked with the branch |
| `$08` | OS base | Mapped address, checked against the image size |
| `$0C` | End of OS RAM usage | `osEnd` |
| `$14` | GEM memory usage parameter block | Followed to the AES initialisation routine when its `$87654321` magic is present |
| `$18` | Build date, BCD `MMDDYYYY` | Build date (TOS 1.00 is `$11201985`) |
| `$1C` | Configuration word | Country (bits 1 to 7) and PAL or NTSC (bit 0) |
| `$1E` | GEMDOS date word | Compared with the BCD date; TOS 1.02 and later |
| `$20` to `$2B` | GEMDOS pool, `kbshift` and `_run` pointers | Listed; TOS 1.02 and later |
| `$2C` | Reserved | `ETOS` on EmuTOS |

EmuTOS is recognised by the `ETOS` magic or by its `EmuTOS` boot text, and its
own version string (`1.4`) is reported in place of the compatibility version
word it writes into the header (`$0104` in the 192 KiB build, `$0206` in the
others). The country and video standard come from the configuration word on
both TOS and EmuTOS; the UK builds report country 3 and PAL, the US builds
country 0 and NTSC, and the multi-language builds country 127.

There is no editable title in a TOS header. Every string in the ROM is
addressed absolutely, so nothing can be renamed without moving code, and the
pane does not offer to.

### Entry points and dispatch tables

TOS records no table of its components. The BIOS, XBIOS, GEMDOS, VDI, AES and
desktop are linked into one image and nothing marks where one ends and the
next begins. What the ROM does prove are entry points, and every one the
decoder lists is backed by an instruction or a magic number:

- the reset code, from the header;
- the `TRAP #1` (GEMDOS), `TRAP #2` (AES and VDI), `TRAP #13` (BIOS) and
  `TRAP #14` (XBIOS) handlers, and the Line-A vector, from explicit
  `MOVE.L #handler,vector` instructions in the ROM;
- the BIOS and XBIOS dispatch tables, from the `LEA table(PC),A0` a TOS stub
  performs or the `MOVE.W count,D1 / LEA table,A0` an EmuTOS stub performs;
- the VDI entry, from the `CMP.W #$73,D0 / BNE / JSR` in the `TRAP #2` stub;
- the GEM memory usage parameter block and the AES initialisation routine it
  names.

A ROM that installs a vector through a table copy rather than an explicit
move, as TOS 4.0x does for GEMDOS, is reported as lacking that evidence rather
than given a guessed address. These entry points seed the Workbench
disassembler's reachability analysis.

When the ROM is opened as a volume (the `tosrom` filing system), the entry
points are listed in its validation report, and the volume itself has three
kinds of entry: `HEADER`, the proven header range; `OS`, everything from the
reset code to the end of the image, marked as unsegmented; and `DATA`, the
system-font block described below. The BIOS, XBIOS, GEMDOS, VDI, AES and
desktop are never presented as separate segments, because their boundaries
cannot be proved from the ROM alone.

### System fonts

The VDI's 6x6, 8x8 and 8x16 system fonts (and the 16x32 font of TOS 3.06)
carry 88-byte headers naming the font, its point size, character range,
offset table and glyph data. The decoder validates each pointer against the
ROM before accepting a header, so the same words inside a message are not
mistaken for a font. The fonts' headers, tables and glyph data together form
the `DATA` segment, reported only when those structures account for at least
nine tenths of the range they span. The 1 MiB EmuTOS build carries a second
font set for other character sets and reports it as `DATA2`.

### Cartridge structures

A cartridge ROM begins with `$ABCDEF42` and a chain of application headers,
each holding a pointer to the next, an initialisation pointer with flags in
its top byte, a run pointer, a GEMDOS time and date, a size, and an 8.3 name.
The decoder lists the chain and every in-ROM initialisation and run routine.
The cartridge application name is the one field the pane can rename, because
it is fixed at 14 bytes and nothing else moves.

## ROM Workbench

Open **Tools -> ROM Workbench** for maintenance and development. Its tabs share
the same working ROM and project metadata. Closing the Workbench does not save
the image to the host; use the pane save control for that.

### Overview

![ROM Workbench Overview with bank map, identity and audit result](../app/static/help/rom-workbench-overview.png)

Overview shows bank count, bank size, exact catalogue identity and health. The
bank map relates logical bank, file offset, decoded title, type and duplicate
banks. On an interleaved image it also describes physical byte lanes.

Audit findings can offer one narrowly defined repair:

- rewrite the GEMDOS date word at `$1E` from the BCD build date at `$18`.

The repair creates an automatic undo checkpoint. TOS 1.00 has no date word,
and the app does not offer a guess-based repair for a wrong OS base, a broken
reset vector or ambiguous code, because those cannot be corrected in one field.

**Identify this exact ROM** stores title, version, publisher, platform and notes
against the complete SHA-256. Built-in catalogue records live in
`app/rom_catalogue.json` and cover EmuTOS 1.4 only. User records live in an
owner-scoped catalogue in the work volume, so another browser owner does not
inherit them. Independently of the catalogue, the identity report states what
the header declares: release, version word, country, video standard, machine,
build date and mapped base.

### Disassembly

![ROM Workbench Disassembly showing controls, reachability and references](../app/static/help/rom-workbench-disassembly.png)

Select bank, architecture, mapped origin, byte offset and byte count. Numeric
fields accept normal `0x` notation. The result reports decoded instruction
count, reachable instructions and referenced targets.

| Architecture | Interpretation |
| --- | --- |
| 68000 family | Big-endian, as every Atari processor reads it. Bytes that decode to no instruction remain `DC.B` data. |
| 68010, 68020, 68030, 68040, 68060 | The same set with each generation's additions, so an instruction the target cannot run is not offered as if it could. |
| Auto | The processor the release implies: 68030 for TOS 3.06 and 4.0x, and the baseline 68000 otherwise. |

Proven entry points and dispatch-table addresses seed control-flow
reachability. Direct branch and call destinations receive cross-references.
System calls are labelled from the function word pushed before the `TRAP`:
`MOVE.W #$3D,-(SP) / TRAP #1` is reported as `GEMDOS Fopen`, `TRAP #13` and
`TRAP #14` are named from the BIOS and XBIOS tables, and `TRAP #2` is
reported as a VDI or AES call from the selector loaded into D0 (`$73` or
`$C8`). Absolute addresses are named from the ST memory map: the shifter,
palette, MMU, DMA and FDC, PSG, STE DMA sound, blitter, joypad, MFP 68901,
ACIA and SCC registers, the 68000 exception vectors including the TRAP and
MFP vectors, and the TOS system variables at `$380` to `$5FF`. A short
absolute operand is sign-extended the way the processor does it, so `$8240.W`
is reported as the palette at `$FF8240`. This is a bounded static analysis,
not an emulator. Indirect calls, generated code and vectors installed through
table copies can remain unresolved.

Project symbols use `address = label`, for example `0xE00030 = reset`.
Known regions use `start-end = meaning`, for example
`0xE00DA4-0xE00DD3 = BIOS dispatch table`. Save them in Project and
disassemble again. Symbols are applied consistently to every 68000-family
listing. Address keys may use decimal, `0x` hexadecimal or Motorola `$`
hexadecimal notation. Every word and address region is big-endian, because
that is how the hardware reads it.

For file-level disassembly, bookmarks, synchronized bytes, region
classification and emulator hand-off, see the
[file editor and code analysis handbook](FILE-EDITOR-GUIDE.md).

### Compare and guarded patches

Open a second ROM in another pane, then choose it in Compare. The report groups
contiguous changed byte ranges and counts changed bytes. You can export all
changes or tick reviewed ranges for a selective patch. Comparing two country
variants of the same TOS release, or a dump against the committed EmuTOS
build, is the quickest way to see where a ROM has been altered.

An Atari File Forge patch stores the patch format, complete source SHA-256,
complete target SHA-256, source and target sizes, and fixed byte ranges. Patch
creation has a 16 MiB safety limit. Applying a patch fails if the selected
source checksum is wrong, any range is invalid, or the completed image does not
match the target checksum. Patch application creates a normal image checkpoint.

### Build

The cartridge scaffold creates an inert `$ABCDEF42` cartridge with one
application header per name you enter, in 16 KiB, 32 KiB, 64 KiB or 128 KiB.
Each run routine is a single `RTS` and no initialisation is requested, so a
scaffold fitted to a machine before its program is written does nothing. It
is a development starting point, not a finished cartridge and not proof that
the named applications exist.

The file-archive builder stores named host bytes in the documented
`AFFARCHIVE1` layout inside a valid cartridge ROM. It needs a companion
program written for that layout. TOS lists the cartridge but does not read
the archive, and Atari File Forge does not describe it as a native filing
system.

Both builders replace all working ROM bytes after a dangerous-operation
confirmation and automatic checkpoint. A TOS operating-system ROM is never
built from a template: open a real TOS or EmuTOS image instead.

### Programmer

![ROM Workbench Programmer tab configured for two byte-wide chips](../app/static/help/rom-workbench-programmer.png)

Programmer prepares bytes for a physical device without changing the logical
working ROM. Available transforms are applied in a defined sequence:

1. pad with the configured erased byte, or mirror the image to the requested
   device size;
2. optionally swap adjacent byte pairs;
3. optionally swap 16-bit words within each 32-bit group;
4. optionally swap address-bit pairs such as `0:1` for A0 and A1, on a
   power-of-two device;
5. split the result into one, two or four byte lanes, then into the chips a
   board takes.

The chip sets a real board takes are offered by size:

| Image | Board | Chips |
| --- | --- | --- |
| 192 KiB | ST, Mega ST | six 32 KiB chips in three even/odd pairs (`even-1`, `odd-1`, `even-2`, ...) |
| 256 KiB | STE, Mega STE | two 128 KiB chips, even and odd |
| 512 KiB | TT, Falcon | two 256 KiB chips, even and odd, or four 128 KiB chips in two pairs |

The requested device must be large enough for the image, and the chip count
must be a multiple of the lane count that divides the device evenly.
Address-bit numbers must be valid for the device's address range and a bit
cannot participate in conflicting swaps. The ZIP contains each chip file,
named for its lane and position, and a programming report with transform,
size and checksum details. Verify those checksums against programmer
read-back. The chip files reassemble with **Byte interleave** on open:
concatenate each lane's pieces, then interleave the lanes.

### Project

Project fields are annotations. They do not modify ROM bytes. Store:

- hardware, board, socket and chip information;
- research or repair notes;
- address labels used by Disassembly;
- known address regions;
- retained emulator results.

The normal saved ZIP includes `ROM-project.json`, allowing the reasoning behind
a repair or build to travel with the ROM.

### Emulator

Open **Workbench -> Hardware profiles -> Emulator and debugger integration**,
choose the target machine and managed emulator, then save and apply the profile
to the ROM pane. The ROM Workbench reports that selection. Direct attachment is
enabled only when Atari File Forge can prove the selected machine's ROM slot,
bank mapping and replacement policy. It otherwise remains disabled and explains
that the programmer export or a machine-specific image is required. This is
intentional: launching an arbitrary ROM in the wrong machine can produce a
convincing but invalid result.

## Editing operations

| Operation | Result | Important restriction |
| --- | --- | --- |
| Rename image | Changes the working filename. | Does not alter anything inside the ROM. |
| Rename bank | Rewrites a cartridge's first application name in its fixed 14-byte field. | A TOS ROM has no title field and is refused; raw banks cannot be renamed as if they were files. |
| Add ROM banks | Appends one or several files. | Exact bank multiples split; silent truncation is refused. |
| Append empty bank | Grows by one configured bank. | Uses the configured erased byte. |
| Erase bank | Fills the selected bank. | Keeps bank and image size. |
| Cut, Copy, Paste | Moves or duplicates whole logical banks. | An overlapping move is atomic. |
| Drag between ROM panes | Copies selected banks in order. | Target layout and capacity rules still apply. |
| Hex edit | Replaces fixed byte ranges. | Cannot insert, delete or resize bytes. |
| Repair | Rewrites the GEMDOS date word from the BCD build date. | Offered only when the two disagree and the ROM is TOS 1.02 or later. |

ROM banks can move between ROM panes. A disk filesystem cannot represent a ROM
bank as a mounted folder. Where a destination can store ordinary files, use an
explicit file export or archive workflow rather than pretending a bank is a
filesystem.

## Hex editor behaviour

Opening Hex from the pane scopes the editor to that pane. Opening a table,
an entry point, a known region or the whole bank from the decoder scopes the
editor to the decoder dialog. Closing the nested editor returns to the same
decoder scroll position. If bytes were written, the decoder is rebuilt from the
new data.

Raw writes are fixed-size replacements and require the dangerous-operation
confirmation. The server rejects stale, overlapping and out-of-range changes,
creates an undo checkpoint, writes reviewed ranges, flushes storage and clears
decoded caches. Refresh the pane and run Image Health afterwards.

## Saving and accompanying files

Save produces a timestamped ZIP rather than replacing the browser-selected
source. A ROM save includes:

- the logical ROM image;
- a detailed technical README;
- `ROM-project.json`;
- reconstructed component files when a component set was opened;
- applicable loose-file metadata generated by other export operations.

The technical README records format, byte size, bank size, bank count, erased
byte, platform, logical layout, component order, recognised headers, bank
fingerprints and complete image SHA-256. Keep it with the programmed image.

After a successful save, the pane's changed indicator clears only when the
prepared archive corresponds to the current image revision.

## Health checks and troubleshooting

Choose **Analyse -> Image health dashboard** after structural changes and raw
edits. ROM checks include:

- zero length and invalid configured bank size;
- partial final bank;
- erased or unrecognised banks;
- byte-identical banks;
- an image size that is not a TOS or cartridge size;
- an OS base that does not match the image size;
- a GEMDOS date word that disagrees with the BCD build date;
- TRAP vectors for which no explicit install was found;
- current target and layout context.

### A release is missing or wrong

The image may have no TOS header, a reset vector that disagrees with the
branch, a different logical bank size, or it may be a byte-swapped or
interleaved dump. Confirm layout first, then inspect the first 48 bytes in the
hex editor. Use fingerprinted identity for collection metadata rather than
inventing a header repair.

### Entry points are missing

Static extraction intentionally favours precision. A vector installed through
a table copy, as TOS 4.0x installs GEMDOS, is invisible to it. Inspect the
reset code in Disassembly, follow the copy loop by hand, and save the
addresses you find as project symbols.

### A reported entry point is wrong

Record the ROM SHA-256, bank, reported entry and the instruction bytes at its
install site. The extractor needs better structural evidence or an additional
supported install pattern.

### The processor or mapped address looks wrong

Check target family, bank size and mapped origin. The processor follows the
release named by the version word, and the mapped base comes from the header,
which can itself be wrong in a modified image. A custom image may have no
single mapped origin.

### Disassembly looks like nonsense

Confirm architecture, origin and offset. You may be looking at text, font
glyphs, resource trees, an interleaved physical dump or code reached only
through a vector. Disassembly is not an automatic separation of code and data.

### A physical chip does not boot

Verify chip size, erase value, lane order (even before odd), byte and word
swaps, address-line mapping and programmer read-back checksum. Confirm the
board's links and ROM socket voltage. A 192 KiB image in a 256 KiB socket
needs the board strapped for the `$FC0000` base, not padding. Return to the
untouched original before trying another transform.

### The ROM is known but the catalogue says Unknown

Built-in and private identities are exact SHA-256 matches, and the built-in
catalogue lists EmuTOS only. A one-byte change, different padding or a
concatenated bank set is a different image. The identity report still states
what the header declares, which names the release and country without
proving the dump is unaltered. Use **Identify this exact ROM** only after
confirming that the dump is sound.

## What ROM support deliberately does not claim

Atari File Forge does not fully emulate a machine, infer component boundaries
that the ROM does not record, decompile machine code into source, defeat copy
protection, prove electrical compatibility, or convert arbitrary disk software
into a bootable ROM automatically. The cartridge scaffold and the file archive
are tools for developers who will supply the missing code. Labels such as
`unsegmented`, `declared` and `unrecognised` are intentional boundaries
between evidence and guesswork.
