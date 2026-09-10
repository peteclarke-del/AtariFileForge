"""FastCopy Pro DIM images: a sector image behind a 32-byte header.

FastCopy Pro was the copier most ST owners used, and its ``.dim`` output is
the raw sectors it read, track by track and side by side, after a small
header that records the shape. Unlike an ``.st`` the shape is therefore
never in doubt.

The header, with the byte offsets FastCopy Pro used (the layout is shared
with the HxC loader's ``dim_format.h``; the reader Greaseweazle ships under
the same name is the unrelated PC-98 DIFC format and is no guide here):

* ``0x00`` word ``0x4242`` (the letters ``BB``);
* ``0x03`` whether only used sectors were copied (0 = all, 1 = used);
* ``0x06`` sides minus one;
* ``0x08`` sectors per track;
* ``0x0A`` first track and ``0x0C`` last track, both counted from zero;
* ``0x0D`` density (0 = double, 1 = high);
* ``0x0E`` sector size as a big-endian word, zero meaning 512;
* the rest is unused.

The full form holds every sector. The "used sectors" form was FastCopy's
space saver: the sectors GEMDOS had not allocated were left out. Reading it
back means walking the FAT the image itself carries, placing the system
area first and then each allocated cluster in order. That is done here only
when the packed length agrees exactly with what the FAT predicts; otherwise
the leading sectors are placed as far as they go and the shortfall is
reported, never silently zeroed. Only the full form is ever written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .floppy_geometry import (
    SECTOR_SIZE,
    FloppyGeometry,
    geometry_for_layout,
    resolve_geometry,
)


MAGIC = b"BB"
HEADER_SIZE = 32

_USED_SECTORS_ONLY = 0x03
_SIDES = 0x06
_SECTORS_PER_TRACK = 0x08
_START_TRACK = 0x0A
_END_TRACK = 0x0C
_DENSITY = 0x0D
_SECTOR_SIZE = 0x0E


class DIMError(ValueError):
    """A DIM image could not be read or built."""


@dataclass(frozen=True)
class DIMImage:
    used_sectors_only: bool
    sides: int
    sectors_per_track: int
    start_track: int
    end_track: int
    density: int
    sector_size: int
    data: bytes
    warnings: list[str] = field(default_factory=list)

    @property
    def geometry(self) -> FloppyGeometry:
        return geometry_for_layout(self.end_track + 1, self.sides, self.sectors_per_track)

    @property
    def track_size(self) -> int:
        return self.sectors_per_track * self.sector_size

    @property
    def size(self) -> int:
        return self.geometry.size

    @property
    def stored_size(self) -> int:
        """The bytes the file should hold for the tracks its header covers."""
        return (self.end_track - self.start_track + 1) * self.sides * self.track_size

    @property
    def complete(self) -> bool:
        """Whether every sector the header covers is present in the file."""
        return len(self.data) >= self.stored_size


def is_dim(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[:2] == MAGIC


def parse_dim(data: bytes) -> DIMImage:
    if not is_dim(data):
        raise DIMError("The file does not start with the DIM identifier 0x4242.")
    header = data[:HEADER_SIZE]
    sides = header[_SIDES] + 1
    sectors_per_track = header[_SECTORS_PER_TRACK]
    start_track = header[_START_TRACK]
    end_track = header[_END_TRACK]
    sector_size = int.from_bytes(header[_SECTOR_SIZE : _SECTOR_SIZE + 2], "big") or SECTOR_SIZE
    if sides not in (1, 2):
        raise DIMError(f"A DIM cannot have {sides} sides.")
    if not 1 <= sectors_per_track <= 36:
        raise DIMError(f"A DIM cannot have {sectors_per_track} sectors per track.")
    if end_track < start_track:
        raise DIMError(f"The DIM track range {start_track}-{end_track} is not a disk.")
    if sector_size != SECTOR_SIZE:
        raise DIMError(f"Only 512-byte sectors are supported; this DIM uses {sector_size}.")
    image = DIMImage(
        used_sectors_only=header[_USED_SECTORS_ONLY] == 1,
        sides=sides,
        sectors_per_track=sectors_per_track,
        start_track=start_track,
        end_track=end_track,
        density=header[_DENSITY],
        sector_size=sector_size,
        data=data[HEADER_SIZE:],
    )
    if start_track:
        image.warnings.append(
            f"The image starts at track {start_track}; earlier tracks are left blank."
        )
    if len(image.data) > image.stored_size:
        image.warnings.append(
            f"{len(image.data) - image.stored_size:,} bytes follow the last sector and are ignored."
        )
    return image


# ---------------------------------------------------------------------------
# The "used sectors" form
# ---------------------------------------------------------------------------


def _bpb_word(boot: bytes, offset: int) -> int:
    return int.from_bytes(boot[offset : offset + 2], "little")


def _fat12_used_clusters(fat: bytes, count: int) -> list[int]:
    """Clusters the first FAT marks as allocated, in cluster order."""
    used = []
    for cluster in range(2, count + 2):
        index = cluster + cluster // 2
        if index + 1 >= len(fat):
            break
        pair = fat[index] | (fat[index + 1] << 8)
        entry = (pair >> 4) if cluster & 1 else (pair & 0x0FFF)
        if entry:
            used.append(cluster)
    return used


def _expand_used_sectors(image: DIMImage) -> tuple[bytes, list[str]]:
    """Place a "used sectors" DIM's data where the FAT says it belongs."""
    data = image.data
    warnings: list[str] = []
    full = bytearray(image.size)
    if len(data) >= image.size:
        warnings.append(
            "The header says only used sectors were copied, but every sector is present."
        )
        full[:] = data[: image.size]
        return bytes(full), warnings

    boot = data[:SECTOR_SIZE]
    sectors_per_cluster = boot[0x0D] if len(boot) > 0x0D else 0
    reserved = _bpb_word(boot, 0x0E)
    fats = boot[0x10] if len(boot) > 0x10 else 0
    root_entries = _bpb_word(boot, 0x11)
    total = _bpb_word(boot, 0x13)
    sectors_per_fat = _bpb_word(boot, 0x16)
    layout_ok = (
        len(boot) == SECTOR_SIZE
        and _bpb_word(boot, 0x0B) == SECTOR_SIZE
        and sectors_per_cluster
        and fats
        and sectors_per_fat
        and total == image.geometry.total_sectors
    )
    if layout_ok:
        system = reserved + fats * sectors_per_fat + (root_entries * 32 + SECTOR_SIZE - 1) // SECTOR_SIZE
        cluster_count = (total - system) // sectors_per_cluster
        fat_offset = reserved * SECTOR_SIZE
        fat = data[fat_offset : fat_offset + sectors_per_fat * SECTOR_SIZE]
        used = _fat12_used_clusters(fat, cluster_count)
        expected = (system + len(used) * sectors_per_cluster) * SECTOR_SIZE
        if expected == len(data):
            full[: system * SECTOR_SIZE] = data[: system * SECTOR_SIZE]
            source = system * SECTOR_SIZE
            cluster_bytes = sectors_per_cluster * SECTOR_SIZE
            for cluster in used:
                target = (system + (cluster - 2) * sectors_per_cluster) * SECTOR_SIZE
                full[target : target + cluster_bytes] = data[source : source + cluster_bytes]
                source += cluster_bytes
            warnings.append(
                f"Only used sectors were copied: {len(used):,} allocated clusters were "
                "placed from the FAT and the unallocated ones are blank."
            )
            return bytes(full), warnings
        warnings.append(
            f"The FAT predicts {expected:,} bytes of used sectors but the file holds "
            f"{len(data):,}, so the used-sector layout could not be applied."
        )
    else:
        warnings.append(
            "The boot sector carries no usable BIOS parameter block, so the used-sector "
            "layout could not be applied."
        )
    full[: len(data)] = data
    warnings.append(
        f"The first {len(data):,} bytes were placed in order; the remaining "
        f"{image.size - len(data):,} bytes of the disk are blank."
    )
    return bytes(full), warnings


