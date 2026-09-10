"""GEMDOS: the FAT12 and FAT16 filing system TOS uses on every disk.

The Atari ST stores files in the same structures as MS-DOS: a boot sector
with a BIOS parameter block, one or two file allocation tables, a fixed-size
root directory and a data area of clusters. The differences are in the
details, and every one of them is handled here rather than left to a generic
FAT reader:

* The BPB fields are little-endian, on a big-endian machine.
* TOS ignores the jump instruction and the media byte, so a volume is
  identified by whether its BPB is plausible and its FAT readable.
* A boot sector runs only when its 256 words sum to ``0x1234``.
* Floppies use two sectors per cluster; hard-disk partitions keep that and
  grow the *logical* sector instead, because TOS 1.x cannot address more
  than 32766 clusters.

Paths use GEMDOS syntax: ``\\`` separates components, ``/`` is accepted on
input, a drive letter prefix is optional and names are 8.3 upper-case.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from ..errors import ConfigurationError, DataError
from ..file import (
    DEFAULT_ATTRIBUTES,
    EDITABLE_ATTRIBUTES,
    FA_DIRECTORY,
    FA_READONLY,
    FA_VOLUME,
    Access,
    AtariMeta,
    datetime_to_fat,
    fat_to_datetime,
)
from .blocks import (
    DIRECTORY_ENTRY_SIZE,
    FAT16_THRESHOLD,
    LOGICAL_SECTOR_SIZES,
    SECTOR_SIZE,
    TOS_MAX_CLUSTERS,
    BlockReader,
    Geometry,
    apply_boot_checksum,
    is_executable_sector,
    le16_at,
    le32_at,
    put_le16,
    put_le32,
    volume_geometry,
)

# Boot sector offsets.
BS_BRANCH = 0x00
BS_OEM = 0x02
BS_SERIAL = 0x08
BS_BPS = 0x0B
BS_SPC = 0x0D
BS_RES = 0x0E
BS_NFATS = 0x10
BS_NDIRS = 0x11
BS_NSECTS = 0x13
BS_MEDIA = 0x15
BS_SPF = 0x16
BS_SPT = 0x18
BS_NSIDES = 0x1A
BS_NHID = 0x1C
BS_CODE = 0x1E

# Directory entry offsets.
DE_NAME = 0
DE_EXT = 8
DE_ATTR = 11
DE_TIME = 22
DE_DATE = 24
DE_CLUSTER = 26
DE_SIZE = 28

ENTRY_FREE = 0x00
ENTRY_DELETED = 0xE5
ENTRY_LONG_NAME = 0x0F

MAX_BASE = 8
MAX_EXT = 3
MAX_LABEL = 11

#: Characters GEMDOS refuses in a name, plus space.
ILLEGAL_NAME_CHARACTERS = set('\\/:*?"<>|+,;=[] ')

#: Size limits at which successive TOS releases stop mounting a partition.
TOS_PARTITION_LIMITS = (
    (16 * 1024 * 1024, "TOS 1.00"),
    (256 * 1024 * 1024, "TOS 1.02, 1.04 and 1.62"),
    (512 * 1024 * 1024, "TOS 2.06, 3.06 and 4.0x"),
)

_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


# ---------------------------------------------------------------------------
# Names and paths
# ---------------------------------------------------------------------------
def _upper(text: str) -> str:
    """Upper-case ASCII letters only; the Atari character set is not Latin-1."""
    return "".join(chr(ord(c) - 32) if "a" <= c <= "z" else c for c in text)


def split_path(path: str | None) -> list[str]:
    """Split an inner path into components, accepting every root spelling.

    ``\\`` and ``/`` both separate components, a leading drive letter is
    dropped, ``.`` components are ignored and ``..`` steps up one level.
    """
    text = str(path or "").strip()
    if _DRIVE_PREFIX.match(text):
        text = text[2:]
    text = text.replace("/", "\\")
    if text in {"", "\\", ":", "$"}:
        return []
    if text[0] in ":$":
        # Legacy root spellings from earlier releases of the workbench.
        text = text[1:]
    parts: list[str] = []
    for part in text.split("\\"):
        part = part.strip()
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return parts


def join_path(parts) -> str:
    return "\\".join(parts)


def validate_name(name: str) -> str:
    """Reject a name GEMDOS could not store, and return its canonical form.

    The canonical form is upper-case ``BASE.EXT`` with no trailing full stop.
    """
    text = str(name or "").strip()
    if not text:
        raise DataError("A name cannot be empty.")
    if text in {".", ".."}:
        raise DataError(f"{text!r} is reserved for the directory itself and its parent.")
    bad = sorted({c for c in text if c in ILLEGAL_NAME_CHARACTERS or ord(c) < 32 or ord(c) > 255})
    if bad:
        shown = " ".join("space" if c == " " else c for c in bad)
        raise DataError(
            f"A GEMDOS name cannot contain {shown}. Use letters, digits and "
            "! # $ % & ' ( ) - @ ^ _ ` { } ~ in an 8.3 pattern such as FOO.PRG."
        )
    base, _dot, ext = text.partition(".")
    if "." in ext:
        raise DataError(
            f"{text!r} has more than one full stop. A GEMDOS name is up to eight "
            "characters, one full stop and up to three more."
        )
    if not base:
        raise DataError(f"{text!r} needs at least one character before the full stop.")
    if len(base) > MAX_BASE:
        raise DataError(
            f"{text!r} is too long: a GEMDOS name has at most eight characters "
            "before the full stop."
        )
    if len(ext) > MAX_EXT:
        raise DataError(
            f"{text!r} is too long: a GEMDOS name has at most three characters "
            "after the full stop."
        )
    upper = _upper(base)
    return f"{upper}.{_upper(ext)}" if ext else upper


def validate_label(label: str) -> str:
    """Check a volume label: up to eleven characters, upper-cased."""
    text = _upper(str(label or "").strip())
    if not text:
        return ""
    bad = sorted({c for c in text if (c in ILLEGAL_NAME_CHARACTERS and c != " ") or ord(c) < 32 or ord(c) > 255})
    if bad:
        raise DataError(f"A volume label cannot contain {' '.join(bad)}.")
    base, dot, ext = text.partition(".")
    if dot:
        if "." in ext or len(base) > MAX_BASE or len(ext) > MAX_EXT:
            raise DataError("A volume label with a full stop follows the 8.3 pattern.")
        return f"{base}.{ext}" if ext else base
    if len(text) > MAX_LABEL:
        raise DataError(f"A volume label can hold at most {MAX_LABEL} characters.")
    return text


def _label_field(label: str) -> bytes:
    """Encode a validated label into the 11-byte name field."""
    base, dot, ext = label.partition(".")
    if dot:
        return base.encode("latin-1").ljust(MAX_BASE, b" ") + ext.encode("latin-1").ljust(MAX_EXT, b" ")
    return label.encode("latin-1").ljust(MAX_LABEL, b" ")


def _label_text(field: bytes) -> str:
    base = field[:MAX_BASE].decode("latin-1")
    ext = field[MAX_BASE:MAX_LABEL].decode("latin-1").rstrip(" \0")
    if ext and len(base.rstrip(" \0")) < MAX_BASE:
        return f"{base.rstrip(' ')}.{ext}"
    return (base + ext).rstrip(" \0")


def _name_fields(name: str) -> tuple[bytes, bytes]:
    base, _dot, ext = name.partition(".")
    return (
        base.encode("latin-1").ljust(MAX_BASE, b" "),
        ext.encode("latin-1").ljust(MAX_EXT, b" "),
    )


# ---------------------------------------------------------------------------
# Boot sector
# ---------------------------------------------------------------------------
@dataclass
class BootSector:
    """The decoded BIOS parameter block of one volume."""

    oem: bytes
    serial: int
    sector_size: int
    sectors_per_cluster: int
    reserved: int
    fats: int
    root_entries: int
    total_sectors: int
    media: int
    sectors_per_fat: int
    sectors_per_track: int
    sides: int
    hidden: int
    executable: bool
    raw: bytes

    def geometry(self) -> Geometry:
        tracks = 0
        if self.sectors_per_track and self.sides:
            tracks = self.total_sectors // (self.sectors_per_track * self.sides)
        return Geometry(
            sector_size=self.sector_size,
            sectors_per_cluster=self.sectors_per_cluster,
            sectors_per_track=self.sectors_per_track,
            sides=self.sides,
            tracks=tracks,
            reserved=self.reserved,
            fats=self.fats,
            root_entries=self.root_entries,
            total_sectors=self.total_sectors,
            sectors_per_fat=self.sectors_per_fat,
            media=self.media,
            hidden=self.hidden,
        )

    def to_dict(self) -> dict:
        return {
            "oem": self.oem.decode("latin-1").rstrip("\0 "),
            "serial": self.serial,
            "executable": self.executable,
            **self.geometry().to_dict(),
        }


def parse_boot_sector(data: bytes) -> BootSector:
    """Decode the little-endian BPB out of a 512-byte boot sector."""
    if len(data) < SECTOR_SIZE:
        data = bytes(data).ljust(SECTOR_SIZE, b"\0")
    return BootSector(
        oem=bytes(data[BS_OEM:BS_OEM + 6]),
        serial=int.from_bytes(data[BS_SERIAL:BS_SERIAL + 3], "big"),
        sector_size=le16_at(data, BS_BPS),
        sectors_per_cluster=data[BS_SPC],
        reserved=le16_at(data, BS_RES),
        fats=data[BS_NFATS],
        root_entries=le16_at(data, BS_NDIRS),
        total_sectors=le16_at(data, BS_NSECTS),
        media=data[BS_MEDIA],
        sectors_per_fat=le16_at(data, BS_SPF),
        sectors_per_track=le16_at(data, BS_SPT),
        sides=le16_at(data, BS_NSIDES),
        hidden=le16_at(data, BS_NHID),
        executable=is_executable_sector(data),
        raw=bytes(data[:SECTOR_SIZE]),
    )


def geometry_from_bpb(boot_sector: bytes) -> Geometry:
    """Read a volume's geometry out of its boot sector."""
    boot = parse_boot_sector(boot_sector)
    problems = bpb_problems(boot, None)
    if problems:
        raise DataError("The boot sector does not hold a usable BPB: " + "; ".join(problems))
    return boot.geometry()


