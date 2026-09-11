"""AHDI root sectors, XGM chains, ICD tables, MBRs and byte-swapped images."""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from atarinut.errors import ConfigurationError, DataError
from atarinut.filesystem import (
    AhdiMount,
    create_partitioned_image,
    format_volume,
    identify,
    partition_reader,
    read_partition_table,
    reader_for,
    volume_geometry,
    write_partition_table,
)
from atarinut.filesystem.ahdi import (
    ICD_PARTITIONS,
    ROOT_PARTITIONS,
    plan_layout,
)
from atarinut.filesystem.blocks import (
    SECTOR_SIZE,
    ByteSwappedReader,
    be32_at,
    is_executable_sector,
    swap_bytes,
    word_sum,
)
from atarinut.filesystem.gemdos import parse_boot_sector

MIB = 1024 * 1024

SAMPLES = Path(
    os.environ.get("ATARI_FILE_FORGE_SAMPLES")
    or Path(__file__).resolve().parents[1] / "samples"
)
HDD = SAMPLES / "hdd"


def _sample(name: str) -> Path | None:
    path = HDD / name
    return path if path.is_file() else None


def _entry(sector: bytes, offset: int) -> tuple[int, bytes, int, int]:
    return (
        sector[offset],
        sector[offset + 1:offset + 4],
        be32_at(sector, offset + 4),
        be32_at(sector, offset + 8),
    )


class RootSectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_root_sector_holding_a_loader_is_marked_executable(self) -> None:
        """The mark follows the loader, so a real one still gets one.

        A driver writes its loader into the root sector and then asks for the
        sector to be made executable. That has to keep working: withholding
        the mark from a sector that genuinely boots would leave a prepared
        drive unable to start.
        """
        path = self.tmp / "loader.ahd"
        create_partitioned_image(path, 32 * MIB, [{"label": "SYS"}], bootable=False)
        reader = reader_for(path, writable=True)
        try:
            sector = bytearray(reader.read_block(0))
            # Anything but zeros stands in for a driver's loader here; what
            # matters is that the sector is no longer empty.
            sector[:0x1C2] = b"\x60\x1E" + bytes(0x1C0)
            reader.write_block(0, bytes(sector))
            reader.flush()
            disk = write_partition_table(
                reader,
                [{"label": "SYS", "size_bytes": 8 * MIB, "start_sector": 1}],
                bootable=True,
            )
        finally:
            reader.close()
        self.assertTrue(disk.bootable)
        self.assertTrue(is_executable_sector(path.read_bytes()[:512]))

    def test_an_empty_root_sector_is_never_marked_executable(self) -> None:
        """A machine given zeros to execute halts on a double bus error.

        The ROM runs the root sector when its words sum to 0x1234 and looks no
        further, so the mark on a sector with nothing in it is a promise the
        drive cannot keep: TOS loads the sector, jumps into it, runs off the
        end of the zeros and halts before the desktop appears.
        """
        path = self.tmp / "empty.ahd"
        disk = create_partitioned_image(
            path, 32 * MIB, [{"label": "SYS", "bootable": True}], bootable=True,
        )
        self.assertFalse(disk.bootable)
        root = path.read_bytes()[:512]
        self.assertFalse(is_executable_sector(root))
        # The partition is still flagged, because that is a separate thing:
        # it tells a driver which partition to boot once one is installed.
        self.assertEqual(root[ROOT_PARTITIONS], 0x81)

    def test_root_sector_layout_is_big_endian_and_checksummed(self) -> None:
        path = self.tmp / "hd.ahd"
        disk = create_partitioned_image(
            path,
            32 * MIB,
            [
                {"label": "SYS", "size_bytes": 8 * MIB, "bootable": True},
                {"label": "WORK", "size_bytes": 8 * MIB},
                {"label": "BIG"},
            ],
            bootable=True,
        )
        self.assertEqual(disk.scheme, "ahdi")
        # ``bootable`` asks for a root sector the ROM will execute, and there
        # is no loader in this one to execute. Marking it anyway hands the
        # machine a page of zeros and halts it on a double bus error, so the
        # mark is withheld until a driver writes its loader in.
        self.assertFalse(disk.bootable)
        self.assertFalse(disk.byte_swapped)
        root = path.read_bytes()[:512]
        self.assertNotEqual(word_sum(root), 0x1234)
        self.assertEqual(be32_at(root, 0x1C2), 32 * MIB // SECTOR_SIZE)
        first = _entry(root, ROOT_PARTITIONS)
        self.assertEqual(first, (0x81, b"GEM", 1, 8 * MIB // SECTOR_SIZE))
        second = _entry(root, ROOT_PARTITIONS + 12)
        self.assertEqual(second[:3], (0x01, b"GEM", 1 + 8 * MIB // SECTOR_SIZE))
        third = _entry(root, ROOT_PARTITIONS + 24)
        self.assertEqual(third[1], b"GEM")
        self.assertEqual(third[2] + third[3], 32 * MIB // SECTOR_SIZE)
        self.assertEqual(_entry(root, ROOT_PARTITIONS + 36)[0], 0)
        self.assertEqual(be32_at(root, 0x1F6), 0)
        self.assertEqual(be32_at(root, 0x1FA), 0)
        self.assertEqual([p.name for p in disk.partitions], ["C:", "D:", "E:"])
        self.assertEqual([p.label for p in disk.partitions], ["SYS", "WORK", "BIG"])
        self.assertTrue(disk.partitions[0].bootable)
        self.assertEqual(disk.notes, [])
        row = disk.partitions[0].to_dict()
        self.assertEqual(row["device"], "C:")
        self.assertEqual(row["sizeBytes"], 8 * MIB)
        self.assertEqual(identify(path)[0].filesystem, "ahdi")

        reader = reader_for(path)
        mount = AhdiMount(reader)
        # A table read back from disk carries no labels; they live in the
        # volumes, which is where they are checked.
        self.assertEqual([p.label for p in mount.partitions], ["", "", ""])
        for partition, created in zip(mount.partitions, disk.partitions):
            volume = mount.open_partition(partition.index)
            self.assertEqual(volume.format, "FAT16")
            self.assertEqual(volume.title, created.label)
            self.assertEqual(volume.validate(), [])
            volume.close()
        mount.close()

    def test_not_bootable_root_sector_does_not_sum_to_the_magic(self) -> None:
        path = self.tmp / "hd.ahd"
        disk = create_partitioned_image(path, 8 * MIB, [{"label": "X"}], bootable=False)
        self.assertFalse(disk.bootable)
        self.assertNotEqual(word_sum(path.read_bytes()[:512]), 0x1234)

    def test_xgm_chain_matches_the_kernel_walk(self) -> None:
        path = self.tmp / "five.ahd"
        sizes = [4 * MIB, 4 * MIB, 4 * MIB, 4 * MIB, 4 * MIB]
        disk = create_partitioned_image(
            path, 24 * MIB, [{"label": f"P{index}", "size_bytes": size} for index, size in enumerate(sizes)]
        )
        self.assertEqual(disk.scheme, "xgm")
        self.assertEqual(len(disk.partitions), 5)
        self.assertEqual([p.extended for p in disk.partitions], [False, False, False, True, True])
        raw = path.read_bytes()
        root = raw[:512]
        hd_size = be32_at(root, 0x1C2)
        # Walk the table exactly as block/partitions/atari.c does.
        found = []
        for slot in range(4):
            flag, ident, start, size = _entry(root, ROOT_PARTITIONS + slot * 12)
            if not flag & 1:
                continue
            if ident != b"XGM":
                found.append((start, size))
                continue
            extensect = start
            partsect = start
            while True:
                table = raw[partsect * 512:(partsect + 1) * 512]
                head = _entry(table, ROOT_PARTITIONS)
                self.assertTrue(head[0] & 1)
                self.assertTrue(head[2] + head[3] <= hd_size)
                found.append((partsect + head[2], head[3]))
                link = _entry(table, ROOT_PARTITIONS + 12)
                if not link[0] & 1 or link[1] != b"XGM":
                    break
                partsect = link[2] + extensect
        self.assertEqual(found, [(p.start_sector, p.size_sectors) for p in disk.partitions])
        for earlier, later in zip(disk.partitions, disk.partitions[1:]):
            self.assertLessEqual(earlier.end_sector, later.start_sector)
        reader = reader_for(path, writable=True)
        mount = AhdiMount(reader)
        for partition in mount.partitions:
            volume = mount.open_partition(partition.index, writable=True)
            volume.write_bytes("MARK.TXT", partition.name.encode())
            volume.close()
        for partition in mount.partitions:
            volume = mount.open_partition(partition.index)
            self.assertEqual(volume.read_bytes("MARK.TXT"), partition.name.encode())
            self.assertEqual(volume.title, f"P{partition.index}")
            volume.close()
        mount.close()

    def test_icd_table_holds_more_than_four_entries_flat(self) -> None:
        path = self.tmp / "icd.ahd"
        disk = create_partitioned_image(
            path, 12 * MIB, [{"label": f"I{index}", "size_bytes": 1 * MIB} for index in range(6)], scheme="icd"
        )
        self.assertEqual(disk.scheme, "icd")
        self.assertEqual(len(disk.partitions), 6)
        root = path.read_bytes()[:512]
        self.assertEqual(_entry(root, ICD_PARTITIONS)[1], b"GEM")
        self.assertEqual(_entry(root, ICD_PARTITIONS + 12)[1], b"GEM")
        self.assertEqual(_entry(root, ICD_PARTITIONS + 24)[0], 0)
        reread = read_partition_table(reader_for(path))
        self.assertEqual([p.start_sector for p in reread.partitions], [p.start_sector for p in disk.partitions])
        mount = AhdiMount(reader_for(path))
        volume = mount.open_partition(5)
        self.assertEqual(volume.title, "I5")
        volume.close()
        mount.close()

    def test_mbr_table_is_read_and_written(self) -> None:
        path = self.tmp / "mbr.img"
        disk = create_partitioned_image(
            path, 40 * MIB, [{"label": "C", "size_bytes": 20 * MIB, "bootable": True}, {"label": "D"}], scheme="mbr"
        )
        self.assertEqual(disk.scheme, "mbr")
        self.assertEqual(len(disk.partitions), 2)
        sector = path.read_bytes()[:512]
        self.assertEqual(sector[510:512], b"\x55\xaa")
        self.assertEqual(sector[0x1BE], 0x80)
        self.assertEqual(sector[0x1BE + 4], 0x04)
        self.assertEqual(struct.unpack_from("<I", sector, 0x1BE + 8)[0], 1)
        self.assertEqual(struct.unpack_from("<I", sector, 0x1BE + 12)[0], 20 * MIB // SECTOR_SIZE)
        self.assertEqual(disk.partitions[0].type_code, 0x04)
        self.assertTrue(disk.partitions[0].is_gemdos)
        self.assertTrue(disk.partitions[0].bootable)
        self.assertIn("MBR", identify(path)[0].detail)
        mount = AhdiMount(reader_for(path))
        self.assertEqual(mount.disk.scheme, "mbr")
        volume = mount.open_partition(1)
        self.assertEqual(volume.title, "D")
        self.assertEqual(volume.format, "FAT16")
        volume.close()
        mount.close()

    def test_byte_swapped_image_is_detected_and_read_transparently(self) -> None:
        path = self.tmp / "ide.hd"
        create_partitioned_image(path, 8 * MIB, [{"label": "SWAP", "size_bytes": 4 * MIB}, {"label": "TWO"}])
        mount = AhdiMount(reader_for(path, writable=True))
        volume = mount.open_partition(0, writable=True)
        payload = os.urandom(5001)
        volume.write_bytes("DATA.BIN", payload)
        volume.close()
        mount.close()
        path.write_bytes(swap_bytes(path.read_bytes()))

        candidates = identify(path)
        self.assertEqual(candidates[0].filesystem, "ahdi")
        self.assertIn("byte-swapped", candidates[0].detail)
        mount = AhdiMount(reader_for(path, writable=True))
        self.assertTrue(mount.disk.byte_swapped)
        self.assertTrue(mount.disk.bootable is False)
        self.assertEqual(len(mount.partitions), 2)
        self.assertTrue(mount.partitions[0].byte_swapped)
        window = partition_reader(mount.reader, mount.partitions[0])
        self.assertIsInstance(window, ByteSwappedReader)
        window.close()
        volume = mount.open_partition(0, writable=True)
        self.assertEqual(volume.title, "SWAP")
        self.assertEqual(volume.read_bytes("DATA.BIN"), payload)
        volume.write_bytes("MORE.BIN", b"more data here")
        self.assertEqual(volume.validate(), [])
        volume.close()
        mount.close()

        # Undo the swap and read the second write with a plain reader.
        path.write_bytes(swap_bytes(path.read_bytes()))
        disk = read_partition_table(reader_for(path))
        self.assertFalse(disk.byte_swapped)
        mount = AhdiMount(reader_for(path))
        volume = mount.open_partition(0)
        self.assertEqual(volume.read_bytes("MORE.BIN"), b"more data here")
        self.assertEqual(volume.read_bytes("DATA.BIN"), payload)
        self.assertEqual(volume.validate(), [])
        volume.close()
        mount.close()

    def test_small_partition_is_fat16_regardless_of_cluster_count(self) -> None:
        path = self.tmp / "small.ahd"
        disk = create_partitioned_image(path, 5 * MIB, [{"label": "TINY", "size_bytes": 4 * MIB}])
        mount = AhdiMount(reader_for(path))
        volume = mount.open_partition(0)
        self.assertEqual(volume.format, "FAT16")
        self.assertLess(volume.volume.total_clusters, 4085)
        self.assertEqual(volume.geometry.sector_size, 512)
        volume.close()
        mount.close()
        self.assertEqual(disk.partitions[0].id, "GEM")

    def test_large_partitions_get_bgm_ids_large_sectors_and_notes(self) -> None:
        path = self.tmp / "big.ahd"
        disk = create_partitioned_image(path, 40 * MIB, [{"label": "BIG"}])
        self.assertEqual(disk.partitions[0].id, "BGM")
        self.assertTrue(any("TOS 1.00" in note for note in disk.notes))
        mount = AhdiMount(reader_for(path))
        volume = mount.open_partition(0)
        self.assertEqual(volume.geometry.sector_size, 1024)
        self.assertLessEqual(volume.volume.total_clusters, 32766)
        volume.close()
        mount.close()

    def test_bare_volume_image_is_not_mistaken_for_a_table(self) -> None:
        path = self.tmp / "bare.img"
        size = 16 * MIB
        with path.open("wb") as handle:
            handle.truncate(size)
        reader = reader_for(path, writable=True)
        format_volume(reader, label="BARE", geometry=volume_geometry(size))
        reader.close()
        self.assertEqual([c.filesystem for c in identify(path)], ["gemdos"])
        with self.assertRaises(DataError):
            read_partition_table(reader_for(path))

    def test_layout_validation(self) -> None:
        with self.assertRaises(ConfigurationError):
            plan_layout(100, [{"size_bytes": 200 * SECTOR_SIZE}])
        with self.assertRaises(ConfigurationError):
            plan_layout(100, [])
        path = self.tmp / "overlap.ahd"
        with path.open("wb") as handle:
            handle.truncate(4 * MIB)
        reader = reader_for(path, writable=True)
        with self.assertRaises(ConfigurationError):
            write_partition_table(
                reader,
                [
                    {"id": "GEM", "start_sector": 1, "size_sectors": 100},
                    {"id": "GEM", "start_sector": 50, "size_sectors": 100},
                ],
            )
        with self.assertRaises(ConfigurationError):
            write_partition_table(reader, [{"id": "GEM", "start_sector": 0, "size_sectors": 100}])
        reader.close()

    def test_partition_reader_window_covers_exactly_the_partition(self) -> None:
        path = self.tmp / "win.ahd"
        disk = create_partitioned_image(path, 4 * MIB, [{"label": "A", "size_bytes": MIB}, {"label": "B"}])
        reader = reader_for(path)
        second = partition_reader(reader, disk.partitions[1])
        self.assertEqual(second.offset, disk.partitions[1].start_sector * SECTOR_SIZE)
        self.assertEqual(second.total_blocks, disk.partitions[1].size_sectors)
        boot = parse_boot_sector(second.read_block(0))
        self.assertEqual(boot.total_sectors, disk.partitions[1].size_sectors)
        second.close()
        reader.close()


@unittest.skipUnless(HDD.is_dir(), "sample hard-disk images are not present")
class SampleHardDiskTests(unittest.TestCase):
    def test_acsi_800mb_image_has_four_bgm_primaries(self) -> None:
        path = _sample("petari_acsi_800mb_icd.hd")
        if path is None:
            self.skipTest("sample missing")
        reader = reader_for(path)
        disk = read_partition_table(reader)
        self.assertEqual(disk.scheme, "ahdi")
        self.assertTrue(disk.bootable)
        self.assertFalse(disk.byte_swapped)
        self.assertEqual(disk.hd_size, 1638400)
        self.assertEqual(
            [(p.id, p.start_sector, p.size_sectors, p.flags) for p in disk.partitions],
            [
                ("BGM", 2, 65535, 0x81),
                ("BGM", 65537, 523437, 0x01),
                ("BGM", 588974, 523437, 0x01),
                ("BGM", 1112411, 523437, 0x01),
            ],
        )
        self.assertTrue(disk.partitions[0].bootable)
        self.assertEqual(disk.notes, [])
        mount = AhdiMount(reader)
        first = mount.open_partition(0)
        self.assertEqual(first.format, "FAT16")
        self.assertEqual(first.geometry.sector_size, 2048)
        self.assertIn("ICDBOOT.SYS", [e.name for e in first.iter_entries()])
        self.assertEqual(first.validate(), [])
        first.close()
        second = mount.open_partition(1)
        self.assertEqual(second.geometry.sector_size, 8192)
        self.assertEqual(second.validate(), [])
        second.close()
        mount.close()
        self.assertEqual(identify(path)[0].filesystem, "ahdi")

    def test_ide_1600mb_image_is_byte_swapped_with_an_xgm_chain(self) -> None:
        path = _sample("petari_ide_1600mb_ahdi.hd")
        if path is None:
            self.skipTest("sample missing")
        reader = reader_for(path)
        with reader:
            self.assertFalse(is_executable_sector(reader.read_block(0)))
            self.assertTrue(is_executable_sector(swap_bytes(reader.read_block(0))))
        reader = reader_for(path)
        disk = read_partition_table(reader)
        self.assertTrue(disk.byte_swapped)
        self.assertTrue(disk.bootable)
        self.assertEqual(disk.scheme, "xgm")
        self.assertEqual(disk.hd_size, 3276000)
        self.assertEqual(
            [(p.id, p.start_sector, p.size_sectors, p.extended) for p in disk.partitions],
            [
                ("BGM", 2, 8192, False),
                ("BGM", 8194, 817152, False),
                ("BGM", 825346, 817152, False),
                ("BGM", 1642499, 817151, True),
                ("BGM", 2459651, 815103, True),
            ],
        )
        self.assertEqual(disk.notes, [])
        mount = AhdiMount(reader)
        first = mount.open_partition(0)
        self.assertEqual(first.format, "FAT16")
        self.assertLess(first.volume.total_clusters, 4085)
        self.assertIn("SHDRIVER.SYS", [e.name for e in first.iter_entries()])
        self.assertEqual(first.validate(), [])
        first.close()
        last = mount.open_partition(4)
        self.assertEqual(last.geometry.sector_size, 8192)
        self.assertTrue(list(last.iter_entries()))
        self.assertEqual(last.validate(), [])
        last.close()
        mount.close()
        self.assertIn("byte-swapped", identify(path)[0].detail)

    def test_mbr_images_with_16k_logical_sectors(self) -> None:
        for name in ("zero_to_hero_512mb.img", "falcon_mint_drive0_512mb.img"):
            path = _sample(name)
            if path is None:
                continue
            with self.subTest(sample=name):
                reader = reader_for(path)
                disk = read_partition_table(reader)
                self.assertEqual(disk.scheme, "mbr")
                self.assertFalse(disk.byte_swapped)
                self.assertEqual(len(disk.partitions), 1)
                partition = disk.partitions[0]
                self.assertEqual((partition.type_code, partition.start_sector, partition.size_sectors), (0x06, 1, 1048575))
                self.assertTrue(partition.bootable)
                boot = parse_boot_sector(reader.read_block(1))
                self.assertEqual(
                    (boot.sector_size, boot.sectors_per_cluster, boot.reserved, boot.fats, boot.root_entries,
                     boot.total_sectors, boot.sectors_per_fat),
                    (16384, 2, 1, 2, 512, 32767, 2),
                )
                mount = AhdiMount(reader)
                volume = mount.open_partition(0)
                self.assertEqual(volume.format, "FAT16")
                self.assertEqual(volume.geometry.sector_size, 16384)
                self.assertEqual(volume.title, "BOOT")
                self.assertIn("AUTO", [e.name for e in volume.iter_entries()])
                self.assertTrue(volume.stat("AUTO").is_dir)
                volume.close()
                mount.close()
                self.assertEqual(identify(path)[0].filesystem, "ahdi")


if __name__ == "__main__":
    unittest.main()
