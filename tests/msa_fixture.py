"""Sector images with real boot sectors, for the container tests.

The preferred fixture is a FAT12 volume written by ``mkfs.fat``, so the boot
sector is one a real tool produced rather than one the tests invented. When
the tool is absent the tests that need it are skipped rather than fed a
substitute; the synthetic image below carries only a BIOS parameter block
and is for the tests that need a known shape, not a real filesystem.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.floppy_geometry import GEOMETRIES, SECTOR_SIZE, FloppyGeometry

MKFS_FAT = shutil.which("mkfs.fat") or (
    "/usr/sbin/mkfs.fat" if Path("/usr/sbin/mkfs.fat").is_file() else None
)


def fat12_720k_image() -> bytes:
    """A 720 KiB FAT12 volume made by mkfs.fat, or a skip when it is absent."""
    if MKFS_FAT is None:
        raise unittest.SkipTest("mkfs.fat is not installed on this host")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "fat720.img"
        subprocess.run(
            [MKFS_FAT, "-F", "12", "-S", "512", "-s", "2", "-r", "112", "-f", "2",
             "-C", str(path), "720"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return path.read_bytes()


def boot_sector(geometry: FloppyGeometry, *, sectors_per_cluster: int = 2) -> bytes:
    """A boot sector carrying the BIOS parameter block TOS writes."""
    boot = bytearray(SECTOR_SIZE)
    boot[0:2] = b"\x60\x38"
    boot[2:8] = b"Loader"
    boot[0x0B:0x0D] = SECTOR_SIZE.to_bytes(2, "little")
    boot[0x0D] = sectors_per_cluster
    boot[0x0E:0x10] = (1).to_bytes(2, "little")
    boot[0x10] = 2
    boot[0x11:0x13] = (112).to_bytes(2, "little")
    boot[0x13:0x15] = geometry.total_sectors.to_bytes(2, "little")
    boot[0x15] = 0xF9 if geometry.sides == 2 else 0xF8
    boot[0x16:0x18] = (5 if geometry.sectors >= 10 else 3).to_bytes(2, "little")
    boot[0x18:0x1A] = geometry.sectors.to_bytes(2, "little")
    boot[0x1A:0x1C] = geometry.sides.to_bytes(2, "little")
    return bytes(boot)


def patterned_image(geometry: FloppyGeometry, *, with_boot: bool = True) -> bytes:
    """An image in which even tracks stay literal and odd tracks pack.

    Every track is a sequence with no repeated neighbours, so the packer has
    nothing to fold; a lone ``0xE5`` in the even tracks costs four bytes as
    a run record, making the packed form longer and the raw form the one
    stored. The odd tracks add a 64-byte run so they pack shorter.
    """
    image = bytearray(geometry.size)
    for track in range(geometry.tracks):
        for side in range(geometry.sides):
            offset = (track * geometry.sides + side) * geometry.track_size
            body = bytearray(
                ((index * 7 + track * 13 + side * 5) & 0xFF) for index in range(geometry.track_size)
            )
            body[300] = 0xE5
            if track % 2:
                body[64:128] = bytes((track & 0xFF,)) * 64
                body[200:204] = b"\xe5\xe5\xe5\xe5"
            image[offset : offset + geometry.track_size] = body
    if with_boot:
        image[:SECTOR_SIZE] = boot_sector(geometry)
    return bytes(image)


def blank_image(geometry: FloppyGeometry) -> bytes:
    """A blank disk of a known shape, boot sector only."""
    image = bytearray(geometry.size)
    image[:SECTOR_SIZE] = boot_sector(geometry)
    return bytes(image)


DS_720K = GEOMETRIES["ds-80t-9s"]
SS_360K = GEOMETRIES["ss-80t-9s"]
PC_360K = GEOMETRIES["pc-360k"]
DS_800K = GEOMETRIES["ds-80t-10s"]
DS_82_10 = GEOMETRIES["ds-82t-10s"]
