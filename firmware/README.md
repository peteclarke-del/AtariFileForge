# Firmware

Two kinds of firmware matter to the emulator hand-off, and the repository
treats them differently.

**EmuTOS is bundled.** It is a free operating system for the Atari range,
released under the GNU General Public License version 2, so the ROM images
under `firmware/emutos/` are committed on purpose and reach every build. They
are what boot a machine when no real TOS is available.

**Atari TOS is never committed and never downloaded.** TOS ROMs remain the
copyright of Atari's successors. Nothing in the build fetches one, none is in
the repository, and `firmware/tos/` is ignored by Git so that a ROM you keep
there cannot reach the public repository through a stray `git add`. That
exclusion is the only reason ROMs may sit there at all: move them elsewhere in
the tree and they are no longer covered.

## The bundled EmuTOS

`firmware/emutos/` holds EmuTOS 1.4, unmodified, with its licence and the
upstream README for each size. Source and binaries are published at
<https://emutos.sourceforge.io/> and <https://github.com/emutos/emutos>.

| File | Size | Boots | Notes |
| --- | --- | --- | --- |
| `etos192uk.img`, `etos192us.img` | 192 KiB | ST, Mega ST | Comparable to TOS 1; plain 68000 only, no extra-hardware detection. |
| `etos256uk.img`, `etos256us.img` | 256 KiB | STE, Mega STE | Comparable to TOS 2; DMA sound and the blitter are supported. |
| `etos512uk.img`, `etos512us.img` | 512 KiB | TT030, Falcon030 | Comparable to TOS 3 and 4; TT RAM, SCSI, IDE, VIDEL and the DSP. |
| `etos1024k.img` | 1024 KiB | Any machine under Hatari | Multilanguage; the image Hatari itself ships. Not for real hardware. |

The `uk` images are PAL with an English desktop; the `us` images are NTSC.
The application picks the UK image for a machine and offers the 1024 KiB one
as an explicit choice (`emulatorFirmware: "emutos-1024k"` in a profile).

Checksums of the committed files:

    154803e3ff4851f3dc358b91b16d6b6110d187a81d8132ecb665af49878939d5  etos1024k.img
    2d6f3f6f304c9ba340aff8d47ba72b274ae29b8fbe6214138846dada97edf0f3  etos192uk.img
    8fbbf8b44fc3e34281eaf8cda5265510e9af9ccda0e3e409111648060d244cfc  etos192us.img
    3bfdc561eb193a8f65aa772169aa2aca241015a2bad9388a2fea3326b1b0aeb0  etos256uk.img
    f1fe68360db345551231791edc6a7769e825edadf3632f59b10f3b2100ed75b3  etos256us.img
    f3177763bd3f2a984bf7d2f112f4a3bb4a6d20c7e2d77549f6973bb884edb49e  etos512uk.img
    167f5f148419a684a3646519ef12cd7be00e1a35e10040358184f4d471e27da9  etos512us.img

## Your own TOS ROMs

Real TOS is what most software was written against, and some of it will not
run on anything else, so the application prefers a real ROM whenever it finds
one. Put yours in the directory named by `ATARI_FILE_FORGE_TOS_DIR` (default
`~/.config/atari-file-forge/tos`) or in this repository's `firmware/tos/`.
The operator directory is searched first.

The names matter, because each machine is matched to a ROM by filename. Use
the release number followed by the language code, as the emulator community
does:

| Machine | Releases it shipped with | Preferred filenames |
| --- | --- | --- |
| 520ST, 1040ST | TOS 1.00, 1.02, 1.04 | `tos104uk.img`, `tos102uk.img`, `tos100uk.img` |
| Mega ST | TOS 1.02, 1.04 | `tos104uk.img`, `tos102uk.img` |
| 520STE, 1040STE | TOS 1.06, 1.62 | `tos162uk.img`, `tos106uk.img` |
| Mega STE | TOS 2.05, 2.06 | `tos206uk.img`, `tos205uk.img` |
| TT030 | TOS 3.06 | `tos306uk.img` |
| Falcon030 | TOS 4.00, 4.02, 4.04 | `tos404.img`, `tos402.img`, `tos400.img` |

Any language variant is accepted: `tos104de.img` is still TOS 1.04. Within
one release the file with no language comes first, then `uk`, then `us`, then
the rest in name order. The Falcon ROMs have no language suffix because one
ROM covers every language, which is why the plain name ranks first.

