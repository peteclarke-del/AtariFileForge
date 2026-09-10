"""AHDI and MBR: the partition tables an Atari hard disk can carry.

Sector 0 of an Atari hard disk is the *root sector*. Its tail holds the
disk size, four twelve-byte partition entries, the bad-sector list and a
checksum word, all big-endian. Two extensions widen that:

* **XGM** chains. An entry with the id ``XGM`` points at a sector holding
  another root-sector-shaped table. That table's first entry describes a
  partition relative to the XGM sector itself; its second entry, if it is
  another ``XGM``, points at the next table relative to the *first* XGM
  sector. This module follows that chain exactly as the Linux kernel's
  ``block/partitions/atari.c`` does.
* **ICD** tables. ICD's driver keeps eight more entries at 0x156, ahead of
  the standard four, for twelve partitions in a flat table.

Two more things turn up on real media and are handled here as well:

* **MBR** tables. TOS 4, HDDRIVER, MiNT and Hatari all accept a PC master
  boot record with FAT partition types, and images made on a PC carry one.
* **Byte-swapped** images. An IDE or CompactFlash dump often stores every
  16-bit word with its bytes exchanged. The table is tried as-is and then
  swapped; a swapped disk is flagged and its partitions are read through a
  reader that swaps back, so nothing above this module sees the difference.

Partition ids are ``GEM`` (up to 16 MiB, usable by every TOS), ``BGM``
(larger, TOS 1.04 and later), ``RAW``, ``LNX`` and ``SWP``. MBR partitions
carry their DOS type code instead. Everything is counted in 512-byte
physical sectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ConfigurationError, DataError
from .blocks import (
    SECTOR_SIZE,
    BlockReader,
    ByteSwappedReader,
    apply_boot_checksum,
    be32_at,
    is_executable_sector,
    le32_at,
    partition_geometry,
    put_be32,
    put_le32,
    swap_bytes,
)

ROOT_HD_SIZE = 0x1C2
ROOT_PARTITIONS = 0x1C6
ROOT_BAD_START = 0x1F6
ROOT_BAD_COUNT = 0x1FA
ROOT_CHECKSUM = 0x1FE
ICD_PARTITIONS = 0x156
ICD_EXTRA_ENTRIES = 8
PRIMARY_ENTRIES = 4
ENTRY_SIZE = 12

FLAG_EXISTS = 0x01
FLAG_BOOTABLE = 0x80

#: Ids the ROM driver and TOS mount as GEMDOS volumes.
GEMDOS_IDS = ("GEM", "BGM")
#: Ids accepted by the ICD table check, as in the Linux kernel.
KNOWN_IDS = ("GEM", "BGM", "RAW", "LNX", "SWP")
EXTENDED_ID = "XGM"

#: The largest partition a ``GEM`` id can describe.
GEM_LIMIT_BYTES = 16 * 1024 * 1024

# MBR layout.
MBR_PARTITIONS = 0x1BE
MBR_ENTRY_SIZE = 16
MBR_SIGNATURE = 0x1FE
MBR_TYPE_FAT12 = 0x01
MBR_TYPE_FAT16_SMALL = 0x04
MBR_TYPE_FAT16 = 0x06
MBR_TYPE_FAT16_LBA = 0x0E
MBR_TYPE_EXTENDED = 0x05
MBR_TYPE_EXTENDED_LBA = 0x0F
MBR_FAT_TYPES = (MBR_TYPE_FAT12, MBR_TYPE_FAT16_SMALL, MBR_TYPE_FAT16, MBR_TYPE_FAT16_LBA)
MBR_EXTENDED_TYPES = (MBR_TYPE_EXTENDED, MBR_TYPE_EXTENDED_LBA)
MBR_BOOT_FLAG = 0x80


def _alnum(byte: int) -> bool:
    return byte < 128 and chr(byte).isalnum()


@dataclass
class RawEntry:
    """One twelve-byte AHDI table entry as it sits on disk."""

    flags: int
    id: str
    start: int
    size: int

    @property
    def exists(self) -> bool:
        return bool(self.flags & FLAG_EXISTS)

    @property
    def bootable(self) -> bool:
        return bool(self.flags & FLAG_BOOTABLE)

    def valid(self, hd_size: int) -> bool:
        """The kernel's VALID_PARTITION: flagged, alphanumeric id, inside the disk."""
        raw_id = self.id.encode("latin-1", "replace")
        return (
            self.exists
            and len(raw_id) == 3
            and all(_alnum(byte) for byte in raw_id)
            and self.start <= hd_size
            and self.start + self.size <= hd_size
        )