def build_boot_sector(
    geometry: Geometry,
    *,
    serial: int | None = None,
    oem: bytes | str = b"Loader",
    executable: bool = False,
    boot_code: bytes | None = None,
) -> bytes:
    """Build a boot sector for ``geometry`` with a TOS-style header."""
    raw = bytearray(SECTOR_SIZE)
    raw[BS_BRANCH:BS_BRANCH + 2] = b"\x60\x1c"  # BRA.S to the code at 0x1E
    if isinstance(oem, str):
        oem = oem.encode("latin-1", "replace")
    raw[BS_OEM:BS_OEM + 6] = bytes(oem[:6]).ljust(6, b" ")
    if serial is None:
        serial = int.from_bytes(os.urandom(3), "big")
    raw[BS_SERIAL:BS_SERIAL + 3] = (int(serial) & 0xFFFFFF).to_bytes(3, "big")
    put_le16(raw, BS_BPS, geometry.sector_size)
    raw[BS_SPC] = geometry.sectors_per_cluster
    put_le16(raw, BS_RES, geometry.reserved)
    raw[BS_NFATS] = geometry.fats
    put_le16(raw, BS_NDIRS, geometry.root_entries)
    put_le16(raw, BS_NSECTS, geometry.total_sectors)
    raw[BS_MEDIA] = geometry.media
    put_le16(raw, BS_SPF, geometry.sectors_per_fat)
    put_le16(raw, BS_SPT, geometry.sectors_per_track)
    put_le16(raw, BS_NSIDES, geometry.sides)
    put_le16(raw, BS_NHID, geometry.hidden)
    code = bytes(boot_code) if boot_code else b"\x4e\x75"  # RTS: run nothing
    raw[BS_CODE:BS_CODE + min(len(code), 0x1FE - BS_CODE)] = code[: 0x1FE - BS_CODE]
    apply_boot_checksum(raw, executable)
    return bytes(raw)


def bpb_problems(boot: BootSector, image_sectors: int | None) -> list[str]:
    """List every reason this BPB could not describe a mountable volume.

    TOS does not check the jump instruction or the media byte, and neither
    does this: some formatters leave both at zero. What must hold is that
    the sizes describe a layout that fits in the image and leaves room for
    data clusters.
    """
    problems: list[str] = []
    if boot.sector_size not in LOGICAL_SECTOR_SIZES:
        problems.append(f"logical sector size {boot.sector_size} is not 512 to 8192")
    if boot.sectors_per_cluster == 0 or boot.sectors_per_cluster & (boot.sectors_per_cluster - 1):
        problems.append(f"sectors per cluster {boot.sectors_per_cluster} is not a power of two")
    if boot.fats not in (1, 2):
        problems.append(f"{boot.fats} FATs")
    if boot.reserved == 0:
        problems.append("no reserved sectors")
    if boot.root_entries == 0:
        problems.append("no root directory entries")
    if boot.total_sectors == 0:
        problems.append("no sectors")
    if boot.sectors_per_fat == 0:
        problems.append("no FAT sectors")
    if problems:
        return problems
    geometry = boot.geometry()
    if geometry.data_clusters <= 0:
        problems.append("the FATs and root directory leave no room for data")
    if image_sectors is not None and geometry.physical_sectors > image_sectors:
        declared = geometry.physical_sectors
        problems.append(
            f"the BPB declares {declared} sectors but the image holds {image_sectors}"
        )
    return problems


