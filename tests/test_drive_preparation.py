"""Preparing a hard drive: a driver where one is needed, and a desktop.

The failures worth guarding against here are all of the same shape: the drive
looks prepared and the machine still will not start from it. A root sector
whose checksum was not recomputed, a driver copied into the wrong partition, a
desktop configuration rewritten over the arrangement an operator built by hand
are each a drive that reads correctly here and fails on the hardware.

Where the operator's own drives can settle a question, they settle it. Two of
them are in ``samples/hdd`` and both were prepared on a real Atari, so the
tests that read them assert against evidence rather than against this
application's own idea of what a prepared drive looks like.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.disk_service import DiskError, DiskService
from app.drive_preparation import (
    DEFAULT_FOLDERS,
    DESKTOP_FILES,
    DRIVERLESS,
    NEWDESK,
    application_record,
    default_desktop,
    describe_drivers,
    desktop_icon_record,
    desktop_records,
    driver_for,
    find_distribution,
    installed_applications,
    installed_driver,
    is_installed_application,
    merge_desktop,
    record_letter,
    record_path,
)
from app import drive_preparation


SAMPLES = os.environ.get("ATARI_FILE_FORGE_SAMPLES", "")
HDD = Path(SAMPLES) / "hdd" if SAMPLES else None


def sample(name: str) -> Path | None:
    if HDD is None:
        return None
    path = HDD / name
    return path if path.is_file() else None


class DriverCatalogueTests(unittest.TestCase):
    """The driver choices are the ones the interface sends, so they are fixed."""

    def test_the_driverless_choice_is_the_default_and_needs_no_boot_sector(self) -> None:
        driverless = driver_for(DRIVERLESS)
        self.assertFalse(driverless.boot_sector)
        self.assertEqual(driverless.files, ())
        self.assertIn("EmuTOS", driverless.note)

    def test_every_driver_the_interface_offers_is_recognised(self) -> None:
        offered = {"driver-emutos-builtin", "driver-ahdi", "driver-hddriver",
                   "driver-pp", "driver-icd"}
        self.assertEqual({driver["id"] for driver in describe_drivers()}, offered)

    def test_an_unknown_driver_is_refused_with_the_choices_named(self) -> None:
        with self.assertRaises(DiskError) as raised:
            driver_for("driver-invented")
        self.assertIn("driver-hddriver", str(raised.exception))

    def test_a_driver_file_on_a_drive_identifies_the_driver_that_wrote_it(self) -> None:
        """This is how the operator's own drives are read, so it is asserted here."""
        icd = installed_driver(["ICDBOOT.SYS", "NEWDESK.INF"], ["ICDPRO_6.55A"])
        self.assertEqual(icd["id"], "driver-icd")
        self.assertEqual(icd["version"], "6.55A")

        ahdi = installed_driver(["NEWDESK.INF", "SHDRIVER.SYS"], ["AHDI_6.061"])
        self.assertEqual(ahdi["id"], "driver-ahdi")
        self.assertEqual(ahdi["version"], "6.061")

    def test_a_drive_with_no_driver_file_says_so_rather_than_guessing(self) -> None:
        found = installed_driver(["NEWDESK.INF", "AUTO"], [])
        self.assertEqual(found["id"], DRIVERLESS)
        self.assertFalse(found["installed"])

    def test_a_driver_is_found_inside_the_folder_it_was_published_in(self) -> None:
        """Nobody flattens a distribution before using it, so neither does this."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "ICDPRO_6.55A").mkdir()
            (root / "ICDPRO_6.55A" / "ICDBOOT.SYS").write_bytes(b"driver")
            found = find_distribution(driver_for("driver-icd"), [root])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "ICDBOOT.SYS")
        self.assertEqual(found.version, "6.55A")
        self.assertIsNone(found.boot_code)

    def test_a_driver_that_was_never_supplied_is_simply_absent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(find_distribution(driver_for("driver-icd"), [Path(folder)]))

    def test_boot_code_is_only_believed_when_it_is_exactly_one_sector(self) -> None:
        """A file of another length is not a root sector, whatever it is called."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "HDDRIVER.SYS").write_bytes(b"driver")
            (root / "ROOTSECT.BIN").write_bytes(b"\x00" * 511)
            self.assertIsNone(
                find_distribution(driver_for("driver-hddriver"), [root]).boot_code
            )
            (root / "ROOTSECT.BIN").write_bytes(b"\x00" * 512)
            self.assertEqual(
                len(find_distribution(driver_for("driver-hddriver"), [root]).boot_code), 512
            )


