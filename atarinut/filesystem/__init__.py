"""The filesystem registry, identification cascade and mount protocols.

Atari File Forge only ever asks this package three things: give me a reader
for this image, tell me what is on it, and mount it. Everything else is
reached through the mount object those calls return.

The protocol classes at the top are deliberately structural. A mount
advertises that it carries attribute bits by subclassing ``AtariMetadata``,
so listing code can ask ``isinstance(mount, AtariMetadata)`` without knowing
which filing system produced it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..errors import ConfigurationError, DataError
from ..file import Access, AtariMeta
from .ahdi import (
    AhdiDisk,
    Partition,
    create_partitioned_image,
    partition_reader,
    read_partition_table,
    write_partition_table,
)
from .blocks import (
    BLOCK_SIZE,
    DD_SECTORS,
    HD_SECTORS,
    NAMED_GEOMETRIES,
    SECTOR_SIZE,
    BlockReader,
    Geometry,
    named_geometry,
    partition_geometry,
    volume_geometry,
)
from .gemdos import (
    Entry,
    GEMDOSVolume,
    Stat,
    bpb_problems,
    format_volume,
    geometry_from_bpb,
    join_path,
    parse_boot_sector,
    probe_volume,
    split_path,
    validate_label,
    validate_name,
)


# ---------------------------------------------------------------------------
# Mount protocols
# ---------------------------------------------------------------------------
class AtariMetadata:
    """A mount whose entries carry GEMDOS attribute bits."""

    def atari_meta(self, path: str) -> AtariMeta:  # pragma: no cover - protocol
        raise NotImplementedError


class Datestamped:
    """A mount whose entries carry a datestamp."""

    def datestamp(self, path: str) -> datetime | None:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def reader_for(path: Path | str, *, writable: bool = False, block_size: int = SECTOR_SIZE) -> BlockReader:
    """Open an image file for sector access."""
    return BlockReader(path, writable=writable, block_size=block_size)


# ---------------------------------------------------------------------------
# Mounts
# ---------------------------------------------------------------------------
class GEMDOSMount(AtariMetadata, Datestamped):
    """The workbench-facing view of one mounted FAT12 or FAT16 volume."""

    def __init__(self, volume: GEMDOSVolume, name: str = "gemdos"):
        self.volume = volume
        self.filesystem = name

    # ---- identity -----------------------------------------------------
    @property
    def format(self) -> str:
        return self.volume.format

    @property
    def fat_bits(self) -> int:
        return self.volume.fat_bits

    @property
    def geometry(self) -> Geometry:
        return self.volume.geometry

    @property
    def title(self) -> str:
        return self.volume.title

    def set_title(self, value: str) -> None:
        self.volume.set_title(value)

    def volume_datestamp(self) -> datetime | None:
        return self.volume.volume_datestamp()

    # ---- traversal ----------------------------------------------------
    def exists(self, path: str | None) -> bool:
        return self.volume.exists(path)

    def stat(self, path: str | None) -> Stat:
        return self.volume.stat(path)

    def iter_entries(self, path: str | None = None):
        return self.volume.iter_entries(path)

    # ---- content ------------------------------------------------------
    def read_bytes(self, path: str) -> bytes:
        return self.volume.read_bytes(path)

    def write_bytes(self, path: str, data: bytes, meta: AtariMeta | None = None) -> None:
        self.volume.write_bytes(path, data, meta)

    def mkdir(self, path: str) -> None:
        self.volume.mkdir(path)

    def make_directory(
        self, path: str, *, parents: bool = False, exist_ok: bool = False
    ) -> None:
        """Create a directory, optionally building the chain above it."""
        parts = split_path(path)
        if not parts:
            if exist_ok:
                return
            raise DataError("The volume root already exists.")
        if parents:
            for depth in range(1, len(parts)):
                branch = join_path(parts[:depth])
                if not self.volume.exists(branch):
                    self.volume.mkdir(branch)
        target = join_path(parts)
        if self.volume.exists(target):
            if exist_ok and self.volume.stat(target).is_dir:
                return
            raise DataError(f"{target} already exists.")
        self.volume.mkdir(target)

    def _navigate(self, path: str | None):
        """Return a node view of one path, whether or not it exists yet."""
        return PathNode(self, path or "")

    def remove(self, path: str, *, recursive: bool = False, force: bool = False) -> None:
        """Delete an entry. ``force`` clears read-only bits that would block it.

        A forced removal is recursive, and every read-only entry beneath
        the target is unlocked first, because GEMDOS refuses to delete a
        read-only file wherever it sits in the tree.
        """
        if force:
            recursive = True
            pending = [path]
            while pending:
                current = pending.pop()
                access = self.volume.access(current)
                if access.locked:
                    self.volume.set_access(current, access.with_locked(False))
                if self.volume.stat(current).is_dir:
                    pending.extend(entry.path for entry in self.volume.iter_entries(current))
        self.volume.remove(path, recursive=recursive)

    def rename(self, source: str, destination: str) -> None:
        self.volume.rename(source, destination)

    # ---- metadata -----------------------------------------------------
    def atari_meta(self, path: str) -> AtariMeta:
        return self.volume.atari_meta(path)

    def set_atari_meta(self, path: str, meta: AtariMeta) -> None:
        self.volume.set_atari_meta(path, meta)

    def access(self, path: str) -> Access:
        return self.volume.access(path)

    def set_access(self, path: str, access: Access | int) -> None:
        self.volume.set_access(path, access)

    def datestamp(self, path: str) -> datetime | None:
        return self.volume.datestamp(path)

    def set_datestamp(self, path: str, moment: datetime) -> None:
        self.volume.set_datestamp(path, moment)

    def filetype(self, path: str) -> str | None:
        """Classify an entry by its name, without reading it."""
        from ..file.filetypes import classify_name

        if self.volume.stat(path).is_dir:
            return None
        return classify_name(split_path(path)[-1] if split_path(path) else "")

    # ---- volume-level -------------------------------------------------
    def size_bytes(self) -> int:
        return self.volume.size_bytes()

    def free_bytes(self) -> int:
        return self.volume.free_bytes()

    def used_bytes(self) -> int:
        return self.volume.used_bytes()

    def boot_option(self) -> int:
        return self.volume.boot_option()

    def set_boot_option(self, option: int) -> None:
        self.volume.set_boot_option(option)

    def validate(self) -> list[str]:
        return self.volume.validate()

    def defragment(self) -> int:
        return self.volume.defragment()

    def free_map(self) -> list[bool]:
        return self.volume.free_map()

    def flush(self) -> None:
        self.volume.flush()

    def close(self) -> None:
        self.volume.close()


class PathNode:
    """One place inside a mounted volume, whether or not it exists yet.

    The workbench addresses a destination before creating it, so this node
    is deliberately lazy: it resolves nothing until asked. Only the volume
    root has a title, which is the volume label; GEMDOS keeps no title or
    comment on a directory, so a node inside the volume reports its name.
    """

    def __init__(self, mount: "GEMDOSMount", path: str):
        self.mount = mount
        self.path = join_path(split_path(path))

    # ---- identity -----------------------------------------------------
    @property
    def name(self) -> str:
        parts = split_path(self.path)
        return parts[-1] if parts else self.mount.title

    @property
    def exists(self) -> bool:
        return self.mount.exists(self.path)

    @property
    def is_root(self) -> bool:
        return not split_path(self.path)

    @property
    def is_dir(self) -> bool:
        return self.exists and self.mount.stat(self.path).is_dir

    @property
    def supports_title(self) -> bool:
        """Only the volume root carries a title: its label."""
        return self.is_root

    # ---- title --------------------------------------------------------
    @property
    def title(self) -> str:
        if self.is_root:
            return self.mount.title
        return self.name

    @title.setter
    def title(self, value: str) -> None:
        self.set_title(value)

    def set_title(self, value: str) -> None:
        if self.is_root:
            self.mount.set_title(value)
            return
        raise DataError(
            "GEMDOS keeps no title on a file or directory; only the volume label "
            "can be set. Rename the entry instead."
        )

    # ---- content ------------------------------------------------------
    def read_bytes(self) -> bytes:
        return self.mount.read_bytes(self.path)

    def write_bytes(
        self,
        data: bytes,
        *,
        access: Access | int | None = None,
        datestamp: datetime | None = None,
    ) -> None:
        """Write content and its directory metadata as one update."""
        meta = AtariMeta(access=access, datestamp=datestamp) if access is not None else AtariMeta(
            datestamp=datestamp
        )
        self.mount.write_bytes(self.path, data, meta)

    def chmod(self, value: Access | int) -> None:
        self.mount.set_access(self.path, value)

    def make_directory(self, *, parents: bool = False, exist_ok: bool = False) -> None:
        self.mount.make_directory(self.path, parents=parents, exist_ok=exist_ok)

    def remove(self, *, recursive: bool = False, force: bool = False) -> None:
        self.mount.remove(self.path, recursive=recursive, force=force)


#: Earlier releases addressed only directories through this node.
DirectoryNode = PathNode


class AhdiMount:
    """A partitioned drive presented as a list of mountable volumes."""

    def __init__(self, reader: BlockReader):
        self.reader = reader
        self.disk: AhdiDisk = read_partition_table(reader)
        self.filesystem = "ahdi"

    @property
    def partitions(self) -> list[Partition]:
        return self.disk.partitions

    def partition(self, index: int) -> Partition:
        return self.disk.partition(index)

    def open_partition(self, index: int, *, writable: bool | None = None) -> GEMDOSMount:
        partition = self.partition(index)
        if not partition.is_gemdos:
            raise DataError(
                f"Partition {partition.name} is a {partition.id} partition, not a GEMDOS volume."
            )
        window = partition_reader(self.reader, partition)
        if writable is not None:
            window.writable = bool(writable) and self.reader.writable
        try:
            # A partition reached through a table is FAT16 whatever its
            # cluster count: the driver's BPB flags it so and TOS obeys.
            return GEMDOSMount(GEMDOSVolume(window, fat_bits=16))
        except Exception:
            window.close()
            raise

    def to_dict(self) -> dict:
        return self.disk.to_dict()

    def close(self) -> None:
        self.reader.close()


# ---------------------------------------------------------------------------
# Filesystem registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Candidate:
    """One identification result."""

    filesystem: str
    confidence: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "filesystem": self.filesystem,
            "confidence": round(self.confidence, 3),
            "detail": self.detail,
        }


class GEMDOSFilesystem:
    """Registry entry for FAT12 and FAT16 volumes."""

    name = "gemdos"
    label = "GEMDOS FAT12/FAT16"
    fat_bits: int | None = None

    def open(self, reader: BlockReader, geometry: Geometry | None = None) -> GEMDOSMount:
        return GEMDOSMount(GEMDOSVolume(reader, geometry, fat_bits=self.fat_bits), self.name)

    def identify(self, reader: BlockReader) -> Candidate | None:
        found = probe_volume(reader, fat_bits=self.fat_bits)
        if found is None:
            return None
        confidence, detail = found
        return Candidate(self.name, confidence, detail)


class FAT12Filesystem(GEMDOSFilesystem):
    name = "fat12"
    label = "GEMDOS FAT12 (floppies and small partitions)"
    fat_bits = 12


class FAT16Filesystem(GEMDOSFilesystem):
    name = "fat16"
    label = "GEMDOS FAT16 (hard-disk partitions)"
    fat_bits = 16


def _whole_image_bpb_matches(reader: BlockReader) -> bool:
    """True when sector 0 is a BPB that describes exactly this image.

    A root sector never carries one, so a matching BPB means the image is a
    bare volume even if the bytes at 0x1C6 happen to look like a table.
    """
    boot = parse_boot_sector(reader.read_block(0))
    if bpb_problems(boot, reader.total_blocks):
        return False
    return boot.geometry().physical_sectors == reader.total_blocks


class AhdiFilesystem:
    """Registry entry for a partitioned hard-disk image."""

    name = "ahdi"
    label = "AHDI or MBR partitioned hard disk"

    def open(self, reader: BlockReader, geometry: Geometry | None = None) -> AhdiMount:
        return AhdiMount(reader)

    def identify(self, reader: BlockReader) -> Candidate | None:
        if not reader.total_blocks:
            return None
        try:
            disk = read_partition_table(reader)
        except DataError:
            return None
        if _whole_image_bpb_matches(reader):
            return None
        confidence = 1.0
        if disk.hd_size > reader.total_blocks or disk.notes:
            confidence = 0.6
        gemdos = sum(1 for partition in disk.partitions if partition.is_gemdos)
        detail = (
            f"{len(disk.partitions)} partition(s), {gemdos} GEMDOS, "
            f"{disk.scheme.upper()} table, {disk.hd_size} sectors"
        )
        if disk.byte_swapped:
            detail += ", byte-swapped image"
        return Candidate(self.name, confidence, detail)


class TOSFilesystem:
    """Registry entry for a TOS ROM image, decoded into its components.

    The decoder lives in ``atarinut.tosrom``. It is imported lazily so the
    rest of the engine works, and this entry simply reports nothing, when
    that package is not installed.
    """

    name = "tosrom"
    label = "TOS ROM image"

    def open(self, reader: BlockReader, geometry: Geometry | None = None):
        try:
            from ..tosrom import TOSMount
        except ImportError as error:
            raise ConfigurationError("TOS ROM support is not available in this build.") from error
        return TOSMount(reader)

    def identify(self, reader: BlockReader) -> Candidate | None:
        try:
            from ..tosrom import TOSRom, is_tos_rom
        except ImportError:
            return None
        data = _whole_image(reader)
        if not is_tos_rom(data):
            return None
        try:
            rom = TOSRom(data)
        except DataError:
            return Candidate(self.name, 0.5, "TOS ROM header without a readable image")
        detail = getattr(rom, "description", None) or f"TOS ROM, {len(data) // 1024} KiB"
        return Candidate(self.name, 1.0, str(detail))


FILESYSTEMS = {
    "gemdos": GEMDOSFilesystem,
    "fat12": FAT12Filesystem,
    "fat16": FAT16Filesystem,
    "ahdi": AhdiFilesystem,
    "tosrom": TOSFilesystem,
}

#: Identification order. The partition table is checked first because it
#: wraps volumes that would otherwise be found at an offset.
IDENTIFY_ORDER = ("ahdi", "gemdos", "tosrom")


def create_filesystem(name: str):
    """Return a filesystem driver by name."""
    key = str(name or "").strip().lower()
    if key not in FILESYSTEMS:
        raise ConfigurationError(f"{name!r} is not a filing system this build provides.")
    return FILESYSTEMS[key]()


def list_filesystems() -> list[dict]:
    rows: list[dict] = []
    for factory in FILESYSTEMS.values():
        driver = factory()
        rows.append({"name": driver.name, "label": driver.label})
    return rows


def _whole_image(reader: BlockReader) -> bytes:
    return reader.path.read_bytes()


SUFFIX_HINTS = {
    ".st": ("gemdos", "fat12"),
    ".msa": ("gemdos", "fat12"),
    ".dim": ("gemdos", "fat12"),
    ".img": ("ahdi", "gemdos"),
    ".hd": ("ahdi", "gemdos", "fat16"),
    ".ahd": ("ahdi", "gemdos", "fat16"),
    ".acsi": ("ahdi", "gemdos", "fat16"),
    ".ide": ("ahdi", "gemdos", "fat16"),
    ".raw": ("ahdi", "gemdos"),
    ".bin": ("tosrom", "ahdi", "gemdos"),
    ".tos": ("tosrom",),
    ".rom": ("tosrom",),
}


def identify(
    path: Path | str,
    *,
    suffix_hint: str | None = None,
    filesystems: dict | None = None,
) -> list[Candidate]:
    """Identify an image by content, best guess first.

    ``suffix_hint`` only reorders the cascade; it never lets a filing system
    claim bytes it cannot actually read. ``filesystems`` restricts the
    cascade to a known set, which is how the workbench avoids scanning a
    whole hard disk for a ROM it already knows is not there.
    """
    path = Path(path)
    drivers = filesystems if filesystems is not None else {
        name: create_filesystem(name) for name in IDENTIFY_ORDER
    }
    order = list(drivers)
    hint = (suffix_hint or path.suffix or "").lower()
    preferred = SUFFIX_HINTS.get(hint, ())
    order.sort(key=lambda name: preferred.index(name) if name in preferred else len(preferred))
    results: list[Candidate] = []
    for name in order:
        driver = drivers[name]
        reader = None
        try:
            reader = reader_for(path)
            found = driver.identify(reader)
        except (DataError, OSError):
            found = None
        finally:
            if reader is not None:
                reader.close()
        if found is not None:
            results.append(found)
    results.sort(key=lambda candidate: candidate.confidence, reverse=True)
    return results


def identify_json(path: Path | str, *, suffix_hint: str | None = None) -> str:
    rows = [candidate.to_dict() for candidate in identify(path, suffix_hint=suffix_hint)]
    return json.dumps({"reports": {"candidates": {"rows": rows}}})


__all__ = [
    "AhdiDisk",
    "AhdiFilesystem",
    "AhdiMount",
    "AtariMetadata",
    "BLOCK_SIZE",
    "BlockReader",
    "Candidate",
    "DD_SECTORS",
    "Datestamped",
    "DirectoryNode",
    "Entry",
    "FAT12Filesystem",
    "FAT16Filesystem",
    "FILESYSTEMS",
    "GEMDOSFilesystem",
    "GEMDOSMount",
    "GEMDOSVolume",
    "Geometry",
    "HD_SECTORS",
    "IDENTIFY_ORDER",
    "NAMED_GEOMETRIES",
    "Partition",
    "PathNode",
    "SECTOR_SIZE",
    "SUFFIX_HINTS",
    "Stat",
    "TOSFilesystem",
    "create_filesystem",
    "create_partitioned_image",
    "format_volume",
    "geometry_from_bpb",
    "identify",
    "identify_json",
    "join_path",
    "list_filesystems",
    "named_geometry",
    "partition_geometry",
    "partition_reader",
    "read_partition_table",
    "reader_for",
    "split_path",
    "validate_label",
    "validate_name",
    "volume_geometry",
    "write_partition_table",
]