def tos_limit_notes(size_bytes: int) -> list[str]:
    """Describe which TOS releases cannot use a partition of this size."""
    notes: list[str] = []
    size_bytes = int(size_bytes)
    for limit, releases in TOS_PARTITION_LIMITS:
        if size_bytes > limit:
            notes.append(
                f"{size_bytes // (1024 * 1024)} MiB exceeds the {limit // (1024 * 1024)} MiB "
                f"partition limit of {releases}; those releases will not mount it."
            )
    if size_bytes > TOS_PARTITION_LIMITS[-1][0]:
        notes.append(
            "No TOS release mounts a partition over 512 MiB without a replacement "
            "DOS such as BigDOS or MiNT."
        )
    return notes


# ---------------------------------------------------------------------------
# Public records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    """One directory entry as the workbench sees it."""

    name: str
    path: str
    is_dir: bool
    length: int
    block: int
    attributes: int = DEFAULT_ATTRIBUTES
    datestamp: datetime | None = None

    @property
    def cluster(self) -> int:
        return self.block

    @property
    def access(self) -> Access:
        return Access(self.attributes)


@dataclass(frozen=True)
class Stat:
    """The result of ``stat`` on one path."""

    name: str
    path: str
    is_dir: bool
    length: int
    blocks: int
    block: int
    attributes: int = DEFAULT_ATTRIBUTES
    datestamp: datetime | None = None

    @property
    def cluster(self) -> int:
        return self.block


class _Slot:
    """One raw 32-byte directory record and where it lives."""

    __slots__ = ("sector", "offset", "raw", "name", "attributes", "time", "date", "cluster", "size")

    def __init__(self, sector: int, offset: int, raw: bytes):
        self.sector = sector
        self.offset = offset
        self.raw = bytes(raw)
        first = raw[0]
        base = bytearray(raw[DE_NAME:DE_NAME + MAX_BASE])
        if first == 0x05:
            base[0] = 0xE5
        base_text = base.decode("latin-1").rstrip(" \0")
        ext_text = raw[DE_EXT:DE_EXT + MAX_EXT].decode("latin-1").rstrip(" \0")
        self.attributes = raw[DE_ATTR]
        if self.attributes & FA_VOLUME and not self.attributes & FA_DIRECTORY:
            self.name = _label_text(raw[DE_NAME:DE_NAME + MAX_LABEL])
        else:
            self.name = f"{base_text}.{ext_text}" if ext_text else base_text
        self.time = le16_at(raw, DE_TIME)
        self.date = le16_at(raw, DE_DATE)
        self.cluster = le16_at(raw, DE_CLUSTER)
        self.size = le32_at(raw, DE_SIZE)

    @property
    def is_dir(self) -> bool:
        return bool(self.attributes & FA_DIRECTORY)

    @property
    def is_label(self) -> bool:
        return bool(self.attributes & FA_VOLUME) and not self.is_dir

    @property
    def is_dot(self) -> bool:
        return self.is_dir and self.name in {".", "..", ""}

    @property
    def datestamp(self) -> datetime | None:
        return fat_to_datetime(self.date, self.time)

    @property
    def meta(self) -> AtariMeta:
        return AtariMeta(attributes=self.attributes, datestamp=self.datestamp)


def _raw_entry(
    base: bytes,
    ext: bytes,
    attributes: int,
    cluster: int,
    size: int,
    moment: datetime | None,
) -> bytes:
    raw = bytearray(DIRECTORY_ENTRY_SIZE)
    raw[DE_NAME:DE_NAME + MAX_BASE] = base
    raw[DE_EXT:DE_EXT + MAX_EXT] = ext
    raw[DE_ATTR] = int(attributes) & 0x3F
    date, time = datetime_to_fat(moment)
    put_le16(raw, DE_TIME, time)
    put_le16(raw, DE_DATE, date)
    put_le16(raw, DE_CLUSTER, cluster)
    put_le32(raw, DE_SIZE, size)
    return bytes(raw)