class DesktopConfigurationTests(unittest.TestCase):
    """The records are read off the operator's own drives, so they are asserted."""

    def test_a_default_configuration_carries_the_records_a_desktop_needs(self) -> None:
        letters = [record_letter(record) for record in desktop_records(default_desktop())]
        for required in ("a", "b", "c", "d", "K", "E"):
            self.assertIn(required, letters)
        for install in ("G", "F", "P", "D", "Y"):
            self.assertIn(install, letters)

    def test_the_boot_drive_letter_reaches_the_drive_icon(self) -> None:
        self.assertIn("#M 00 01 00 FF D ", default_desktop("D:"))

    def test_a_program_is_installed_under_the_record_its_extension_picks(self) -> None:
        """The desktop reads the extension and nothing else, so it decides."""
        self.assertTrue(application_record("GAMES\\X\\X.PRG").startswith("#G "))
        self.assertTrue(application_record("GAMES\\X\\X.APP").startswith("#G "))
        self.assertTrue(application_record("GAMES\\X\\X.TOS").startswith("#F "))
        self.assertTrue(application_record("GAMES\\X\\X.TTP").startswith("#P "))
        self.assertTrue(application_record("GAMES\\X\\X.GTP").startswith("#Y "))

    def test_a_file_the_desktop_cannot_start_is_refused(self) -> None:
        with self.assertRaises(DiskError):
            application_record("GAMES\\X\\READ.ME")

    def test_a_record_names_the_program_from_the_drive_letter(self) -> None:
        record = application_record("GAMES\\X\\X.PRG", drive="D")
        self.assertEqual(record_path(record), "D:\\GAMES\\X\\X.PRG")
        self.assertTrue(is_installed_application(record))

    def test_a_desktop_icon_record_names_its_file_despite_the_blank_drive_field(self) -> None:
        """``#X`` writes four numbers and a drive-letter field that may be a space."""
        self.assertEqual(
            record_path("#X 02 01 04 FF   C:\\GAMES.TXT@ GAMES.TXT@ "), "C:\\GAMES.TXT"
        )

    def test_a_record_that_names_only_its_own_numbers_names_nothing(self) -> None:
        self.assertEqual(record_path("#N FF 04 000 @ *.*@ @ "), "")

    def test_an_extension_association_is_not_an_installed_application(self) -> None:
        """``*.PRG`` tells GEM how to run programs; it installs none of them."""
        self.assertFalse(is_installed_application("#G 03 FF 000 *.PRG@ @ @ "))

    def test_merging_leaves_the_arrangement_an_operator_built(self) -> None:
        existing = default_desktop() + "#W 00 00 08 01 1F 17 00 @\r\n"
        merged, added = merge_desktop(existing, [application_record("GAMES\\X\\X.PRG")])
        self.assertEqual(len(added), 1)
        self.assertIn("#W 00 00 08 01 1F 17 00 @", merged)
        self.assertIn("#K 4F 53 4C", merged)
        self.assertEqual(
            [item["path"] for item in installed_applications(merged)], ["C:\\GAMES\\X\\X.PRG"]
        )

    def test_installing_the_same_program_twice_leaves_one_record(self) -> None:
        merged, _added = merge_desktop(
            default_desktop(), [application_record("GAMES\\X\\X.PRG")]
        )
        again, _added = merge_desktop(
            merged, [application_record("GAMES\\X\\X.PRG", documents="*.SAV")]
        )
        installed = installed_applications(again)
        self.assertEqual(len(installed), 1)
        self.assertEqual(installed[0]["documents"], "*.SAV")

    def test_an_installed_program_is_written_above_the_extension_association(self) -> None:
        """The desktop takes the first record that matches, so order is meaning."""
        merged, _added = merge_desktop(
            default_desktop(), [application_record("GAMES\\X\\X.PRG")]
        )
        records = desktop_records(merged)
        installed = next(i for i, r in enumerate(records) if is_installed_application(r))
        association = next(i for i, r in enumerate(records) if "*.APP" in r)
        self.assertLess(installed, association)

    def test_a_desktop_icon_names_the_file_and_a_label(self) -> None:
        record = desktop_icon_record("GAMES\\X\\X.PRG", "Hyper")
        self.assertTrue(record.startswith("#X "))
        self.assertIn("C:\\GAMES\\X\\X.PRG@", record)
        self.assertIn("HYPER@", record)

    @unittest.skipUnless(sample("petari_acsi_800mb_icd.hd"), "the operator's drives are absent")
    def test_the_operators_own_configuration_parses_as_this_expects(self) -> None:
        """The shapes asserted above came from these files, so they are checked."""
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            drive = service.create_from_path(sample("petari_acsi_800mb_icd.hd"))
            service.select_partition(drive, 0)
            text = service.read_file(drive, NEWDESK).decode("latin-1")
        letters = [record_letter(record) for record in desktop_records(text)]
        for required in ("a", "b", "c", "d", "K", "E"):
            self.assertIn(required, letters)
        for install in ("G", "F", "P", "D", "Y"):
            self.assertIn(install, letters)
        # The one document that drive keeps on its desktop.
        self.assertIn("C:\\GAMES.TXT", text)


