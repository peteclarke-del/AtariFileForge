# Preparing a hard drive and installing floppies onto it

Copying a game disk into a partition gives you the files. It does not give you
something you can use. The title still expects to find itself in the root of
`A:`, and the drive still has nothing on its desktop that would start it. This
guide covers the ways Atari File Forge closes that gap, and it is honest about
what each one can and cannot do.

It starts with the drive itself. There is no operating system to install: TOS
lives in the machine's ROM, and where a machine has no usable ROM the EmuTOS
image bundled with this application supplies one. What a drive needs instead is
a **hard-disk driver**, so that a machine can reach the drive at all, and a
**desktop configuration**, so that the desktop shows what is on it. The rest of
the guide covers getting a title onto the drive once the drive is ready.

The install choice appears in the import dialog whenever the pane you are
dropping onto is a mounted GEMDOS volume on a hard drive. Under **Import as**
you get:

* Copy the disk contents in as they are, which is the behaviour that has always
  been there.
* Install it onto this drive, which is what this guide is about.
* Store the original image as an ordinary file, when the disk image itself is
  what you want to keep.

A floppy pane offers no install option, because a floppy has nowhere to install
to. A drive showing its partition table offers none either: a partition table is
not a volume. Enter a partition first.

## Preparing the drive

Choose **Prepare this drive** with a partition open. Preparing a drive does
three things, and you can have any of them on their own:

1. it settles what happens in the drive's **root sector**, which is the first
   thing a machine reads and the only place a hard-disk driver can be loaded
   from;
2. it creates the folders a prepared drive is expected to have, `AUTO`,
   `GEMSYS` and `GAMES`;
3. it writes a **desktop configuration**, `NEWDESK.INF`, if the volume does not
   already have one.

Files already on the volume are left alone. A drive you have been building is
added to rather than replaced, and preparing it twice does not undo work you did
in between. In particular, a desktop configuration you arranged yourself is
never overwritten.

### Atari File Forge cannot supply you with a driver

AHDI, HDDRIVER, the PP driver and the ICD driver are each somebody's copyright,
and none of them may be redistributed. Atari File Forge does not ship one, does
not fetch one, and will not pretend to have one. Point it at the copy you own.

Put the driver's own files in either of these directories, unpacked as they were
published:

* `~/.config/atari-file-forge/drivers`, or the directory named by
  `ATARI_FILE_FORGE_DRIVER_DIR`;
* `firmware/drivers` beside the source, which is git-ignored exactly as
  `firmware/tos` is.

The files may be loose or inside the distribution's own folder; one level of
nesting is looked through, so `firmware/drivers/ICDPRO_6.55A/ICDBOOT.SYS` is
found without your having to flatten anything. The release is read from that
folder's name, which is where both of the drives this workflow was built from
record it.

EmuTOS is the one exception to all of this. It is GPL, it is committed, and it
is not a driver.

### The three choices, and what each one means on real hardware

**Driverless, under EmuTOS.** This is the default. Nothing is written to the
root sector, and the sector is left deliberately inert: its checksum word is set
so that the sum of its 256 big-endian words is *not* `0x1234`, which is the only
thing the ROM checks before it would execute it. EmuTOS reads ACSI, SCSI and IDE
drives itself and finds the partitions without help, so a drive prepared this
way works under EmuTOS on real hardware and in Hatari.

> A machine running its original TOS ROM will not see this drive at all. There
> is no partial state here: without a driver, an ST, STE or Mega STE boots to
> its own desktop with no hard-disk icon.

**A driver you supply.** The driver file is copied into the root of the boot
partition, which is where the loader looks for it: `ICDBOOT.SYS` for the ICD
driver, `SHDRIVER.SYS` for AHDI 6, `HDDRIVER.SYS` for HDDRIVER. Where the
distribution also carries the 512 bytes that belong in the root sector, named
`ROOTSECT.BIN`, `BOOTSECT.BIN`, `HDBOOT.BIN` or `ROOTSECT.BOO`, that code is
written into the sector below the partition table and the checksum word is
recomputed so that the word sum is exactly `0x1234`. The partition entries
themselves are untouched.

> Most distributions do not carry that file, because the loader lives inside the
> driver's own installation program. When that is the case the driver file is
> still copied in and you are told plainly that the root sector was left as it
> was: run the driver's own installer once, on the machine or in Hatari, to
> write the loader. Atari File Forge will not fabricate a loader for a driver it
> does not have.

**A drive with a PC partition table.** A drive prepared on a PC carries a master
boot record, whose own bytes occupy the space an Atari loader would need. Such a
drive is read by EmuTOS's built-in support, and by TOS 4 and MiNT, and no driver
can be installed onto it from here; asking for one is refused with that reason
rather than quietly losing the partition table. Prepare it driverless.

### What a prepared drive looks like

This is what the drives this workflow was built from actually look like, and
what Atari File Forge reports when you open one:

| Drive | Root sector | Boot sector | In the partition root |
| --- | --- | --- | --- |
| ICD-prepared ACSI | executable, word sum `0x1234` | executable | `ICDBOOT.SYS`, `ICDPRO_6.55A`, `NEWDESK.INF`, `DESKTOP.INF` |
| AHDI-prepared IDE, stored byte-swapped | executable once un-swapped | executable | `SHDRIVER.SYS`, `AHDI_6.061`, `NEWDESK.INF` |
| PC partition table, booting under EmuTOS | not executable | not executable | `AUTO`, `GEMSYS`, no driver |

