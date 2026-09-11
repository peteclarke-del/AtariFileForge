"""A hard drive addressed through the partition table it declares.

An ACSI, SCSI or IDE drive prepared for TOS keeps its table in the root
sector. AHDI writes up to four entries there, XGM chains a further table so a
drive can carry more, ICD's driver adds eight lower in the same sector, and a
drive prepared on a PC carries an ordinary MBR that TOS 4 and MiNT both mount.
Opening one therefore means reading that table, choosing a partition, and
mounting it as the ordinary GEMDOS volume it is.

An IDE drive imaged through a byte-swapping adapter has every sector's byte
pairs reversed. The engine reads through the swap and the flag surfaces in the
table, which is what tells a person why the image looks wrong in a hex editor
and right in the workbench.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atarinut.filesystem.blocks import swap_bytes
from app.disk_service import DiskService
from app.errors import DiskError


MIB = 1024 * 1024


class PartitionedDriveTests(unittest.TestCase):
    def test_a_new_drive_reports_the_ahdi_table_it_was_built_with(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            drive = service.create_blank("hd", "TESTHDD", "32MB")
            self.assertEqual(drive.kind, "hd")

            table = service.partition_table(drive)
            self.assertEqual(table["scheme"], "ahdi")
            self.assertFalse(table["byteSwapped"])
            # A blank drive carries no boot loader, so its root sector is not
            # one the ROM will execute. Preparing the drive with a driver is
            # what writes a loader and marks it.
            self.assertFalse(table["bootable"])
            self.assertEqual(table["sizeBytes"], 32 * MIB)
            self.assertEqual(table["hdSize"], 32 * MIB // 512)
            self.assertEqual(len(table["partitions"]), 4)

            rows = service.list_partitions(drive)
            self.assertEqual([row["device"] for row in rows], ["C:", "D:", "E:", "F:"])
            self.assertEqual([row["id"] for row in rows], ["GEM"] * 4)
            # A partition reached through a table is FAT16 whatever its
            # cluster count, because that is what the driver's own parameter
            # block declares and what TOS obeys.
            self.assertEqual([row["format"] for row in rows], ["FAT16"] * 4)
            self.assertEqual([row["gemdos"] for row in rows], [True] * 4)
            self.assertTrue(rows[0]["bootable"])
            self.assertFalse(any(row["bootable"] for row in rows[1:]))
            # Every partition sits inside the drive and after the one before.
            self.assertGreaterEqual(rows[0]["startSector"], 1)
            for earlier, later in zip(rows, rows[1:]):
                self.assertLessEqual(
                    earlier["startSector"] + earlier["sizeSectors"],
                    later["startSector"],
                )

            offered = {row["format"] for row in service.export_formats(drive)}
            self.assertEqual(offered, {"native"})

    def test_selecting_a_partition_mounts_it_as_a_gemdos_volume(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            drive = service.create_blank("hd", "TESTHDD", "32MB")

            # A drive that has just been opened falls back to the first
            # partition, which is what TOS does when it boots from C:.
            self.assertEqual(service.selected_partition(drive), 0)
            self.assertEqual(service.partition_label(drive), "C:")

            self.assertEqual(service.select_partition(drive, 1), 1)
            self.assertEqual(service.selected_partition(drive), 1)
            self.assertEqual(service.partition_label(drive), "D:")

            payload = b"Atari File Forge partition fixture\n"
            source = root / "TEST.DAT"
            source.write_bytes(payload)
            service.put(drive, "TEST.DAT", source)
            with service.partition_mount(drive, writable=False) as mount:
                self.assertEqual(mount.format, "FAT16")
                self.assertEqual(mount.read_bytes("TEST.DAT"), payload)

            # The file went into D: alone; C: is a separate filesystem.
            service.select_partition(drive, 0)
            with service.gemdos_mount(drive, writable=False) as mount:
                self.assertFalse(mount.exists("TEST.DAT"))

            with self.assertRaisesRegex(DiskError, "4 partition"):
                service.select_partition(drive, 9)

            # Clearing the selection puts the pane back on the table itself,
            # which is not a volume and cannot be written into.
            self.assertIsNone(service.select_partition(drive, None))
            self.assertFalse(service.mountable(drive))
            with self.assertRaisesRegex(DiskError, "Choose a partition"):
                with service.gemdos_mount(drive):
                    pass

    def test_an_mbr_drive_is_read_through_the_same_table(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            drive = service.create_blank(
                "hd", "MBRDISK", "40MB", options={"scheme": "mbr", "partitions": 2}
            )

            table = service.partition_table(drive)
            self.assertEqual(table["scheme"], "mbr")
            self.assertEqual(len(table["partitions"]), 2)
            rows = service.list_partitions(drive)
            # 0x04 is the small FAT16 type code TOS 4 and MiNT mount.
            self.assertEqual([row["typeCode"] for row in rows], [0x04, 0x04])
            self.assertEqual([row["gemdos"] for row in rows], [True, True])

            service.select_partition(drive, 1)
            with service.partition_mount(drive, writable=False) as mount:
                self.assertEqual(mount.format, "FAT16")
                self.assertEqual(mount.title, "MBRDISK1")

    def test_a_byte_swapped_image_is_read_through_the_swap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            drive = service.create_blank("hd", "SWAPPED", "16MB")
            payload = b"written before the adapter reversed every byte pair\n"
            source = root / "DATA.BIN"
            source.write_bytes(payload)
            service.put(drive, "DATA.BIN", source)

            drive.path.write_bytes(swap_bytes(drive.path.read_bytes()))
            reopened = service.create_from_path(drive.path)
            self.assertEqual(reopened.kind, "hd")

            table = service.partition_table(reopened)
            self.assertTrue(table["byteSwapped"])
            self.assertTrue(all(row["byteSwapped"] for row in table["partitions"]))
            self.assertEqual(table["scheme"], "ahdi")

            service.select_partition(reopened, 0)
            with service.partition_mount(reopened, writable=False) as mount:
                self.assertEqual(mount.read_bytes("DATA.BIN"), payload)

    def test_a_floppy_has_no_partition_table(self) -> None:
        """Neither reading a table nor choosing from one applies to a floppy."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            floppy = service.create_blank("ds-720k", "GAMES")
            self.assertEqual(floppy.kind, "gemdos")

            with self.assertRaisesRegex(DiskError, "not a partitioned hard disk"):
                service.partition_table(floppy)
            with self.assertRaisesRegex(DiskError, "not a partitioned hard disk"):
                service.select_partition(floppy, 0)
            self.assertEqual(service.partition_label(floppy), "")

            offered = {row["format"] for row in service.export_formats(floppy)}
            self.assertEqual(offered & {"msa", "dim"}, {"msa", "dim"})


if __name__ == "__main__":
    unittest.main()
