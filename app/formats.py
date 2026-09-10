"""File-format declarations shared by upload and image handling.

Extensions are a hint, never a decision: every opened image is identified from
its bytes. What these sets do is decide which probe runs first and which files
the browser offers, so a 400 MiB hard-drive file is not scanned for a TOS ROM
before it is scanned for a partition table.

``.img`` appears in both the ROM and hard-disk sets on purpose. A cartridge
dump and an ACSI drive image are both distributed under it; only the bytes
say which, and that is read at open time.
"""

#: Plain sector images of an ST floppy: no header, the boot sector decides.
ST_EXTENSIONS = {".st"}

#: Magic Shadow Archiver images: a floppy, run-length packed track by track.
MSA_EXTENSIONS = {".msa"}

#: FastCopy Pro images: a floppy behind a 32-byte header.
DIM_EXTENSIONS = {".dim"}

#: Pasti captures: sectors as the controller saw them, protection included.
#: Read only; there is nothing to write one from.
STX_EXTENSIONS = {".stx"}

#: Gotek and HxC track images.
HFE_EXTENSIONS = {".hfe"}

#: SuperCard Pro flux captures.
SCP_EXTENSIONS = {".scp"}

#: SPS preservation captures. Reading one needs the SPS decoder library, which
#: is looked for at run time rather than shipped.
IPF_EXTENSIONS = {".ipf"}

#: CD images. A good deal of ST and Falcon material was published on CD, so a
#: disc is opened and browsed like any other read-only container.
ISO_EXTENSIONS = {".iso", ".cdr"}

#: TOS, cartridge and expansion ROM images. ``.img`` is ambiguous with a
#: hard-disk image and ``.bin`` with a bare volume: the byte probe decides.
ROM_EXTENSIONS = {".img", ".rom", ".tos", ".bin"}

#: ACSI, SCSI and IDE hard-disk images, partitioned or bare.
HARD_DISK_EXTENSIONS = {".img", ".hd", ".ahd", ".acsi", ".ide", ".raw", ".bin"}

#: Anything that may hold a FAT volume TOS can mount: every floppy container
#: whose sectors can be recovered, and every hard-disk image.
GEMDOS_EXTENSIONS = (
    ST_EXTENSIONS
    | MSA_EXTENSIONS
    | DIM_EXTENSIONS
    | STX_EXTENSIONS
    | HFE_EXTENSIONS
    | SCP_EXTENSIONS
    | IPF_EXTENSIONS
    | HARD_DISK_EXTENSIONS
)

#: The geometry sidecar that accompanies a bare hard-disk image.
GEOMETRY_EXTENSIONS = {".geo"}
