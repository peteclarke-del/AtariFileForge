# The Atarinut GEMDOS engine

Atari File Forge does not depend on an external filing-system package. The
engine ships in this repository as `atarinut/`, needs nothing beyond the Python
standard library, and is versioned with the application.

## What it implements

The Atari ST stores files the way MS-DOS does: a boot sector with a BIOS
parameter block, one or two file allocation tables, a fixed root directory and
a data area of clusters. TOS reads FAT12 on floppies and FAT16 on hard disks.
The engine reads and writes both, and it gets the Atari details right rather
than treating the disk as a PC volume.

| Structure | What the engine does |
| --- | --- |
| Boot sector | Little-endian BPB at 0x0B, 24-bit serial at 0x08, six-byte OEM at 0x02. The jump and media byte are ignored, as TOS ignores them. |
| Boot checksum | A boot sector runs when its 256 big-endian words sum to 0x1234. `boot_option` reads that; `set_boot_option` rewrites the word at 0x1FE. |
| FAT | 12-bit entries below 4085 data clusters, 16-bit above. Both copies are written on every change and compared by `validate`. |
| Directories | 32-byte entries, 8.3 upper-case names, attribute byte, FAT date and time words, first cluster, size. Subdirectories carry `.` and `..`; an all-space `.` from a lax formatter is recognised by its cluster. |
| Volume label | The attribute-0x08 root entry. `title` and `set_title` read and write it, up to 11 characters. |
| Names | Case-insensitive lookup, upper-case storage, `\` separator with `/` accepted on input and an optional drive letter. Forbidden characters: `\ / : * ? " < > | + , ; = [ ]` and space. |

There is no comment field, no load address and no owner. `AtariMeta` carries
the attribute byte and the datestamp, nothing else.

## Floppy formats

`create --format` accepts the formats TOS writes, all with 512-byte sectors,
two sectors per cluster, one reserved sector and two FATs.

| Name | Tracks x sides x sectors | Bytes | Root entries | FAT sectors | Media |
| --- | --- | ---: | ---: | ---: | --- |
| `ss-360k` | 80 x 1 x 9 | 368,640 | 112 | 2 | 0xF8 |
| `ss-400k` | 80 x 1 x 10 | 409,600 | 112 | 2 | 0xF8 |
| `ss-440k` | 80 x 1 x 11 | 450,560 | 112 | 2 | 0xF8 |
| `ds-720k` | 80 x 2 x 9 | 737,280 | 112 | 5 | 0xF9 |
| `ds-800k` | 80 x 2 x 10 | 819,200 | 112 | 5 | 0xF9 |
| `ds-880k` | 80 x 2 x 11 | 901,120 | 112 | 5 | 0xF9 |
| `ds-720k-81` to `ds-880k-83` | 81, 82 or 83 tracks, double-sided | | 112 | 5 | 0xF9 |
| `hd-1440k` | 80 x 2 x 18 | 1,474,560 | 224 | 9 | 0xF0 |

TOS allocates five FAT sectors on a double-sided disk even though three would
index the clusters. The engine does the same so an image it formats is
byte-compatible with a disk formatted on the machine. Any FAT size that
indexes every cluster is accepted when reading.

A floppy image's geometry comes from its BPB, not its size. An 819,200-byte
image is an 80 x 2 x 10 disk; the BPB says so, and `geometry_from_bpb` is how
the engine tells it from a 720 KiB disk with the same boot code. A BPB that
declares fewer sectors than the image holds (a 76-track format on an 80-track
dump) is accepted; one that declares more is mounted with reduced confidence.

## Hard disks

### Partition tables

Sector 0 of an Atari hard disk is the AHDI root sector: the disk size at
0x1C2, four twelve-byte entries at 0x1C6 (flag byte, three-character id,
start and size in 512-byte sectors, all big-endian), the bad-sector list at
0x1F6 and a checksum word at 0x1FE that makes the word sum 0x1234 when the
root sector is executable. The engine reads three extensions of that layout
and one alternative:

- **XGM chains.** An entry with id `XGM` points at a sector holding another
  table. Its first entry is a partition whose start is relative to that
  sector; its second entry, if it is `XGM`, points at the next table relative
  to the first XGM sector. The walk is the one in the Linux kernel's
  `block/partitions/atari.c`. `create --partitions 5` and above writes this
  chain, leaving one sector free in front of every partition from the fourth.
- **ICD tables.** Eight extra entries at 0x156 ahead of the standard four,
  for twelve partitions in a flat table. Read when the first of them has the
  exists flag and a known id; written with `scheme="icd"`.
