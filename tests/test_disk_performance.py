from __future__ import annotations

import io
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.disk_service import DiskService
from app.gemdos_items import delete_gemdos_items


class DiskPerformanceTests(unittest.TestCase):
    def test_copy_stream_falls_back_for_an_in_memory_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "upload.img"
            content = b"Atari" * 100_000

            DiskService._copy_stream(io.BytesIO(content), target)

            self.assertEqual(target.read_bytes(), content)

    def test_local_checkpoint_copy_preserves_sparse_zero_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.img"
            target = Path(directory) / "checkpoint.img"
            with source.open("wb") as output:
                output.write(b"GEM")
                output.seek(32 * 1024 * 1024 - 1)
                output.write(b"\0")

            DiskService._copy_local_file(source, target)

            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertLess(target.stat().st_blocks * 512, target.stat().st_size // 4)

    def test_trusted_local_open_uses_filesystem_copy_not_upload_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "firmware.rom"
            source.write_bytes(bytes([0xFF]) * (16 * 1024))
            service = DiskService(root / "work")

            with patch.object(
                service,
                "_copy_local_file",
                wraps=service._copy_local_file,
            ) as local_copy, patch.object(
                service,
                "_copy_stream",
                side_effect=AssertionError("local open used the upload copy path"),
            ):
                session = service.create_from_path(source, force_kind="rom")

            self.assertEqual(local_copy.call_count, 1)
            self.assertEqual(session.path.read_bytes(), source.read_bytes())

    def test_known_gemdos_local_open_skips_the_all_filesystem_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = DiskService(root / "source-work").create_blank(
                "ds-720k", "SOURCE"
            ).path
            service = DiskService(root / "open-work")

            with patch.object(
                service,
                "_run_json",
                side_effect=AssertionError("known GEMDOS media used the generic probe"),
            ):
                opened = service.create_from_path(source)

            self.assertEqual(opened.kind, "gemdos")
            self.assertEqual(opened.path.stat().st_size, source.stat().st_size)

    def test_sparse_optimisation_does_not_look_like_an_image_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "drive.img"
            image.write_bytes(b"\x60\x1c" + bytes(8 * 1024 * 1024))
            timestamp = 1_700_000_000_123_456_789
            os.utime(image, ns=(timestamp, timestamp))

            DiskService._optimise_sparse_file(image)

            self.assertEqual(image.stat().st_mtime_ns, timestamp)
            self.assertEqual(image.read_bytes()[:2], b"\x60\x1c")

    def test_a_whole_disk_is_expanded_into_a_volume_without_the_engine_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = service.create_blank("ds-720k", "SOURCE")
            target = service.create_blank("volume", "TARGET", capacity="8MB")
            for name in ("ONE.DAT", "TWO.DAT"):
                host = root / name.lower()
                host.write_bytes(name.encode("ascii"))
                service.put(source, name, host)
            self.assertEqual(len(service.list_volume_files(source)), 2)

            with patch.object(service, "_run", wraps=service._run) as run:
                destination = service.extract_image_to_directory(
                    source, target, "", "SOFTWARE"
                )

            self.assertEqual(run.call_count, 0)
            self.assertEqual(destination, "SOFTWARE")
            self.assertEqual(
                {
                    row["name"]
                    for row in service.list_directory(target, "SOFTWARE")["entries"]
                },
                {"ONE.DAT", "TWO.DAT"},
            )

    def test_a_gemdos_browse_returns_capacity_without_the_engine_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "BROWSE")
            service.make_directory(session, "GAMES")

            with patch.object(service, "_run", wraps=service._run) as run:
                listing = service.browse_directory(session, "", None)

            self.assertEqual(run.call_count, 0)
            self.assertEqual([row["name"] for row in listing["entries"]], ["GAMES"])
            self.assertTrue(listing["capacity"]["available"])
            self.assertGreater(listing["capacity"]["free"], 0)

    def test_multiple_files_change_access_in_one_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "ACCESS")
            first = root / "one.bin"
            second = root / "two.bin"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            service.put(session, "ONE.BIN", first)
            service.put(session, "TWO.BIN", second)

            updated = service.set_access(session, ["ONE.BIN", "TWO.BIN"], False)

            self.assertEqual(updated, ["ONE.BIN", "TWO.BIN"])
            entries = service.list_directory(session, "", None)["entries"]
            # A locked entry carries the read-only bit, which is the one bit
            # GEMDOS has for refusing a change or a delete.
            self.assertTrue(all(row["attr"].startswith("r") for row in entries), entries)
            # Locking says nothing about whether a file is hidden or has been
            # written since the last backup, so those bits are left alone.
            self.assertTrue(all(row["attr"].endswith("a") for row in entries), entries)

            service.set_access(session, ["ONE.BIN", "TWO.BIN"], True)
            entries = service.list_directory(session, "", None)["entries"]
            self.assertTrue(all(row["attr"].startswith("-") for row in entries), entries)
            self.assertTrue(all(row["attr"].endswith("a") for row in entries), entries)

    def test_multiple_files_delete_in_one_engine_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "DELETE")
            for name in ("ONE.BIN", "TWO.BIN", "KEEP.BIN"):
                host = root / name.lower()
                host.write_bytes(name.encode("ascii"))
                service.put(session, name, host)

            service.mutate(
                session, ["rm", "--force", "{image}:ONE.BIN", "{image}:TWO.BIN"]
            )

            names = {
                row["name"]
                for row in service.list_directory(session, "", None)["entries"]
            }
            self.assertEqual(names, {"KEEP.BIN"})

    def test_multiple_items_delete_in_one_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "DELETE")
            for name in ("ONE.BIN", "TWO.BIN", "KEEP.BIN"):
                host = root / name.lower()
                host.write_bytes(name.encode("ascii"))
                service.put(session, name, host)

            result = delete_gemdos_items(service, session, ["ONE.BIN", "TWO.BIN"])

            self.assertEqual(len(result["deletedItems"]), 2)
            names = {
                row["name"]
                for row in service.list_directory(session, "", None)["entries"]
            }
            self.assertEqual(names, {"KEEP.BIN"})

    def test_host_folder_import_preserves_a_directory_tree_in_one_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "FOLDERS")
            one = root / "one.bin"
            two = root / "two.bin"
            one.write_bytes(b"one")
            two.write_bytes(b"two")

            result = service.put_host_tree(
                session,
                "",
                [
                    {
                        "targetPath": "PACK/ONE.BIN",
                        "hostPath": one,
                        "metadata": {"attributes": "r-----"},
                    },
                    {"targetPath": "PACK/SUB/TWO.BIN", "hostPath": two},
                ],
                preserve_directories=True,
            )

            self.assertEqual(result["conflicts"], [])
            self.assertEqual(
                {
                    row["name"]
                    for row in service.list_directory(session, "PACK", None)["entries"]
                },
                {"ONE.BIN", "SUB"},
            )
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "PACK/SUB", None)["entries"]
                ],
                ["TWO.BIN"],
            )
            imported = next(
                row
                for row in service.list_directory(session, "PACK", None)["entries"]
                if row["name"] == "ONE.BIN"
            )
            self.assertEqual(imported["attributeBits"], 0x01)
            self.assertEqual(imported["attributes"], "r-----")
            self.assertEqual(imported["attr"], imported["attributes"])

    def test_host_folder_import_reports_existing_files_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "FOLDERS")
            old = root / "old.bin"
            new = root / "new.bin"
            old.write_bytes(b"old")
            new.write_bytes(b"new")
            service.put(session, "SAME.BIN", old)

            result = service.put_host_tree(
                session,
                "",
                [{"targetPath": "SAME.BIN", "hostPath": new}],
                preserve_directories=False,
            )

            self.assertEqual(result["conflicts"], ["SAME.BIN"])
            self.assertEqual(service.read_file(session, "SAME.BIN"), b"old")

    def test_an_empty_directory_is_safe_to_reuse(self):
        empty_mount = types.SimpleNamespace(
            exists=lambda _path: True,
            stat=lambda _path: types.SimpleNamespace(is_dir=True),
            iter_entries=lambda _path: iter(()),
        )
        populated_mount = types.SimpleNamespace(
            exists=lambda _path: True,
            stat=lambda _path: types.SimpleNamespace(is_dir=True),
            iter_entries=lambda _path: iter([types.SimpleNamespace(name="DESKTOP.INF")]),
        )
        file_mount = types.SimpleNamespace(
            exists=lambda _path: True,
            stat=lambda _path: types.SimpleNamespace(is_dir=False),
            iter_entries=lambda _path: iter(()),
        )
        missing_mount = types.SimpleNamespace(
            exists=lambda _path: False,
            stat=lambda _path: types.SimpleNamespace(is_dir=True),
            iter_entries=lambda _path: iter(()),
        )

        self.assertTrue(DiskService._is_empty_directory(empty_mount, "EMPTY"))
        self.assertFalse(DiskService._is_empty_directory(populated_mount, "SOFTWARE"))
        self.assertFalse(DiskService._is_empty_directory(file_mount, "NOTADIR.TXT"))
        self.assertFalse(DiskService._is_empty_directory(missing_mount, "MISSING"))

    def test_a_whole_volume_is_collected_under_one_destination_directory(self):
        entries = {
            "": [
                types.SimpleNamespace(name="DESKTOP.INF", path="DESKTOP.INF", is_dir=False),
                types.SimpleNamespace(name="GAMES", path="GAMES", is_dir=True),
            ],
            "GAMES": [
                types.SimpleNamespace(
                    name="ADVENTUR.PRG", path="GAMES\\ADVENTUR.PRG", is_dir=False
                ),
            ],
        }
        mount = types.SimpleNamespace(iter_entries=lambda path: iter(entries.get(path, [])))

        def file_item(_mount, source, destination):
            return {"kind": "file", "dst": destination, "src": source}

        items = DiskService._collect_volume_items(mount, "DISKS\\DISK0026", file_item)

        self.assertIn(
            {"kind": "mkdir", "dst": "DISKS\\DISK0026\\GAMES", "order": 0}, items
        )
        files = [item for item in items if item["kind"] == "file"]
        self.assertEqual(
            [(item["sourceName"], item["dst"]) for item in files],
            [
                ("DESKTOP.INF", "DISKS\\DISK0026\\DESKTOP.INF"),
                ("GAMES\\ADVENTUR.PRG", "DISKS\\DISK0026\\GAMES\\ADVENTUR.PRG"),
            ],
        )

    def test_collected_names_are_carried_across_intact(self):
        """The full stop before a GEMDOS extension is part of the name."""
        entries = {
            "": [
                types.SimpleNamespace(name="DESKTOP.INF", path="DESKTOP.INF", is_dir=False),
                types.SimpleNamespace(name="MYFILES", path="MYFILES", is_dir=True),
            ],
            "MYFILES": [
                types.SimpleNamespace(
                    name="ART.NEO", path="MYFILES\\ART.NEO", is_dir=False
                ),
            ],
        }
        mount = types.SimpleNamespace(iter_entries=lambda path: iter(entries.get(path, [])))

        def file_item(_mount, source, destination):
            return {"kind": "file", "dst": destination, "src": source}

        items = DiskService._collect_volume_items(mount, "DISK0034", file_item)

        self.assertIn({"kind": "mkdir", "dst": "DISK0034\\MYFILES", "order": 0}, items)
        files = [item for item in items if item["kind"] == "file"]
        self.assertEqual(
            sorted(item["dst"] for item in files),
            ["DISK0034\\DESKTOP.INF", "DISK0034\\MYFILES\\ART.NEO"],
        )

    def test_an_extracted_desktop_record_is_carried_across_unchanged(self):
        """Nothing is rewritten on the way in, because nothing needs to be.

        TOS loads a GEMDOS program through its own relocation table and
        resolves a path at run time from the drive the program was started
        from, so a disk expanded into a folder on a hard disk finds its files
        without a single byte being patched.
        """
        record = (
            b"#a000000\r\n"
            b"#b000000\r\n"
            b"#c7770007000600070055200506000600\r\n"
            b'#K 4F 53 4C 00 46 55 4D 00 47 08 0B 00 @\r\n'
            b'#G 03 FF *.APP@ @\r\n'
            b'#F 03 04 *.*@\r\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = DiskService(root / "work")
            source = service.create_blank("ds-720k", "SOURCE")
            target = service.create_blank("volume", "TARGET", capacity="8MB")
            host = root / "desktop.inf"
            host.write_bytes(record)
            service.put(source, "DESKTOP.INF", host)

            service.extract_image_to_directory(source, target, "", "DISK0055")

            self.assertEqual(
                service.read_file(target, "DISK0055\\DESKTOP.INF"), record
            )


if __name__ == "__main__":
    unittest.main()
