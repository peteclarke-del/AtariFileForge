from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.disk_service import DiskService
from tests.generated_media import add_test_file, generated_media_matrix

FIXTURE_PAYLOAD = b"Atari File Forge generated fixture\n"

#: Every shape the workbench opens that can be built without an external
#: engine, keyed exactly as ``generated_media_matrix`` names it.
MATRIX_KEYS = {
    "ds-720k",
    "ds-800k",
    "ds-880k",
    "ss-360k",
    "hd-1440k",
    "ds-720k-boot",
    "volume",
    "hd",
    "rom",
    "cartridge",
    "msa",
    "dim",
}

#: What each generated GEMDOS volume declares about itself. A floppy is
#: FAT12 whatever its geometry; a volume at hard-disk size is FAT16, which is
#: what the driver's own parameter block says and what TOS obeys.
EXPECTED_CAPABILITIES = {
    "ds-720k": ("FAT12", 12, 112),
    "ds-800k": ("FAT12", 12, 112),
    "ds-880k": ("FAT12", 12, 112),
    "ss-360k": ("FAT12", 12, 112),
    "ds-720k-boot": ("FAT12", 12, 112),
    "hd-1440k": ("FAT12", 12, 224),
    "volume": ("FAT16", 16, 512),
}


class GeneratedMediaMatrixTests(unittest.TestCase):
    def test_every_core_format_is_generated_and_reopened_without_private_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            media = generated_media_matrix(service)

            self.assertEqual({item.format for item in media}, MATRIX_KEYS)
            for item in media:
                self.assertTrue(item.session.path.is_file(), item.format)
                self.assertGreater(item.session.path.stat().st_size, 0, item.format)
                reopened = DiskService(root / "work").get(item.session.id)
                summary = service.summary(reopened)
                self.assertEqual(summary["id"], item.session.id)
                if reopened.kind == "hd":
                    # A drive describes itself, so it must declare at least
                    # the partitions it was created with.
                    self.assertGreaterEqual(
                        len(service.list_partitions(reopened)), 1, item.format
                    )
                listing = service.browse_directory(reopened, "", None)
                self.assertIn("entries", listing, item.format)

    def test_each_generated_shape_opens_as_the_session_kind_it_should(self):
        expected = {
            "ds-720k": "gemdos",
            "ds-800k": "gemdos",
            "ds-880k": "gemdos",
            "ss-360k": "gemdos",
            "hd-1440k": "gemdos",
            "ds-720k-boot": "gemdos",
            "volume": "gemdos",
            "hd": "hd",
            "rom": "rom",
            "cartridge": "rom",
            "msa": "msa",
            "dim": "dim",
        }
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            for item in generated_media_matrix(service):
                self.assertEqual(item.session.kind, expected[item.format], item.format)

    def test_generated_writable_filesystems_accept_and_return_known_content(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            for item in generated_media_matrix(service):
                if not service.mountable(item.session):
                    continue
                add_test_file(service, item.session, root, path="TEST.DAT")
                self.assertEqual(
                    service.read_file(item.session, "TEST.DAT"),
                    FIXTURE_PAYLOAD,
                    item.format,
                )
                self.assertEqual(
                    service.validate(item.session),
                    "No structural errors found",
                    item.format,
                )

    def test_every_volume_reports_its_real_capabilities(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            media = {item.format: item.session for item in generated_media_matrix(service)}
            for format_name, (label, bits, entries) in EXPECTED_CAPABILITIES.items():
                session = media[format_name]
                capabilities = service.summary(session)["filesystemCapabilities"]
                self.assertEqual(capabilities["format"], label, format_name)
                self.assertEqual(capabilities["fatBits"], bits, format_name)
                # A name is eight characters, a full stop and three more, and
                # the volume folds it to upper case on the way in.
                self.assertEqual(capabilities["nameLimit"], 12, format_name)
                self.assertEqual(capabilities["nameForm"], "8.3", format_name)
                self.assertTrue(capabilities["caseInsensitive"], format_name)
                # A label occupies one entry's eleven name bytes, with no
                # separating full stop.
                self.assertEqual(capabilities["labelLimit"], 11, format_name)
                # The root is a fixed area written at format time, so its
                # entry count is a real ceiling and the root listing reports
                # exactly the same number.
                self.assertEqual(
                    capabilities["directoryEntryLimit"], entries, format_name
                )
                listing = service.list_directory(session, "", None)
                self.assertEqual(
                    listing["directoryEntryLimit"], entries, format_name
                )
                self.assertEqual(
                    listing["directoryEntriesUsed"],
                    len(listing["entries"]),
                    format_name,
                )

    def test_a_bootable_floppy_carries_a_boot_sector_tos_will_execute(self):
        """TOS runs sector zero only when its big-endian word sum is 0x1234."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            media = {item.format: item.session for item in generated_media_matrix(service)}

            self.assertTrue(service.summary(media["ds-720k-boot"])["bootable"])
            self.assertFalse(service.summary(media["ds-720k"])["bootable"])
            self.assertEqual(self._word_sum(media["ds-720k-boot"].path), 0x1234)
            self.assertNotEqual(self._word_sum(media["ds-720k"].path), 0x1234)

    @staticmethod
    def _word_sum(path: Path) -> int:
        sector = path.read_bytes()[:512]
        return sum(
            int.from_bytes(sector[offset : offset + 2], "big")
            for offset in range(0, 512, 2)
        ) & 0xFFFF

    def test_the_generated_containers_hold_the_tracks_of_a_whole_floppy(self):
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            media = {item.format: item.session for item in generated_media_matrix(service)}
            for container in ("msa", "dim"):
                session = media[container]
                rows = service.list_directory(session, "")["entries"]
                # A 720 KiB disk is 80 tracks on two sides.
                self.assertEqual(len(rows), 160, container)
                self.assertTrue(all(row["complete"] for row in rows), container)
                self.assertEqual(
                    service.validate(session).startswith("Valid"), True, container
                )

    def test_a_full_eight_three_name_round_trips_and_validates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "LONGNAME")
            # Exactly the twelve characters GEMDOS allows.
            long_name = "LONGNAME.DOC"
            self.assertEqual(len(long_name), 12)
            add_test_file(service, session, root, path=long_name)
            self.assertEqual(service.read_file(session, long_name), FIXTURE_PAYLOAD)
            self.assertEqual(service.validate(session), "No structural errors found")

    def test_a_nested_directory_path_round_trips(self):
        """``MYFILES\\DISK.INF`` is an ordinary GEMDOS path."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "NAMES")
            service.make_directory(session, "MYFILES")
            add_test_file(service, session, root, path="MYFILES\\DISK.INF")
            self.assertEqual(
                service.read_file(session, "MYFILES\\DISK.INF"), FIXTURE_PAYLOAD
            )
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "MYFILES", None)["entries"]
                ],
                ["DISK.INF"],
            )

    def test_a_bare_volume_keeps_its_declared_size_through_an_edit(self):
        """A driver hands TOS a fixed number of sectors, so the file cannot grow."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("volume", "DRIVE", "20MB")
            declared = session.path.stat().st_size
            add_test_file(service, session, root, path="PAYLOAD.DAT")

            self.assertEqual(service.read_file(session, "PAYLOAD.DAT"), FIXTURE_PAYLOAD)
            self.assertEqual(service.validate(session), "No structural errors found")
            self.assertEqual(session.path.stat().st_size, declared)

    def test_generated_rom_session_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / "work"
            session = DiskService(work).create_blank("cartridge", "RECOVER")
            restored = DiskService(work).get(session.id)
            self.assertEqual(restored.kind, "rom")
            self.assertEqual(restored.name, session.name)


if __name__ == "__main__":
    unittest.main()
