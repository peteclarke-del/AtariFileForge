"""Raw sector access and the geometry of an Atari volume.

Everything on an Atari disk is addressed in 512-byte physical sectors, which
is what the floppy controller and every ACSI, SCSI and IDE driver hand to
GEMDOS. A volume may group those into larger *logical* sectors (1024 to 16384
bytes on hard-disk partitions), so ``BlockReader`` works in physical sectors
and the volume code above it multiplies up. Keeping the byte-order helpers
here means the volume code never has to remember that the BIOS parameter
block is little-endian while everything else on the machine is big-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ..errors import ConfigurationError, DataError

#: The physical sector size of every Atari floppy and hard disk.
SECTOR_SIZE = 512
#: Kept for callers that address the image in generic blocks.
BLOCK_SIZE = SECTOR_SIZE

#: Logical sector sizes GEMDOS accepts in a BIOS parameter block. AHDI and
#: HDX stop at 8192; TOS 4 and HDDRIVER go to 16384 for 512 MiB partitions.
LOGICAL_SECTOR_SIZES = (512, 1024, 2048, 4096, 8192, 16384)

#: A boot sector or AHDI root sector is executable when its 256 big-endian
#: words sum to this value.
BOOT_CHECKSUM_MAGIC = 0x1234

#: The FAT width changes at this data-cluster count. TOS and every other FAT
#: implementation agree on it.
FAT16_THRESHOLD = 4085

#: The largest cluster count TOS 1.x addresses on a hard-disk partition.
TOS_MAX_CLUSTERS = 32766

#: Entry size of one directory record.
DIRECTORY_ENTRY_SIZE = 32


# ---------------------------------------------------------------------------
# Byte-order helpers
# ---------------------------------------------------------------------------
def le16_at(data: bytes, offset: int) -> int:
    (value,) = struct.unpack_from("<H", data, offset)
    return value


def le32_at(data: bytes, offset: int) -> int:
    (value,) = struct.unpack_from("<I", data, offset)
    return value


def be16_at(data: bytes, offset: int) -> int:
    (value,) = struct.unpack_from(">H", data, offset)
    return value


def be32_at(data: bytes, offset: int) -> int:
    (value,) = struct.unpack_from(">I", data, offset)
    return value


def put_le16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, int(value) & 0xFFFF)


def put_le32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, int(value) & 0xFFFFFFFF)


def put_be16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">H", data, offset, int(value) & 0xFFFF)


def put_be32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">I", data, offset, int(value) & 0xFFFFFFFF)


def swap_bytes(data: bytes) -> bytes:
    """Exchange the two bytes of every 16-bit word.

    IDE and CompactFlash dumps are often stored this way, because the Atari
    IDE interface delivers each word with its bytes reversed and some tools
    save exactly what the bus produced. Hatari calls it ``--ide-swap``.
    """
    swapped = bytearray(len(data))
    swapped[0::2] = data[1::2]
    swapped[1::2] = data[0::2]
    return bytes(swapped)


def word_sum(sector: bytes) -> int:
    """Sum the 256 big-endian words of one 512-byte sector, modulo 65536."""
    if len(sector) < SECTOR_SIZE:
        sector = bytes(sector).ljust(SECTOR_SIZE, b"\0")
    total = 0
    for offset in range(0, SECTOR_SIZE, 2):
        total += be16_at(sector, offset)
    return total & 0xFFFF


def is_executable_sector(sector: bytes) -> bool:
    """True when the ROM would execute this boot or root sector."""
    return word_sum(sector) == BOOT_CHECKSUM_MAGIC


def apply_boot_checksum(sector: bytearray, executable: bool) -> bytearray:
    """Set the checksum word at 0x1FE so the sector is, or is not, executable.

    The ROM runs a boot sector only when the word sum is exactly 0x1234, so
    clearing the flag means choosing a value that breaks that sum. Zero does
    that in every realistic case; the fallback covers a sector whose other
    words already happen to total 0x1234.
    """
    put_be16(sector, 0x1FE, 0)
    remainder = word_sum(bytes(sector))
    if executable:
        put_be16(sector, 0x1FE, (BOOT_CHECKSUM_MAGIC - remainder) & 0xFFFF)
    elif remainder == BOOT_CHECKSUM_MAGIC:
        put_be16(sector, 0x1FE, 1)
    return sector


# ---------------------------------------------------------------------------
# Sector access
# ---------------------------------------------------------------------------
class BlockReader:
    """A seekable window onto an image file, addressed in whole sectors."""

    def __init__(
        self,
        path: Path | str,
        *,
        writable: bool = False,
        offset: int = 0,
        length: int | None = None,
        block_size: int = SECTOR_SIZE,
    ):
        self.path = Path(path)
        self.writable = bool(writable)
        self.block_size = int(block_size)
        self._handle = self.path.open("r+b" if writable else "rb")
        size = self.path.stat().st_size
        self.offset = int(offset)
        if self.offset < 0 or self.offset > size:
            self._handle.close()
            raise DataError("The partition starts beyond the end of the image.")
        available = size - self.offset
        self.length = int(length) if length is not None else available
        if self.length > available:
            # A partition table may describe a drive larger than the file that
            # holds it. Report the honest usable extent rather than reading
            # past the end of the file.
            self.length = available
        self.total_blocks = self.length // self.block_size

    # ---- context management ------------------------------------------
    def __enter__(self) -> "BlockReader":
        return self

    def __exit__(self, *_exception) -> None:
        self.close()

    def close(self) -> None:
        if not self._handle.closed:
            if self.writable:
                self._handle.flush()
            self._handle.close()

    # ---- sector access -----------------------------------------------
    @property
    def total_sectors(self) -> int:
        return self.total_blocks

    def read_block(self, number: int) -> bytes:
        if not 0 <= number < self.total_blocks:
            raise DataError(f"Sector {number} is outside this volume.")
        self._handle.seek(self.offset + number * self.block_size)
        data = self._handle.read(self.block_size)
        if len(data) < self.block_size:
            data = data.ljust(self.block_size, b"\0")
        return data

    def write_block(self, number: int, data: bytes) -> None:
        if not self.writable:
            raise DataError("This volume is open read-only.")
        if not 0 <= number < self.total_blocks:
            raise DataError(f"Sector {number} is outside this volume.")
        if len(data) != self.block_size:
            raise DataError("A sector write must supply exactly one sector.")
        self._handle.seek(self.offset + number * self.block_size)
        self._handle.write(data)

    def read_blocks(self, start: int, count: int) -> bytes:
        """Read ``count`` consecutive sectors in one call."""
        if count <= 0:
            return b""
        if not 0 <= start < self.total_blocks or start + count > self.total_blocks:
            raise DataError(
                f"Sectors {start} to {start + count - 1} are outside this volume."
            )
        self._handle.seek(self.offset + start * self.block_size)
        wanted = count * self.block_size
        data = self._handle.read(wanted)
        if len(data) < wanted:
            data = data.ljust(wanted, b"\0")
        return data

    def write_blocks(self, start: int, data: bytes) -> None:
        """Write whole consecutive sectors starting at ``start``."""
        if not self.writable:
            raise DataError("This volume is open read-only.")
        if len(data) % self.block_size:
            raise DataError("A multi-sector write must supply whole sectors.")
        count = len(data) // self.block_size
        if count == 0:
            return
        if not 0 <= start < self.total_blocks or start + count > self.total_blocks:
            raise DataError(
                f"Sectors {start} to {start + count - 1} are outside this volume."
            )
        self._handle.seek(self.offset + start * self.block_size)
        self._handle.write(data)

    def flush(self) -> None:
        if self.writable and not self._handle.closed:
            self._handle.flush()

    def window(self, offset_blocks: int, length_blocks: int) -> "BlockReader":
        """Open a nested reader for one partition of this device."""
        return BlockReader(
            self.path,
            writable=self.writable,
            offset=self.offset + offset_blocks * self.block_size,
            length=length_blocks * self.block_size,
            block_size=self.block_size,
        )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def _power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def root_directory_sectors(root_entries: int, sector_size: int) -> int:
    return -(-(int(root_entries) * DIRECTORY_ENTRY_SIZE) // int(sector_size))


def minimum_sectors_per_fat(
    total_sectors: int,
    *,
    sector_size: int,
    sectors_per_cluster: int,
    reserved: int,
    fats: int,
    root_entries: int,
    fat_bits: int | None = None,
) -> tuple[int, int]:
    """Return the smallest FAT that indexes every data cluster, and its width.

    The FAT size and the cluster count depend on each other, so the count is
    solved iteratively: start from the largest possible data area and shrink
    it until the FAT that describes it fits in the space set aside for it.
    """
    root_sectors = root_directory_sectors(root_entries, sector_size)
    overhead = reserved + root_sectors
    if total_sectors <= overhead + fats + sectors_per_cluster:
        raise ConfigurationError("The volume is too small to hold a FAT and a root directory.")
    spf = 1
    while True:
        data_sectors = total_sectors - overhead - fats * spf
        clusters = data_sectors // sectors_per_cluster
        if clusters <= 0:
            raise ConfigurationError("The volume is too small to hold any data clusters.")
        bits = fat_bits or (12 if clusters < FAT16_THRESHOLD else 16)
        needed_bytes = ((clusters + 2) * 3 + 1) // 2 if bits == 12 else (clusters + 2) * 2
        needed = -(-needed_bytes // sector_size)
        if needed <= spf:
            return spf, bits
        spf = needed


class ByteSwappedReader(BlockReader):
    """A reader over a byte-swapped image that presents it unswapped.

    Every read is swapped back and every write is swapped before it lands,
    so the volume code above never learns the image was stored this way.
    """

    byte_swapped = True

    def read_block(self, number: int) -> bytes:
        return swap_bytes(super().read_block(number))

    def read_blocks(self, start: int, count: int) -> bytes:
        return swap_bytes(super().read_blocks(start, count))

    def write_block(self, number: int, data: bytes) -> None:
        super().write_block(number, swap_bytes(bytes(data)))

    def write_blocks(self, start: int, data: bytes) -> None:
        super().write_blocks(start, swap_bytes(bytes(data)))

    def window(self, offset_blocks: int, length_blocks: int) -> "ByteSwappedReader":
        return ByteSwappedReader(
            self.path,
            writable=self.writable,
            offset=self.offset + offset_blocks * self.block_size,
            length=length_blocks * self.block_size,
            block_size=self.block_size,
        )


@dataclass
class Geometry:
    """The BIOS parameter block of one volume, plus its physical layout.

    ``sector_size`` is the logical sector size GEMDOS works in. Floppies use
    512 bytes; AHDI partitions use larger logical sectors so the cluster
    count stays within what TOS 1.x can address. ``total_sectors`` and
    ``sectors_per_fat`` are counted in logical sectors.
    """

    sector_size: int = SECTOR_SIZE
    sectors_per_cluster: int = 2
    sectors_per_track: int = 9
    sides: int = 2
    tracks: int = 80
    reserved: int = 1
    fats: int = 2
    root_entries: int = 112
    total_sectors: int = 1440
    sectors_per_fat: int = 5
    media: int = 0xF9
    hidden: int = 0
    label: str = ""
    #: An explicit FAT width. Hard-disk partitions are FAT16 whatever their
    #: cluster count, because the driver's BPB says so; None applies the
    #: cluster-count rule floppies follow.
    fat_width: int | None = None

    # ---- derived layout ----------------------------------------------
    @property
    def root_sectors(self) -> int:
        return root_directory_sectors(self.root_entries, self.sector_size)

    @property
    def fat_start(self) -> int:
        return self.reserved

    @property
    def root_start(self) -> int:
        return self.reserved + self.fats * self.sectors_per_fat

    @property
    def data_start(self) -> int:
        return self.root_start + self.root_sectors

    @property
    def data_clusters(self) -> int:
        data = self.total_sectors - self.data_start
        return max(0, data // self.sectors_per_cluster)

    @property
    def fat_bits(self) -> int:
        if self.fat_width in (12, 16):
            return self.fat_width
        return 12 if self.data_clusters < FAT16_THRESHOLD else 16

    @property
    def cluster_bytes(self) -> int:
        return self.sector_size * self.sectors_per_cluster

    @property
    def size_bytes(self) -> int:
        return self.total_sectors * self.sector_size

    @property
    def physical_per_logical(self) -> int:
        return self.sector_size // SECTOR_SIZE

    @property
    def physical_sectors(self) -> int:
        return self.total_sectors * self.physical_per_logical

    @property
    def format(self) -> str:
        return f"FAT{self.fat_bits}"

    def check(self) -> None:
        """Reject a geometry GEMDOS could not mount."""
        if self.sector_size not in LOGICAL_SECTOR_SIZES:
            raise ConfigurationError(
                f"A logical sector is 512, 1024, 2048, 4096 or 8192 bytes, not {self.sector_size}."
            )
        if not _power_of_two(self.sectors_per_cluster) or self.sectors_per_cluster > 128:
            raise ConfigurationError("Sectors per cluster must be a power of two up to 128.")
        if self.fats not in (1, 2):
            raise ConfigurationError("A volume carries one or two FATs.")
        if self.reserved < 1:
            raise ConfigurationError("At least one reserved sector is needed for the boot sector.")
        if self.root_entries <= 0:
            raise ConfigurationError("The root directory needs at least one entry.")
        if self.sectors_per_fat <= 0:
            raise ConfigurationError("Each FAT needs at least one sector.")
        if self.data_clusters <= 0:
            raise ConfigurationError("The volume has no room for data clusters.")
        minimum, _bits = minimum_sectors_per_fat(
            self.total_sectors,
            sector_size=self.sector_size,
            sectors_per_cluster=self.sectors_per_cluster,
            reserved=self.reserved,
            fats=self.fats,
            root_entries=self.root_entries,
            fat_bits=self.fat_width,
        )
        if self.sectors_per_fat < minimum:
            raise ConfigurationError(
                f"A FAT of {self.sectors_per_fat} sector(s) cannot index "
                f"{self.data_clusters} clusters; at least {minimum} are needed."
            )

    def to_dict(self) -> dict:
        return {
            "sectorSize": self.sector_size,
            "sectorsPerCluster": self.sectors_per_cluster,
            "sectorsPerTrack": self.sectors_per_track,
            "sides": self.sides,
            "tracks": self.tracks,
            "reserved": self.reserved,
            "fats": self.fats,
            "rootEntries": self.root_entries,
            "totalSectors": self.total_sectors,
            "sectorsPerFat": self.sectors_per_fat,
            "media": self.media,
            "hidden": self.hidden,
            "fatBits": self.fat_bits,
            "format": self.format,
            "clusterBytes": self.cluster_bytes,
            "dataClusters": self.data_clusters,
            "sizeBytes": self.size_bytes,
            "label": self.label,
        }


#: FAT sizes TOS writes for its standard floppy formats. The mathematically
#: smallest FAT would be shorter on a double-sided disk; TOS allocates five
#: sectors regardless, and matching it keeps an image byte-compatible with a
#: disk formatted on the machine.
TOS_FLOPPY_FAT_SECTORS = {9: 5, 10: 5, 11: 5, 18: 9}
TOS_SINGLE_SIDED_FAT_SECTORS = {9: 2, 10: 2, 11: 2}


def floppy_geometry(tracks: int, sides: int, sectors_per_track: int) -> Geometry:
    """Build the geometry TOS writes when it formats a floppy of this shape."""
    total = tracks * sides * sectors_per_track
    high_density = sectors_per_track >= 15
    root_entries = 224 if high_density else 112
    if high_density:
        media = 0xF0
    else:
        media = 0xF9 if sides == 2 else 0xF8
    minimum, _bits = minimum_sectors_per_fat(
        total,
        sector_size=SECTOR_SIZE,
        sectors_per_cluster=2,
        reserved=1,
        fats=2,
        root_entries=root_entries,
    )
    table = TOS_FLOPPY_FAT_SECTORS if sides == 2 else TOS_SINGLE_SIDED_FAT_SECTORS
    spf = max(minimum, table.get(sectors_per_track, minimum))
    return Geometry(
        sector_size=SECTOR_SIZE,
        sectors_per_cluster=2,
        sectors_per_track=sectors_per_track,
        sides=sides,
        tracks=tracks,
        reserved=1,
        fats=2,
        root_entries=root_entries,
        total_sectors=total,
        sectors_per_fat=spf,
        media=media,
    )


#: Named floppy geometries the workbench can create.
NAMED_GEOMETRIES: dict[str, Geometry] = {
    "ss-360k": floppy_geometry(80, 1, 9),
    "ss-400k": floppy_geometry(80, 1, 10),
    "ss-440k": floppy_geometry(80, 1, 11),
    "ds-720k": floppy_geometry(80, 2, 9),
    "ds-800k": floppy_geometry(80, 2, 10),
    "ds-880k": floppy_geometry(80, 2, 11),
    "ds-720k-81": floppy_geometry(81, 2, 9),
    "ds-800k-81": floppy_geometry(81, 2, 10),
    "ds-880k-81": floppy_geometry(81, 2, 11),
    "ds-720k-82": floppy_geometry(82, 2, 9),
    "ds-800k-82": floppy_geometry(82, 2, 10),
    "ds-880k-82": floppy_geometry(82, 2, 11),
    "ds-720k-83": floppy_geometry(83, 2, 9),
    "ds-800k-83": floppy_geometry(83, 2, 10),
    "ds-880k-83": floppy_geometry(83, 2, 11),
    "hd-1440k": floppy_geometry(80, 2, 18),
}

#: Friendly spellings accepted by the command line.
GEOMETRY_ALIASES = {
    "360k": "ss-360k",
    "400k": "ss-400k",
    "440k": "ss-440k",
    "720k": "ds-720k",
    "800k": "ds-800k",
    "880k": "ds-880k",
    "1440k": "hd-1440k",
    "hd": "hd-1440k",
    "dd": "ds-720k",
    "ss": "ss-360k",
    "ds": "ds-720k",
    "floppy": "ds-720k",
}

DD_SECTORS = NAMED_GEOMETRIES["ds-720k"].total_sectors
HD_SECTORS = NAMED_GEOMETRIES["hd-1440k"].total_sectors


def named_geometry(name: str) -> Geometry:
    """Return a copy of a named floppy geometry."""
    key = str(name or "").strip().lower()
    key = GEOMETRY_ALIASES.get(key, key)
    if key not in NAMED_GEOMETRIES:
        raise ConfigurationError(
            f"{name!r} is not a floppy format. Choose one of: "
            + ", ".join(sorted(NAMED_GEOMETRIES))
        )
    source = NAMED_GEOMETRIES[key]
    return Geometry(**{field: getattr(source, field) for field in source.__dataclass_fields__})


def partition_geometry(
    physical_sectors: int,
    *,
    root_entries: int = 512,
    label: str = "",
) -> Geometry:
    """Choose the BIOS parameter block a hard-disk driver writes for a partition.

    AHDI, HDX and HDDRIVER all keep two sectors per cluster and grow the
    *logical* sector instead: the smallest power of two from 512 to 16384
    bytes that brings the cluster count to 32766 or fewer, because TOS 1.x
    holds the cluster number in a signed 16-bit word. 16 KiB sectors give a
    32 KiB cluster and cover 512 MiB, which is the largest partition TOS
    can use without a replacement DOS. The partition is FAT16 whatever its
    cluster count, because the driver's BPB flags it so.
    """
    physical_sectors = int(physical_sectors)
    for sector_size in LOGICAL_SECTOR_SIZES:
        per_logical = sector_size // SECTOR_SIZE
        logical_total = physical_sectors // per_logical
        if logical_total // 2 <= TOS_MAX_CLUSTERS:
            break
    sectors_per_cluster = 2
    while logical_total // sectors_per_cluster > TOS_MAX_CLUSTERS and sectors_per_cluster < 128:
        # Beyond 512 MiB no logical sector size keeps the count in range.
        # Doubling the cluster keeps the volume usable by later systems that
        # ignore the TOS 1.x limit.
        sectors_per_cluster *= 2
    spf, _bits = minimum_sectors_per_fat(
        logical_total,
        sector_size=sector_size,
        sectors_per_cluster=sectors_per_cluster,
        reserved=1,
        fats=2,
        root_entries=root_entries,
        fat_bits=16,
    )
    return Geometry(
        sector_size=sector_size,
        sectors_per_cluster=sectors_per_cluster,
        sectors_per_track=0,
        sides=0,
        tracks=0,
        reserved=1,
        fats=2,
        root_entries=root_entries,
        total_sectors=logical_total,
        sectors_per_fat=spf,
        media=0xF8,
        label=label,
        fat_width=16,
    )


def volume_geometry(size_bytes: int, *, label: str = "") -> Geometry:
    """Pick a geometry for an image of arbitrary size.

    Floppy-sized images get the matching TOS floppy format when one exists;
    anything else is laid out as a hard-disk partition.
    """
    sectors = int(size_bytes) // SECTOR_SIZE
    for geometry in NAMED_GEOMETRIES.values():
        if geometry.total_sectors == sectors:
            copy = named_geometry(
                next(name for name, value in NAMED_GEOMETRIES.items() if value is geometry)
            )
            copy.label = label
            return copy
    return partition_geometry(sectors, label=label)


__all__ = [
    "BLOCK_SIZE",
    "BOOT_CHECKSUM_MAGIC",
    "ByteSwappedReader",
    "DD_SECTORS",
    "DIRECTORY_ENTRY_SIZE",
    "FAT16_THRESHOLD",
    "GEOMETRY_ALIASES",
    "HD_SECTORS",
    "LOGICAL_SECTOR_SIZES",
    "NAMED_GEOMETRIES",
    "SECTOR_SIZE",
    "TOS_MAX_CLUSTERS",
    "BlockReader",
    "Geometry",
    "apply_boot_checksum",
    "be16_at",
    "be32_at",
    "floppy_geometry",
    "is_executable_sector",
    "le16_at",
    "le32_at",
    "minimum_sectors_per_fat",
    "named_geometry",
    "partition_geometry",
    "put_be16",
    "put_be32",
    "put_le16",
    "put_le32",
    "root_directory_sectors",
    "swap_bytes",
    "volume_geometry",
    "word_sum",
]