class DrivePreparationTests(unittest.TestCase):
    """Preparation writes to sectors, so it is checked by reading them back."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.drivers = self.root / "drivers"
        self.drivers.mkdir()
        self._previous = drive_preparation.DRIVER_DIR
        drive_preparation.DRIVER_DIR = self.drivers
        self.addCleanup(setattr, drive_preparation, "DRIVER_DIR", self._previous)

    def _drive(self, name: str = "SYSTEM", capacity: str = "40MB"):
        drive = self.service.create_blank("hd", name, capacity)
        self.service.select_partition(drive, 0)
        return drive

    def _supply(self, folder: str, name: str, *, boot_code: bytes | None = None) -> None:
        home = self.drivers / folder
        home.mkdir(parents=True, exist_ok=True)
        (home / name).write_bytes(b"\x60\x1a" + b"\x00" * 26 + b"driver")
        if boot_code is not None:
            (home / "ROOTSECT.BIN").write_bytes(boot_code)

    def _root_sector(self, drive) -> bytes:
        from atarinut.filesystem import reader_for

        reader = reader_for(drive.path, writable=False)
        try:
            return reader.read_block(0)
        finally:
            reader.close()

    def test_a_driverless_drive_is_left_with_an_inert_root_sector(self) -> None:
        """EmuTOS finds the partitions itself; nothing should run from sector 0."""
        from atarinut.filesystem.blocks import is_executable_sector

        drive = self._drive()
        result = self.service.prepare_drive(drive)

        self.assertFalse(is_executable_sector(self._root_sector(drive)))
        self.assertFalse(result["driver"]["installed"])
        self.assertEqual(result["driver"]["id"], DRIVERLESS)
        self.assertTrue(
            any("EmuTOS" in warning for warning in result["warnings"]),
            result["warnings"],
        )

    def test_a_driverless_drive_still_gets_its_folders_and_a_desktop(self) -> None:
        drive = self._drive()
        result = self.service.prepare_drive(drive)

        self.assertEqual(result["folders"], list(DEFAULT_FOLDERS))
        self.assertEqual(result["desktop"], [NEWDESK])
        names = {row["name"] for row in self.service.list_directory(drive, "")["entries"]}
        self.assertTrue(set(DEFAULT_FOLDERS) <= names)
        self.assertIn(NEWDESK, names)

    def test_folders_can_be_declined(self) -> None:
        drive = self._drive()
        result = self.service.prepare_drive(drive, create_folders=False, desktop=False)
        self.assertEqual(result["folders"], [])
        self.assertEqual(result["desktop"], [])

    def test_a_driver_the_operator_supplied_lands_in_the_partition_root(self) -> None:
        drive = self._drive()
        self._supply("HDDRIVER_12.06", "HDDRIVER.SYS")

        result = self.service.prepare_drive(drive, driver="driver-hddriver")

        self.assertEqual(result["files"], ["HDDRIVER.SYS"])
        self.assertEqual(result["driver"], {
            "id": "driver-hddriver", "installed": True, "version": "12.06",
        })
        self.assertTrue(
            self.service.read_file(drive, "HDDRIVER.SYS").startswith(b"\x60\x1a")
        )

    def test_a_driver_with_no_loader_leaves_the_root_sector_alone_and_says_so(self) -> None:
        """Most distributions keep the loader inside their own install program."""
        from atarinut.filesystem.blocks import is_executable_sector

        drive = self._drive()
        self._supply("HDDRIVER_12.06", "HDDRIVER.SYS")
        before = self._root_sector(drive)

        result = self.service.prepare_drive(drive, driver="driver-hddriver")

        self.assertEqual(self._root_sector(drive), before)
        self.assertEqual(
            is_executable_sector(self._root_sector(drive)), is_executable_sector(before)
        )
        self.assertTrue(
            any("no root-sector loader" in warning for warning in result["warnings"]),
            result["warnings"],
        )

    def test_a_loader_is_written_and_the_checksum_recomputed(self) -> None:
        """0x1234 is the whole of what the ROM checks before it executes it."""
        from atarinut.filesystem.blocks import is_executable_sector, word_sum

        drive = self._drive()
        self._supply("ICDPRO_6.55A", "ICDBOOT.SYS", boot_code=bytes(range(256)) * 2)

        result = self.service.prepare_drive(drive, driver="driver-icd")

        sector = self._root_sector(drive)
        self.assertTrue(is_executable_sector(sector))
        self.assertEqual(word_sum(sector), 0x1234)
        self.assertEqual(result["files"], ["ICDBOOT.SYS"])
        self.assertTrue(result["rootSectorExecutable"])

    def test_writing_a_loader_leaves_the_partition_table_intact(self) -> None:
        """Boot code and the AHDI table share the sector; only one of them moves."""
        drive = self._drive()
        before = self.service.list_partitions(drive)
        self._supply("ICDPRO_6.55A", "ICDBOOT.SYS", boot_code=b"\xff" * 512)

        self.service.prepare_drive(drive, driver="driver-icd")

        after = self.service.list_partitions(drive)
        self.assertEqual(
            [(row["startSector"], row["sizeSectors"]) for row in after],
            [(row["startSector"], row["sizeSectors"]) for row in before],
        )

    def test_a_driver_that_was_not_supplied_is_refused_with_the_licence_reason(self) -> None:
        drive = self._drive()
        with self.assertRaises(DiskError) as raised:
            self.service.prepare_drive(drive, driver="driver-ahdi")
        message = str(raised.exception)
        self.assertIn(str(self.drivers), message)
        self.assertIn("EmuTOS", message)

    def test_preparing_twice_does_not_undo_what_was_done_in_between(self) -> None:
        drive = self._drive()
        self.service.prepare_drive(drive)
        edited = default_desktop() + "#W 00 00 08 01 1F 17 00 @\r\n"
        from app import volume_copy

        volume_copy.write_file(self.service, drive, NEWDESK, edited.encode("latin-1"))
        self.service.make_directory(drive, "GAMES\\CHUCK")

        self.service.prepare_drive(drive)

        self.assertIn(
            "#W 00 00 08 01 1F 17 00 @",
            self.service.read_file(drive, NEWDESK).decode("latin-1"),
        )
        self.assertTrue(volume_copy.directory_exists(self.service, drive, "GAMES\\CHUCK"))

    def test_the_state_a_prepared_drive_reports_is_read_off_the_drive(self) -> None:
        drive = self._drive()
        self._supply("ICDPRO_6.55A", "ICDBOOT.SYS", boot_code=bytes(512))

        self.service.prepare_drive(drive, driver="driver-icd")
        state = self.service.drive_preparation(drive)

        self.assertEqual(state["scheme"], "ahdi")
        self.assertTrue(state["rootSectorExecutable"])
        self.assertEqual(state["driver"]["id"], "driver-icd")
        self.assertEqual(state["driver"]["file"], "ICDBOOT.SYS")
        self.assertEqual(state["desktop"], [NEWDESK])
        self.assertEqual(sorted(state["folders"]), sorted(DEFAULT_FOLDERS))

    def test_a_pc_partition_table_refuses_a_driver_and_explains_why(self) -> None:
        """There is no room for an Atari loader beside an MBR, and no need."""
        drive = self.service.create_blank(
            "hd", "PCDISK", "40MB", options={"scheme": "mbr"}
        )
        self.service.select_partition(drive, 0)
        self._supply("ICDPRO_6.55A", "ICDBOOT.SYS", boot_code=bytes(512))

        with self.assertRaises(DiskError) as raised:
            self.service.prepare_drive(drive, driver="driver-icd")
        self.assertIn("EmuTOS", str(raised.exception))

        result = self.service.prepare_drive(drive)
        self.assertTrue(
            any("PC partition table" in warning for warning in result["warnings"]),
            result["warnings"],
        )

    def test_a_floppy_has_no_root_sector_to_prepare(self) -> None:
        floppy = self.service.create_blank("ds-720k", "GAME")
        with self.assertRaises(DiskError):
            self.service.prepare_drive(floppy)


class DesktopInstallationTests(unittest.TestCase):
    """Installing a title on the desktop is what makes it startable."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.drive = self.service.create_blank("hd", "SYSTEM", "40MB")
        self.service.select_partition(self.drive, 0)
        self.service.prepare_drive(self.drive)
        self.service.make_directory(self.drive, "GAMES\\CHUCK")
        program = self.root / "chuck"
        program.write_bytes(b"\x60\x1a" + b"\x00" * 26 + b"code")
        self.service.put(self.drive, "GAMES\\CHUCK\\CHUCK.PRG", program)

    def test_a_program_is_installed_and_put_on_the_desktop(self) -> None:
        result = self.service.install_desktop_application(
            self.drive, "GAMES\\CHUCK\\CHUCK.PRG", label="Chuck"
        )

        self.assertEqual(result["file"], NEWDESK)
        text = self.service.read_file(self.drive, NEWDESK).decode("latin-1")
        self.assertIn("#G 03 FF 000 C:\\GAMES\\CHUCK\\CHUCK.PRG@", text)
        self.assertIn("#X ", text)
        self.assertIn("CHUCK@", text)
        self.assertEqual(
            [item["path"] for item in result["applications"]], ["C:\\GAMES\\CHUCK\\CHUCK.PRG"]
        )

    def test_the_desktop_icon_can_be_declined(self) -> None:
        result = self.service.install_desktop_application(
            self.drive, "GAMES\\CHUCK\\CHUCK.PRG", on_desktop=False
        )
        self.assertEqual([record_letter(record) for record in result["records"]], ["G"])

    def test_a_program_that_is_not_on_the_volume_is_refused(self) -> None:
        with self.assertRaises(DiskError):
            self.service.install_desktop_application(self.drive, "GAMES\\NOPE\\NOPE.PRG")

    def test_the_existing_configuration_is_kept_when_one_is_already_there(self) -> None:
        from app import volume_copy

        volume_copy.write_file(
            self.service, self.drive, DESKTOP_FILES[1],
            default_desktop().encode("latin-1"),
        )
        result = self.service.install_desktop_application(
            self.drive, "GAMES\\CHUCK\\CHUCK.PRG"
        )
        # NEWDESK.INF is what a prepared drive is given, and TOS reads it first.
        self.assertEqual(result["file"], NEWDESK)