A byte-swapped image is one taken through an IDE or CompactFlash adapter that
exchanges the two bytes of every word. It is detected, read through the swap and
written back through it, so nothing you see or do here has to know about it.

### The desktop configuration

The desktop shows what `NEWDESK.INF` tells it to show, falling back to the older
`DESKTOP.INF` on TOS 1.x. Preparing a drive writes one if there is none, with
the records a working desktop needs: `#a`, `#b`, `#c` and `#d` for the video and
colour settings, `#K` for the keyboard table, `#E` for the desktop preferences,
`#W` for a window position, the drive and trash icons, and the document-type
records `#N`, `#D`, `#G`, `#Y`, `#P` and `#F` that make a folder open as a
folder and a program run as a program.

Installing a title on the desktop adds two more records:

* one of `#G`, `#F`, `#P` or `#Y`, chosen by the program's own extension,
  naming the program in full. The extension is the whole of what the desktop
  reads, so it decides how the program runs: a `.TTP` is asked for a command
  line, a `.TOS` runs without GEM, a `.PRG` or `.APP` runs with it.
* an `#X` record, which is what puts the icon on the desktop itself.

The new records are inserted above the `*.PRG`-style associations of the same
letter, because the desktop takes the first record that matches and a wildcard
association would otherwise swallow the specific one. Installing the same
program twice replaces its record instead of adding a second. Everything else in
the file, including window positions and icons you placed yourself, is left
where it was.

## Getting a title onto the drive

There are four honest ways, and the import dialog offers three of them; the
fourth is a single program, which is offered wherever one file is selected.

### Stage it for installing later

This is the default, because it is the only mode that cannot half-succeed. The
disk is extracted into a folder **on the drive being built**, under
`INSTALL\STAGE` unless you name somewhere else. Nothing is emulated, nothing is
guessed at, and it is always fast.

Putting the staged set on the target image rather than in a directory on this
computer is the whole point. You can boot the drive in Hatari, or put it in a
real Atari, open the folder and run the title's own installer against it with
the disks already in front of you.

Disks staged under the same title merge into one tree, which is what an
installer expects to be pointed at. Where two disks carry the same path with
different contents, the first is kept and the later one is filed under
`INSTALL\STAGE\CLASH`, so a set is never silently reduced to its last disk; the
staged-disks dialog tells you how many files differed. Staging a disk again
under a label that is already there is treated as a correction rather than as a
second disk: its files replace what the earlier attempt wrote, and any conflict
recorded against that label is dropped.

Titles are sentences and GEMDOS folder names are eight characters, so the folder
is named from the title by the filing system's own rules: *Bubble Bobble (1987)*
is staged into `BUBBLE_B`. The readable title is kept in the record beside it,
which is what the dialog shows.

That record, `INSTALL\STAGE\CLASH\<TITLE>\STAGE.INF`, lives on the drive rather
than on this computer, so a drive you carry to another machine still describes
what is waiting on it. It is kept out of the payload folder on purpose: that
folder has to be exactly what gets installed.

### Install it into a folder on this drive

For a title that runs from wherever it is put, which is most games and demos.
The staged tree is **moved** out of the staging folder into a folder of its own,
`GAMES\<TITLE>` unless you name another. Both ends are on the same volume, so
this is a move rather than a copy: the attributes and datestamps the disks
carried are the ones already written, and nothing is read or written twice.

Nothing in the moved tree is rewritten, and nothing needs to be. TOS resolves a
path at run time against the drive the program was started from, and a relative
path spelled with a leading backslash means the current drive either way, so a
program that worked in `A:` works in `C:\GAMES\TITLE` without being patched.

If no program is found in the installed folder's own root, you are told so:
there is nothing there the desktop could start, and the program is probably in a
folder below it.

### Run the title's own installer

Productivity software installs itself by running a program that reads the
machine it finds and asks where things should go. It cannot be run unattended
and no tool can answer its questions for somebody else, so this mode stops
trying. It boots the drive in Hatari with the title's first disk in `A:` and
hands you the keyboard. Up to two disks can be inserted at once, because an
Atari has two floppy drives; swap the rest as the installer asks.

Every mode stages first, so a run that goes wrong has still put the disk's
contents somewhere you can finish by hand.

### Copy a single program in

The smallest install there is, and the commonest: one `.PRG` or `.TOS` that is
the whole of the software. It is copied into the folder you name and, where you
ask for it, installed on the desktop. Nothing is staged, because there is
nothing to merge and nothing to finish later. A file TOS would not start is
refused rather than copied in and left inert.

## Checking what is already installed

**Check installed drive software** walks the volume and reports every folder
that holds a program. Two things are checked, and only one of them has a repair,
because only one of them has an answer that can be proved:

* **A program that is not a program.** A file named `.PRG` whose first word is
  not `0x601A`, or whose header declares more text and data than the file holds,
  would be refused by TOS. This is reported and never rewritten: what the right
  bytes would have been is not knowable from here.
* **A desktop record naming a file that is not there.** A `#G`, `#F`, `#P`,
  `#Y` or `#X` record that installs a program which is not on the volume cannot
  start anything. Removing it is offered as a repair, and it takes nothing away.

The first pass is read-only and lists the exact change it would make for each
folder before anything is written. The audit is run again before a repair, so a
result that has gone stale is refused rather than acted on.

## What is deliberately not here

There is no loader-patching mode. The previous platform this application was
written for had a third-party loader that games were patched to run under; TOS
has no counterpart, and offering one would mean inventing a workflow that does
not exist.

There is no operating-system install, because there is no operating system to
install. There is no release published on CD to install from either.

There is no driver download. See above: it is not ours to give you.
