"""The GEMDOS engine: boot sectors, FATs, directories and the TOS rules."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from atarinut.errors import ConfigurationError, DataError
from atarinut.file import (
    Access,
    AtariMeta,
    datetime_to_fat,
    fat_to_datetime,
    format_access_text,
    parse_access_text,
)
from atarinut.file.filetypes import classify, classify_name, detect_content_type
from atarinut.filesystem import (
    GEMDOSMount,
    create_filesystem,
    format_volume,
    geometry_from_bpb,
    identify,
    reader_for,
)
from atarinut.filesystem.blocks import (
    NAMED_GEOMETRIES,
    SECTOR_SIZE,
    Geometry,
    is_executable_sector,
    le16_at,
    named_geometry,
    partition_geometry,
    volume_geometry,
    word_sum,
)
from atarinut.filesystem.gemdos import (
    GEMDOSVolume,
    bpb_problems,
    build_boot_sector,
    join_path,
    parse_boot_sector,
    split_path,
    tos_limit_notes,
    validate_name,
)

MKFS = shutil.which("mkfs.fat") or ("/usr/sbin/mkfs.fat" if Path("/usr/sbin/mkfs.fat").exists() else None)
FSCK = shutil.which("fsck.fat") or ("/usr/sbin/fsck.fat" if Path("/usr/sbin/fsck.fat").exists() else None)

SAMPLES = Path(
    os.environ.get("ATARI_FILE_FORGE_SAMPLES")
    or Path(__file__).resolve().parents[1] / "samples"
)
FLOPPY_SAMPLES = sorted(SAMPLES.glob("floppies/*.st")) if SAMPLES.is_dir() else []


def make_image(directory: Path, name: str = "ds-720k", label: str = "TEST") -> Path:
    geometry = named_geometry(name)
    path = directory / f"{name}.st"
    path.write_bytes(b"\0" * (geometry.physical_sectors * SECTOR_SIZE))
    reader = reader_for(path, writable=True)
    try:
        format_volume(reader, label=label, geometry=geometry)
    finally:
        reader.close()
    return path


def open_volume(path: Path, *, writable: bool = False) -> GEMDOSVolume:
    return GEMDOSVolume(reader_for(path, writable=writable))


class GeometryTests(unittest.TestCase):
    def test_named_floppy_geometries_match_what_tos_formats(self) -> None:
        for name, geometry in NAMED_GEOMETRIES.items():
            with self.subTest(name=name):
                self.assertEqual(geometry.sector_size, 512)
                self.assertEqual(geometry.sectors_per_cluster, 2)
                self.assertEqual(geometry.reserved, 1)
                self.assertEqual(geometry.fats, 2)
                self.assertEqual(geometry.fat_bits, 12)
                geometry.check()
        ds = NAMED_GEOMETRIES["ds-720k"]
        self.assertEqual((ds.tracks, ds.sides, ds.sectors_per_track), (80, 2, 9))
        self.assertEqual(ds.total_sectors, 1440)
        self.assertEqual(ds.sectors_per_fat, 5)
        self.assertEqual(ds.root_entries, 112)
        self.assertEqual(ds.media, 0xF9)
        self.assertEqual(NAMED_GEOMETRIES["ds-800k"].sectors_per_fat, 5)
        self.assertEqual(NAMED_GEOMETRIES["ds-880k"].total_sectors, 1760)
        ss = NAMED_GEOMETRIES["ss-360k"]
        self.assertEqual((ss.tracks, ss.sides, ss.sectors_per_track), (80, 1, 9))
        self.assertEqual(ss.media, 0xF8)
        self.assertEqual(ss.sectors_per_fat, 2)
        hd = NAMED_GEOMETRIES["hd-1440k"]
        self.assertEqual((hd.tracks, hd.sides, hd.sectors_per_track), (80, 2, 18))
        self.assertEqual(hd.root_entries, 224)
        self.assertEqual(hd.total_sectors, 2880)
        self.assertEqual(NAMED_GEOMETRIES["ds-880k-83"].total_sectors, 83 * 2 * 11)

    def test_boot_sector_fields_are_little_endian(self) -> None:
        boot = build_boot_sector(named_geometry("ds-720k"), serial=0x123456, oem="Loader")
        self.assertEqual(boot[0x02:0x08], b"Loader")
        self.assertEqual(boot[0x08:0x0B], b"\x12\x34\x56")
        self.assertEqual(boot[0x0B:0x0D], b"\x00\x02")  # 512 as LE
        self.assertEqual(boot[0x0D], 2)
        self.assertEqual(boot[0x0E:0x10], b"\x01\x00")
        self.assertEqual(boot[0x10], 2)
        self.assertEqual(boot[0x11:0x13], b"\x70\x00")  # 112
        self.assertEqual(boot[0x13:0x15], b"\xa0\x05")  # 1440
        self.assertEqual(boot[0x15], 0xF9)
        self.assertEqual(boot[0x16:0x18], b"\x05\x00")
        self.assertEqual(boot[0x18:0x1A], b"\x09\x00")
        self.assertEqual(boot[0x1A:0x1C], b"\x02\x00")
        parsed = parse_boot_sector(boot)
        self.assertEqual(parsed.geometry().to_dict(), named_geometry("ds-720k").to_dict())
        self.assertEqual(bpb_problems(parsed, 1440), [])

    def test_boot_checksum_word_makes_the_sector_executable(self) -> None:
        plain = build_boot_sector(named_geometry("ds-720k"), serial=1, executable=False)
        self.assertNotEqual(word_sum(plain), 0x1234)
        self.assertFalse(is_executable_sector(plain))
        bootable = build_boot_sector(named_geometry("ds-720k"), serial=1, executable=True)
        self.assertEqual(word_sum(bootable), 0x1234)
        self.assertTrue(is_executable_sector(bootable))
        self.assertEqual(bootable[:0x1FE], plain[:0x1FE])

    def test_bpb_plausibility_rejects_garbage_and_accepts_lax_formatters(self) -> None:
        zeros = parse_boot_sector(bytes(512))
        self.assertTrue(bpb_problems(zeros, 1440))
        odd = bytearray(build_boot_sector(named_geometry("ds-720k")))
        odd[0:2] = b"\0\0"      # no jump
        odd[0x15] = 0           # no media byte
        self.assertEqual(bpb_problems(parse_boot_sector(bytes(odd)), 1440), [])
        with self.assertRaises(DataError):
            geometry_from_bpb(bytes(512))

    def test_partition_geometry_follows_the_driver_rule(self) -> None:
        mib = 1024 * 1024
        cases = {
            4 * mib: (512, 16),
            8 * mib: (512, 16),
            33 * mib: (1024, 16),
            100 * mib: (2048, 16),
            255 * mib: (4096, 16),
            400 * mib: (8192, 16),
            512 * mib: (16384, 16),
        }
        for size, (sector_size, fat_bits) in cases.items():
            with self.subTest(size=size // mib):
                geometry = partition_geometry(size // SECTOR_SIZE)
                self.assertEqual(geometry.sector_size, sector_size)
                self.assertEqual(geometry.sectors_per_cluster, 2)
                self.assertEqual(geometry.fat_bits, fat_bits)
                self.assertLessEqual(geometry.data_clusters, 32766)
                geometry.check()
        self.assertLess(partition_geometry(4 * mib // SECTOR_SIZE).data_clusters, 4085)

    def test_tos_limit_notes(self) -> None:
        mib = 1024 * 1024
        self.assertEqual(tos_limit_notes(8 * mib), [])
        self.assertEqual(len(tos_limit_notes(20 * mib)), 1)
        self.assertIn("TOS 1.00", tos_limit_notes(20 * mib)[0])
        self.assertEqual(len(tos_limit_notes(300 * mib)), 2)
        self.assertEqual(len(tos_limit_notes(600 * mib)), 4)


class PathAndNameTests(unittest.TestCase):
    def test_split_path_accepts_both_separators_and_drive_letters(self) -> None:
        self.assertEqual(split_path("C:\\AUTO\\FOO.PRG"), ["AUTO", "FOO.PRG"])
        self.assertEqual(split_path("AUTO/FOO.PRG"), ["AUTO", "FOO.PRG"])
        self.assertEqual(split_path("\\AUTO\\.\\FOO.PRG"), ["AUTO", "FOO.PRG"])
        self.assertEqual(split_path("AUTO\\..\\FOO.PRG"), ["FOO.PRG"])
        for root in ("", "\\", "/", "C:\\", ":", None):
            self.assertEqual(split_path(root), [])
        self.assertEqual(join_path(["AUTO", "FOO.PRG"]), "AUTO\\FOO.PRG")

    def test_validate_name_enforces_8_3_and_forbidden_characters(self) -> None:
        self.assertEqual(validate_name("foo.prg"), "FOO.PRG")
        self.assertEqual(validate_name("README"), "README")
        self.assertEqual(validate_name("NAME."), "NAME")
        for bad, fragment in (
            ("TOOLONGNAME.TXT", "eight"),
            ("A.TOOLONG", "three"),
            ("BAD NAME", "space"),
            ("A/B", "/"),
            ("A.B.C", "more than one"),
            (".PRG", "before the full stop"),
            ("", "empty"),
            ("..", "reserved"),
            ("A*B", "*"),
        ):
            with self.subTest(name=bad):
                with self.assertRaises(DataError) as caught:
                    validate_name(bad)
                self.assertIn(fragment, str(caught.exception))


class AccessTests(unittest.TestCase):
    def test_access_text_round_trips(self) -> None:
        self.assertEqual(format_access_text(Access.ARCHIVE), "-----a")
        self.assertEqual(format_access_text(Access.READ_ONLY | Access.ARCHIVE), "r----a")
        self.assertEqual(format_access_text(Access.DIRECTORY), "----d-")
        self.assertEqual(parse_access_text("r----a"), Access.READ_ONLY | Access.ARCHIVE)
        self.assertEqual(parse_access_text("R----A"), Access.READ_ONLY | Access.ARCHIVE)
        self.assertEqual(parse_access_text("rh"), Access.READ_ONLY | Access.HIDDEN | Access.ARCHIVE)
        self.assertEqual(parse_access_text("0x21"), Access.READ_ONLY | Access.ARCHIVE)
        self.assertEqual(parse_access_text("33"), Access.READ_ONLY | Access.ARCHIVE)
        self.assertEqual(parse_access_text("$01"), Access.READ_ONLY)
        self.assertEqual(parse_access_text(""), Access.ARCHIVE)
        self.assertTrue(Access.READ_ONLY.locked)
        self.assertTrue(Access.ARCHIVE.readable)
        self.assertFalse(Access.READ_ONLY.writable)
        self.assertEqual(Access.ARCHIVE.with_locked(True), Access.READ_ONLY | Access.ARCHIVE)
        with self.assertRaises(DataError):
            parse_access_text("xyz")

    def test_fat_datestamps_have_two_second_resolution_and_a_1980_floor(self) -> None:
        moment = datetime(1999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
        date_word, time_word = datetime_to_fat(moment)
        self.assertEqual(date_word >> 9, 19)
        self.assertEqual(fat_to_datetime(date_word, time_word), moment.replace(second=58))
        self.assertIsNone(fat_to_datetime(0, 0))
        early = datetime_to_fat(datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(fat_to_datetime(*early).year, 1980)
        late = datetime_to_fat(datetime(2200, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(fat_to_datetime(*late).year, 2107)


class FiletypeTests(unittest.TestCase):
    def test_extension_and_content_classification(self) -> None:
        self.assertEqual(classify_name("AUTO\\FOO.PRG"), "executable")
        self.assertEqual(classify_name("DESKTOP.INF"), "configuration")
        self.assertEqual(classify_name("PIC.PI1"), "picture")
        self.assertEqual(classify_name("GAME.ZIP"), "archive")
        self.assertIsNone(classify_name("NOEXT"))
        header = b"\x60\x1a" + (10).to_bytes(4, "big") + bytes(4) * 3 + bytes(4) + bytes(4) + bytes(2)
        self.assertEqual(detect_content_type(header + bytes(10)), "executable")
        self.assertIsNone(detect_content_type(header))  # text does not fit
        degas = b"\x00\x00" + bytes(32032)
        self.assertEqual(detect_content_type(degas), "picture")
        self.assertEqual(detect_content_type(b"\x00\x01" + bytes(32032)), "picture")
        self.assertIsNone(detect_content_type(b"\x00\x05" + bytes(32032)))
        self.assertEqual(detect_content_type(b"\x00\x10" + b"Lionpoubnk" + bytes(40)), "basic")
        self.assertEqual(classify("X.DAT", header + bytes(10)), "executable")
        self.assertEqual(classify("X.TXT", b"hello"), "text")


class VolumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip_on_every_named_geometry(self) -> None:
        payloads = {
            "AUTO\\SUB\\BIG.DAT": os.urandom(70000),
            "AUTO\\SUB\\ODD.BIN": os.urandom(1025),
            "HELLO.TXT": b"hello world",
            "EMPTY.TXT": b"",
            "ONE.DAT": os.urandom(1024),
        }
        for name in NAMED_GEOMETRIES:
            with self.subTest(geometry=name):
                path = make_image(self.tmp, name)
                volume = open_volume(path, writable=True)
                volume.mkdir("AUTO")
                volume.mkdir("AUTO\\SUB")
                for inner, data in payloads.items():
                    volume.write_bytes(inner, data)
                volume.close()

                volume = open_volume(path)
                self.assertEqual(volume.title, "TEST")
                self.assertEqual(volume.format, "FAT12")
                self.assertEqual(
                    sorted(entry.name for entry in volume.iter_entries("")),
                    ["AUTO", "EMPTY.TXT", "HELLO.TXT", "ONE.DAT"],
                )
                self.assertEqual(
                    sorted(entry.path for entry in volume.iter_entries("AUTO\\SUB")),
                    ["AUTO\\SUB\\BIG.DAT", "AUTO\\SUB\\ODD.BIN"],
                )
                for inner, data in payloads.items():
                    self.assertEqual(volume.read_bytes(inner), data)
                    self.assertEqual(volume.read_bytes(inner.lower().replace("\\", "/")), data)
                self.assertEqual(volume.validate(), [])
                self.assertEqual(volume.stat("AUTO\\SUB\\BIG.DAT").blocks, 69)
                self.assertEqual(volume.stat("EMPTY.TXT").block, 0)
                candidates = identify(path)
                self.assertEqual(candidates[0].filesystem, "gemdos")
                self.assertEqual(candidates[0].confidence, 1.0)
                volume.close()

    def test_both_fats_are_written_and_markers_are_set(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.write_bytes("A.TXT", b"x" * 5000)
        volume.close()
        raw = path.read_bytes()
        fat1 = raw[512:512 + 5 * 512]
        fat2 = raw[512 + 5 * 512:512 + 10 * 512]
        self.assertEqual(fat1, fat2)
        self.assertEqual(fat1[:3], b"\xf9\xff\xff")
        self.assertNotEqual(fat1[3:6], bytes(3))

    def test_names_are_stored_upper_case_and_matched_case_insensitively(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.write_bytes("hello.txt", b"1")
        self.assertEqual([entry.name for entry in volume.iter_entries()], ["HELLO.TXT"])
        self.assertTrue(volume.exists("Hello.TXT"))
        volume.write_bytes("HELLO.TXT", b"22")
        self.assertEqual(len(list(volume.iter_entries())), 1)
        self.assertEqual(volume.read_bytes("hello.txt"), b"22")
        with self.assertRaises(DataError):
            volume.write_bytes("this name is too long.txt", b"")
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_attributes_datestamps_and_read_only_deletion(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.write_bytes("A.TXT", b"a")
        self.assertEqual(format_access_text(volume.access("A.TXT")), "-----a")
        volume.set_access("A.TXT", Access.READ_ONLY | Access.ARCHIVE)
        self.assertEqual(format_access_text(volume.access("A.TXT")), "r----a")
        with self.assertRaises(DataError):
            volume.remove("A.TXT")
        moment = datetime(1992, 6, 15, 12, 30, 31, tzinfo=timezone.utc)
        volume.set_datestamp("A.TXT", moment)
        self.assertEqual(volume.datestamp("A.TXT"), moment.replace(second=30))
        meta = volume.atari_meta("A.TXT")
        self.assertEqual(meta, AtariMeta(attributes=0x21, datestamp=moment.replace(second=30)))
        volume.set_access("A.TXT", volume.access("A.TXT").with_locked(False))
        volume.remove("A.TXT")
        self.assertFalse(volume.exists("A.TXT"))
        volume.write_bytes("B.TXT", b"b", AtariMeta(attributes=Access.HIDDEN | Access.ARCHIVE, datestamp=moment))
        self.assertEqual(format_access_text(volume.access("B.TXT")), "-h---a")
        self.assertEqual(volume.datestamp("B.TXT"), moment.replace(second=30))
        volume.mkdir("D")
        self.assertEqual(format_access_text(volume.access("D")), "----d-")
        volume.set_access("D", Access.HIDDEN)
        self.assertEqual(format_access_text(volume.access("D")), "-h--d-")
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_volume_label_and_boot_option(self) -> None:
        path = make_image(self.tmp, label="")
        volume = open_volume(path, writable=True)
        self.assertEqual(volume.title, "")
        volume.set_title("mydisk")
        self.assertEqual(volume.title, "MYDISK")
        self.assertNotIn("MYDISK", [entry.name for entry in volume.iter_entries()])
        volume.set_title("GAMES.ST")
        self.assertEqual(volume.title, "GAMES.ST")
        volume.set_title("")
        self.assertEqual(volume.title, "")
        with self.assertRaises(DataError):
            volume.set_title("TWELVECHARSX")
        self.assertEqual(volume.boot_option(), 0)
        volume.set_boot_option(1)
        self.assertEqual(volume.boot_option(), 1)
        self.assertTrue(is_executable_sector(path.read_bytes()[:512]))
        volume.set_boot_option(0)
        self.assertEqual(volume.boot_option(), 0)
        with self.assertRaises(ConfigurationError):
            volume.set_boot_option(2)
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_rename_move_and_directory_parent_links(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.mkdir("ONE")
        volume.mkdir("TWO")
        volume.write_bytes("ONE\\A.TXT", b"a")
        volume.rename("ONE\\A.TXT", "ONE\\B.TXT")
        self.assertEqual([entry.name for entry in volume.iter_entries("ONE")], ["B.TXT"])
        volume.rename("ONE\\B.TXT", "TWO\\C.TXT")
        self.assertEqual(list(volume.iter_entries("ONE")), [])
        self.assertEqual(volume.read_bytes("TWO\\C.TXT"), b"a")
        volume.rename("TWO", "ONE\\INNER")
        self.assertEqual(volume.read_bytes("ONE\\INNER\\C.TXT"), b"a")
        with self.assertRaises(DataError):
            volume.rename("ONE", "ONE\\INNER\\LOOP")
        with self.assertRaises(DataError):
            volume.rename("ONE\\INNER\\C.TXT", "ONE\\INNER\\C.TXT\\X")
        self.assertEqual(volume.validate(), [])
        volume.remove("ONE", recursive=True)
        self.assertEqual(list(volume.iter_entries()), [])
        self.assertEqual(volume.free_bytes(), volume.size_bytes())
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_a_full_volume_raises_before_any_entry_is_written(self) -> None:
        path = make_image(self.tmp, "ss-360k")
        volume = open_volume(path, writable=True)
        volume.write_bytes("FILL.DAT", b"\xaa" * (volume.free_bytes() - 2048))
        self.assertEqual(volume.free_bytes(), 2048)
        with self.assertRaises(DataError) as caught:
            volume.write_bytes("TOOBIG.DAT", b"\xbb" * 4096)
        self.assertIn("free", str(caught.exception))
        self.assertEqual([entry.name for entry in volume.iter_entries()], ["FILL.DAT"])
        self.assertEqual(volume.free_bytes(), 2048)
        self.assertEqual(volume.validate(), [])
        # Replacing the big file with a bigger one reuses its own clusters.
        volume.write_bytes("FILL.DAT", b"\xcc" * (volume.size_bytes() - 1024))
        self.assertEqual(volume.free_bytes(), 1024)
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_root_directory_limit_and_growing_subdirectories(self) -> None:
        path = make_image(self.tmp, "ss-360k", label="")
        volume = open_volume(path, writable=True)
        for index in range(112):
            volume.write_bytes(f"F{index:03d}", b"")
        with self.assertRaises(DataError) as caught:
            volume.write_bytes("ONEMORE", b"")
        self.assertIn("root directory is full", str(caught.exception))
        volume.remove("F000")
        volume.mkdir("SUB")
        for index in range(70):
            volume.write_bytes(f"SUB\\S{index:03d}.TXT", b"x")
        self.assertEqual(len(list(volume.iter_entries("SUB"))), 70)
        self.assertEqual(volume.stat("SUB").blocks, 3)
        self.assertEqual(volume.validate(), [])
        volume.close()

    def test_defragment_rewrites_fragmented_files_contiguously(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.write_bytes("A.DAT", b"a" * 1024)
        volume.write_bytes("B.DAT", b"b" * 1024)
        volume.write_bytes("C.DAT", b"c" * 1024)
        volume.remove("B.DAT")
        payload = os.urandom(2048)
        volume.write_bytes("D.DAT", payload)
        chain = volume._chain(volume.stat("D.DAT").block)
        self.assertNotEqual(chain[1], chain[0] + 1)
        self.assertEqual(volume.defragment(), 2)
        chain = volume._chain(volume.stat("D.DAT").block)
        self.assertEqual(chain[1], chain[0] + 1)
        self.assertEqual(volume.read_bytes("D.DAT"), payload)
        self.assertEqual(volume.defragment(), 0)
        self.assertEqual(volume.validate(), [])
        free_map = volume.free_map()
        self.assertEqual(len(free_map), volume.total_clusters)
        self.assertEqual(free_map.count(False), 4)
        volume.close()

    def test_validate_reports_cross_links_lost_clusters_and_size_mismatch(self) -> None:
        path = make_image(self.tmp)
        volume = open_volume(path, writable=True)
        volume.write_bytes("A.DAT", b"a" * 3000)
        volume.write_bytes("B.DAT", b"b" * 3000)
        first_b = volume.stat("B.DAT").block
        # Point A's second cluster at B's chain, and orphan the rest.
        chain_a = volume._chain(volume.stat("A.DAT").block)
        volume._fat_set(chain_a[0], first_b)
        volume._store_fat()
        problems = volume.validate()
        self.assertTrue(any("claimed by both" in problem for problem in problems))
        self.assertTrue(any("belong to no file" in problem for problem in problems))
        self.assertTrue(any("declares" in problem for problem in problems))
        volume.close()
        # Diverging FAT copies are reported too.
        raw = bytearray(path.read_bytes())
        raw[512 + 5 * 512 + 6] ^= 0xFF
        path.write_bytes(bytes(raw))
        volume = open_volume(path)
        self.assertTrue(any("FAT copy 2" in problem for problem in volume.validate()))
        volume.close()

    def test_mount_wrapper_and_path_nodes(self) -> None:
        path = make_image(self.tmp)
        mount = create_filesystem("gemdos").open(reader_for(path, writable=True))
        self.assertIsInstance(mount, GEMDOSMount)
        mount.make_directory("A\\B\\C", parents=True)
        node = mount._navigate("A\\B\\C")
        self.assertTrue(node.is_dir)
        self.assertFalse(node.supports_title)
        self.assertEqual(node.title, "C")
        with self.assertRaises(DataError):
            node.set_title("X")
        root = mount._navigate("")
        root.set_title("LABEL")
        self.assertEqual(mount.title, "LABEL")
        mount.write_bytes("A\\B\\C\\F.PRG", b"\x60\x1a" + bytes(30))
        self.assertEqual(mount.filetype("A\\B\\C\\F.PRG"), "executable")
        mount.set_access("A\\B\\C\\F.PRG", Access.READ_ONLY)
        mount.remove("A", force=True)
        self.assertFalse(mount.exists("A"))
        self.assertEqual(mount.validate(), [])
        mount.close()

    def test_bare_hard_disk_volume_is_fat16_with_large_logical_sectors(self) -> None:
        size = 40 * 1024 * 1024
        path = self.tmp / "bare.img"
        with path.open("wb") as handle:
            handle.truncate(size)
        reader = reader_for(path, writable=True)
        try:
            volume = format_volume(reader, label="HARD", geometry=volume_geometry(size))
            self.assertEqual(volume.format, "FAT16")
            self.assertEqual(volume.geometry.sector_size, 1024)
            self.assertEqual(len(volume.notes), 1)
            self.assertIn("TOS 1.00", volume.notes[0])
            payload = os.urandom(3 * 1024 * 1024 + 7)
            volume.mkdir("AUTO")
            volume.write_bytes("AUTO\\BIG.PRG", payload)
            self.assertEqual(volume.read_bytes("AUTO\\BIG.PRG"), payload)
            self.assertEqual(volume.validate(), [])
        finally:
            reader.close()
        candidates = identify(path)
        self.assertEqual(candidates[0].filesystem, "gemdos")
        self.assertIn("FAT16", candidates[0].detail)
        reader = reader_for(path)
        volume = GEMDOSVolume(reader)
        self.assertEqual(volume.read_bytes("AUTO\\BIG.PRG"), payload)
        reader.close()

    def test_small_partition_dump_with_big_sectors_is_detected_as_fat16(self) -> None:
        # A 4 MiB partition has fewer than 4085 clusters, which the floppy
        # rule would call FAT12. Dumped on its own with hard-disk sectors and
        # 16-bit FAT markers it must still open as the FAT16 volume it is.
        sectors = 4 * 1024 * 1024 // SECTOR_SIZE
        geometry = partition_geometry(sectors)
        geometry.sector_size = 1024
        geometry.total_sectors = sectors // 2
        geometry.sectors_per_fat = 8
        path = self.tmp / "small.img"
        with path.open("wb") as handle:
            handle.truncate(sectors * SECTOR_SIZE)
        reader = reader_for(path, writable=True)
        try:
            volume = format_volume(reader, geometry=geometry)
            self.assertEqual(volume.format, "FAT16")
            self.assertLess(volume.total_clusters, 4085)
            volume.write_bytes("X.TXT", b"x")
        finally:
            reader.close()
        reader = reader_for(path)
        volume = GEMDOSVolume(reader)
        self.assertEqual(volume.format, "FAT16")
        self.assertEqual(volume.read_bytes("X.TXT"), b"x")
        reader.close()

    def test_probe_rejects_a_plausible_bpb_over_a_garbage_root(self) -> None:
        path = make_image(self.tmp)
        raw = bytearray(path.read_bytes())
        root_start = (1 + 2 * 5) * 512
        raw[root_start:root_start + 7 * 512] = os.urandom(7 * 512)
        path.write_bytes(bytes(raw))
        candidates = identify(path)
        self.assertTrue(candidates)
        self.assertLessEqual(candidates[0].confidence, 0.4)

    def test_geometry_dataclass_rejects_impossible_layouts(self) -> None:
        with self.assertRaises(ConfigurationError):
            Geometry(sector_size=256).check()
        with self.assertRaises(ConfigurationError):
            Geometry(sectors_per_fat=1, total_sectors=1440).check()


@unittest.skipUnless(MKFS and FSCK, "dosfstools is not installed")
class DosfstoolsCrossCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    #: fsck.fat 4.2 wants a PC-style label field at 0x2B of the boot sector,
    #: which a TOS boot sector never carries. Those remarks are the only
    #: thing it may say about a volume this engine wrote.
    _LABEL_NOISE = re.compile(
        r"^(Label '.*' stored in boot sector is not valid\.|"
        r"There is no label in boot sector.*|Volume label '.*' stored in root directory.*|"
        r"  Auto-(removing|copying) (volume )?label.*)$"
    )
    _TROUBLE = re.compile(
        r"differ|wrong|bad |invalid|truncat|orphan|not consistent|reclaim|unable|expected|"
        r"drop|remov|free cluster summary|cross|loop|contains a free cluster|unexpected|error",
        re.IGNORECASE,
    )

    def _fsck(self, path: Path) -> tuple[int, str]:
        result = subprocess.run([FSCK, "-n", "-v", str(path)], capture_output=True)
        return result.returncode, (result.stdout + result.stderr).decode("latin-1")

    def _assert_clean(self, code: int, output: str) -> None:
        lines = [line for line in output.splitlines() if not self._LABEL_NOISE.match(line)]
        troubles = [line for line in lines if self._TROUBLE.search(line)]
        self.assertEqual(troubles, [], output)
        self.assertIn(code, (0, 1), output)
        if code == 1:
            self.assertTrue(any(self._LABEL_NOISE.match(line) for line in output.splitlines()), output)

    def test_mkfs_fat_volume_is_read_with_matching_free_space(self) -> None:
        path = self.tmp / "mk.img"
        subprocess.run(
            [MKFS, "-F", "12", "-S", "512", "-s", "2", "-r", "112", "-f", "2", "-C", str(path), "720"],
            check=True,
            capture_output=True,
        )
        code, output = self._fsck(path)
        self._assert_clean(code, output)
        clusters = int(re.search(r"(\d+) data clusters", output).group(1))
        used, total = map(int, re.search(r"(\d+)/(\d+) clusters", output).groups())
        self.assertEqual(total, clusters)
        volume = open_volume(path)
        self.assertEqual(volume.format, "FAT12")
        self.assertEqual(volume.total_clusters, total)
        self.assertEqual(volume.free_bytes(), (total - used) * 1024)
        self.assertEqual(list(volume.iter_entries()), [])
        self.assertEqual(volume.validate(), [])
        volume.close()
        self.assertEqual(identify(path)[0].confidence, 1.0)

        volume = open_volume(path, writable=True)
        volume.mkdir("DIR")
        volume.mkdir("DIR\\DEEP")
        volume.write_bytes("DIR\\DEEP\\A.TXT", b"x" * 3000)
        volume.write_bytes("B.TXT", b"y" * 100)
        volume.write_bytes("EMPTY", b"")
        volume.rename("B.TXT", "DIR\\B.TXT")
        volume.set_access("DIR\\B.TXT", Access.READ_ONLY | Access.ARCHIVE)
        volume.close()
        code, output = self._fsck(path)
        self._assert_clean(code, output)
        used_after, _total = map(int, re.search(r"(\d+)/(\d+) clusters", output).groups())
        self.assertEqual(used_after, used + 6)  # DIR, DEEP, 3 for A.TXT, 1 for B.TXT

    def test_engine_formatted_floppy_passes_fsck(self) -> None:
        path = make_image(self.tmp, "ds-720k", label="CHECKED")
        volume = open_volume(path, writable=True)
        volume.mkdir("AUTO")
        volume.write_bytes("AUTO\\X.PRG", os.urandom(5000))
        volume.write_bytes("Y.TXT", b"y")
        volume.remove("Y.TXT")
        volume.rename("AUTO\\X.PRG", "AUTO\\Z.PRG")
        volume.mkdir("AUTO\\DEEP")
        volume.rename("AUTO\\DEEP", "DEEP")
        volume.close()
        code, output = self._fsck(path)
        self._assert_clean(code, output)
        self.assertIn("4 files, 7/711 clusters", output)  # fsck counts the label entry


@unittest.skipUnless(FLOPPY_SAMPLES, "sample floppies are not present")
class SampleFloppyTests(unittest.TestCase):
    def _sample(self, fragment: str) -> Path | None:
        for path in FLOPPY_SAMPLES:
            if fragment.lower() in path.name.lower():
                return path
        return None

    def test_every_sample_is_a_80x2x10_image_by_size(self) -> None:
        for path in FLOPPY_SAMPLES:
            self.assertEqual(path.stat().st_size, 80 * 2 * 10 * 512, path.name)

    def test_geometry_from_bpb_distinguishes_ten_sector_tracks(self) -> None:
        for path in FLOPPY_SAMPLES:
            boot = path.read_bytes()[:512]
            with self.subTest(sample=path.name):
                try:
                    geometry = geometry_from_bpb(boot)
                except DataError:
                    # A copy-protected disk may carry a nonsense BPB; the
                    # engine must refuse it rather than invent a geometry.
                    self.assertTrue(bpb_problems(parse_boot_sector(boot), 1600))
                    continue
                self.assertEqual(geometry.sides, 2)
                self.assertEqual(geometry.sectors_per_track, 10)
                self.assertEqual(geometry.sectors_per_cluster, 2)
                self.assertEqual(le16_at(boot, 0x18), 10)

    def test_battle_hawks_lists_and_validates(self) -> None:
        path = self._sample("Battle_Hawks")
        if path is None:
            self.skipTest("Battle Hawks sample missing")
        candidates = identify(path)
        self.assertEqual(candidates[0].filesystem, "gemdos")
        self.assertEqual(candidates[0].confidence, 1.0)
        geometry = geometry_from_bpb(path.read_bytes()[:512])
        self.assertEqual(geometry.total_sectors, 1520)  # fewer than the image holds
        volume = open_volume(path)
        names = [entry.name for entry in volume.iter_entries()]
        self.assertIn("B_HAWK.PRG", names)
        self.assertIn("DESKTOP.INF", names)
        self.assertEqual(volume.validate(), [])
        self.assertEqual(detect_content_type(volume.read_bytes("B_HAWK.PRG")), "executable")
        volume.close()

    def test_copy_protected_samples_are_not_claimed_with_confidence(self) -> None:
        for fragment in ("Red_Heat", "Rogue_Trooper"):
            path = self._sample(fragment)
            if path is None:
                continue
            with self.subTest(sample=path.name):
                candidates = identify(path)
                self.assertTrue(not candidates or candidates[0].confidence <= 0.5)


if __name__ == "__main__":
    unittest.main()
