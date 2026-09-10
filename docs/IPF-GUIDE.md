# IPF captures and the SPS decoder library

An IPF is a preservation image made by the Software Preservation Society. It
records what was physically on the disk: the bit cells, their timing, and the
deliberate irregularities that copy protection depends on. That is why a
protected ST disk survives as an IPF and not as a plain `.st`, and why an IPF
is worth keeping even after you have extracted the files from it.

Atari File Forge can open an IPF and read the ordinary sectors out of it. It
cannot invent a sector image that holds the parts a sector image has no way
to express; where a track is not a standard track, the workbench says so
rather than filling the gap.

## Why the library is not included

Decoding an IPF needs the SPS decoder library, usually built as
`libcapsimage`. Its licence permits use and non-commercial redistribution but
not sale or inclusion in a commercial product, so Atari File Forge does not
ship it. Instead it looks for the library when you open an IPF, and tells you
plainly when it is not there.

Nothing else in the application depends on it. Every other format is handled
in-tree.

## Installing it

Build it once and put it where the workbench looks:

```bash
git clone --depth 1 https://github.com/FrodeSolheim/capsimg.git
cd capsimg
./bootstrap          # needs autoconf and autoheader
./configure
make

mkdir -p ~/.config/atari-file-forge/lib
cp CAPSImg/libcapsimage.so.5.1 ~/.config/atari-file-forge/lib/
ln -sf libcapsimage.so.5.1 ~/.config/atari-file-forge/lib/libcapsimage.so.5
ln -sf libcapsimage.so.5.1 ~/.config/atari-file-forge/lib/libcapsimage.so
```

The workbench searches these places, in order:

1. the file named by `ATARI_FILE_FORGE_CAPSIMAGE`, if that variable is set;
2. `~/.config/atari-file-forge/lib`;
3. `/opt/atari-file-forge/native/lib`, where the packaged builds put it;
4. `/usr/local/lib` and `/usr/lib`.

Point the environment variable at one exact file when you want to test a
particular build:

```bash
ATARI_FILE_FORGE_CAPSIMAGE=/path/to/libcapsimage.so.5.1 python -m app.cli identify capture.ipf
```

On Windows the library is `CAPSImg.dll` and on macOS `libcapsimage.dylib`; the
same search order applies.

## What opening an IPF does

1. The library decodes the capture into each track's MFM bit cells.
2. Atari File Forge reads those cells the way the ST's WD1772 controller
   does: it finds the three `A1` sync bytes whose missing clock bit marks an
   address mark, reads the ID field naming the cylinder, head, sector and
   size, checks its CRC-16, then finds the data mark that follows and checks
   the CRC over the sector's bytes.
3. A sector that passes both checks is written into a working `.st`. One that
   fails is reported and its place left as zeroes. The layout is taken from
   the sectors themselves: the highest sector number found on any track is
   the count per track, which copes with nine-, ten- and eleven-sector disks
   without being told which.
4. The pane opens on the working image, and the original capture is left
   untouched beside it.

The pane's warnings say how many of the expected sectors were recovered. A
capture of an unprotected disk normally recovers all of them; a protected one
often does not, and the difference is the protection itself.

## What it does not do

- It does not write IPF. The format is a preservation record of a physical
  read; the workbench has nothing to preserve a reading of.
- It does not reproduce fuzzy bits, long tracks, non-standard sector sizes or
  out-of-place sector IDs in the working image. Those survive only in the
  capture, and a 256- or 1024-byte sector is reported rather than placed.
- It does not fall back to guessing. If no standard sector is recovered, the
  open is refused with the reason rather than handing you an empty disk.

## When the library is missing

Opening an IPF then fails with a message naming the library, the directory to
put it in, and the environment variable that overrides the search. Nothing
else changes: the rest of the application works exactly as it does with the
library installed.
