# Atari file catalogue metadata

A GEMDOS directory entry records rather little beyond the name and the bytes:
one attribute byte and one datestamp. That is the whole of it. Knowing what is
absent matters as much as knowing what is present, because software written
for other machines routinely assumes fields the Atari never had.

Atari File Forge shows those two values at file level and preserves them
across copies, imports, exports and editor saves. It never invents one because
the bytes happen to resemble a program.

## What GEMDOS stores, and what it does not

| Value | Where it lives | Notes |
| --- | --- | --- |
| Attribute byte | The directory entry | Six meaningful bits, printed `rhsvda`. A set bit means the flag is on, with no inversion anywhere. |
| Datestamp | The directory entry | A FAT date and time word pair. The epoch is 1 January 1980 and the resolution is two seconds, so an odd second cannot be stored. |
| Comment | Nowhere | GEMDOS has no comment field. Nothing in the format can hold one, so the application does not offer one. |
| Load or execution address | Nowhere | A GEMDOS program is relocatable. Its own header records the text, data and uninitialised sizes and a flags word; the directory records none of it. |
| Desktop icon | `DESKTOP.INF` and its later names | The desktop configuration file installs applications and assigns icons. It is an ordinary text file on the volume, not a per-entry field. |

The properties dialog therefore edits the attribute byte and the datestamp,
and nothing else.

## The attribute byte

```text
r h s v d a
│ │ │ │ │ └── archive     the file changed since the last backup
│ │ │ │ └──── directory   this entry is a folder
│ │ │ └────── volume      this entry is the volume label, not a file
│ │ └──────── system      hidden from the desktop, and treated as the system's
│ └────────── hidden      hidden from ordinary directory listings
└──────────── read-only   writes and deletions are refused
```

A newly written file carries the archive bit alone, which prints as `-----a`.
Marking it read-only gives `r----a`. A folder reads `----da`, and the volume
label reads `---v--`.

Two of the six are structural rather than editable. The directory and volume
bits say what kind of entry this is, so changing them would not change a
property of the file, it would claim the entry is something it is not. The
application shows them and refuses to edit them. Read-only, hidden, system and
archive are yours to set.

TOS itself takes little notice of the hidden and system bits: the desktop
honours them, most software does not, and a hidden file is not protected in
any sense. Use read-only when you mean to prevent a write.

## The datestamp

The stored date and time are local to whichever machine wrote them, because
GEMDOS records no time zone and the ST had no reliable clock unless a
cartridge or a Mega's battery supplied one. A great many real disks therefore
carry dates that are plainly wrong, and some carry the same date on every
file because the formatter wrote it once.

The representable range runs from 1980 to 2107. A file imported from your
computer with a timestamp outside that range cannot be represented, and the
application says so rather than storing a date that would read back as
something else. Seconds are rounded down to the nearest even second, which is
the format's own resolution and not a limitation of this application.

## Where the metadata is available

| Source | Display | Edit | Notes |
| --- | --- | --- | --- |
| ST sector images, and the containers that decode to them | Yes | Yes | Any geometry, at any depth of folder. |
| A partition on a hard disk | Yes | Yes | The metadata belongs to the file inside that partition's own volume. |
| A bare GEMDOS volume | Yes | Yes | The same operation as a floppy. |
| Pasti captures | Yes | No | The capture records a physical read and is opened read-only. |
| CD images | Yes | No | Everything on a disc reads as read-only, with the recording date. |
| ZIP and LZH members | Yes when the archive carries it | Read-only inside the archive | A ZIP written on a machine that stored the attribute byte supplies it. Extract into writable media to change it. |
| TOS ROM segments | Read-only and system | No | A ROM is not a catalogue. The segment's address and whether its range was proven are shown beside it instead. |
| Raw ROM banks | Not applicable | Not applicable | A ROM image is decoded as banks and structures. |

## Editing the attributes and the datestamp

1. Open the volume and navigate to the file.
2. Read the **Attributes** column, printed in the fixed six-letter form.
3. Choose **File properties**, then set the bits you intend and the datestamp.
4. Confirm. The operation creates the normal image undo point, changes only
   the directory entry, and leaves the file's bytes untouched.

A missing file, a read-only image or an unsupported filing system is refused
before anything is written.

## Import metadata priority

An image-to-image copy reads the source directory entry directly. A file taken
from your computer carries no GEMDOS metadata, so imports use reliable
evidence in this order:

1. the source GEMDOS volume, when the file came from one;
2. the attribute byte a ZIP records for that member, where the archive was
   written on a machine that stored one;
3. neutral defaults: the archive bit alone, and the host file's own
   modification time clamped into the representable range.

Batch imports apply that decision separately to every file, so **apply to all
remaining** accepts each file's own detected values rather than reusing the
first file's.

## Target filenames

The import planner and the write API share one filename policy, and it is
strict because GEMDOS is.

A name is at most eight characters, then optionally a full stop and at most
three more. It is stored upper case, and comparisons ignore case, so `GAME.PRG`
and `game.prg` are the same file and cannot share a folder. The full stop is a
separator here rather than an ordinary character, which is the opposite of
several other machines of the period.

These characters cannot appear in a name:

```text
\ / : * ? " < > | + , ; = [ ]
```

Space is excluded too, along with control characters, and every target must be
representable in the Atari character set. Before a cross-format write, the
compatibility review shows every truncation, character replacement and
collision it is about to make, so a batch that would silently overwrite one
file with another stops first. A name that has to be shortened gains a numeric
suffix inside the eight characters rather than beyond them.

Two partitions may hold volumes with the same label, because a partition is
identified by its drive letter and its place in the partition table rather
than by the label of the volume in it.

## Verification checklist

When correcting metadata for software that previously failed to run:

- compare the values with an original image or a trusted source;
- check that nothing needed at run time is marked read-only, since a game that
  saves its own high scores must be able to write;
- confirm that a file you intend to hide is hidden for a reason, because TOS
  does not treat hidden as protected;
- check that the datestamps are inside the representable range and that a
  build or installer does not depend on one being newer than another;
- save, reopen and verify the directory before testing on hardware;
- retain a checkpoint or the original image until the software has run on its
  intended machine.
