from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.disk_service import (
    TOS_PARTITION_LIMIT,
    SESSION_OWNER,
    DiskError,
    DiskService,
    ImageSession,
)
from app.gemdos_items import move_gemdos_items

try:
    from app.server import create_app
except ModuleNotFoundError:  # Flask is intentionally absent from the light host test env.
    create_app = None

SAMPLES = Path(
    os.environ.get("ATARI_FILE_FORGE_SAMPLES")
    or Path(__file__).resolve().parents[1] / "samples"
)
HDD_SAMPLES = sorted(
    [*(SAMPLES / "hdd").glob("*.hd"), *(SAMPLES / "hdd").glob("*.img")]
    if (SAMPLES / "hdd").is_dir()
    else []
)
FLOPPY_SAMPLES = (
    sorted((SAMPLES / "floppies").glob("*.st"))
    if (SAMPLES / "floppies").is_dir()
    else []
)


def boot_sector_word_sum(path: Path) -> int:
    """The big-endian word sum TOS checks before it executes sector zero."""
    sector = path.read_bytes()[:512]
    return sum(
        int.from_bytes(sector[offset : offset + 2], "big")
        for offset in range(0, 512, 2)
    ) & 0xFFFF


class DiskErrorTests(unittest.TestCase):
    @unittest.skipIf(create_app is None, "Flask is available in the application container")
    def test_browser_storage_owner_restores_missing_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch(
            "app.server.WORK_DIR", Path(folder)
        ):
            application = create_app()
            first_browser = application.test_client()
            first_response = first_browser.get("/api/health")
            owner = first_response.headers["X-Atari-Session-Owner"]
            self.assertRegex(owner, r"^[A-Za-z0-9_-]{32,64}$")

            replacement_cookie_jar = application.test_client()
            restored_response = replacement_cookie_jar.get(
                "/api/health",
                headers={"X-Atari-Session-Owner": owner},
            )

            self.assertEqual(restored_response.headers["X-Atari-Session-Owner"], owner)
            self.assertIn(
                f"atari_file_forge_owner={owner}",
                restored_response.headers["Set-Cookie"],
            )

    def test_each_target_medium_is_a_distinct_profile(self) -> None:
        for profile in ("auto", "floppy", "hd", "volume", "tos"):
            self.assertEqual(DiskService._target_hardware(profile), profile)
        self.assertEqual(DiskService._target_hardware(None), "auto")
        with self.assertRaises(DiskError):
            DiskService._target_hardware("a1200")

    def test_capacity_sums_the_partitions_a_drive_declares(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            drive = service.create_blank("hd", "DRIVE", "32MB")
            # A drive that has not had a partition chosen reports the table's
            # own arithmetic, which is what TOS sees before it mounts anything.
            table_view = ImageSession(drive.id, drive.name, "hd", drive.path)
            partitions = service.list_partitions(table_view)
            self.assertEqual(len(partitions), 4)

            capacity = service.capacity(table_view)

            self.assertTrue(capacity["available"])
            self.assertEqual(capacity["unit"], "bytes")
            self.assertEqual(capacity["total"], drive.path.stat().st_size)
            self.assertEqual(
                capacity["used"],
                sum(int(row["sizeBytes"]) for row in partitions),
            )
            self.assertEqual(
                capacity["free"], capacity["total"] - capacity["used"]
            )
            self.assertEqual(capacity["detail"], "4 partitions")

    def test_a_volume_root_lists_its_files_and_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "VOLUME")
            host = Path(folder) / "payload"
            host.write_bytes(b"test")
            service.make_directory(session, "GAMES")
            service.put(session, "GAMES\\MYFILE.DAT", host)

            root = service.list_directory(session, "", None)
            directory = service.list_directory(session, "GAMES", None)

            self.assertEqual([row["name"] for row in root["entries"]], ["GAMES"])
            self.assertEqual(root["entries"][0]["type"], "dir")
            self.assertEqual(
                [row["name"] for row in directory["entries"]], ["MYFILE.DAT"]
            )
            # Only the root has a fixed entry count, because it is an area of
            # a fixed size written at format time.
            self.assertEqual(root["directoryEntriesUsed"], 1)
            self.assertNotIn("directoryEntryLimit", directory)

    def test_browsing_a_volume_reports_content_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "CONTENTS")
            record = Path(folder) / "record"
            record.write_bytes(b"#a000000\r\n#b000000\r\n#G 03 FF *.APP@ @\r\n")
            program = Path(folder) / "program"
            program.write_bytes(b"\x60\x1a" + bytes(510))
            service.put(session, "DESKTOP.INF", record)
            service.put(session, "GAME.PRG", program)

            listing = service.browse_directory(session, "", None)

            self.assertEqual(
                sorted(row["name"] for row in listing["entries"]),
                ["DESKTOP.INF", "GAME.PRG"],
            )
            self.assertTrue(
                all(row.get("contentKind") for row in listing["entries"]),
                listing["entries"],
            )
            kinds = {row["name"]: row["contentKind"] for row in listing["entries"]}
            self.assertEqual(kinds["GAME.PRG"], "program")

    def test_attribute_edits_survive_reopening_a_volume(self) -> None:
        """A GEMDOS entry carries one attribute byte, not two addresses."""
        for image_format in ("ds-720k", "ds-880k"):
            with self.subTest(image_format=image_format), tempfile.TemporaryDirectory() as folder:
                service = DiskService(folder)
                session = service.create_blank(image_format, "ATTRIBS")
                host = Path(folder) / "payload"
                host.write_bytes(b"machine code")
                service.put(session, "PROGRAM.PRG", host)

                service.set_file_metadata(session, "PROGRAM.PRG", "r-s---")
                reopened = service.create_from_stream(
                    session.name, io.BytesIO(session.path.read_bytes()),
                )
                row = service.browse_directory(reopened, "", None)["entries"][0]

                self.assertEqual(int(row["attributeBits"]), 0x05)
                self.assertEqual(row["attributes"], "r-s---")
                self.assertEqual(row["attr"], row["attributes"])
                # A row carries what a GEMDOS directory entry holds and
                # nothing invented to fill a gap: no second attribute word,
                # no note field, no load or execution address.
                self.assertLessEqual(
                    set(row),
                    {
                        "name",
                        "path",
                        "type",
                        "length",
                        "attributes",
                        "attributeBits",
                        "attr",
                        "datestamp",
                        "filetype",
                        "contentKind",
                        "damaged",
                    },
                )
                self.assertEqual(
                    service.read_file(reopened, "PROGRAM.PRG"), b"machine code"
                )

    def test_writing_into_a_missing_directory_is_refused(self) -> None:
        """A full stop separates an extension, so this is a missing folder."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "VOLUME")
            host = Path(folder) / "payload"
            host.write_bytes(b"test")

            with self.assertRaises(DiskError):
                service.put(session, "GAMES\\MYFILE.DAT", host)
            service.put(session, "GAMES.DAT", host)
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "", None)["entries"]
                ],
                ["GAMES.DAT"],
            )

    def test_files_move_between_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "VOLUME")
            host = Path(folder) / "payload"
            host.write_bytes(b"test")
            service.make_directory(session, "GAMES")
            service.put(session, "HELLO.TXT", host)

            moved = move_gemdos_items(
                service,
                session,
                [{"source": "HELLO.TXT", "destination": "GAMES\\HELLO.TXT"}],
            )

            self.assertEqual(moved["moved"][0]["destination"], "GAMES\\HELLO.TXT")
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "", None)["entries"]
                ],
                ["GAMES"],
            )
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "GAMES", None)["entries"]
                ],
                ["HELLO.TXT"],
            )

    def test_a_directory_tree_keeps_its_contents_separate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-880k", "VOLUME")
            host = Path(folder) / "payload"
            host.write_bytes(b"contents")
            service.make_directory(session, "ONE")
            service.make_directory(session, "TWO")
            service.put(session, "TWO\\FILE.DAT", host)

            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "ONE", None)["entries"]
                ],
                [],
            )
            self.assertEqual(
                [
                    row["name"]
                    for row in service.list_directory(session, "TWO", None)["entries"]
                ],
                ["FILE.DAT"],
            )

    def test_download_preparation_reports_its_phases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "DOWNLOAD")
            progress = []

            result = service.prepare_download(
                session,
                lambda message, current=None, total=None: progress.append(
                    (message, current, total)
                ),
            )

            self.assertEqual(result, session.path)
            self.assertEqual([item[1] for item in progress], [0, 2])
            self.assertTrue(all(item[2] == 2 for item in progress))

    def test_a_prepared_download_hands_back_the_edited_bytes_unchanged(self) -> None:
        """A sector image is written to a floppy exactly as it is on screen."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "EXACT")
            host = Path(folder) / "payload"
            host.write_bytes(b"payload")
            service.put(session, "GAME.PRG", host)
            before = session.path.read_bytes()

            self.assertEqual(service.prepare_download(session), session.path)
            self.assertEqual(session.path.read_bytes(), before)

    def test_mark_saved_clears_and_persists_dirty_state(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-720k", "SAVED")
            self.assertTrue(session.dirty)

            service.mark_saved(session)

            self.assertFalse(session.dirty)
            restored = service._restore_session(session.id)
            self.assertFalse(restored.dirty)

    def test_clean_edited_flux_uses_the_prepared_export(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            session_folder = Path(folder) / ("1" * 32)
            session_folder.mkdir()
            raw = session_folder / "working.st"
            original = session_folder / "original.hfe"
            exported = session_folder / "saved.hfe"
            raw.write_bytes(b"raw")
            original.write_bytes(b"original")
            exported.write_bytes(b"edited")
            service = DiskService(folder)
            session = ImageSession(
                "1" * 32,
                "disk.hfe",
                "gemdos",
                raw,
                dirty=False,
                hfe_original_path=original,
                hfe_export_path=exported,
            )

            self.assertEqual(service._prepare_hfe_download(session), exported)

    def test_image_rename_preserves_format_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("hd", "DRIVE", "8MB")
            self.assertTrue(session.name.endswith(".img"))

            service.rename_session(session, "GAMES")

            self.assertEqual(session.name, "GAMES.img")
            self.assertTrue((session.path.parent / "session.json").is_file())
            self.assertEqual(service._restore_session(session.id).name, "GAMES.img")

    def test_image_rename_cannot_change_its_format(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "disk.st"
            image_path.write_bytes(b"image")
            session = ImageSession("b" * 32, "disk.st", "gemdos", image_path)

            with self.assertRaisesRegex(DiskError, r"\.st"):
                DiskService(folder).rename_session(session, "disk.img")

    def test_blank_image_targets_follow_the_selected_format(self) -> None:
        self.assertEqual(DiskService._blank_target_hardware("hd", "floppy"), "hd")
        self.assertEqual(DiskService._blank_target_hardware("volume", "tos"), "volume")
        # A ROM is not a medium a machine profile says anything about.
        self.assertEqual(DiskService._blank_target_hardware("rom", "floppy"), "auto")
        self.assertEqual(DiskService._blank_target_hardware("cartridge", "hd"), "auto")
        # Every floppy is the same disk on every ST, so a hard-disk or TOS
        # profile is not a choice a new floppy can make.
        self.assertEqual(DiskService._blank_target_hardware("ds-720k", "hd"), "floppy")
        self.assertEqual(DiskService._blank_target_hardware("ds-880k", "tos"), "floppy")
        self.assertEqual(DiskService._blank_target_hardware("hfe-st-720k", "volume"), "floppy")
        self.assertEqual(DiskService._blank_target_hardware("ds-720k", "floppy"), "floppy")
        self.assertEqual(DiskService._blank_target_hardware("hd-1440k", None), "auto")

    def test_failed_blank_creation_removes_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)

            with patch.object(
                service, "_format_floppy_image", side_effect=DiskError("failed")
            ):
                with self.assertRaisesRegex(DiskError, "failed"):
                    service.create_blank("ds-720k", "BLANK")

            self.assertEqual(list(root.iterdir()), [])

    def test_image_can_expand_directly_into_the_current_directory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source, target = self._extraction_pair(service, root)
            service.mark_saved(target)

            destination = service.extract_image_to_directory(
                source, target, "", None, create_directory=False
            )

            self.assertEqual(destination, "")
            self.assertEqual(
                {
                    row["name"]
                    for row in service.list_directory(target, "")["entries"]
                },
                {"GAME.PRG"},
            )
            self.assertTrue(target.dirty)
            self.assertEqual(list((root / "work").glob("*/.import-rollback-*")), [])

    def _extraction_pair(self, service: DiskService, root: Path):
        source = service.create_blank("ds-720k", "SOURCE", options={"bootable": True})
        target = service.create_blank("ds-880k", "TARGET")
        host = root / "game.prg"
        host.write_bytes(b"\x60\x1a" + bytes(510))
        service.put(source, "GAME.PRG", host)
        return source, target

    def test_root_extraction_carries_the_source_boot_option(self) -> None:
        # A disk installed into the root without its boot sector setting has
        # all its files but cannot start itself, which is the difference
        # between the contents being present and the title running.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source, target = self._extraction_pair(service, root)
            self.assertNotEqual(boot_sector_word_sum(target.path), 0x1234)

            destination = service.extract_image_to_directory(
                source, target, "", None, create_directory=False
            )

            self.assertEqual(destination, "")
            self.assertEqual(boot_sector_word_sum(target.path), 0x1234)
            self.assertTrue(service.refresh_gemdos_capabilities(target)["bootable"])
            self.assertEqual(target.warnings, [])

    def test_a_directory_destination_leaves_the_boot_option_alone(self) -> None:
        # A boot sector runs the loader it contains, which expects the layout
        # of the disk it came from. Setting it after installing into a folder
        # would start a loader whose files are no longer where it looks, and
        # break an image which previously started. Software installed into
        # its own folder is reached from the desktop instead.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source, target = self._extraction_pair(service, root)

            with patch.object(service, "_run", return_value="1\n") as run:
                for destination in ("GAME", "GAMES\\CHUCK", "SOFTWARE"):
                    with self.subTest(destination=destination):
                        self.assertIsNone(
                            service.carry_boot_option(source, target, destination)
                        )
            run.assert_not_called()

    def test_a_destination_that_is_not_a_volume_is_declined(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source, target = self._extraction_pair(service, root)
            target.kind = "hd"

            with patch.object(service, "_run", return_value="1\n") as run:
                self.assertIsNone(service.carry_boot_option(source, target, ""))
            run.assert_not_called()

    def test_a_source_disk_with_no_boot_option_sets_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            plain = service.create_blank("ds-720k", "PLAIN")
            target = service.create_blank("ds-880k", "TARGET")
            before = target.path.read_bytes()

            self.assertIsNone(service.carry_boot_option(plain, target, ""))

            self.assertEqual(target.path.read_bytes(), before)

    def test_a_failed_boot_option_warns_and_keeps_the_installed_files(self) -> None:
        # The files are already in place, so refusing the whole extraction over
        # the boot option would lose more than it protects.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source, target = self._extraction_pair(service, root)

            def run(args, *_a, **_k):
                if args[0] == "opt" and len(args) > 2:
                    raise DiskError("engine refused")
                return "1\n"

            with patch.object(service, "_run", side_effect=run):
                destination = service.extract_image_to_directory(
                    source, target, "", None, create_directory=False
                )

            self.assertEqual(destination, "")
            self.assertEqual(
                {
                    row["name"]
                    for row in service.list_directory(target, "")["entries"]
                },
                {"GAME.PRG"},
            )
            self.assertTrue(
                any("boot option" in warning for warning in target.warnings),
                target.warnings,
            )

    def test_an_empty_source_image_is_refused_before_anything_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            empty = service.create_blank("ds-720k", "EMPTY")
            target = service.create_blank("ds-880k", "TARGET")
            before = target.path.read_bytes()

            with self.assertRaisesRegex(DiskError, "empty"):
                service.extract_image_to_directory(empty, target, "", "SOFTWARE")

            self.assertEqual(target.path.read_bytes(), before)

    def test_import_preview_traverses_source_directories(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image = root / "source.st"
            image.write_bytes(b"image")
            session = ImageSession("5" * 32, image.name, "gemdos", image)

            def listing(_session, path, *_args, **_kwargs):
                if not path:
                    return {"entries": [
                        {"name": "DESKTOP.INF", "type": "file", "length": 24},
                        {"name": "GAMES", "type": "dir", "length": 0},
                    ]}
                return {"entries": [{"name": "CHUCK.PRG", "type": "file", "length": 1088}]}

            with patch.object(service, "list_directory", side_effect=listing):
                preview = service.preview_image_contents(session)

            self.assertEqual(preview["total"], 3)
            self.assertFalse(preview["truncated"])
            self.assertEqual(
                [(entry["path"], entry["name"]) for entry in preview["entries"]],
                [("", "DESKTOP.INF"), ("", "GAMES"), ("GAMES", "CHUCK.PRG")],
            )

    def test_recoverable_sessions_lists_persisted_working_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            image_id = "a" * 32
            session_folder = root / image_id
            session_folder.mkdir()
            image = session_folder / "drive.img"
            image.write_bytes(bytes(512))
            session = ImageSession(
                image_id,
                image.name,
                "gemdos",
                image,
                target_hardware="volume",
            )
            service._persist_session(session)

            recovered = service.recoverable_sessions()

            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0]["id"], image_id)
            self.assertEqual(recovered[0]["name"], "drive.img")
            self.assertEqual(recovered[0]["size"], 512)
            self.assertEqual(recovered[0]["targetHardware"], "volume")

    def test_recovery_is_scoped_to_current_browser_owner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root)
            owner_token = SESSION_OWNER.set("owner-one")
            try:
                image_id = "b" * 32
                session_folder = root / image_id
                session_folder.mkdir()
                image = session_folder / "private.st"
                image.write_bytes(bytes(737280))
                session = ImageSession(image_id, image.name, "gemdos", image)
                service.sessions[image_id] = session
                service._persist_session(session)
                self.assertEqual(len(service.recoverable_sessions()), 1)
            finally:
                SESSION_OWNER.reset(owner_token)

            other_token = SESSION_OWNER.set("owner-two")
            try:
                self.assertEqual(service.recoverable_sessions(), [])
                with self.assertRaisesRegex(DiskError, "no longer exists"):
                    service.get(image_id)
                self.assertEqual(service.clear_recoverable_sessions(), 0)
                self.assertTrue(image.is_file())
            finally:
                SESSION_OWNER.reset(other_token)

    def test_restore_replaces_a_superseded_partition_note(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder))
            session = service.create_blank("hd", "DRIVE", "8MB")
            session.warnings = [
                "Opened an AHDI hard disk with 4 partitions.",
                "A useful current warning",
            ]
            service._persist_session(session)

            restored = service._restore_session(session.id)

            self.assertEqual(restored.warnings[0], "A useful current warning")
            self.assertEqual(len(restored.warnings), 2)
            self.assertIn("Choose a partition", restored.warnings[1])

    def test_a_session_saved_with_the_old_companion_keys_still_restores(self) -> None:
        """Working sessions on a developer's machine predate the Atari port.

        Those were written while the workbench still paired an image with a
        geometry file, so their session.json carries two keys nothing reads
        any more. Restoring one must simply ignore them.
        """
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder))
            session = service.create_blank("ds-720k", "WORK")
            service._persist_session(session)
            metadata_path = session.path.parent / "session.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["descriptorName"] = "WORK.geo"
            metadata["descriptorFile"] = "WORK.geo"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            (session.path.parent / "WORK.geo").write_text(
                "cylinders=615\nheads=4\nsectors=17\n", encoding="utf-8"
            )

            restored = service._restore_session(session.id)

            self.assertEqual(restored.name, session.name)
            self.assertEqual(restored.kind, "gemdos")
            self.assertFalse(hasattr(restored, "descriptor_path"))
            self.assertNotIn("hasDescriptor", service.summary(restored))

    def test_a_decode_one_sector_short_of_a_floppy_is_completed(self) -> None:
        """A flux decode may omit an unreadable final sector, and only that."""
        from app.flux_containers import restore_omitted_tail_sector

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            short = root / "short.st"
            short.write_bytes(bytes(737280 - 512))

            self.assertTrue(restore_omitted_tail_sector(short, "gemdos"))
            self.assertEqual(short.stat().st_size, 737280)

            # A complete image is left alone, and a hole larger than one
            # sector is never filled.
            self.assertFalse(restore_omitted_tail_sector(short, "gemdos"))
            gapped = root / "gapped.st"
            gapped.write_bytes(bytes(737280 - 4096))
            self.assertFalse(restore_omitted_tail_sector(gapped, "gemdos"))
            self.assertEqual(gapped.stat().st_size, 737280 - 4096)

    def test_engine_traceback_is_reduced_to_final_error(self) -> None:
        message = """Traceback (most recent call last):
  File "/usr/local/bin/disc", line 8, in <module>
ValueError: A concise engine failure"""

        self.assertEqual(
            DiskService._friendly_engine_error(message),
            "A concise engine failure",
        )

    def test_a_created_drive_matches_the_table_it_declares(self) -> None:
        """A driver multiplies the table out and refuses a mismatch."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("hd", "DRIVE", "32MB")
            table = service.partition_table(session)

            self.assertEqual(table["scheme"], "ahdi")
            self.assertFalse(table["byteSwapped"])
            self.assertEqual(len(table["partitions"]), 4)
            self.assertLessEqual(
                table["hdSize"] * 512, session.path.stat().st_size
            )
            for partition in table["partitions"]:
                end = (
                    int(partition["startSector"]) + int(partition["sizeSectors"])
                ) * 512
                self.assertLessEqual(end, session.path.stat().st_size)
                self.assertTrue(partition["gemdos"])
            self.assertTrue(table["partitions"][0]["bootable"])

    def test_a_partition_past_the_tos_limit_is_reported_not_reformatted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank(
                "hd", "BIG", "600MB", "hd", {"partitions": 1}
            )

            self.assertEqual(TOS_PARTITION_LIMIT, 256 * 1024 * 1024)
            partition = service.list_partitions(session)[0]
            self.assertLessEqual(int(partition["sizeBytes"]), TOS_PARTITION_LIMIT)
            # Nothing is reformatted to fit: the remainder is simply left
            # unallocated, which is visible in the drive's own capacity.
            table_view = ImageSession(session.id, session.name, "hd", session.path)
            self.assertGreater(service.capacity(table_view)["free"], 0)

    def test_a_created_volume_carries_the_requested_label(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("volume", "WORKDISK", capacity="32MB")

            summary = service.summary(session)

            self.assertEqual(summary["label"], "WORKDISK")
            self.assertEqual(summary["title"], summary["label"])
            self.assertEqual(summary["format"], "FAT16")
            # Eleven characters is all one directory entry's name bytes hold.
            long_title = service.create_blank(
                "volume", "A VERY LONG VOLUME NAME", capacity="32MB"
            )
            self.assertLessEqual(len(service.summary(long_title)["label"]), 11)

    def test_a_damaged_volume_is_reported_rather_than_read_as_though_intact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "DAMAGED")
            host = root / "payload"
            host.write_bytes(b"payload" * 200)
            service.put(session, "GAME.PRG", host)
            self.assertEqual(service.validate(session), "No structural errors found")

            # Point the entry's first cluster past the end of the volume.
            with session.path.open("r+b") as image:
                image.seek(0x200 * 3 + 0x1A)
                image.write(b"\xff\x7f")

            self.assertNotEqual(service.validate(session), "No structural errors found")

    def test_a_repair_leaves_a_healthy_volume_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            session = service.create_blank("ds-880k", "HEALTHY")
            service.make_directory(session, "GAMES")
            before = session.path.read_bytes()

            self.assertEqual(service.validate(session), "No structural errors found")
            self.assertEqual(session.path.read_bytes(), before)

    def test_a_bootable_boot_sector_sums_to_the_value_tos_looks_for(self) -> None:
        """TOS executes sector zero only when its word sum is 0x1234."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(folder)
            bootable = service.create_blank(
                "ds-720k", "BOOTER", options={"bootable": True}
            )
            plain = service.create_blank("ds-720k", "PLAIN")

            self.assertEqual(boot_sector_word_sum(bootable.path), 0x1234)
            self.assertNotEqual(boot_sector_word_sum(plain.path), 0x1234)
            self.assertTrue(service.summary(bootable)["bootable"])
            self.assertFalse(service.summary(plain)["bootable"])
            self.assertTrue(
                any("0x1234" in warning for warning in bootable.warnings),
                bootable.warnings,
            )

    def test_a_cluster_outside_the_volume_is_explained_not_blamed_on_the_reader(self) -> None:
        message = "DataError: Block 3200 is outside this volume."

        friendly = DiskService._friendly_engine_error(message)

        self.assertIn("damaged", friendly)
        self.assertIn("hex editor", friendly)

    def test_a_disk_that_boots_its_own_loader_is_not_called_damaged(self) -> None:
        """An executable Atari boot sector does not promise a filing system.

        A great many ST games were published this way: the boot sector is the
        game's own loader and the rest of the disk is whatever layout it
        wants. Reporting them as unformatted or damaged sends somebody looking
        for a fault in a dump that is perfectly good.
        """
        message = (
            "The disk has an executable boot sector but no filing system. "
            "It is unformatted, truncated or damaged."
        )

        friendly = DiskService._friendly_engine_error(message)

        self.assertIn("boots a loader of its own", friendly)
        self.assertIn("ST games", friendly)
        self.assertIn("hex editor", friendly)

    def test_read_only_media_refuse_an_edit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "disk.st"
            path.write_bytes(bytes(737280))
            for kind, fragment in (
                ("stx", "Pasti"),
                ("tosrom", "read-only"),
                ("iso", "read-only"),
            ):
                with self.subTest(kind=kind):
                    session = ImageSession("test", path.name, kind, path)
                    with self.assertRaisesRegex(DiskError, fragment):
                        DiskService.require_writable_geometry(session)

            flux = ImageSession(
                "test", path.name, "gemdos", path, hfe_read_only=True
            )
            with self.assertRaisesRegex(DiskError, "cannot be rewritten safely"):
                DiskService.require_writable_geometry(flux)

            ordinary = ImageSession("test", path.name, "gemdos", path)
            self.assertIsNone(DiskService.require_writable_geometry(ordinary))


