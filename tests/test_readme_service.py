from __future__ import annotations

import struct
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.readme_service import (
    build_download_readme,
    timestamped_archive_name,
    write_download_readme,
)


GENERATED = datetime(2026, 8, 1, 14, 5, 9, tzinfo=timezone.utc)
MEBIBYTE = 1024 * 1024


def floppy_bytes() -> bytes:
    """A 720 KiB image whose BIOS parameter block declares its own shape."""
    image = bytearray(80 * 2 * 9 * 512)
    struct.pack_into("<H", image, 0x0B, 512)
    struct.pack_into("<H", image, 0x13, 80 * 2 * 9)
    struct.pack_into("<H", image, 0x18, 9)
    struct.pack_into("<H", image, 0x1A, 2)
    return bytes(image)


class FakeService:
    def __init__(self, *, tree=None, partitions=None, summary=None, banks=None):
        self.tree = dict(tree or {})
        self.partitions = list(partitions or [])
        self._summary = dict(summary or {})
        self.banks = list(banks or [])

    def summary(self, session):
        return dict(self._summary)

    def list_directory(self, session, inner, side=None):
        return {"entries": list(self.tree.get(inner, [])), "path": inner}

    def list_partitions(self, session):
        return list(self.partitions)

    def list_rom_banks(self, session):
        return list(self.banks)


