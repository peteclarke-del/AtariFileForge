"""Hand-built Pasti captures, laid out exactly as the format describes.

A real STX comes from a real disk and the interesting ones are copyrighted
games, so none is bundled. These builders write the same structures the
reader parses, field by field, which is enough to prove the reader places
sectors, honours the controller status and notices protection evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.stx import (
    FILE_HEADER_SIZE,
    SECTOR_DESCRIPTOR_SIZE,
    TRACK_FLAG_SECTOR_DESCRIPTORS,
    TRACK_FLAG_SYNC_OFFSET,
    TRACK_FLAG_TRACK_IMAGE,
    TRACK_HEADER_SIZE,
)


@dataclass
class SectorSpec:
    number: int
    data: bytes
    fdc_status: int = 0
    flags: int = 0
    cylinder: int | None = None
    head: int | None = None
    size_code: int = 2
    read_time: int = 0
    bit_position: int = 0


@dataclass
class TrackSpec:
    track: int
    side: int
    sectors: list[SectorSpec] = field(default_factory=list)
    fuzzy: bytes = b""
    track_image: bytes | None = None
    sync_offset: int | None = None
    track_length: int = 6250
    descriptors: bool = True


def sector_payload(track: int, side: int, number: int) -> bytes:
    return bytes(((track * 31 + side * 17 + number * 7 + index) & 0xFF) for index in range(512))


def standard_track(track: int, side: int, sectors: int = 9) -> TrackSpec:
    return TrackSpec(
        track,
        side,
        [SectorSpec(number, sector_payload(track, side, number)) for number in range(1, sectors + 1)],
    )


def build_track(spec: TrackSpec) -> bytes:
    """One track record, header included."""
    body = bytearray()
    flags = 0
    if spec.descriptors:
        flags |= TRACK_FLAG_SECTOR_DESCRIPTORS
        data_area = bytearray()
        if spec.track_image is not None:
            flags |= TRACK_FLAG_TRACK_IMAGE
            if spec.sync_offset is not None:
                flags |= TRACK_FLAG_SYNC_OFFSET
                data_area += spec.sync_offset.to_bytes(2, "little")
            data_area += len(spec.track_image).to_bytes(2, "little")
            data_area += spec.track_image
        descriptors = bytearray()
        for sector in spec.sectors:
            offset = len(data_area)
            size = 128 << sector.size_code
            if not sector.fdc_status & 0x10:
                data_area += sector.data[:size].ljust(size, b"\x00")
            descriptor = bytearray(SECTOR_DESCRIPTOR_SIZE)
            descriptor[0:4] = offset.to_bytes(4, "little")
            descriptor[4:6] = sector.bit_position.to_bytes(2, "little")
            descriptor[6:8] = sector.read_time.to_bytes(2, "little")
            descriptor[8] = spec.track if sector.cylinder is None else sector.cylinder
            descriptor[9] = spec.side if sector.head is None else sector.head
            descriptor[10] = sector.number
            descriptor[11] = sector.size_code
            descriptor[12:14] = (0x1234).to_bytes(2, "little")
            descriptor[14] = sector.fdc_status
            descriptor[15] = sector.flags
            descriptors += descriptor
        body += descriptors + spec.fuzzy + data_area
    else:
        for sector in spec.sectors:
            body += sector.data[:512].ljust(512, b"\x00")
    header = bytearray(TRACK_HEADER_SIZE)
    header[0:4] = (TRACK_HEADER_SIZE + len(body)).to_bytes(4, "little")
    header[4:8] = len(spec.fuzzy).to_bytes(4, "little")
    header[8:10] = len(spec.sectors).to_bytes(2, "little")
    header[10:12] = flags.to_bytes(2, "little")
    header[12:14] = spec.track_length.to_bytes(2, "little")
    header[14] = spec.track | (0x80 if spec.side else 0)
    header[15] = 0
    return bytes(header) + bytes(body)


def build_stx(tracks: list[TrackSpec], *, revision: int = 2) -> bytes:
    header = bytearray(FILE_HEADER_SIZE)
    header[0:4] = b"RSY\x00"
    header[4:6] = (3).to_bytes(2, "little")
    header[6:8] = (1).to_bytes(2, "little")
    header[10] = len(tracks)
    header[11] = revision
    return bytes(header) + b"".join(build_track(spec) for spec in tracks)


def one_track_with_a_crc_error() -> tuple[bytes, TrackSpec]:
    """The reference fixture: nine good sectors and one the controller rejected."""
    spec = standard_track(0, 0, 9)
    spec.sectors.append(
        SectorSpec(10, sector_payload(0, 0, 10), fdc_status=0x08)
    )
    return build_stx([spec]), spec
