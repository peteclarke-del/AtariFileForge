# Reading and writing physical floppy disks

The native Linux edition of Atari File Forge can send an open floppy image to
a Greaseweazle drive, and capture a physical disk back into a working image.
The browser and Docker editions deliberately cannot access host USB hardware.
Image editing remains shared between both editions; only the final hardware
adapter is desktop-specific.

## Supported images

| Image | Write | Read | Automatic verification |
| --- | ---: | ---: | ---: |
| ST sector image (`.st`) | Yes, with its geometry | Yes, with its geometry | Yes |
| MSA (`.msa`) | Yes | Yes, with its geometry | Yes |
| DIM (`.dim`) | Convert to `.st` first | No | Not applicable |
| STX (`.stx`) | No | No, capture flux instead | Not applicable |
| HFE | Yes | Yes | No |
| SCP | Yes | Yes | No |
| IPF | No | Yes | No |
| One partition of a hard-disk image | No | Not applicable | Not applicable |

Greaseweazle reads a `.dim` as the PC-98 DIFC format, which is not the
FastCopy Pro image an ST user means by the name, so a DIM is converted to
`.st` before it is written. It has no Pasti support at all: the disk an STX
came from is captured as SCP or HFE flux, and the STX itself can be converted
to `.st` to write its plain sectors.

## Geometry

An ST floppy is IBM-style MFM with 512-byte sectors: nine per track on a
TOS-formatted disk, ten or eleven when a formatter squeezed more in, on one
or two sides, over eighty tracks or a few more. A plain `.st` carries no
header, so its shape has to be known before Greaseweazle can decode or write
it. Atari File Forge reads the shape from the boot sector's BIOS parameter
block and falls back to the file size only when that names exactly one
shape; a 360 KiB file is both an 80-track single-sided ST disk and a
40-track double-sided PC one, and the two are not interchangeable.

Greaseweazle is told the shape with `--format`, using its own definitions:
`atarist.360`, `atarist.400` and `atarist.440` for single-sided disks of
nine, ten and eleven sectors, `atarist.720`, `atarist.800` and `atarist.880`
for double-sided ones, `ibm.1440` for high density and `ibm.360` or
`ibm.180` for 5.25-inch PC media. Those definitions cover eighty tracks.
An image with 81, 82 or 83 tracks has no Greaseweazle definition, and Atari
File Forge refuses to write it rather than let the last tracks be dropped;
export it as HFE or SCP flux instead.

An MSA carries its own shape, so writing one needs no format. Reading a disk
into an MSA still does, because Greaseweazle has no sectors to describe
until a format tells it how to decode the flux.

## Reading a physical disk

Select **Read physical floppy**, choose the connected drive, the capture
format and, for a sector format, the geometry, then read. The capture is
written to a private temporary file first and is only opened as an image
pane once Greaseweazle has exited cleanly and left a usable file behind, so
an empty drive or a failed read never becomes a pane you might mistake for
real data. A failed capture removes its partial file.

Choose the capture format to match the intent:

| Format | Captures | Use when |
| --- | --- | --- |
| `st` | Decoded sectors | The disk is a standard TOS-formatted floppy of known shape |
| `msa` | Decoded sectors, packed | The same, when the result is for distribution |
| `ipf` | Preserved flux | The disk is being kept in the SPS preservation format |
| `hfe` | Bitcell image | The disk has non-standard tracks worth keeping |
| `scp` | Raw flux | Preservation, copy protection, or a disk that will not decode |

A sector format decodes while reading and fails on an unreadable track. A flux
capture keeps everything the drive produced, including tracks no filesystem
decoder accepts, so it is the safer choice for a disk of unknown condition or
one you may only get one chance to read. Use `--revs` through the API, or the
revolutions control, to capture several revolutions per track when a disk is
marginal.

Greaseweazle describes HFE and SCP as flux or raw bitcell data, so it cannot
perform its usual sector read-back verification. Atari File Forge calls this
out before and after the write. Test an HFE- or SCP-derived physical disk on
suitable hardware before depending on it.

Opening, creating and saving the HFE itself uses the HxCFloppyEmulator
command-line converter (`hxcfe`) bundled with Atari File Forge. That conversion
stage is separate from the optional Greaseweazle hardware write. See the
[HFE, SCP and HxCFE guide](HFE-HXC-GUIDE.md) for the supported track-container
workflow and its byte-comparison save check.

## Using a real floppy controller