class OperatorDriveTests(unittest.TestCase):
    """What a prepared drive looks like, asserted against two real ones.

    These are the drives the workflow was designed from. They are large and
    not redistributable, so the tests skip when they are not there.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(Path(self._temporary.name) / "work")

    def _open(self, name: str):
        path = sample(name)
        if path is None:
            self.skipTest(f"{name} is not in the samples directory")
        return self.service.create_from_path(path)

    @unittest.skipUnless(sample("petari_acsi_800mb_icd.hd"), "the operator's drives are absent")
    def test_an_icd_prepared_acsi_drive_reads_as_one(self) -> None:
        drive = self._open("petari_acsi_800mb_icd.hd")
        self.service.select_partition(drive, 0)
        state = self.service.drive_preparation(drive)

        self.assertTrue(state["rootSectorExecutable"])
        self.assertTrue(state["bootSectorExecutable"])
        self.assertFalse(state["byteSwapped"])
        self.assertEqual(state["driver"]["id"], "driver-icd")
        self.assertEqual(state["driver"]["file"], "ICDBOOT.SYS")
        self.assertEqual(sorted(state["desktop"]), sorted(DESKTOP_FILES))

    @unittest.skipUnless(sample("petari_ide_1600mb_ahdi.hd"), "the operator's drives are absent")
    def test_an_ahdi_prepared_ide_drive_reads_through_its_byte_swap(self) -> None:
        drive = self._open("petari_ide_1600mb_ahdi.hd")
        self.service.select_partition(drive, 0)
        state = self.service.drive_preparation(drive)

        self.assertTrue(state["byteSwapped"])
        self.assertTrue(state["rootSectorExecutable"])
        self.assertTrue(state["bootSectorExecutable"])
        self.assertEqual(state["driver"]["id"], "driver-ahdi")
        self.assertEqual(state["driver"]["file"], "SHDRIVER.SYS")
        self.assertEqual(state["desktop"], [NEWDESK])

    @unittest.skipUnless(sample("falcon_mint_drive0_512mb.img"), "the operator's drives are absent")
    def test_a_pc_partitioned_drive_has_neither_sector_executable(self) -> None:
        """It boots through EmuTOS's built-in support, so nothing runs from a sector."""
        drive = self._open("falcon_mint_drive0_512mb.img")
        self.service.select_partition(drive, 0)
        state = self.service.drive_preparation(drive)

        self.assertEqual(state["scheme"], "mbr")
        self.assertFalse(state["rootSectorExecutable"])
        self.assertFalse(state["bootSectorExecutable"])
        self.assertFalse(state["driver"]["installed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
