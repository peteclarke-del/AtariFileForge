# Atari File Forge backlog

This backlog records the state of the port to the Atari ST range. It is
separate from the [release checklist](RELEASE-CHECKLIST.md): the checklist is a
repeatable validation gate, this page records product work that is not
finished.

A checked item is implemented and covered by the normal project documentation
and tests. An unchecked item remains in scope. The first release that can be
called usable is `0.1.0`.

## 1. Filing system and media

- [x] Replace the filing-system engine with GEMDOS: little-endian BPB boot
      sectors, the `0x1234` executable checksum, FAT12 floppies and FAT16
      partitions with two sectors per cluster and logical sectors up to
      16 KiB, 8.3 names, attributes and FAT datestamps.
- [x] Read and write AHDI partition tables, extended chains, the ICD twelve
      entry table and PC partition tables, and detect byte-swapped drive
      images so an image dumped from an IDE adapter opens correctly.
- [x] Report the TOS release limits for a partition size rather than silently
      producing a volume the target cannot mount.
- [x] Read and write ST sector images and MSA and DIM containers, and decode
      Pasti STX captures read-only with a per-track protection report.
- [x] Decode preservation captures through the optional decoder library using
      the IBM MFM layout the Atari actually writes.
- [x] Keep HFE and SCP support, retargeted at ST geometries, with the encode,
      decode and byte-for-byte compare policy intact.
- [ ] Write a container back out in the exact packing the original tool chose,
      rather than the shortest encoding, when a source container is being
      updated in place.
- [ ] Support the 1.44M high-density geometry end to end, including the flux
      round trip, once it has been measured on hardware.

## 2. ROM images

- [x] Decode the TOS header: version, operating-system base, both dates,
      country and video standard, and the later pointers.
- [x] Recognise EmuTOS and report its own version.
- [x] Prove trap entry points from the vector installs rather than guessing
      component boundaries, and say plainly when a boundary cannot be proven.
- [x] Build cartridge ROMs and split a ROM into the chip files a real board
      takes.
- [ ] Identify a real TOS ROM by exact hash from a catalogue the operator
      builds, with the same per-owner privacy rule the ROM workbench already
      uses.

## 3. Emulator and hardware

- [x] Drive Hatari for every machine in the range, with floppy, ACSI, SCSI,
      IDE and host-folder media.
- [x] Choose firmware automatically: a TOS ROM the operator supplies, falling
      back to the bundled EmuTOS so the emulator always works.
- [x] Describe the Atari hardware range as profiles with requires and
      conflicts, and use them in analysis, deployment and the emulator.
- [ ] Use the Hatari control socket for remote control during a managed
      session, so a test run can be driven rather than only watched.
- [ ] Correlate a debugger watchpoint with a cheat candidate, which is the one
      remaining piece of the cheat workflow that is still tester supplied.

## 4. Preparing a drive and installing software

- [x] Prepare a drive end to end: partition, format, write the boot sector and
      report what will boot it.
- [x] Install an operator-supplied hard-disk driver into the `AUTO` folder and
      the boot sector, recording exactly what was installed. Where a driver's
      distribution carries no 512-byte root-sector loader, and most do not
      because the loader lives inside the driver's own Atari installer, the
      root sector is left alone and the result says so.
- [x] Offer driverless booting under the bundled EmuTOS as the default, since
      it needs no third-party file.
- [x] Stage a floppy onto a drive, install a staged title into its own folder,
      and run a title's own installer under the emulator.
- [x] Write and merge `DESKTOP.INF` entries so an installed title appears on
      the desktop.

## 5. Analysis, reports and deployment

- [x] Report Atari findings: `AUTO` folder order, desktop configuration,
      program headers and their flags, bootable disks, name conflicts and the
      TOS limits that apply to the image.
- [x] Generate the saved-package README from the Atari facts, with attributes
      and datestamps instead of the previous platform's metadata.
- [x] Produce deployment packages for a Gotek, an SD card, a CF card, a host
      folder and a real ACSI drive, each with its own verification steps.

## 6. Online library and identification

- [ ] Search and download from the Atari collections that answer an ordinary
      client, and disable with a stated reason any source that does not.
- [ ] Identify a title from the naming conventions the Atari archives use,
      including the release-group tags.

## 7. Editors and languages

- [x] Read and list GFA BASIC, STOS BASIC and Atari ST BASIC, and write back
      the dialects that round-trip exactly.
- [x] Annotate disassembly with the trap calls, system variables and hardware
      registers the Atari actually uses.
- [ ] Recognise the picture, music and resource formats the ST range uses well
      enough to preview them.
- [ ] Draw a filename through the Atari ST character set. The ST font has a
      printable glyph at every code below 32, and real disks use them: the
      LucasFilm sample carries a file whose extension is the two bytes 0x0E and
      0x0F, which the ST drew as musical notes and a browser draws as nothing
      at all. Names are decoded as Latin-1 so that writing one back produces
      the identical bytes, which is right and must not change. The mapping
      belongs at the point of display only.

## 8. Interface and documentation

- [x] Give the application an Atari theme and icon without changing the layout
      or component structure.
- [x] Port the workbench frontend to the Atari media, machines and columns.
- [x] Rewrite the in-application handbook and recapture every screenshot from
      a running build.
- [x] Rewrite the main handbook and the remaining guides.

## 9. Release engineering

- [x] Establish the repository, the naming, the bundled firmware and the
      version line.
- [x] Build the container image with the emulator, the flux converter and the
      engine, and prove all three run inside it.
- [ ] Run the complete architecture build matrix for a release candidate.
- [ ] Run the generated-media and fault-injection gates for the candidate.
- [ ] Complete the real-hardware gate on an ST or STE with a real drive and a
      real hard-disk interface.
- [ ] Choose the release version, tag it, publish the notes and retain the
      previous known-good build for rollback.