# ---------------------------------------------------------------------------
# The volume
# ---------------------------------------------------------------------------
class GEMDOSVolume:
    """A mounted FAT12 or FAT16 volume."""

    def __init__(
        self,
        reader: BlockReader,
        geometry: Geometry | None = None,
        *,
        fat_bits: int | None = None,
    ):
        self.reader = reader
        if not reader.total_blocks:
            raise DataError("The image is empty.")
        self.boot = parse_boot_sector(reader.read_block(0))
        if geometry is None:
            problems = bpb_problems(self.boot, None)
            if problems:
                raise DataError(
                    "No GEMDOS volume was found: the boot sector's BPB is not usable ("
                    + "; ".join(problems)
                    + ")."
                )
            geometry = self.boot.geometry()
        self.geometry = geometry
        self.sector_size = geometry.sector_size
        self.physical_per_logical = geometry.physical_per_logical
        self.cluster_bytes = geometry.cluster_bytes
        self.total_clusters = geometry.data_clusters
        if self.total_clusters <= 0:
            raise DataError("The volume has no data clusters.")
        self.max_cluster = self.total_clusters + 1
        self.read_only = not reader.writable
        self.notes: list[str] = []
        self._fat: bytearray | None = None
        self._fat_dirty = False
        self.fat_bits = 16
        # Reading the FAT proves the volume is addressable at all.
        self._load_fat()
        self.fat_bits = int(fat_bits) if fat_bits else self._detect_fat_width()
        if self.fat_bits not in (12, 16):
            raise ConfigurationError("A GEMDOS FAT is 12 or 16 bits wide.")
        self.format = f"FAT{self.fat_bits}"

    def _detect_fat_width(self) -> int:
        """Decide the FAT width for a volume opened without a partition table.

        The geometry's own rule (an explicit width, else the 4085-cluster
        threshold) is right for floppies and for partitions reached through
        a table, which are FAT16 whatever their size. A small partition
        dumped on its own loses that context, so one clue is used: a volume
        with hard-disk logical sectors, a FAT large enough for 16-bit
        entries, and 16-bit media and end markers at its head is FAT16.
        """
        if self.geometry.fat_width in (12, 16):
            return self.geometry.fat_width
        rule = self.geometry.fat_bits
        if rule == 16 or self.sector_size == SECTOR_SIZE:
            return rule
        fat = self._load_fat()
        if len(fat) < (self.max_cluster + 1) * 2:
            return rule
        marker = le16_at(fat, 0)
        end = le16_at(fat, 2)
        if marker == 0xFF00 | self.geometry.media and end == 0xFFFF:
            return 16
        return rule

    # ---- constants ---------------------------------------------------
    @property
    def _eoc(self) -> int:
        return 0xFFF if self.fat_bits == 12 else 0xFFFF

    def _is_eoc(self, value: int) -> bool:
        return value >= (0xFF8 if self.fat_bits == 12 else 0xFFF8)

    def _is_bad(self, value: int) -> bool:
        return value == (0xFF7 if self.fat_bits == 12 else 0xFFF7)

    @property
    def size_bytes_per_entry(self) -> int:
        return DIRECTORY_ENTRY_SIZE

    # ---- sector and cluster IO ---------------------------------------
    def _read_sectors(self, logical: int, count: int = 1) -> bytes:
        return self.reader.read_blocks(
            logical * self.physical_per_logical, count * self.physical_per_logical
        )

    def _write_sectors(self, logical: int, data: bytes) -> None:
        self.reader.write_blocks(logical * self.physical_per_logical, data)

    def _cluster_sector(self, cluster: int) -> int:
        return self.geometry.data_start + (cluster - 2) * self.geometry.sectors_per_cluster

    def _check_cluster(self, cluster: int) -> None:
        if 2 <= cluster <= self.max_cluster:
            return
        # A cluster number this far out of range did not come from a formatter.
        # The usual cause is not damage but a disk that never held a filing
        # system: a game whose loader reads its own tracks leaves whatever it
        # likes where the root directory would be, and a plausible parameter
        # block in the boot sector is not evidence to the contrary. Say that,
        # because "cluster 6911 is outside this volume" sends somebody looking
        # for a fault in a disk that is exactly as its author wrote it.
        damage = self._root_directory_damage()
        if damage:
            raise DataError(
                f"This disk has no readable filing system: {damage}. It was "
                "probably written to be started by its own loader rather than "
                "through GEMDOS. Its bytes can still be inspected."
            )
        raise DataError(f"Cluster {cluster} is outside this volume.")

    def _read_cluster(self, cluster: int) -> bytes:
        self._check_cluster(cluster)
        return self._read_sectors(self._cluster_sector(cluster), self.geometry.sectors_per_cluster)

    def _write_cluster(self, cluster: int, data: bytes) -> None:
        self._check_cluster(cluster)
        if len(data) > self.cluster_bytes:
            raise DataError("A cluster write must fit in one cluster.")
        self._write_sectors(self._cluster_sector(cluster), bytes(data).ljust(self.cluster_bytes, b"\0"))

    # ---- FAT ---------------------------------------------------------
    def _fat_copy(self, index: int) -> bytes:
        start = self.geometry.fat_start + index * self.geometry.sectors_per_fat
        return self._read_sectors(start, self.geometry.sectors_per_fat)

    def _load_fat(self) -> bytearray:
        if self._fat is None:
            self._fat = bytearray(self._fat_copy(0))
            self._fat_dirty = False
        return self._fat

    def _discard_fat(self) -> None:
        self._fat = None
        self._fat_dirty = False

    def _store_fat(self) -> None:
        """Write the in-memory FAT to every copy on disk."""
        if self._fat is None or not self._fat_dirty:
            return
        for index in range(self.geometry.fats):
            start = self.geometry.fat_start + index * self.geometry.sectors_per_fat
            self._write_sectors(start, bytes(self._fat))
        self._fat_dirty = False

    def _fat_get(self, cluster: int, table: bytes | None = None) -> int:
        fat = table if table is not None else self._load_fat()
        if self.fat_bits == 16:
            offset = cluster * 2
            if offset + 2 > len(fat):
                raise DataError(f"The FAT is too short to hold cluster {cluster}.")
            return le16_at(fat, offset)
        offset = cluster + cluster // 2
        if offset + 2 > len(fat):
            raise DataError(f"The FAT is too short to hold cluster {cluster}.")
        if cluster & 1:
            return (fat[offset] >> 4) | (fat[offset + 1] << 4)
        return fat[offset] | ((fat[offset + 1] & 0x0F) << 8)

    def _fat_set(self, cluster: int, value: int) -> None:
        fat = self._load_fat()
        if self.fat_bits == 16:
            put_le16(fat, cluster * 2, value)
        else:
            offset = cluster + cluster // 2
            value &= 0xFFF
            if cluster & 1:
                fat[offset] = (fat[offset] & 0x0F) | ((value << 4) & 0xF0)
                fat[offset + 1] = (value >> 4) & 0xFF
            else:
                fat[offset] = value & 0xFF
                fat[offset + 1] = (fat[offset + 1] & 0xF0) | ((value >> 8) & 0x0F)
        self._fat_dirty = True

    def _chain(self, first: int, *, strict: bool = True) -> list[int]:
        """Follow a cluster chain from its first cluster."""
        clusters: list[int] = []
        if first == 0:
            return clusters
        seen: set[int] = set()
        current = first
        while True:
            if current < 2 or current > self.max_cluster or current in seen:
                if strict:
                    raise DataError(
                        f"A cluster chain is damaged: cluster {current} follows "
                        f"{clusters[-1] if clusters else first} but is not usable."
                    )
                return clusters
            seen.add(current)
            clusters.append(current)
            following = self._fat_get(current)
            if self._is_eoc(following):
                return clusters
            if following == 0 or self._is_bad(following):
                if strict:
                    raise DataError(
                        f"A cluster chain is damaged: cluster {current} is followed by "
                        f"{'a free' if following == 0 else 'a bad'} cluster."
                    )
                return clusters
            current = following

    def _free_clusters(self) -> list[int]:
        fat = self._load_fat()
        return [cluster for cluster in range(2, self.max_cluster + 1) if self._fat_get(cluster, fat) == 0]

    def _free_cluster_count(self) -> int:
        return len(self._free_clusters())

    def _allocate_chain(self, count: int, *, contiguous: bool = False) -> list[int]:
        """Reserve ``count`` clusters and link them into one chain."""
        if count <= 0:
            return []
        free = self._free_clusters()
        chosen: list[int] = []
        if contiguous:
            run: list[int] = []
            for cluster in free:
                if run and cluster != run[-1] + 1:
                    run = []
                run.append(cluster)
                if len(run) == count:
                    chosen = run
                    break
            if not chosen:
                raise DataError(f"No run of {count} free clusters is available.")
        else:
            if len(free) < count:
                raise DataError(
                    f"{count} cluster(s) are needed but only {len(free)} are free."
                )
            chosen = free[:count]
        for index, cluster in enumerate(chosen):
            self._fat_set(cluster, chosen[index + 1] if index + 1 < count else self._eoc)
        return chosen

    def _release_chain(self, first: int) -> None:
        for cluster in self._chain(first, strict=False):
            self._fat_set(cluster, 0)

    # ---- directories -------------------------------------------------
    def _dir_sectors(self, dir_cluster: int) -> list[int]:
        if dir_cluster == 0:
            start = self.geometry.root_start
            return list(range(start, start + self.geometry.root_sectors))
        sectors: list[int] = []
        for cluster in self._chain(dir_cluster):
            first = self._cluster_sector(cluster)
            sectors.extend(range(first, first + self.geometry.sectors_per_cluster))
        return sectors

    def _iter_slots(self, dir_cluster: int):
        for sector in self._dir_sectors(dir_cluster):
            data = self._read_sectors(sector)
            for offset in range(0, self.sector_size, DIRECTORY_ENTRY_SIZE):
                yield sector, offset, data[offset:offset + DIRECTORY_ENTRY_SIZE]

    def _entries(self, dir_cluster: int, *, include_special: bool = False) -> list[_Slot]:
        """Return the live entries of one directory in storage order."""
        found: list[_Slot] = []
        for sector, offset, raw in self._iter_slots(dir_cluster):
            first = raw[0]
            if first == ENTRY_FREE:
                break
            if first == ENTRY_DELETED or raw[DE_ATTR] == ENTRY_LONG_NAME:
                continue
            slot = _Slot(sector, offset, raw)
            if not include_special and (slot.is_dot or slot.is_label):
                continue
            found.append(slot)
        return found

    def _root_directory_damage(self) -> str:
        """Describe a root directory that no formatter could have written.

        Returns an empty string for a healthy root. The checks are the ones
        TOS itself never makes, which is exactly why a disk that passes the
        BPB test can still list as nonsense on a real machine.
        """
        bad = 0
        total = 0
        try:
            for _sector, _offset, raw in self._iter_slots(0):
                first = raw[0]
                if first == ENTRY_FREE:
                    break
                if first == ENTRY_DELETED or raw[DE_ATTR] == ENTRY_LONG_NAME:
                    continue
                total += 1
                name = raw[DE_NAME:DE_NAME + MAX_LABEL]
                if (
                    raw[DE_ATTR] & ~0x3F
                    or any(byte < 0x20 for byte in name[1:])
                    or (first < 0x20 and first != 0x05)
                    or le16_at(raw, DE_CLUSTER) > self.max_cluster
                    or (raw[DE_ATTR] & FA_DIRECTORY and le32_at(raw, DE_SIZE))
                ):
                    bad += 1
        except DataError as error:
            return str(error)
        if bad and bad * 4 >= total:
            return f"{bad} of {total} root directory entries are not valid"
        return ""

    def _find(self, dir_cluster: int, name: str) -> _Slot | None:
        wanted = _upper(str(name).strip().rstrip("."))
        for slot in self._entries(dir_cluster):
            if _upper(slot.name) == wanted:
                return slot
        return None

    def _write_slot(self, sector: int, offset: int, raw: bytes) -> None:
        data = bytearray(self._read_sectors(sector))
        data[offset:offset + DIRECTORY_ENTRY_SIZE] = raw
        self._write_sectors(sector, bytes(data))

    def _allocate_slot(self, dir_cluster: int) -> tuple[int, int]:
        """Find a free directory record, growing a subdirectory if needed."""
        for sector, offset, raw in self._iter_slots(dir_cluster):
            if raw[0] in (ENTRY_FREE, ENTRY_DELETED):
                return sector, offset
        if dir_cluster == 0:
            raise DataError(
                f"The root directory is full: it holds at most {self.geometry.root_entries} entries."
            )
        chain = self._chain(dir_cluster)
        new = self._allocate_chain(1)[0]
        self._write_cluster(new, b"")
        self._fat_set(chain[-1], new)
        self._store_fat()
        return self._cluster_sector(new), 0

    # ---- lookup ------------------------------------------------------
    def _resolve(self, path: str | None) -> tuple[list[str], _Slot | None]:
        """Return the path parts and the entry they name (None for the root)."""
        parts = split_path(path)
        dir_cluster = 0
        slot: _Slot | None = None
        for index, part in enumerate(parts):
            slot = self._find(dir_cluster, part)
            if slot is None:
                raise DataError(f"Path not found: {join_path(parts[: index + 1])}")
            if index < len(parts) - 1:
                if not slot.is_dir:
                    raise DataError(f"{join_path(parts[: index + 1])} is not a directory.")
                dir_cluster = self._dir_cluster_of(slot)
        return parts, slot

    def _dir_cluster_of(self, slot: _Slot) -> int:
        if not slot.is_dir:
            raise DataError(f"{slot.name} is not a directory.")
        if slot.cluster == 0:
            raise DataError(f"Directory {slot.name} has no cluster and cannot be read.")
        self._check_cluster(slot.cluster)
        return slot.cluster

    def _parent_cluster(self, parts: list[str]) -> int:
        _parent_parts, slot = self._resolve(join_path(parts[:-1]))
        return 0 if slot is None else self._dir_cluster_of(slot)

    def _require_writable(self) -> None:
        if self.read_only:
            raise DataError("This volume is open read-only.")

    # ---- volume identity ---------------------------------------------
    def _label_slot(self) -> _Slot | None:
        for slot in self._entries(0, include_special=True):
            if slot.is_label:
                return slot
        return None

    @property
    def title(self) -> str:
        slot = self._label_slot()
        return slot.name if slot else ""

    def set_title(self, value: str) -> None:
        self._require_writable()
        label = validate_label(value)
        slot = self._label_slot()
        if not label:
            if slot is not None:
                raw = bytearray(slot.raw)
                raw[0] = ENTRY_DELETED
                self._write_slot(slot.sector, slot.offset, bytes(raw))
            return
        field = _label_field(label)
        raw = _raw_entry(field[:MAX_BASE], field[MAX_BASE:], FA_VOLUME, 0, 0, datetime.now(timezone.utc))
        if slot is not None:
            self._write_slot(slot.sector, slot.offset, raw)
            return
        sector, offset = self._allocate_slot(0)
        self._write_slot(sector, offset, raw)

    def volume_datestamp(self) -> datetime | None:
        slot = self._label_slot()
        return slot.datestamp if slot else None

    def size_bytes(self) -> int:
        return self.total_clusters * self.cluster_bytes

    def free_bytes(self) -> int:
        return self._free_cluster_count() * self.cluster_bytes

    def used_bytes(self) -> int:
        return self.size_bytes() - self.free_bytes()

    # ---- traversal ---------------------------------------------------
    def exists(self, path: str | None) -> bool:
        try:
            self._resolve(path)
        except DataError:
            return False
        return True

    def stat(self, path: str | None) -> Stat:
        parts, slot = self._resolve(path)
        if slot is None:
            return Stat(
                name=self.title,
                path="",
                is_dir=True,
                length=0,
                blocks=self.geometry.root_sectors,
                block=0,
                attributes=FA_DIRECTORY,
                datestamp=self.volume_datestamp(),
            )
        try:
            blocks = len(self._chain(slot.cluster))
        except DataError:
            blocks = 0
        return Stat(
            name=slot.name,
            path=join_path(parts),
            is_dir=slot.is_dir,
            length=0 if slot.is_dir else slot.size,
            blocks=blocks,
            block=slot.cluster,
            attributes=slot.attributes,
            datestamp=slot.datestamp,
        )

    def iter_entries(self, path: str | None = None):
        parts, slot = self._resolve(path)
        dir_cluster = 0 if slot is None else self._dir_cluster_of(slot)
        prefix = join_path(parts)
        for child in self._entries(dir_cluster):
            yield Entry(
                name=child.name,
                path=f"{prefix}\\{child.name}" if prefix else child.name,
                is_dir=child.is_dir,
                length=0 if child.is_dir else child.size,
                block=child.cluster,
                attributes=child.attributes,
                datestamp=child.datestamp,
            )

    # ---- reading -----------------------------------------------------
    def read_bytes(self, path: str) -> bytes:
        parts, slot = self._resolve(path)
        if slot is None or slot.is_dir:
            raise DataError(f"{join_path(parts) or 'The volume root'} is not a file.")
        chunks: list[bytes] = []
        remaining = slot.size
        for cluster in self._chain(slot.cluster):
            if remaining <= 0:
                break
            chunk = self._read_cluster(cluster)[:remaining]
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) < slot.size:
            raise DataError(
                f"{join_path(parts)} declares {slot.size:,} bytes but only "
                f"{len(data):,} are present. The file is truncated."
            )
        return data

    # ---- metadata ----------------------------------------------------
    def atari_meta(self, path: str) -> AtariMeta:
        _parts, slot = self._resolve(path)
        if slot is None:
            return AtariMeta(attributes=FA_DIRECTORY, datestamp=self.volume_datestamp())
        return slot.meta

    def set_atari_meta(self, path: str, meta: AtariMeta) -> None:
        self._require_writable()
        parts, slot = self._resolve(path)
        if slot is None:
            raise DataError("The volume root has no attributes to set.")
        raw = bytearray(slot.raw)
        raw[DE_ATTR] = (int(meta.attributes) & EDITABLE_ATTRIBUTES) | (slot.attributes & FA_DIRECTORY)
        if meta.datestamp is not None:
            date, time = datetime_to_fat(meta.datestamp)
            put_le16(raw, DE_TIME, time)
            put_le16(raw, DE_DATE, date)
        self._write_slot(slot.sector, slot.offset, bytes(raw))

    def access(self, path: str) -> Access:
        return self.atari_meta(path).access

    def set_access(self, path: str, access: Access | int) -> None:
        value = access.value if isinstance(access, Access) else int(access)
        self.set_atari_meta(path, self.atari_meta(path).with_attributes(value))

    def datestamp(self, path: str) -> datetime | None:
        return self.atari_meta(path).datestamp

    def set_datestamp(self, path: str, moment: datetime) -> None:
        self.set_atari_meta(path, self.atari_meta(path).with_datestamp(moment))

    # ---- writing -----------------------------------------------------
    def mkdir(self, path: str) -> int:
        self._require_writable()
        parts = split_path(path)
        if not parts:
            raise DataError("The volume root already exists.")
        name = validate_name(parts[-1])
        parent = self._parent_cluster(parts)
        if self._find(parent, name) is not None:
            raise DataError(f"{join_path(parts)} already exists.")
        now = datetime.now(timezone.utc)
        try:
            sector, offset = self._allocate_slot(parent)
            cluster = self._allocate_chain(1)[0]
            block = bytearray(self.cluster_bytes)
            block[0:DIRECTORY_ENTRY_SIZE] = _raw_entry(b".       ", b"   ", FA_DIRECTORY, cluster, 0, now)
            block[DIRECTORY_ENTRY_SIZE:2 * DIRECTORY_ENTRY_SIZE] = _raw_entry(
                b"..      ", b"   ", FA_DIRECTORY, parent, 0, now
            )
            self._write_cluster(cluster, bytes(block))
            self._store_fat()
        except Exception:
            self._discard_fat()
            raise
        base, ext = _name_fields(name)
        self._write_slot(sector, offset, _raw_entry(base, ext, FA_DIRECTORY, cluster, 0, now))
        return cluster

    def write_bytes(self, path: str, data: bytes, meta: AtariMeta | None = None) -> int:
        """Create or replace a file. Returns its first cluster (0 when empty).

        The data clusters and both FATs are written before the directory
        entry, so a failure part way through leaves at worst some allocated
        but unreferenced clusters, never an entry pointing at data that was
        not written.
        """
        self._require_writable()
        parts = split_path(path)
        if not parts:
            raise DataError("A file needs a name.")
        name = validate_name(parts[-1])
        parent = self._parent_cluster(parts)
        existing = self._find(parent, name)
        if existing is not None and existing.is_dir:
            raise DataError(f"{join_path(parts)} is a directory.")
        payload = bytes(data)
        needed = -(-len(payload) // self.cluster_bytes)
        old_chain = self._chain(existing.cluster, strict=False) if existing else []
        try:
            slot = (existing.sector, existing.offset) if existing else self._allocate_slot(parent)
            free = self._free_cluster_count()
            if needed > free:
                if needed > free + len(old_chain):
                    raise DataError(
                        f"{len(payload):,} bytes need {needed} cluster(s) of "
                        f"{self.cluster_bytes:,} bytes but only {free} are free."
                    )
                # Not enough room for the old and new copies to coexist, so
                # the old chain is released first and may be overwritten.
                for cluster in old_chain:
                    self._fat_set(cluster, 0)
                old_chain = []
            chain = self._allocate_chain(needed)
            for index, cluster in enumerate(chain):
                self._write_cluster(
                    cluster, payload[index * self.cluster_bytes:(index + 1) * self.cluster_bytes]
                )
            for cluster in old_chain:
                self._fat_set(cluster, 0)
            self._store_fat()
        except Exception:
            self._discard_fat()
            raise
        source = meta if meta is not None else (existing.meta if existing else None)
        attributes = source.attributes if source is not None else DEFAULT_ATTRIBUTES
        attributes = int(attributes) & EDITABLE_ATTRIBUTES
        moment = source.datestamp if source is not None and source.datestamp else datetime.now(timezone.utc)
        base, ext = _name_fields(name)
        raw = _raw_entry(base, ext, attributes, chain[0] if chain else 0, len(payload), moment)
        self._write_slot(slot[0], slot[1], raw)
        return chain[0] if chain else 0

    def remove(self, path: str, *, recursive: bool = False) -> None:
        self._require_writable()
        parts, slot = self._resolve(path)
        if slot is None:
            raise DataError("The volume root cannot be deleted.")
        if slot.is_dir:
            children = list(self.iter_entries(join_path(parts)))
            if children and not recursive:
                raise DataError(f"{join_path(parts)} is not empty.")
            for child in children:
                self.remove(child.path, recursive=True)
            _parts, slot = self._resolve(join_path(parts))
        if slot.attributes & FA_READONLY:
            raise DataError(f"{join_path(parts)} is read-only and cannot be deleted.")
        # The entry goes first: a failure after this point leaves clusters
        # that validation can reclaim, never an entry pointing at freed data.
        raw = bytearray(slot.raw)
        raw[0] = ENTRY_DELETED
        self._write_slot(slot.sector, slot.offset, bytes(raw))
        try:
            self._release_chain(slot.cluster)
            self._store_fat()
        except Exception:
            self._discard_fat()
            raise

    def rename(self, source: str, destination: str) -> None:
        self._require_writable()
        source_parts, slot = self._resolve(source)
        destination_parts = split_path(destination)
        if slot is None or not destination_parts:
            raise DataError("Both a source and a destination name are required.")
        name = validate_name(destination_parts[-1])
        if (
            slot.is_dir
            and len(destination_parts) > len(source_parts)
            and [_upper(p) for p in destination_parts[: len(source_parts)]]
            == [_upper(p) for p in source_parts]
        ):
            raise DataError(f"{join_path(source_parts)} cannot be moved inside itself.")
        source_parent = self._parent_cluster(source_parts)
        target_parent = self._parent_cluster(destination_parts)
        clash = self._find(target_parent, name)
        if clash is not None and (clash.sector, clash.offset) != (slot.sector, slot.offset):
            raise DataError(f"{join_path(destination_parts)} already exists.")
        raw = bytearray(slot.raw)
        base, ext = _name_fields(name)
        raw[DE_NAME:DE_NAME + MAX_BASE] = base
        raw[DE_EXT:DE_EXT + MAX_EXT] = ext
        if source_parent == target_parent:
            self._write_slot(slot.sector, slot.offset, bytes(raw))
            return
        sector, offset = self._allocate_slot(target_parent)
        self._write_slot(sector, offset, bytes(raw))
        old = bytearray(slot.raw)
        old[0] = ENTRY_DELETED
        self._write_slot(slot.sector, slot.offset, bytes(old))
        if slot.is_dir:
            self._set_parent_link(slot.cluster, target_parent)

    def _set_parent_link(self, dir_cluster: int, parent: int) -> None:
        """Repoint the ``..`` entry of a moved directory."""
        for sector, offset, raw in self._iter_slots(dir_cluster):
            if raw[0] == ENTRY_FREE:
                return
            if raw[DE_ATTR] & FA_DIRECTORY and raw[DE_NAME:DE_NAME + 2] == b"..":
                patched = bytearray(raw)
                put_le16(patched, DE_CLUSTER, parent)
                self._write_slot(sector, offset, bytes(patched))
                return

    # ---- boot sector -------------------------------------------------
    def boot_option(self) -> int:
        """Return 1 when the boot sector is executable, else 0."""
        return 1 if is_executable_sector(self.reader.read_block(0)) else 0

    def set_boot_option(self, option: int) -> None:
        """Make the boot sector executable (1) or not (0) via its checksum word."""
        self._require_writable()
        option = int(option)
        if option not in (0, 1):
            raise ConfigurationError("A boot option is either 0 (not bootable) or 1 (bootable).")
        raw = bytearray(self.reader.read_block(0))
        apply_boot_checksum(raw, bool(option))
        self.reader.write_block(0, bytes(raw))
        self.reader.flush()

    # ---- maintenance -------------------------------------------------
    def validate(self) -> list[str]:
        """Walk every structure and report what a real machine would refuse."""
        problems: list[str] = []
        fat = self._load_fat()
        meaningful = (self.max_cluster + 1) * 2 if self.fat_bits == 16 else (self.max_cluster + 1) * 3 // 2 + 2
        meaningful = min(meaningful, len(fat))
        for index in range(1, self.geometry.fats):
            if bytes(fat[:meaningful]) != self._fat_copy(index)[:meaningful]:
                problems.append(f"FAT copy {index + 1} does not match FAT copy 1.")
        marker = self._fat_get(0)
        expected_marker = (0xF00 if self.fat_bits == 12 else 0xFF00) | self.geometry.media
        if marker not in (0, expected_marker):
            problems.append(
                f"The FAT media marker is 0x{marker:X}; the boot sector media byte "
                f"0x{self.geometry.media:02X} implies 0x{expected_marker:X}."
            )
        owners: dict[int, str] = {}

        def claim(cluster: int, owner: str) -> None:
            if cluster in owners:
                problems.append(
                    f"Cluster {cluster} is claimed by both {owners[cluster]} and {owner}."
                )
            owners[cluster] = owner

        def walk(dir_cluster: int, prefix: str, ancestors: set[int]) -> None:
            try:
                slots = self._entries(dir_cluster, include_special=True)
            except DataError as error:
                problems.append(f"{prefix or 'The root directory'}: {error}")
                return
            for slot in slots:
                path = f"{prefix}\\{slot.name}" if prefix else slot.name
                if slot.is_label:
                    if slot.cluster or slot.size:
                        problems.append("The volume label entry claims a cluster or a size.")
                    continue
                if slot.is_dot:
                    expected = dir_cluster if slot.name == "." else None
                    if slot.name == ".." and slot.cluster and slot.cluster not in ancestors:
                        problems.append(f"{prefix}: the .. entry does not point at the parent.")
                    if expected is not None and slot.cluster != expected:
                        problems.append(f"{prefix}: the . entry does not point at itself.")
                    continue
                if slot.is_dir:
                    if slot.cluster == 0:
                        problems.append(f"{path} is a directory without a cluster.")
                        continue
                    if slot.cluster in ancestors:
                        problems.append(f"{path} loops back to one of its parents.")
                        continue
                    if slot.size:
                        problems.append(f"{path} is a directory with a non-zero size.")
                    try:
                        chain = self._chain(slot.cluster)
                    except DataError as error:
                        problems.append(f"{path}: {error}")
                        continue
                    for cluster in chain:
                        claim(cluster, path)
                    walk(slot.cluster, path, ancestors | {slot.cluster, dir_cluster})
                    continue
                try:
                    chain = self._chain(slot.cluster)
                except DataError as error:
                    problems.append(f"{path}: {error}")
                    continue
                expected = -(-slot.size // self.cluster_bytes)
                if len(chain) != expected:
                    problems.append(
                        f"{path} declares {slot.size:,} bytes ({expected} cluster(s)) but its chain "
                        f"holds {len(chain)}."
                    )
                for cluster in chain:
                    claim(cluster, path)

        walk(0, "", {0})
        lost = [
            cluster
            for cluster in range(2, self.max_cluster + 1)
            if cluster not in owners
            and self._fat_get(cluster, fat) != 0
            and not self._is_bad(self._fat_get(cluster, fat))
        ]
        if lost:
            problems.append(
                f"{len(lost)} cluster(s) are allocated but belong to no file (first: {lost[0]})."
            )
        return problems

    def defragment(self) -> int:
        """Rewrite fragmented files contiguously. Returns the clusters moved."""
        self._require_writable()
        moved = 0
        paths: list[str] = []

        def collect(directory: str) -> None:
            for entry in self.iter_entries(directory):
                if entry.is_dir:
                    collect(entry.path)
                else:
                    paths.append(entry.path)

        collect("")
        for path in paths:
            _parts, slot = self._resolve(path)
            if slot is None:
                continue
            chain = self._chain(slot.cluster)
            if all(chain[i + 1] == chain[i] + 1 for i in range(len(chain) - 1)):
                continue
            data = self.read_bytes(path)
            try:
                try:
                    # Prefer a run that leaves the old chain intact until the
                    # new data is safely written.
                    new_chain = self._allocate_chain(len(chain), contiguous=True)
                except DataError:
                    # No such run exists; release the old chain first so its
                    # clusters can be part of the new one.
                    for cluster in chain:
                        self._fat_set(cluster, 0)
                    try:
                        new_chain = self._allocate_chain(len(chain), contiguous=True)
                    except DataError:
                        self._discard_fat()
                        continue
                else:
                    for cluster in chain:
                        self._fat_set(cluster, 0)
                for index, cluster in enumerate(new_chain):
                    self._write_cluster(
                        cluster, data[index * self.cluster_bytes:(index + 1) * self.cluster_bytes]
                    )
                self._store_fat()
            except Exception:
                self._discard_fat()
                raise
            raw = bytearray(slot.raw)
            put_le16(raw, DE_CLUSTER, new_chain[0])
            self._write_slot(slot.sector, slot.offset, bytes(raw))
            moved += len(new_chain)
        return moved

    def free_map(self) -> list[bool]:
        """Return one flag per data cluster, True when it is free."""
        fat = self._load_fat()
        return [self._fat_get(cluster, fat) == 0 for cluster in range(2, self.max_cluster + 1)]

    def flush(self) -> None:
        self._store_fat()
        self.reader.flush()

    def close(self) -> None:
        try:
            if not self.read_only:
                self.flush()
        finally:
            self.reader.close()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def format_volume(
    reader: BlockReader,
    *,
    label: str = "",
    geometry: Geometry | None = None,
    bootable: bool = False,
    serial: int | None = None,
    oem: bytes | str = b"Loader",
    fat_bits: int | None = None,
) -> GEMDOSVolume:
    """Write a brand-new empty volume across ``reader``.

    Without a geometry the image is treated as a floppy when its size is one
    of the standard formats and as a hard-disk partition otherwise. The
    returned volume's ``notes`` list names any TOS release that cannot
    mount a partition of this size.
    """
    if not reader.writable:
        raise DataError("The image is open read-only.")
    if geometry is None:
        geometry = volume_geometry(reader.length, label=label)
    geometry.check()
    if geometry.physical_sectors > reader.total_blocks:
        raise ConfigurationError(
            f"The geometry needs {geometry.physical_sectors} sectors but the image holds "
            f"{reader.total_blocks}."
        )
    if fat_bits is not None and int(fat_bits) != geometry.fat_bits:
        raise ConfigurationError(
            f"{geometry.data_clusters} clusters make a FAT{geometry.fat_bits} volume; "
            f"FAT{fat_bits} would need a different cluster count."
        )
    label = validate_label(label)
    per_logical = geometry.physical_per_logical
    blank = b"\0" * geometry.sector_size

    boot = build_boot_sector(geometry, serial=serial, oem=oem, executable=bootable)
    reader.write_blocks(0, boot + b"\0" * (geometry.sector_size - SECTOR_SIZE))
    for logical in range(1, geometry.reserved):
        reader.write_blocks(logical * per_logical, blank)

    fat = bytearray(geometry.sectors_per_fat * geometry.sector_size)
    if geometry.fat_bits == 12:
        marker = 0xF00 | geometry.media
        fat[0] = marker & 0xFF
        fat[1] = ((marker >> 8) & 0x0F) | 0xF0
        fat[2] = 0xFF
    else:
        put_le16(fat, 0, 0xFF00 | geometry.media)
        put_le16(fat, 2, 0xFFFF)
    for index in range(geometry.fats):
        start = (geometry.fat_start + index * geometry.sectors_per_fat) * per_logical
        reader.write_blocks(start, bytes(fat))

    root = bytearray(geometry.root_sectors * geometry.sector_size)
    if label:
        field = _label_field(label)
        root[0:DIRECTORY_ENTRY_SIZE] = _raw_entry(
            field[:MAX_BASE], field[MAX_BASE:], FA_VOLUME, 0, 0, datetime.now(timezone.utc)
        )
    reader.write_blocks(geometry.root_start * per_logical, bytes(root))
    reader.flush()
    volume = GEMDOSVolume(reader, geometry)
    volume.notes = tos_limit_notes(geometry.size_bytes)
    if geometry.data_clusters > TOS_MAX_CLUSTERS:
        volume.notes.append(
            f"{geometry.data_clusters} clusters exceed the 32766 TOS 1.x can address."
        )
    return volume


def probe_volume(reader: BlockReader, *, fat_bits: int | None = None) -> tuple[float, str] | None:
    """Score how convincingly ``reader`` holds a GEMDOS volume.

    Returns a confidence and a description, or None. A plausible BPB with
    a FAT whose first entries carry the media and end markers scores full
    marks; a FAT left at zero by a lax formatter costs a little; a BPB that
    describes more sectors than the image holds costs more but still
    mounts, because a truncated dump is still readable up to where it ends.
    """
    if not reader.total_blocks:
        return None
    boot = parse_boot_sector(reader.read_block(0))
    problems = bpb_problems(boot, reader.total_blocks)
    if problems and bpb_problems(boot, None):
        return None
    geometry = boot.geometry()
    if geometry.data_clusters < 1:
        return None
    if fat_bits is not None and geometry.fat_bits != int(fat_bits):
        return None
    try:
        volume = GEMDOSVolume(reader, geometry)
        marker = volume._fat_get(0)
        end = volume._fat_get(1)
        label = volume.title
        damaged = volume._root_directory_damage()
    except DataError:
        return None
    expected = (0xF00 if volume.fat_bits == 12 else 0xFF00) | geometry.media
    confidence = 1.0
    if problems:
        confidence = 0.6
    elif marker == 0 and end == 0:
        confidence = 0.85
    elif marker != expected or not volume._is_eoc(end):
        confidence = 0.7
    if geometry.sectors_per_cluster > 2:
        confidence = min(confidence, 0.75)
    if damaged:
        # A copy-protected game disk often carries a believable BPB in
        # front of a root directory that is not one. Say so rather than
        # claim a volume TOS would list as garbage.
        confidence = min(confidence, 0.4)
        problems = [*problems, damaged]
        label = ""
    shape = ""
    if geometry.sides and geometry.sectors_per_track and geometry.tracks:
        shape = f", {geometry.tracks}x{geometry.sides}x{geometry.sectors_per_track}"
    detail = (
        f"{volume.format} volume named {label!r}, {geometry.size_bytes // 1024} KiB"
        f"{shape}, {geometry.sector_size}-byte sectors"
    )
    if problems:
        detail += " (" + "; ".join(problems) + ")"
    return confidence, detail


__all__ = [
    "BootSector",
    "Entry",
    "FAT16_THRESHOLD",
    "GEMDOSVolume",
    "ILLEGAL_NAME_CHARACTERS",
    "MAX_BASE",
    "MAX_EXT",
    "MAX_LABEL",
    "Stat",
    "TOS_PARTITION_LIMITS",
    "bpb_problems",
    "build_boot_sector",
    "format_volume",
    "geometry_from_bpb",
    "join_path",
    "parse_boot_sector",
    "probe_volume",
    "split_path",
    "tos_limit_notes",
    "validate_label",
    "validate_name",
]