def make_session(path: Path, kind: str = "gemdos", **overrides) -> SimpleNamespace:
    session = SimpleNamespace(
        id="a" * 32,
        name=path.name,
        kind=kind,
        path=path,
        descriptor_path=None,
        descriptor_name=None,
        partition=None,
        hardware_profile={},
        target_hardware="auto",
        warnings=[],
        compatibility_reports=[],
        ffs_capabilities={},
        hfe_original_path=None,
        hfe_version=None,
        hfe_read_only=False,
        rom_platform="tos",
        rom_bank_size=256 * 1024,
        rom_erase_byte=0xFF,
        rom_layout="linear",
        rom_component_names=[],
        rom_project={"symbols": {}},
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


class ArchiveNameTests(unittest.TestCase):
    def test_the_archive_name_uses_the_image_stem_and_a_timestamp(self) -> None:
        self.assertEqual(
            timestamped_archive_name("GAMES.LIBRARY.img", GENERATED),
            "GAMES.LIBRARY-20260801-140509.zip",
        )


class FloppyReadmeTests(unittest.TestCase):
    def readme(self, folder: str) -> str:
        path = Path(folder) / "GAMES.ST"
        path.write_bytes(floppy_bytes())
        service = FakeService(
            tree={
                "": [
                    {"name": "AUTO", "type": "dir", "length": 1},
                    {
                        "name": "GAME.PRG", "type": "file", "length": 20480,
                        "attributes": "-----a", "datestamp": "1992-06-01T09:00:00",
                        "filetype": "Program",
                    },
                ],
                "AUTO": [{
                    "name": "START.PRG", "type": "file", "length": 512,
                    "attributes": "r----a", "filetype": "Program",
                }],
            },
            summary={"label": "GAMES", "revision": "1"},
        )
        session = make_session(
            path,
            ffs_capabilities={
                "format": "FAT12", "nameLimit": 12, "labelLimit": 11,
                "directoryEntryLimit": 112, "caseInsensitive": True, "bootable": True,
            },
            hardware_profile={
                "name": "1040STE", "machine": "ste",
                "addons": ["tos-206", "drive-a-ds", "monitor-colour"],
            },
        )
        return build_download_readme(service, session, path, GENERATED)

    def test_the_identity_block_names_the_shape_format_label_and_boot_sector(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            readme = self.readme(folder)

        self.assertIn("- Image kind: GEMDOS volume", readme)
        self.assertIn("- Floppy geometry:", readme)
        self.assertIn("720", readme)
        self.assertIn("- Filing system: FAT12", readme)
        self.assertIn("- Volume label: GAMES", readme)
        self.assertIn("- Boot sector: executable", readme)
        self.assertIn("- Root directory entries: 112", readme)
        self.assertIn("- Image SHA-256:", readme)

    def test_the_catalogue_columns_are_name_attributes_datestamp_size_and_kind(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            readme = self.readme(folder)

        header = next(line for line in readme.splitlines() if line.startswith("| Name |"))
        self.assertEqual(
            [cell.strip() for cell in header.strip("|").split("|")],
            ["Name", "Attributes", "Datestamp", "Size", "Kind"],
        )
        row = next(line for line in readme.splitlines() if "`AUTO/START.PRG`" in line)
        self.assertEqual(
            [cell.strip() for cell in row.strip("|").split("|")],
            ["`AUTO/START.PRG`", "`r----a`", "-", "512", "Program"],
        )
        self.assertIn("1992-06-01T09:00:00", readme)

    def test_the_hardware_profile_is_described_in_atari_terms(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            readme = self.readme(folder)

        self.assertIn("- Hardware profile: 1040STE", readme)
        self.assertIn("- Base machine: ste", readme)
        self.assertIn("tos-206", readme)

    def test_the_technical_notes_describe_the_auto_folder_and_the_fat_dates(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            readme = self.readme(folder)

        self.assertIn("1980 to 2107", readme)
        self.assertIn("`AUTO`", readme)


class HardDriveReadmeTests(unittest.TestCase):
    def test_every_partition_is_listed_with_its_drive_letter_and_id(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "SYSTEM.img"
            path.write_bytes(bytes(4 * MEBIBYTE))
            service = FakeService(
                partitions=[
                    {
                        "device": "C:", "id": "GEM", "startSector": 2,
                        "sizeBytes": 12 * MEBIBYTE, "format": "FAT16", "bootable": True,
                    },
                    {
                        "device": "D:", "id": "BGM", "startSector": 24578,
                        "sizeBytes": 300 * MEBIBYTE, "format": "FAT16", "bootable": False,
                    },
                ],
                summary={"scheme": "ahdi", "byteSwapped": False, "revision": "1"},
            )
            session = make_session(path, "hd")

            readme = build_download_readme(service, session, path, GENERATED)

        self.assertIn("- Partition scheme: AHDI", readme)
        self.assertIn("- Byte order: plain", readme)
        self.assertIn("| Drive | Id | Start sector | Size | Filing system | Boot |", readme)
        self.assertIn("| `C:` | GEM | 2 | 12,582,912 bytes | FAT16 | yes |", readme)
        self.assertIn("| `D:` | BGM |", readme)
        self.assertIn("up to 16 MiB, mounted by every TOS release", readme)
        self.assertIn("### TOS partition limits", readme)
        self.assertIn("256 MiB", readme)

    def test_a_byte_swapped_drive_says_which_devices_need_it_un_swapped(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "IDE.img"
            path.write_bytes(bytes(MEBIBYTE))
            service = FakeService(summary={"byteSwapped": True, "scheme": "mbr", "revision": "1"})
            session = make_session(path, "hd")

            readme = build_download_readme(service, session, path, GENERATED)

        self.assertIn("- Byte order: byte-swapped", readme)
        self.assertIn("ACSI device needs the un-swapped bytes", readme)


class RomReadmeTests(unittest.TestCase):
    def test_the_rom_header_facts_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "TOS104.IMG"
            path.write_bytes(bytes(192 * 1024))
            service = FakeService(banks=[{
                "bank": 0, "name": "TOS 1.04", "length": 192 * 1024, "empty": False,
                "filetype": "TOS ROM", "diagnostics": {"sha256": "abc"},
                "header": {
                    "release": "TOS 1.04", "versionHex": "0104", "country": "United Kingdom",
                    "countryShort": "UK", "videoStandard": "PAL", "base": 0xFC0000,
                    "machine": "ST", "emutos": False, "date": "1989-04-06", "roles": "TOS",
                },
            }])
            session = make_session(path, "tosrom")

            readme = build_download_readme(service, session, path, GENERATED)

        self.assertIn("- Release: TOS 1.04", readme)
        self.assertIn("- Country: United Kingdom (UK)", readme)
        self.assertIn("- Video standard: PAL", readme)
        self.assertIn("- Mapped base address: &FC0000", readme)
        self.assertIn("- EmuTOS: no, this is an Atari TOS ROM", readme)
        self.assertIn("## ROM bank catalogue", readme)


class DeploymentReadmeTests(unittest.TestCase):
    def test_a_deployment_package_carries_its_installation_steps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "GAMES.ST"
            path.write_bytes(floppy_bytes())
            service = FakeService(summary={"revision": "1"})
            session = make_session(path)

            readme = build_download_readme(
                service, session, path, GENERATED,
                deployment={
                    "target": "gotek",
                    "targetLabel": "Gotek with FlashFloppy",
                    "instructions": ["Format the USB device as FAT32.", "Copy GOTEK-USB across."],
                    "issues": [{"severity": "warning", "message": "No Gotek is declared."}],
                },
            )

        self.assertIn("## Hardware deployment", readme)
        self.assertIn("1. Format the USB device as FAT32.", readme)
        self.assertIn("- WARNING: No Gotek is declared.", readme)

    def test_the_readme_is_written_beside_the_working_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "GAMES.ST"
            path.write_bytes(floppy_bytes())
            service = FakeService(summary={"revision": "1"})
            session = make_session(path)

            written = write_download_readme(service, session, path, GENERATED)

        self.assertEqual(written.name, "download-README.md")


if __name__ == "__main__":
    unittest.main()