- **Byte-swapped images.** IDE and CompactFlash dumps often store every 16-bit
  word with its bytes exchanged (Hatari's `--ide-swap`). The root sector is
  tried as-is and then swapped. A swapped disk carries `byte_swapped = True`,
  and `partition_reader` hands back a reader that swaps every read and write,
  so the volume code never sees the difference.
- **MBR tables.** A PC master boot record (0x55AA at 0x1FE) with FAT types
  0x01, 0x04, 0x06 and 0x0E, and extended chains of type 0x05 and 0x0F. TOS 4,
  HDDRIVER, MiNT and Hatari all accept one. Reported with `scheme = "mbr"`;
  written with `scheme="mbr"` for up to four primary partitions.

The `scheme` field of the decoded disk is `ahdi`, `xgm`, `icd` or `mbr`.
Partitions are numbered from 0 and named `C:`, `D:` and so on, which is how
TOS assigns drive letters. An image whose sector 0 is a BPB describing the
whole file is a bare volume, not a partitioned disk, even if bytes at 0x1C6
happen to look like an entry.

### Partition geometry

A hard-disk driver keeps two sectors per cluster and grows the *logical*
sector instead: the smallest power of two from 512 to 16384 bytes that brings
the cluster count to 32766 or fewer, because TOS 1.x holds the cluster number
in a signed 16-bit word. `partition_geometry` and `format_volume` apply that
rule. The sample images confirm it: an 8 MiB partition uses 512-byte sectors,
a 32 MiB one 2048, a 255 MiB one 8192 and a 512 MiB one 16384.

A partition reached through a table is FAT16 whatever its cluster count,
because the driver's BPB flags it so and TOS obeys. A 4 MiB partition has 4063
clusters, below the FAT12 threshold, and is still FAT16. A partition dumped on
its own loses that context; the engine then applies the cluster-count rule,
with one exception: a bare image with hard-disk logical sectors, a FAT large
enough for 16-bit entries and 16-bit media and end markers at its head is
opened as FAT16.

### TOS limits

`format_volume` and `create_partitioned_image` return notes naming the TOS
releases that cannot mount a partition of the requested size:

| Limit | Releases |
| ---: | --- |
| 16 MiB | TOS 1.00 |
| 256 MiB | TOS 1.02, 1.04 and 1.62 |
| 512 MiB | TOS 2.06, 3.06 and 4.0x |

Nothing above 512 MiB mounts without a replacement DOS such as BigDOS or MiNT.
The `create` command prints the notes on standard error and still creates the
image.

## Identification

TOS ignores the jump instruction and the media byte, so the engine cannot use
them either. A volume is identified by whether its BPB is plausible and its
FAT readable:

- logical sector size 512 to 16384, a power-of-two cluster size, one or two
  FATs, a reserved sector, root entries, a FAT size and a sector count that
  leave room for data;
- the sector count fits in the image, or the confidence drops to 0.6;
- the first FAT entry carries the media marker and the second the end marker,
  or the confidence drops to 0.85 when both are zero (some formatters leave
  them so) and 0.7 when they disagree;
- the root directory contains entries a formatter could have written, or the
  confidence drops to 0.4.

That last rule matters for game disks. A copy-protected disk often carries a
believable BPB in front of a root directory that is not one, and a disk with
a nonsense BPB (28,672 root entries, say) is not claimed at all. Both are
reported honestly rather than listed as garbage.

Identification order is AHDI, then GEMDOS, then TOS ROM. File suffixes only
reorder that cascade; they never let a driver claim bytes it cannot read.
`fat12` and `fat16` are the same driver constrained to one width.

## What it does

- Creates every floppy format above and hard-disk images of any size, bare or
  partitioned.
- Reads and writes files of any length the volume can hold, keeping both FATs
  in step.
- Writes data clusters and FATs before the directory entry, so a failure part
  way through leaves at worst some allocated but unreferenced clusters, never
  an entry pointing at data that was not written. Deletion marks the entry
  first and frees the chain second, for the same reason.
- Preserves attribute bits and datestamps across a copy.
- Defragments in place, rewriting only files whose clusters are not already
  contiguous, and reports the clusters moved.
- Validates the structures: both FATs agreeing, the media marker, chain
  consistency, cross-linked clusters, lost clusters, directory loops, `.` and
  `..` links, and each file's size against its chain length.
- Cross-checks against dosfstools: a `mkfs.fat -F 12 -s 2 -r 112` volume opens
  with the free space `fsck.fat` reports, and a volume the engine writes passes
  `fsck.fat -n`. The tests skip when the tools are absent.

## Command line

`python -m atarinut` keeps the verbs the previous engine had, with the same
JSON shapes, and adds two:

| Verb | Purpose |
| --- | --- |
| `create --format ds-720k --label NAME image` | A floppy image. |
| `create --size 32M --label NAME image` | A bare hard-disk volume. |
| `create --filesystem ahdi --size 64M --partitions 3 image` | A partitioned hard disk, each partition formatted. |
| `format [--partition N] [--format NAME] [--label NAME] image` | Format an existing image or one partition in place. |
| `partitions --as json image` | The partition table with each partition's format, label, size and free space. |
| `ls`, `stat`, `get`, `put`, `cp`, `mv`, `rm`, `mkdir`, `cat`, `type`, `tree`, `find`, `export`, `import` | File operations; all take `--partition N` for AHDI images. |
| `chmod`, `lock`, `unlock`, `get-datestamp`, `set-datestamp` | Attribute bits (`rhsvda` text or a number) and datestamps. |
| `opt`, `title`, `validate`, `compact`, `freemap`, `filetype` | Boot checksum, volume label, structure check, defragmentation, cluster map, content classification. |

Inner paths use GEMDOS syntax: `image.st:AUTO\FOO.PRG`. A forward slash is
accepted and normalised.

## Sample images

The `samples/` directory, when present, holds real media the tests exercise:
three 80 x 2 x 10 game floppies from the Internet Archive, an 800 MiB ACSI
image with four BGM partitions and 2048- and 8192-byte logical sectors, a
byte-swapped 1.6 GiB IDE image with a two-link XGM chain, and two 512 MiB
images with an MBR and 16 KiB logical sectors. The tests skip when the files
are absent.

## The workbench boundary

The application reaches the engine through `atarinut.filesystem` (readers,
identification, mounts), `atarinut.disc.mount` (compound paths), `atarinut.file`
(attributes and datestamps) and the bulk-copy helpers in `atarinut.disc.cli`
that `app/atarinut_internals.py` borrows. `tests/test_atarinut_internals.py`
pins those names.