A collection gathered from the preservation archives carries alternative
dumps beside the good ones, so two more rules apply. A file that does not
decode as a ROM is ignored altogether, and between two dumps of one release
the larger is taken. Both are needed: a dump of half the expected length
still carries a perfectly good header and reports its version happily, and
booting one gives a machine that hangs with nothing on screen.

## How the application chooses

For the machine in the hardware profile:

1. If the profile names a release (the `tos-104` add-on and its relations),
   that release is looked for in the operator directory, then in
   `firmware/tos/`.
2. Otherwise every release the machine shipped with is looked for, newest
   first, in the same two places.
3. If nothing is found, or the profile carries the `tos-emutos` add-on, the
   bundled EmuTOS of the size that fits the machine boots it instead.

The emulator status reports which ROM was chosen and why, and a machine with
no real TOS is never reported as unable to start: EmuTOS is always there. The
full hand-off, including every Hatari option each machine receives, is
described in the [emulator guide](../docs/EMULATOR-GUIDE.md).

## Boot floppies for the earliest machines

The first 520ST machines had no TOS in ROM. They loaded it from a boot floppy
into RAM, and those disks survive as `.st` images. `firmware/tos/disks/` is a
conventional place to keep such disks alongside the ROMs; it is ignored by Git
in the same way. The application does not select boot disks automatically:
open one as a floppy and hand it to the emulator with an EmuTOS ROM if you
want to see it load.

## Hard-disk drivers

Preparing a drive so that a real Atari will boot from it needs a hard-disk
driver, and none is bundled. Every driver worth using is somebody's copyright:
AHDI is Atari's, ICD Pro is ICD's, and the free alternatives have outlived the
sites that hosted them. The application therefore installs from the copy you
already own, which is almost certainly the one already sitting on a drive you
have.

| Driver | Terms | Obtained |
| --- | --- | --- |
| ICD Pro | ICD stated none and the company is gone; mirrored freely for decades | Downloaded when chosen |
| Atari AHDI | Atari stated none and never released it; treated as free everywhere | Supply your own |
| HDDRIVER | Sold by Uwe Seimet | Supply your own |
| PP driver | Sold by Pera Putnik, who lists the prices himself | Supply your own |

The two that are sold are never fetched, and that is decided by the catalogue
rather than by the request, so nothing can ask for one. AHDI is not fetched
either, for a different reason: no source was found that is the owner's rather
than somebody's copy, so wiring one up would be asserting a provenance this
cannot show.

Put a driver you supply in its own folder under `firmware/drivers/`, or under
`~/.config/atari-file-forge/drivers`. It is also read straight out of a ZIP or
a `.st`, `.msa` or `.dim` floppy image, so a download does not have to be
unpacked first, and **Other…** points at a folder of your own for one install.
Both locations are ignored by Git for the same reason the ROMs are.

A driver that can be downloaded is offered whether or not a copy is here. One
that is sold is listed, marked as not supplied and not selectable, so the
choice you cannot make is visible rather than absent.

A driver's control panel module goes into the `CPX` folder, where XControl
reads them from: ICD Pro carries `ADSCSI.CPX`. Its driver ships as
`ICDBOOT.PRG` and is installed as `ICDBOOT.SYS` in the partition root, because
that is the name the root sector loads.

You do not need a driver at all if you are booting the drive under EmuTOS,
which mounts a partitioned drive without one. That is the default, and it is
the only route that needs nothing you have to find first.

## Hard-disk boot loaders

A driver is only half of what a machine running its original TOS ROM needs.
The ROM runs a loader in the drive's root sector, which runs a second loader in
the boot partition's boot sector, which loads the driver file. AHDI and ICD
Pro keep both loaders inside their own Atari installation programs rather than
as files, so the place to get them is a drive that driver has already
prepared.

The prepare-drive dialog copies them from such a drive when it is open in the
other pane, and keeps a copy here so that later drives do not need it open.
Each driver release gets a folder of its own under `firmware/bootloaders/`, or
under `~/.config/atari-file-forge/bootloaders`, which is where the application
saves them:

| File | Holds |
| --- | --- |
| `ROOTLOAD.BIN` | The root sector's loader, with the partition table below it cleared |
| `BOOTLOAD.BIN` | The boot sector's loader, with its serial number and parameter block cleared |
| `SOURCE.TXT` | Which drive the pair was saved from, and which file it loads |

Both sectors keep a valid boot checksum. When a drive is prepared, the loaders
go in and the drive keeps its own partition table and parameter block. The
pair names the driver file it loads, `ICDBOOT.SYS` or `SHDRIVER.SYS`, and that
decides which driver it is used for, not the folder's name. The loaders are
the driver's own code, so this folder is ignored by Git like the drivers are.