A host with an actual floppy controller, such as a Raspberry Pi or a PC with a
drive attached, can read and write disks directly through `/dev/fd0` with no
Greaseweazle hardware. Select the drive and the disk's geometry, then read or
write.

This path is not equivalent to Greaseweazle, and the difference decides which
you should use:

- A floppy controller returns **decoded sectors** at whatever geometry the
  kernel has been told the disk uses. Anything the controller cannot decode
  fails rather than being captured.
- Greaseweazle captures **flux**, so it reads a disk whether or not a
  filesystem decoder accepts it.

Because an ST disk is ordinary MFM, a PC controller reads one directly once
the kernel knows its shape. Set it with `setfdprm` from the `fdutils`
package, or open the device node that carries the geometry: `/dev/fd0u720`
for the everyday double-sided nine-sector disk, `/dev/fd0u800` and
`/dev/fd0u880` for ten and eleven sectors, `/dev/fd0u360` for a 5.25-inch PC
disk and `/dev/fd0u1440` for high density. Single-sided 80-track disks and
the extended track counts have no stock node and need `setfdprm`. Atari File
Forge checks the captured length against the chosen geometry and refuses a
short or mismatched read, so a disk the controller could not fully decode is
never presented as a complete image.

Use the controller for ordinary, healthy disks in a standard format. Use
Greaseweazle for anything damaged, copy protected, unusual, or that you may
only get one chance to read.

Writing through the controller erases the disk completely and cannot be undone,
so the write is refused until it is explicitly confirmed. The image's shape is
taken from its boot sector, or from its size when that is unambiguous, or from
the geometry you choose; the kernel geometry must agree with it, and the
mismatch message names the device node to use when there is one.

The supported geometries are the ST family (80 to 83 tracks, one or two
sides, 9 to 11 sectors), the 40-track single- and double-sided PC disks, and
the 1440 KiB high-density disk.

## Install Greaseweazle

Install the official Greaseweazle host tools so the `gw` command is available
in the desktop session. Follow the project's current installation and Linux
udev instructions:

- <https://github.com/keirf/greaseweazle/wiki/Software-Installation>
- <https://github.com/keirf/greaseweazle/wiki/Supported-Image-Types>

Connect the device and check it outside Atari File Forge first:

```bash
gw info
```

If `gw info` fails, correct the USB connection, firmware or udev permissions.
Atari File Forge reports the same diagnostic and does not start a write.

## Write a disk

1. Open a supported image in the native Linux application. At the root of a
   hard drive, open the partition you want to write.
2. Open **Tools** and choose **Write physical floppy**, or right-click the
   image title or coloured format badge and choose the same command.
3. Select Greaseweazle drive A, B, 0, 1, 2 or 3.
4. Insert the destination disk. Confirm that all existing data on it may be
   overwritten.
5. Select **Write and verify**. HFE and SCP instead say **finish unverified**.
6. Keep the device connected while cylinder, head and verification progress is
   shown. **Abort operation** terminates Greaseweazle, but the disk in the
   drive must then be treated as incomplete and rewritten.
7. Keep the disk only after the completion dialog reports verification. For
   HFE or SCP, test it separately because automatic verification is unavailable.

The current working image is finalised, then copied to a private stable
snapshot before `gw write` starts. Further edits cannot change bytes halfway
through a physical write. The source image and its undo history are never
modified by the hardware operation.

## Safety and failure handling

- Commands are executed as argument arrays without a shell. Drive identifiers
  are restricted to the supported connector values, and format names to
  Greaseweazle's own.
- A failed probe never starts the motor or writes a track.
- Sector images are not reported as successful unless Greaseweazle prints its
  complete verification confirmation.
- A verification failure, missing confirmation, timeout, cancellation or
  non-zero exit status says that the physical disk may be incomplete.
- A 30-minute watchdog terminates a stalled command.
- Temporary partition extractions and write snapshots are removed after
  success, failure or cancellation.

## Shared integration module

The UI-neutral implementation is the top-level `atari_greaseweazle` Python
package. It owns supported suffixes, the refused ones and their alternatives,
drive validation, format-name validation, discovery, stable snapshots,
subprocess control, progress parsing and verification policy. It has no
Flask, GTK or Nautilus dependency, so the companion `nautilus-atarifs`
project can consume the same module rather than maintaining a second hardware
implementation. The floppy-controller adapter is the `atari_floppy` package,
which takes its geometries from `app.floppy_geometry`, the one table of
shapes every part of the workbench reads.