def dim_to_st(data: bytes) -> bytes:
    """Rebuild the sector image, in either form."""
    image, _warnings = decode_dim(data)
    return image


def decode_dim(data: bytes) -> tuple[bytes, list[str]]:
    """Rebuild the sector image and say what had to be inferred to do it."""
    parsed = parse_dim(data)
    warnings = list(parsed.warnings)
    if parsed.used_sectors_only:
        image, extra = _expand_used_sectors(parsed)
        return image, warnings + extra
    offset = parsed.start_track * parsed.sides * parsed.track_size
    held = parsed.size - offset
    if len(parsed.data) < held:
        raise DIMError(
            f"The DIM holds {len(parsed.data):,} bytes of sectors but its header "
            f"describes a {parsed.size:,}-byte disk"
            + (f" from track {parsed.start_track}" if parsed.start_track else "")
            + "."
        )
    if parsed.start_track:
        full = bytearray(parsed.size)
        full[offset:] = parsed.data[:held]
        return bytes(full), warnings
    return bytes(parsed.data[: parsed.size]), warnings


def st_to_dim(image: bytes, geometry: FloppyGeometry | None = None) -> bytes:
    """Wrap a sector image in the full-form header."""
    if geometry is None:
        geometry = resolve_geometry(len(image), image[:SECTOR_SIZE])
    if geometry is None:
        raise DIMError(
            f"A {len(image):,}-byte image has no boot sector geometry and its size "
            "does not identify one shape; state the geometry explicitly."
        )
    if geometry.size != len(image):
        raise DIMError(
            f"The image is {len(image):,} bytes but {geometry.label} is {geometry.size:,}."
        )
    if geometry.tracks > 256 or geometry.sides not in (1, 2):
        raise DIMError(f"{geometry.label} cannot be written as a DIM.")
    header = bytearray(HEADER_SIZE)
    header[:2] = MAGIC
    header[_USED_SECTORS_ONLY] = 0
    header[_SIDES] = geometry.sides - 1
    header[_SECTORS_PER_TRACK] = geometry.sectors
    header[_START_TRACK] = 0
    header[_END_TRACK] = geometry.tracks - 1
    header[_DENSITY] = 1 if geometry.sectors >= 15 else 0
    header[_SECTOR_SIZE : _SECTOR_SIZE + 2] = SECTOR_SIZE.to_bytes(2, "big")
    return bytes(header) + image


def dim_project(data: bytes) -> dict:
    """Describe the header and the tracks it covers, for the inspector view."""
    parsed = parse_dim(data)
    _image, warnings = decode_dim(data)
    geometry = parsed.geometry
    return {
        "format": "dim",
        "usedSectorsOnly": parsed.used_sectors_only,
        "sides": parsed.sides,
        "sectorsPerTrack": parsed.sectors_per_track,
        "startTrack": parsed.start_track,
        "endTrack": parsed.end_track,
        "density": "high" if parsed.density else "double",
        "sectorSize": parsed.sector_size,
        "geometry": {"id": geometry.identifier, "label": geometry.label},
        "size": parsed.size,
        "storedBytes": len(parsed.data),
        "complete": parsed.complete,
        "warnings": warnings,
    }


__all__ = [
    "HEADER_SIZE",
    "MAGIC",
    "DIMError",
    "DIMImage",
    "decode_dim",
    "dim_project",
    "dim_to_st",
    "is_dim",
    "parse_dim",
    "st_to_dim",
]