def _read_entry(sector: bytes, offset: int) -> RawEntry:
    return RawEntry(
        flags=sector[offset],
        id=sector[offset + 1:offset + 4].decode("latin-1"),
        start=be32_at(sector, offset + 4),
        size=be32_at(sector, offset + 8),
    )


def _write_entry(sector: bytearray, offset: int, entry: RawEntry | None) -> None:
    if entry is None:
        sector[offset:offset + ENTRY_SIZE] = bytes(ENTRY_SIZE)
        return
    sector[offset] = entry.flags & 0xFF
    sector[offset + 1:offset + 4] = entry.id.encode("latin-1")[:3].ljust(3, b" ")
    put_be32(sector, offset + 4, entry.start)
    put_be32(sector, offset + 8, entry.size)


@dataclass
class Partition:
    """One partition, resolved to absolute sectors."""

    index: int
    id: str
    start_sector: int
    size_sectors: int
    bootable: bool = False
    flags: int = FLAG_EXISTS
    label: str = ""
    extended: bool = False
    type_code: int | None = None
    byte_swapped: bool = False
    sector_size: int = SECTOR_SIZE

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * self.sector_size

    @property
    def end_sector(self) -> int:
        return self.start_sector + self.size_sectors

    @property
    def name(self) -> str:
        """The drive letter TOS assigns: C: for the first partition."""
        return f"{chr(ord('C') + self.index)}:" if self.index < 14 else f"#{self.index}"

    @property
    def is_gemdos(self) -> bool:
        if self.type_code is not None:
            return self.type_code in MBR_FAT_TYPES
        return self.id in GEMDOS_IDS

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "id": self.id,
            "name": self.name,
            "device": self.name,
            "label": self.label,
            "bootable": self.bootable,
            "flags": self.flags,
            "extended": self.extended,
            "typeCode": self.type_code,
            "byteSwapped": self.byte_swapped,
            "startSector": self.start_sector,
            "sizeSectors": self.size_sectors,
            "sizeBytes": self.size_bytes,
            "gemdos": self.is_gemdos,
        }