@unittest.skipUnless(HDD_SAMPLES, "sample hard disks are not present")
class SampleHardDiskTests(unittest.TestCase):
    """Real drives imaged from real Atari hardware, opened as they arrived."""

    #: What each drive's own table says: scheme, partition count, byte order.
    EXPECTED = {
        "petari_acsi_800mb_icd.hd": ("ahdi", 4, False),
        "petari_ide_1600mb_ahdi.hd": ("xgm", 5, True),
        "zero_to_hero_512mb.img": ("mbr", 1, False),
        "falcon_mint_drive0_512mb.img": ("mbr", 1, False),
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._folder = tempfile.TemporaryDirectory()
        cls.service = DiskService(Path(cls._folder.name) / "work")
        cls.sessions = {
            path.name: cls.service.create_from_path(path) for path in HDD_SAMPLES
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._folder.cleanup()

    def test_every_sample_opens_as_a_partitioned_hard_disk(self) -> None:
        self.assertTrue(self.sessions)
        for name, session in self.sessions.items():
            with self.subTest(sample=name):
                self.assertEqual(session.kind, "hd")
                self.assertEqual(
                    self.service.summary(session)["kind"], "hd"
                )

    def test_each_sample_declares_the_partitions_its_table_holds(self) -> None:
        for name, session in self.sessions.items():
            expected = self.EXPECTED.get(name)
            if expected is None:
                continue
            scheme, count, swapped = expected
            with self.subTest(sample=name):
                table = self.service.partition_table(session)
                self.assertEqual(table["scheme"], scheme)
                self.assertEqual(len(table["partitions"]), count)
                self.assertEqual(bool(table["byteSwapped"]), swapped)

                rows = self.service.list_partitions(session)
                self.assertEqual(len(rows), count)
                self.assertEqual(
                    [row["device"] for row in rows],
                    [f"{chr(ord('C') + index)}:" for index in range(count)],
                )
                self.assertTrue(all(row["gemdos"] for row in rows))
                self.assertTrue(all(row["format"] == "FAT16" for row in rows))

                summary = self.service.summary(session)
                self.assertEqual(summary["partitionScheme"], scheme)
                self.assertEqual(summary["partitionCount"], count)
                self.assertEqual(summary["byteSwapped"], swapped)

    def test_each_sample_mounts_c_and_lists_its_root(self) -> None:
        for name, session in self.sessions.items():
            with self.subTest(sample=name):
                self.assertEqual(self.service.select_partition(session, 0), 0)
                self.assertEqual(self.service.partition_label(session), "C:")

                listing = self.service.browse_directory(session, "", None)

                self.assertTrue(listing["entries"], name)
                self.assertTrue(listing["capacity"]["available"], name)
                self.assertEqual(
                    self.service.summary(session)["format"], "FAT16", name
                )
                self.assertEqual(
                    listing["directoryEntriesUsed"], len(listing["entries"])
                )

    def test_a_byte_swapped_drive_says_so_rather_than_looking_damaged(self) -> None:
        session = self.sessions.get("petari_ide_1600mb_ahdi.hd")
        if session is None:
            self.skipTest("the byte-swapped sample is not present")
        self.assertTrue(self.service.partition_table(session)["byteSwapped"])
        self.assertTrue(
            any(
                "byte-swapping IDE adapter" in warning
                for warning in self.service.summary(session)["warnings"]
            ),
            self.service.summary(session)["warnings"],
        )


@unittest.skipUnless(FLOPPY_SAMPLES, "sample floppies are not present")
class SampleFloppyTests(unittest.TestCase):
    """Three real 800 KiB game disks: one filing system, two loaders."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._folder = tempfile.TemporaryDirectory()
        cls.service = DiskService(Path(cls._folder.name) / "work")
        cls.sessions = {
            path.name: cls.service.create_from_path(path) for path in FLOPPY_SAMPLES
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls._folder.cleanup()

    def test_every_sample_opens_and_is_an_eight_hundred_kilobyte_disk(self) -> None:
        self.assertTrue(self.sessions)
        for name, session in self.sessions.items():
            with self.subTest(sample=name):
                self.assertEqual(session.path.stat().st_size, 80 * 2 * 10 * 512)
                self.assertIn(session.kind, {"gemdos", "unknown"})

    def test_a_gemdos_sample_lists_reads_and_validates(self) -> None:
        listed = 0
        for name, session in self.sessions.items():
            if session.kind != "gemdos":
                continue
            listed += 1
            with self.subTest(sample=name):
                listing = self.service.list_directory(session, "", None)
                self.assertTrue(listing["entries"])
                self.assertEqual(
                    listing["directoryEntriesUsed"], len(listing["entries"])
                )
                self.assertEqual(
                    self.service.summary(session)["format"], "FAT12"
                )
                self.assertEqual(
                    self.service.validate(session), "No structural errors found"
                )

                readable = next(
                    row
                    for row in listing["entries"]
                    if row["type"] == "file" and row["length"] > 0
                )
                data = self.service.read_file(session, readable["name"])
                self.assertEqual(len(data), readable["length"])
        self.assertGreaterEqual(listed, 1)

    def test_a_loader_disk_is_kept_rather_than_turned_away(self) -> None:
        for name, session in self.sessions.items():
            if session.kind != "unknown":
                continue
            with self.subTest(sample=name):
                self.assertTrue(
                    any(
                        "boots its own loader" in warning
                        for warning in session.warnings
                    ),
                    session.warnings,
                )
                # There is nothing to list, but the sectors can still be
                # converted and written back to a floppy unchanged.
                with self.assertRaises(DiskError):
                    self.service.list_directory(session, "", None)
                self.assertEqual(
                    [row["format"] for row in self.service.export_formats(session)],
                    ["native", "msa", "dim"],
                )


if __name__ == "__main__":
    unittest.main()
