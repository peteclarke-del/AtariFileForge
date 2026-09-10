"""Reading SPS IPF captures, when the decoder library is installed.

IPF is the Software Preservation Society's preservation format. Unlike a
plain ``.st`` it records what was actually on the disk, including the timing
and the deliberate irregularities copy protection relies on, which is why a
protected disk survives as an IPF and not as a sector image.

Decoding one needs the SPS decoder library (``libcapsimage``). That library is
source-available under a non-commercial licence and is not ours to ship, so
nothing here bundles it: the workbench looks for it at run time and, when it is
absent, says so plainly instead of failing in an obscure way. Installing it is
documented in ``docs/IPF-GUIDE.md``.

What the library returns is a track's MFM bit cells, not its files. Turning
those into sectors is done here the way the ST's WD1772 controller does it:
find the three ``A1`` sync bytes whose missing clock bit marks an address
mark, read the ID field that names the cylinder, head, sector and size, check
its CRC, then find the data mark that follows and check the CRC over the
sector's bytes. A sector that does not check out is reported rather than
written, because a preservation image is exactly where a silently wrong byte
does the most damage.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import DiskError
from .floppy_geometry import SECTOR_SIZE, FloppyGeometry, geometry_for_layout

#: Names the decoder library is installed under, newest first.
LIBRARY_NAMES = (
    "libcapsimage.so.5.1",
    "libcapsimage.so.5",
    "libcapsimage.so.4.2",
    "libcapsimage.so.4",
    "libcapsimage.so",
    "capsimg.so",
    "CAPSImg.dll",
    "libcapsimage.dylib",
)

#: Where the workbench looks, in order. The environment variable wins so a
#: build or a test can point at one exact file.
ENVIRONMENT_VARIABLE = "ATARI_FILE_FORGE_CAPSIMAGE"


def _search_directories() -> list[Path]:
    return [
        Path.home() / ".config" / "atari-file-forge" / "lib",
        Path("/opt/atari-file-forge/native/lib"),
        Path("/usr/local/lib"),
        Path("/usr/lib"),
    ]


class IPFError(DiskError):
    """An IPF capture could not be read."""


# Lock flags, from the library's own header. Together they ask the decoder for
# a fully decoded, index-aligned track with variable density applied, which is
# what an emulator asks for and what a sector decoder needs.
DI_LOCK_INDEX = 1 << 0
DI_LOCK_DENVAR = 1 << 2
DI_LOCK_DENAUTO = 1 << 3
DI_LOCK_DENNOISE = 1 << 4
DI_LOCK_UPDATEFD = 1 << 8
DI_LOCK_TYPE = 1 << 9

_LOCK_FLAGS = (
    DI_LOCK_INDEX
    | DI_LOCK_DENVAR
    | DI_LOCK_DENAUTO
    | DI_LOCK_DENNOISE
    | DI_LOCK_UPDATEFD
    | DI_LOCK_TYPE
)

_UDWORD = ctypes.c_uint32
_SDWORD = ctypes.c_int32


class _CapsDateTimeExt(ctypes.Structure):
    _fields_ = [
        ("year", _UDWORD), ("month", _UDWORD), ("day", _UDWORD),
        ("hour", _UDWORD), ("min", _UDWORD), ("sec", _UDWORD), ("tick", _UDWORD),
    ]


class _CapsImageInfo(ctypes.Structure):
    _fields_ = [
        ("type", _UDWORD),
        ("release", _UDWORD),
        ("revision", _UDWORD),
        ("mincylinder", _UDWORD),
        ("maxcylinder", _UDWORD),
        ("minhead", _UDWORD),
        ("maxhead", _UDWORD),
        ("crdt", _CapsDateTimeExt),
        ("platform", _UDWORD * 4),
    ]


class _CapsTrackInfoT2(ctypes.Structure):
    """The version 2 track block, which returns one decoded buffer."""

    _fields_ = [
        ("type", _UDWORD),
        ("cylinder", _UDWORD),
        ("head", _UDWORD),
        ("sectorcnt", _UDWORD),
        ("sectorsize", _UDWORD),
        ("trackbuf", ctypes.POINTER(ctypes.c_ubyte)),
        ("tracklen", _UDWORD),
        ("timelen", _UDWORD),
        ("timebuf", ctypes.POINTER(_UDWORD)),
        ("overlap", _SDWORD),
        ("startbit", _UDWORD),
        ("wseed", _UDWORD),
        ("weakcnt", _UDWORD),
    ]


@dataclass
class IPFReport:
    """What an IPF conversion produced, and what it could not."""

    sectors: bytes = b""
    cylinders: int = 0
    heads: int = 0
    sectors_per_track: int = 0
    recovered: int = 0
    expected: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.expected > 0 and self.recovered == self.expected

    @property
    def geometry(self) -> FloppyGeometry:
        return geometry_for_layout(self.cylinders, self.heads, self.sectors_per_track)


def library_path() -> Path | None:
    """Return the decoder library this machine has, or None."""
    override = os.environ.get(ENVIRONMENT_VARIABLE, "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    for directory in _search_directories():
        for name in LIBRARY_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def available() -> bool:
    """Whether IPF captures can be read on this machine."""
    return library_path() is not None


def unavailable_message() -> str:
    """One sentence explaining what is missing and what to do about it."""
    return (
        "Reading an IPF capture needs the SPS decoder library, which is not "
        "ours to distribute and is not installed here. Build libcapsimage and "
        f"put it in {Path.home() / '.config' / 'atari-file-forge' / 'lib'}, or "
        f"set {ENVIRONMENT_VARIABLE} to its path. docs/IPF-GUIDE.md has the steps."
    )


def _load() -> ctypes.CDLL:
    path = library_path()
    if path is None:
        raise IPFError(unavailable_message())
    try:
        library = ctypes.CDLL(str(path))
    except OSError as exc:
        raise IPFError(f"The SPS decoder library at {path} could not be loaded: {exc}") from exc
    if library.CAPSInit() != 0:
        raise IPFError("The SPS decoder library refused to initialise.")
    return library


# ---------------------------------------------------------------------------
# IBM/ISO MFM, as the WD1772 reads it
# ---------------------------------------------------------------------------
#: The MFM word of an ``A1`` byte with its clock bit deliberately missing.
#: Three in a row precede every address mark.
SYNC_WORD = 0x4489
_SYNC_BITS = format((SYNC_WORD << 32) | (SYNC_WORD << 16) | SYNC_WORD, "048b")
_SYNC_BYTES = b"\xa1\xa1\xa1"

ID_ADDRESS_MARK = 0xFE
DATA_ADDRESS_MARK = 0xFB
DELETED_DATA_ADDRESS_MARK = 0xF8

#: The most sectors an ID field may plausibly name on a floppy. Anything
#: higher is a protection scheme's invention, not a layout.
MAX_SECTORS_PER_TRACK = 36

#: How far past an ID field the data mark may lie. The standard gap is 22
#: bytes of ``4E`` and 12 of ``00`` before the sync; sixty bytes leaves room
#: for a formatter that stretched it.
_DATA_MARK_WINDOW = 60 * 16

#: How much of the track's start is repeated after its end so a sector that
#: straddles the index is read whole: the largest sector plus its marks.
_RING_OVERLAP = (3 + 1 + 4 + 2 + 60 + 3 + 1 + 1024 + 2) * 16


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    """The CRC the WD1772 keeps over an address mark and what follows it."""
    crc = initial
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def _bit_string(raw: bytes) -> str:
    return format(int.from_bytes(raw, "big"), f"0{len(raw) * 8}b") if raw else ""


def _decode_bytes(bits: str, start: int, count: int) -> bytes:
    """Read ``count`` MFM bytes beginning at bit ``start``.

    In MFM every data bit is followed by a clock bit, so the data bits are the
    odd positions of each sixteen-bit cell pair.
    """
    data_bits = bits[start + 1 : start + 16 * count : 2]
    if len(data_bits) != 8 * count:
        return b""
    return int(data_bits, 2).to_bytes(count, "big")


def _decode_track(
    raw: bytes, sectors_per_track: int | None = None
) -> tuple[dict[int, bytes], list[str]]:
    """Pull every CRC-checked 512-byte sector out of one track's bit cells.

    Sectors are keyed by their zero-based number. ``sectors_per_track`` limits
    the numbers accepted; when it is None any plausible number is kept and
    the caller derives the layout from what was found.
    """
    found: dict[int, bytes] = {}
    warnings: list[str] = []
    bits = _bit_string(raw)
    limit = len(bits)
    ring = bits + bits[:_RING_OVERLAP]
    upper = sectors_per_track or MAX_SECTORS_PER_TRACK
    position = 0
    while position < limit:
        marker = ring.find(_SYNC_BITS, position)
        if marker < 0 or marker >= limit:
            break
        position = marker + 1
        field_start = marker + 48
        if _decode_bytes(ring, field_start, 1) != bytes((ID_ADDRESS_MARK,)):
            continue
        header = _decode_bytes(ring, field_start + 16, 4)
        stored = _decode_bytes(ring, field_start + 16 * 5, 2)
        if len(header) != 4 or len(stored) != 2:
            break
        cylinder, _head, number, size_code = header
        if crc16_ccitt(_SYNC_BYTES + bytes((ID_ADDRESS_MARK,)) + header) != int.from_bytes(stored, "big"):
            warnings.append(f"Track {cylinder}: a sector header failed its CRC.")
            continue
        data_marker = ring.find(_SYNC_BITS, field_start + 16 * 7, field_start + 16 * 7 + _DATA_MARK_WINDOW)
        if data_marker < 0:
            warnings.append(f"Track {cylinder} sector {number}: no data mark follows the header.")
            continue
        mark = _decode_bytes(ring, data_marker + 48, 1)
        if mark not in (bytes((DATA_ADDRESS_MARK,)), bytes((DELETED_DATA_ADDRESS_MARK,))):
            warnings.append(f"Track {cylinder} sector {number}: the data mark is not one the controller reads.")
            continue
        size = 128 << size_code if size_code <= 3 else 0
        payload = _decode_bytes(ring, data_marker + 48 + 16, size)
        stored = _decode_bytes(ring, data_marker + 48 + 16 + 16 * size, 2)
        if not size or len(payload) != size or len(stored) != 2:
            warnings.append(f"Track {cylinder} sector {number}: the data field is cut off.")
            continue
        if crc16_ccitt(_SYNC_BYTES + mark + payload) != int.from_bytes(stored, "big"):
            warnings.append(f"Track {cylinder} sector {number}: the data failed its CRC.")
            continue
        position = data_marker + 48 + 16 * (1 + size)
        if size != SECTOR_SIZE:
            warnings.append(f"Track {cylinder} sector {number}: {size}-byte sectors are not a GEMDOS layout.")
            continue
        if not 1 <= number <= upper:
            warnings.append(f"Track {cylinder}: sector number {number} is outside the layout.")
            continue
        found.setdefault(number - 1, payload)
    return found, warnings


def read_ipf(path: Path, *, sectors_per_track: int | None = None) -> IPFReport:
    """Decode an IPF capture into the sectors a plain ``.st`` holds.

    The layout is taken from the sectors themselves unless the caller names
    a sector count: the highest sector number recovered on any track is the
    count per track, which is what a formatter wrote even when a protected
    track is missing some. A track that does not carry standard sectors is
    reported and left as zeroes, because what makes it worth preserving is
    exactly what a sector image cannot hold.
    """
    library = _load()
    report = IPFReport(sectors_per_track=sectors_per_track or 0)
    image_id = library.CAPSAddImage()
    if image_id < 0:
        raise IPFError("The SPS decoder library would not allocate an image.")
    tracks: dict[tuple[int, int], dict[int, bytes]] = {}
    try:
        if library.CAPSLockImage(image_id, str(path).encode()) != 0:
            raise IPFError(f"{path.name} is not a capture the SPS decoder library accepts.")
        try:
            if library.CAPSLoadImage(image_id, _LOCK_FLAGS) != 0:
                raise IPFError(f"{path.name} could not be decoded by the SPS decoder library.")
            info = _CapsImageInfo()
            if library.CAPSGetImageInfo(ctypes.byref(info), image_id) != 0:
                raise IPFError("The capture's own description could not be read.")
            report.cylinders = int(info.maxcylinder) + 1
            report.heads = int(info.maxhead) + 1
            for cylinder in range(int(info.mincylinder), int(info.maxcylinder) + 1):
                for head in range(int(info.minhead), int(info.maxhead) + 1):
                    track = _CapsTrackInfoT2()
                    track.type = 2
                    if library.CAPSLockTrack(
                        ctypes.byref(track), image_id, cylinder, head, _LOCK_FLAGS
                    ) != 0:
                        report.warnings.append(
                            f"Cylinder {cylinder} head {head} could not be locked."
                        )
                        continue
                    try:
                        length = int(track.tracklen)
                        if not track.trackbuf or length <= 0:
                            report.warnings.append(
                                f"Cylinder {cylinder} head {head} decoded to nothing."
                            )
                            continue
                        raw = bytes(bytearray(track.trackbuf[:length]))
                        sectors, warnings = _decode_track(raw, sectors_per_track)
                        report.warnings.extend(warnings)
                        tracks[(cylinder, head)] = sectors
                    finally:
                        library.CAPSUnlockTrack(image_id, cylinder, head)
        finally:
            library.CAPSUnlockImage(image_id)
    finally:
        library.CAPSRemImage(image_id)
        library.CAPSExit()
    report.sectors, report.recovered, report.sectors_per_track = assemble_image(
        tracks, report.cylinders, report.heads, sectors_per_track
    )
    report.expected = report.cylinders * report.heads * report.sectors_per_track
    if not report.recovered:
        raise IPFError(
            f"No standard GEMDOS sector was recovered from {path.name}. "
            "The capture may hold a protected format that a sector image cannot represent."
        )
    return report


def assemble_image(
    tracks: dict[tuple[int, int], dict[int, bytes]],
    cylinders: int,
    heads: int,
    sectors_per_track: int | None = None,
) -> tuple[bytes, int, int]:
    """Lay recovered sectors out as a sector image.

    Returns the image, the number of sectors placed and the sectors per
    track the layout settled on. Separate from ``read_ipf`` so the layout
    rule can be tested without the decoder library.
    """
    if sectors_per_track is None:
        sectors_per_track = max(
            (number + 1 for sectors in tracks.values() for number in sectors),
            default=0,
        )
    if not sectors_per_track:
        return b"", 0, 0
    image = bytearray(cylinders * heads * sectors_per_track * SECTOR_SIZE)
    recovered = 0
    for (cylinder, head), sectors in tracks.items():
        base = (cylinder * heads + head) * sectors_per_track
        for number, payload in sectors.items():
            if number >= sectors_per_track:
                continue
            offset = (base + number) * SECTOR_SIZE
            image[offset : offset + SECTOR_SIZE] = payload
            recovered += 1
    return bytes(image), recovered, sectors_per_track


__all__ = [
    "DATA_ADDRESS_MARK",
    "DELETED_DATA_ADDRESS_MARK",
    "ENVIRONMENT_VARIABLE",
    "ID_ADDRESS_MARK",
    "SYNC_WORD",
    "IPFError",
    "IPFReport",
    "assemble_image",
    "available",
    "crc16_ccitt",
    "library_path",
    "read_ipf",
    "unavailable_message",
]