@dataclass
class AhdiDisk:
    """The decoded partition table and every partition reachable from it."""

    hd_size: int
    partitions: list[Partition] = field(default_factory=list)
    bad_sector_start: int = 0
    bad_sector_count: int = 0
    bootable: bool = False
    scheme: str = "ahdi"
    byte_swapped: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def size_bytes(self) -> int:
        return self.hd_size * SECTOR_SIZE

    def partition(self, index: int) -> Partition:
        for candidate in self.partitions:
            if candidate.index == index:
                return candidate
        raise DataError(f"Partition {index} does not exist on this drive.")

    def to_dict(self) -> dict:
        return {
            "hdSize": self.hd_size,
            "sizeBytes": self.size_bytes,
            "badSectorStart": self.bad_sector_start,
            "badSectorCount": self.bad_sector_count,
            "bootable": self.bootable,
            "scheme": self.scheme,
            "byteSwapped": self.byte_swapped,
            "partitions": [partition.to_dict() for partition in self.partitions],
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _read_sector(reader: BlockReader, number: int, swapped: bool) -> bytes:
    data = reader.read_block(number)
    return swap_bytes(data) if swapped else data


def _ahdi_disk(reader: BlockReader, root: bytes, swapped: bool) -> AhdiDisk | None:
    """Decode an AHDI root sector, or return None when it is not one."""
    hd_size = be32_at(root, ROOT_HD_SIZE)
    primary = [_read_entry(root, ROOT_PARTITIONS + slot * ENTRY_SIZE) for slot in range(PRIMARY_ENTRIES)]
    icd = [_read_entry(root, ICD_PARTITIONS + slot * ENTRY_SIZE) for slot in range(ICD_EXTRA_ENTRIES)]
    if not any(entry.valid(hd_size) for entry in primary):
        return None
    disk = AhdiDisk(
        hd_size=hd_size,
        bad_sector_start=be32_at(root, ROOT_BAD_START),
        bad_sector_count=be32_at(root, ROOT_BAD_COUNT),
        bootable=is_executable_sector(root),
        byte_swapped=swapped,
    )

    def add(entry: RawEntry, start: int, extended: bool = False) -> None:
        disk.partitions.append(
            Partition(
                index=len(disk.partitions),
                id=entry.id,
                start_sector=start,
                size_sectors=entry.size,
                bootable=entry.bootable,
                flags=entry.flags,
                extended=extended,
                byte_swapped=swapped,
            )
        )

    has_extended = False
    for entry in primary:
        if not entry.exists:
            continue
        if entry.id != EXTENDED_ID:
            add(entry, entry.start)
            continue
        has_extended = True
        first_extended = entry.start
        table_sector = first_extended
        seen: set[int] = set()
        while True:
            if table_sector in seen or table_sector >= reader.total_blocks:
                disk.notes.append(f"The XGM chain at sector {table_sector} is damaged.")
                break
            seen.add(table_sector)
            table = _read_sector(reader, table_sector, swapped)
            head = _read_entry(table, ROOT_PARTITIONS)
            if not head.valid(hd_size):
                disk.notes.append(f"The XGM table at sector {table_sector} has no valid partition.")
                break
            add(head, table_sector + head.start, extended=True)
            link = _read_entry(table, ROOT_PARTITIONS + ENTRY_SIZE)
            if not link.exists or link.id != EXTENDED_ID:
                break
            table_sector = first_extended + link.start
    if has_extended:
        disk.scheme = "xgm"
    elif icd[0].exists and icd[0].id in KNOWN_IDS:
        disk.scheme = "icd"
        for entry in icd:
            if entry.exists and entry.id in KNOWN_IDS:
                add(entry, entry.start)
    return disk


def _mbr_entry(sector: bytes, offset: int) -> tuple[int, int, int, int]:
    return (
        sector[offset],
        sector[offset + 4],
        le32_at(sector, offset + 8),
        le32_at(sector, offset + 12),
    )


def _mbr_disk(reader: BlockReader, sector: bytes, swapped: bool) -> AhdiDisk | None:
    """Decode a PC master boot record, or return None when it is not one."""
    if sector[MBR_SIGNATURE:MBR_SIGNATURE + 2] != b"\x55\xaa":
        return None
    entries = [_mbr_entry(sector, MBR_PARTITIONS + slot * MBR_ENTRY_SIZE) for slot in range(4)]
    usable = [
        entry for entry in entries
        if entry[1] in MBR_FAT_TYPES + MBR_EXTENDED_TYPES
        and entry[0] in (0, MBR_BOOT_FLAG)
        and entry[2] > 0
        and entry[3] > 0
    ]
    if not usable:
        return None
    disk = AhdiDisk(
        hd_size=reader.total_blocks,
        bootable=any(entry[0] == MBR_BOOT_FLAG for entry in usable),
        scheme="mbr",
        byte_swapped=swapped,
    )

    def add(boot: int, kind: int, start: int, size: int, extended: bool = False) -> None:
        disk.partitions.append(
            Partition(
                index=len(disk.partitions),
                id=f"{kind:02X}",
                start_sector=start,
                size_sectors=size,
                bootable=boot == MBR_BOOT_FLAG,
                flags=FLAG_EXISTS | (FLAG_BOOTABLE if boot == MBR_BOOT_FLAG else 0),
                extended=extended,
                type_code=kind,
                byte_swapped=swapped,
            )
        )

    for boot, kind, start, size in usable:
        if kind not in MBR_EXTENDED_TYPES:
            add(boot, kind, start, size)
            continue
        first_extended = start
        table_sector = start
        seen: set[int] = set()
        while True:
            if table_sector in seen or table_sector >= reader.total_blocks:
                disk.notes.append(f"The extended partition chain at sector {table_sector} is damaged.")
                break
            seen.add(table_sector)
            table = _read_sector(reader, table_sector, swapped)
            if table[MBR_SIGNATURE:MBR_SIGNATURE + 2] != b"\x55\xaa":
                disk.notes.append(f"The extended boot record at sector {table_sector} has no signature.")
                break
            head = _mbr_entry(table, MBR_PARTITIONS)
            if head[1] in MBR_FAT_TYPES and head[3] > 0:
                add(head[0], head[1], table_sector + head[2], head[3], extended=True)
            link = _mbr_entry(table, MBR_PARTITIONS + MBR_ENTRY_SIZE)
            if link[1] not in MBR_EXTENDED_TYPES or link[3] == 0:
                break
            table_sector = first_extended + link[2]
    return disk


def read_partition_table(reader: BlockReader) -> AhdiDisk:
    """Decode sector 0 as an AHDI root sector or an MBR, swapped if need be."""
    if not reader.total_blocks:
        raise DataError("The image is empty.")
    raw = reader.read_block(0)
    already_swapped = bool(getattr(reader, "byte_swapped", False))
    for swapped in (False, True):
        sector = swap_bytes(raw) if swapped else raw
        disk = _ahdi_disk(reader, sector, swapped) or _mbr_disk(reader, sector, swapped)
        if disk is None:
            continue
        if already_swapped:
            # The reader itself already undoes the swap; do not report or
            # apply it a second time.
            disk.byte_swapped = False
            for partition in disk.partitions:
                partition.byte_swapped = False
        for partition in disk.partitions:
            if partition.end_sector > reader.total_blocks:
                disk.notes.append(
                    f"Partition {partition.name} ends at sector {partition.end_sector}, beyond the "
                    f"{reader.total_blocks} sectors the image holds."
                )
        return disk
    raise DataError("This image does not carry an AHDI or MBR partition table.")


def partition_reader(reader: BlockReader, partition: Partition) -> BlockReader:
    """Open a nested reader covering exactly one partition.

    A partition of a byte-swapped image comes back through a reader that
    swaps every read and write, so the volume code sees ordinary sectors.
    """
    if partition.byte_swapped and not getattr(reader, "byte_swapped", False):
        return ByteSwappedReader(
            reader.path,
            writable=reader.writable,
            offset=reader.offset + partition.start_sector * reader.block_size,
            length=partition.size_sectors * reader.block_size,
            block_size=reader.block_size,
        )
    return reader.window(partition.start_sector, partition.size_sectors)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _id_for_size(size_bytes: int) -> str:
    return "GEM" if size_bytes <= GEM_LIMIT_BYTES else "BGM"


def _mbr_type_for(size_sectors: int) -> int:
    if size_sectors < 65536:
        return MBR_TYPE_FAT16_SMALL
    return MBR_TYPE_FAT16


def _coerce(entries, image_sectors: int) -> list[Partition]:
    result: list[Partition] = []
    for index, item in enumerate(entries):
        if isinstance(item, Partition):
            partition = Partition(
                index=index,
                id=item.id,
                start_sector=item.start_sector,
                size_sectors=item.size_sectors,
                bootable=item.bootable,
                flags=item.flags,
                label=item.label,
                type_code=item.type_code,
            )
        else:
            size = int(item.get("size_sectors") or item.get("sizeSectors") or 0)
            if not size and item.get("size_bytes") is not None:
                size = int(item["size_bytes"]) // SECTOR_SIZE
            start = int(item.get("start_sector") or item.get("startSector") or 0)
            bootable = bool(item.get("bootable", False))
            partition = Partition(
                index=index,
                id=str(item.get("id") or _id_for_size(size * SECTOR_SIZE)).upper()[:3],
                start_sector=start,
                size_sectors=size,
                bootable=bootable,
                flags=FLAG_EXISTS | (FLAG_BOOTABLE if bootable else 0),
                label=str(item.get("label") or ""),
                type_code=item.get("type_code"),
            )
        if partition.size_sectors <= 0:
            raise ConfigurationError(f"Partition {index} has no size.")
        if partition.start_sector < 1:
            raise ConfigurationError(f"Partition {index} would overwrite the root sector.")
        if partition.end_sector > image_sectors:
            raise ConfigurationError(
                f"Partition {index} ends at sector {partition.end_sector}, beyond the image's "
                f"{image_sectors} sectors."
            )
        result.append(partition)
    ordered = sorted(result, key=lambda p: p.start_sector)
    for earlier, later in zip(ordered, ordered[1:]):
        if earlier.end_sector > later.start_sector:
            raise ConfigurationError(f"Partitions {earlier.index} and {later.index} overlap.")
    return result


def write_partition_table(
    reader: BlockReader,
    partitions,
    *,
    bootable: bool = False,
    hd_size: int | None = None,
    scheme: str = "ahdi",
) -> AhdiDisk:
    """Write a partition table describing ``partitions``.

    With the default ``ahdi`` scheme up to four partitions fit in the root
    sector; a fifth and later become an XGM chain, whose fourth root slot
    points at an extended table sector that must sit immediately before
    each such partition. Callers laying out a disk therefore leave one
    sector free in front of every partition after the third. ``icd`` writes
    up to twelve entries flat; ``mbr`` writes up to four primary entries of
    a PC master boot record.
    """
    if not reader.writable:
        raise DataError("The image is open read-only.")
    if hd_size is None:
        hd_size = reader.total_blocks
    entries = _coerce(partitions, reader.total_blocks)
    if not entries:
        raise ConfigurationError("A partition table needs at least one partition.")
    scheme = str(scheme or "ahdi").lower()
    if scheme == "mbr":
        _write_mbr(reader, entries)
        disk = read_partition_table(reader)
        for partition, entry in zip(disk.partitions, entries):
            partition.label = entry.label
        return disk
    root = bytearray(reader.read_block(0))
    root[ICD_PARTITIONS:ROOT_CHECKSUM] = bytes(ROOT_CHECKSUM - ICD_PARTITIONS)
    put_be32(root, ROOT_HD_SIZE, hd_size)

    def raw(partition: Partition, start: int) -> RawEntry:
        flags = FLAG_EXISTS | (FLAG_BOOTABLE if partition.bootable else 0)
        return RawEntry(flags=flags, id=partition.id, start=start, size=partition.size_sectors)

    if scheme == "icd":
        if len(entries) > PRIMARY_ENTRIES + ICD_EXTRA_ENTRIES:
            raise ConfigurationError("An ICD table holds at most twelve partitions.")
        for slot, partition in enumerate(entries[:PRIMARY_ENTRIES]):
            _write_entry(root, ROOT_PARTITIONS + slot * ENTRY_SIZE, raw(partition, partition.start_sector))
        for slot, partition in enumerate(entries[PRIMARY_ENTRIES:]):
            _write_entry(root, ICD_PARTITIONS + slot * ENTRY_SIZE, raw(partition, partition.start_sector))
    elif len(entries) <= PRIMARY_ENTRIES:
        for slot, partition in enumerate(entries):
            _write_entry(root, ROOT_PARTITIONS + slot * ENTRY_SIZE, raw(partition, partition.start_sector))
    else:
        for slot, partition in enumerate(entries[:PRIMARY_ENTRIES - 1]):
            _write_entry(root, ROOT_PARTITIONS + slot * ENTRY_SIZE, raw(partition, partition.start_sector))
        extended = entries[PRIMARY_ENTRIES - 1:]
        first_table = extended[0].start_sector - 1
        if first_table < 1:
            raise ConfigurationError("There is no room for the first XGM table sector.")
        _write_entry(
            root,
            ROOT_PARTITIONS + (PRIMARY_ENTRIES - 1) * ENTRY_SIZE,
            RawEntry(flags=FLAG_EXISTS, id=EXTENDED_ID, start=first_table, size=reader.total_blocks - first_table),
        )
        for position, partition in enumerate(extended):
            table_sector = partition.start_sector - 1
            table = bytearray(SECTOR_SIZE)
            put_be32(table, ROOT_HD_SIZE, hd_size)
            _write_entry(table, ROOT_PARTITIONS, raw(partition, partition.start_sector - table_sector))
            if position + 1 < len(extended):
                following = extended[position + 1]
                next_table = following.start_sector - 1
                if next_table < partition.end_sector:
                    raise ConfigurationError(
                        f"Partition {following.index} needs a free sector before it for its XGM table."
                    )
                _write_entry(
                    table,
                    ROOT_PARTITIONS + ENTRY_SIZE,
                    RawEntry(
                        flags=FLAG_EXISTS,
                        id=EXTENDED_ID,
                        start=next_table - first_table,
                        size=reader.total_blocks - next_table,
                    ),
                )
            reader.write_block(table_sector, bytes(table))
    put_be32(root, ROOT_BAD_START, 0)
    put_be32(root, ROOT_BAD_COUNT, 0)
    apply_boot_checksum(root, bootable)
    reader.write_block(0, bytes(root))
    reader.flush()
    disk = read_partition_table(reader)
    for partition, entry in zip(disk.partitions, entries):
        partition.label = entry.label
    return disk


def _write_mbr(reader: BlockReader, entries: list[Partition]) -> None:
    if len(entries) > 4:
        raise ConfigurationError("This build writes at most four primary MBR partitions.")
    sector = bytearray(reader.read_block(0))
    sector[MBR_PARTITIONS:MBR_SIGNATURE] = bytes(MBR_SIGNATURE - MBR_PARTITIONS)
    for slot, partition in enumerate(entries):
        offset = MBR_PARTITIONS + slot * MBR_ENTRY_SIZE
        sector[offset] = MBR_BOOT_FLAG if partition.bootable else 0
        sector[offset + 1:offset + 4] = b"\x00\x02\x00" if slot == 0 else b"\xfe\xff\xff"
        sector[offset + 4] = partition.type_code or _mbr_type_for(partition.size_sectors)
        sector[offset + 5:offset + 8] = b"\xfe\xff\xff"
        put_le32(sector, offset + 8, partition.start_sector)
        put_le32(sector, offset + 12, partition.size_sectors)
    sector[MBR_SIGNATURE:MBR_SIGNATURE + 2] = b"\x55\xaa"
    reader.write_block(0, bytes(sector))
    reader.flush()


def plan_layout(
    total_sectors: int,
    requests: list[dict],
    *,
    scheme: str = "ahdi",
    first_sector: int = 1,
) -> list[dict]:
    """Assign start sectors to partition requests, in order.

    Requests without a ``size_bytes`` share the remaining space equally. The
    XGM scheme needs one spare sector before every partition from the
    fourth onwards for its table.
    """
    if not requests:
        raise ConfigurationError("At least one partition is needed.")
    scheme = str(scheme or "ahdi").lower()
    planned = [dict(request) for request in requests]
    fixed = 0
    flexible = 0
    for index, request in enumerate(planned):
        chained = scheme == "ahdi" and len(planned) > PRIMARY_ENTRIES and index >= PRIMARY_ENTRIES - 1
        request["_overhead"] = 1 if chained else 0
        size = request.get("size_bytes")
        if size is None:
            flexible += 1
        else:
            fixed += -(-int(size) // SECTOR_SIZE) + request["_overhead"]
    available = total_sectors - first_sector
    if fixed > available:
        raise ConfigurationError(
            f"The requested partitions need {fixed} sectors but only {available} are available."
        )
    share = (available - fixed) // flexible if flexible else 0
    cursor = first_sector
    for request in planned:
        overhead = request.pop("_overhead")
        size = request.get("size_bytes")
        sectors = -(-int(size) // SECTOR_SIZE) if size is not None else share - overhead
        if sectors <= 0:
            raise ConfigurationError("A partition would have no sectors; the image is too small.")
        cursor += overhead
        request["start_sector"] = cursor
        request["size_sectors"] = sectors
        request["size_bytes"] = sectors * SECTOR_SIZE
        if scheme == "mbr":
            request.setdefault("type_code", _mbr_type_for(sectors))
            request["id"] = f"{request['type_code']:02X}"
        else:
            request.setdefault("id", _id_for_size(sectors * SECTOR_SIZE))
        cursor += sectors
    return planned


def create_partitioned_image(
    path: Path | str,
    size_bytes: int,
    partitions: list[dict],
    *,
    bootable: bool = False,
    scheme: str = "ahdi",
    root_entries: int = 512,
) -> AhdiDisk:
    """Create an image, write its partition table and format every partition.

    ``partitions`` entries take ``label``, ``size_bytes`` (optional), ``id``
    and ``bootable``. Each GEMDOS partition is formatted FAT16 with the
    logical sector size a hard-disk driver would choose. The returned
    disk's ``notes`` list any TOS release that cannot mount one of them.
    """
    from .gemdos import format_volume

    path = Path(path)
    size_bytes = int(size_bytes)
    total_sectors = size_bytes // SECTOR_SIZE
    if total_sectors < 4:
        raise ConfigurationError("A hard-disk image needs at least four sectors.")
    layout = plan_layout(total_sectors, partitions, scheme=scheme)
    with path.open("wb") as handle:
        handle.truncate(total_sectors * SECTOR_SIZE)
    reader = BlockReader(path, writable=True)
    try:
        disk = write_partition_table(reader, layout, bootable=bootable, scheme=scheme)
        for partition, request in zip(disk.partitions, layout):
            partition.label = str(request.get("label") or "")
            if not partition.is_gemdos:
                continue
            window = partition_reader(reader, partition)
            try:
                geometry = partition_geometry(
                    partition.size_sectors, root_entries=root_entries, label=partition.label
                )
                volume = format_volume(window, label=partition.label, geometry=geometry)
                disk.notes.extend(f"{partition.name} {note}" for note in volume.notes)
            finally:
                window.close()
    finally:
        reader.close()
    return disk


__all__ = [
    "EXTENDED_ID",
    "FLAG_BOOTABLE",
    "FLAG_EXISTS",
    "GEMDOS_IDS",
    "GEM_LIMIT_BYTES",
    "ICD_PARTITIONS",
    "KNOWN_IDS",
    "MBR_FAT_TYPES",
    "MBR_EXTENDED_TYPES",
    "ROOT_PARTITIONS",
    "AhdiDisk",
    "Partition",
    "RawEntry",
    "create_partitioned_image",
    "partition_reader",
    "plan_layout",
    "read_partition_table",
    "write_partition_table",
]