## Replacement desktops

The built-in TOS desktop has no icons of your own, no program groups and no
way to find a file, so every serious Atari acquired a replacement. Preparing a
drive can install one, and the same rule applies as to the drivers: put your
own copy in place and it will be offered by name.

Each one goes in its own folder under `firmware/desktops/`, or under
`~/.config/atari-file-forge/desktops`. One level of nesting is read, so a
folder per desktop unpacked as it was published is the shape to use. Naming
the folder after the release, `TERADESK_4.06` say, means the version is read
from it and reported.

| Desktop | Licence | Obtained | Suits |
| --- | --- | --- | --- |
| TeraDesk | Free software, GPL 2 | Downloaded when chosen | Any machine, and the one to choose below 2 MB |
| NeoDesk 4 | Freeware, Apache 2.0 with the Commons Clause | Downloaded when chosen | ST to TT with 2 MB or more |
| Thing | Open source, by its author | Downloaded when chosen | STE and later, and anything running MagiC or MiNT |
| Gemini with Mupfel | Shareware, source later MIT | Supply your own | Anyone who wants a shell in the desktop |
| Geneva | Freeware, Apache 2.0 with the Commons Clause | Downloaded when chosen | Alongside NeoDesk, for multitasking |

Geneva is not a desktop. It is a cooperative multitasker that runs under one,
giving the machine a dropdown menu bar and several programs at once. It was
written to pair with NeoDesk, so it is offered alongside rather than instead.

**The licence decides whether it is fetched, not how easy it is to find.**
Gribnif released NeoDesk and Geneva as freeware under Apache 2.0 with the
Commons Clause, which permits use and redistribution but not sale, so both are
downloaded from Gribnif when chosen. TeraDesk and Thing come from their own
publishers the same way. Gemini was shareware and its source was later
released under the MIT licence, but no binary distribution was found to fetch
from, so it is installed from your own copy.

A download lands in the same directory you would have put a copy in, so
afterwards a download and your own copy are the same thing. Nothing is bundled
in the repository.

**A distribution is read wherever it is, in whatever shape it arrived.** An
unpacked folder, a ZIP, a `.st`, `.msa` or `.dim` floppy image, or a ZIP with
the original floppies inside it, which is what both Gribnif downloads are.
Nothing has to be unpacked first.

**Files go where TOS looks for them.** A program and its resources go in a
folder of their own. A desk accessory goes in the root of the boot drive,
because that is the only place TOS loads one from, and on these products the
control panel is an accessory: NeoDesk's is `NEOCNTRL.ACC` and Geneva's task
manager is `TASKMAN.ACC`. An `AUTO` program goes in `AUTO`, and a control
panel module goes in `CPX`.

**Nothing already on the drive is replaced.** An `AUTO` program holds a place
in a sequence you may have arranged deliberately, and an accessory may be your
own, so an existing one is kept and reported as kept rather than overwritten.
TOS loads only the first six accessories it finds in the root, so you are told
when a drive goes past that and which ones will be ignored.

**Other…** in the prepare-drive dialog points the application at a folder of
your own for one install, which is where to send it if your copies live in a
downloads folder. Archives are read without unpacking them, so a ZIP straight
from the publisher works as it is.

**How each one starts is taken from its own installer.** NeoDesk and Geneva
ship an `INSTALL.SCR` on their master disk, and that script is the authority:
both put a program in `AUTO`, which is what starts them when the machine comes
up. `NEOLOAD.PRG` and `GENEVA.PRG` go there, and Geneva goes in first, because
`AUTO` runs its programs in the order the folder holds them and Geneva has to
be up before NeoDesk loads under it. The resulting order is reported so you can
see it.

Whether NeoDesk takes the place of the built-in desktop rather than running
alongside it depends on the machine's ROM version. Gribnif's own installer says
so and offers Geneva as the way to arrange it, so that is what this repeats
rather than guessing.

TeraDesk and Thing put nothing in `AUTO`, so nothing starts them, and the
result says so.

**An accessory is installed with the resource it reads.** One without its
resource loads and then has nothing to draw, which from the outside looks
exactly like not loading at all. `NEOCNTRL.ACC` needs `NEOCNTRL.RSC`,
`NEOQUEUE.ACC` needs two, one per resolution, and so on.

## Checking a ROM

    python3 -m atarinut identify /path/to/tos104uk.img

That reports what the file is, including a TOS ROM's release, date, language
and target machine, without loading an emulator.
