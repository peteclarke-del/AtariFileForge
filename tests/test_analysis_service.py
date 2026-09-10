from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.analysis_service import (
    AUTO_IGNORED,
    AUTO_NOT_A_PROGRAM,
    AUTO_ORDER,
    BOOT_EXECUTABLE,
    BOOT_INERT,
    BOOT_LOADS_FILE,
    DATESTAMP_OUT_OF_RANGE,
    DESKTOP_APPLICATION,
    DESKTOP_DRIVE,
    HIDDEN_ATTRIBUTE,
    NAME_CONFLICT,
    NAME_LOWER_CASE,
    NAME_TOO_LONG,
    PROGRAM_TT_RAM_ON_ST,
    ROOT_DIRECTORY_FULL,
    SYSTEM_ATTRIBUTE,
    TOS_MOUNT_LIMIT,
    OperationCancelled,
    accept_compatibility_report,
    attribute_findings,
    auto_folder_findings,
    basic_commands,
    boot_findings,
    build_manifest,
    capacity_findings,
    datestamp_findings,
    dependency_report,
    describe_boot_sector,
    describe_program,
    desktop_findings,
    duplicate_report,
    health_report,
    inspect_file,
    manifest_csv,
    name_findings,
    parse_desktop_inf,
    preflight_report,
    program_findings,
    workspace_metadata_records,
)
from app.errors import DiskError


def program_header(
    text: int = 0x100,
    data: int = 0x20,
    bss: int = 0x40,
    symbols: int = 0,
    flags: int = 0,
) -> bytes:
    """One GEMDOS program header, exactly as the TOS loader reads it."""
    return struct.pack(">HIIIIIIH", 0x601A, text, data, bss, symbols, 0, flags, 0)


def boot_sector(
    *,
    executable: bool = True,
    ldmode: int = 0,
    filename: bytes = b"TOSBOOT PRG",
    execflg: int = 1,
    start_sector: int = 0,
    sector_count: int = 0,
    load_address: int = 0x00010000,
) -> bytes:
    sector = bytearray(512)
    sector[0:3] = b"\xEB\x38\x90"
    struct.pack_into(">HHHH", sector, 0x1E, execflg, ldmode, start_sector, sector_count)
    struct.pack_into(">II", sector, 0x26, load_address, 0)
    sector[0x2E:0x39] = filename.ljust(11)[:11]
    total = sum(
        int.from_bytes(sector[offset : offset + 2], "big") for offset in range(0, 512, 2)
    )
    remainder = (0x1234 - total) & 0xFFFF
    struct.pack_into(">H", sector, 0x1FE, remainder if executable else (remainder + 1) & 0xFFFF)
    return bytes(sector)


def row(name: str, **overrides) -> dict:
    entry = {"name": name, "type": "file", "length": 1024, "attributes": "-----a"}
    entry.update(overrides)
    return entry


class FakeService:
    """The handful of methods every report in this module calls."""

    def __init__(self, tree=None, contents=None, *, partitions=None, summary=None):
        self.tree = dict(tree or {})
        self.contents = dict(contents or {})
        self.partitions = list(partitions or [])
        self._summary = dict(summary or {"revision": "1", "label": "GAMES"})
        self.temporary: list[Path] = []

    def list_directory(self, session, inner, side=None):
        return {"entries": list(self.tree.get(inner, [])), "path": inner}

    def read_file(self, session, path, side=None):
        return self.contents.get(path, b"")

    def export_file(self, session, path, side=None):
        handle = tempfile.NamedTemporaryFile(delete=False)
        handle.write(self.contents.get(path, b""))
        handle.close()
        self.temporary.append(Path(handle.name))
        return Path(handle.name)

    def summary(self, session):
        return dict(self._summary)

    def list_partitions(self, session):
        return list(self.partitions)

    def validate(self, session):
        return "the filing system is consistent"

    def boot_sector(self, session):
        return self.contents.get("$boot")

    def cleanup(self):
        for path in self.temporary:
            path.unlink(missing_ok=True)


def make_session(kind: str = "gemdos", **overrides) -> SimpleNamespace:
    session = SimpleNamespace(
        id="a" * 32,
        name="GAMES.ST",
        kind=kind,
        path=Path("GAMES.ST"),
        partition=None,
        hardware_profile={},
        target_hardware="auto",
        warnings=[],
        compatibility_reports=[],
        editor_projects={},
        ffs_capabilities={},
        rom_project={},
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


class ProgramHeaderTests(unittest.TestCase):
    def test_a_program_header_reports_its_sections_and_loader_flags(self) -> None:
        data = program_header(text=0x200, data=0x40, bss=0x80, flags=0x0007)

        program = describe_program(data, file_size=0x400)

        self.assertEqual(program["text"], 0x200)
        self.assertEqual(program["data"], 0x40)
        self.assertEqual(program["bss"], 0x80)
        self.assertEqual(program["flagsHex"], "00000007")
        self.assertTrue(program["fastLoad"])
        self.assertTrue(program["ttRamLoad"])
        self.assertTrue(program["ttRamMalloc"])
        self.assertEqual(program["memoryMode"], "private")

    def test_a_world_readable_shared_text_program_is_decoded(self) -> None:
        program = describe_program(program_header(flags=0x1030), file_size=0x1000)

        self.assertEqual(program["memoryMode"], "world-readable")
        self.assertTrue(program["sharedText"])

    def test_anything_without_the_magic_word_is_not_a_program(self) -> None:
        self.assertIsNone(describe_program(b"This is a text file, not a program."))
        self.assertIsNone(describe_program(b"\x60\x1a"))

    def test_a_header_whose_sections_do_not_fit_is_rejected(self) -> None:
        self.assertIsNone(describe_program(program_header(text=0x10000), file_size=64))

    def test_tt_ram_flags_are_reported_against_a_68000_profile(self) -> None:
        program = describe_program(program_header(flags=0x0006), file_size=0x400)

        on_st = program_findings([("AUTO/FAST.PRG", program)], "st")
        on_tt = program_findings([("AUTO/FAST.PRG", program)], "tt030")

        self.assertTrue(any(item["code"] == PROGRAM_TT_RAM_ON_ST for item in on_st))
        self.assertFalse(any(item["code"] == PROGRAM_TT_RAM_ON_ST for item in on_tt))
        self.assertIn("_p_flags &00000006", on_tt[0]["detail"])


class BootSectorTests(unittest.TestCase):
    def test_an_executable_boot_sector_names_the_file_it_loads(self) -> None:
        boot = describe_boot_sector(boot_sector())

        self.assertTrue(boot["executable"])
        self.assertEqual(boot["checksum"], 0x1234)
        self.assertEqual(boot["filename"], "TOSBOOT.PRG")
        self.assertIn("TOSBOOT.PRG", boot["loads"])

    def test_a_sector_loading_boot_sector_reports_its_range(self) -> None:
        boot = describe_boot_sector(
            boot_sector(ldmode=1, start_sector=18, sector_count=6)
        )

        self.assertEqual(boot["startSector"], 18)
        self.assertEqual(boot["sectorCount"], 6)
        self.assertIn("6 sector(s) from sector 18", boot["loads"])

    def test_an_inert_boot_sector_is_reported_as_such(self) -> None:
        findings = boot_findings(boot_sector(executable=False))

        self.assertEqual([item["code"] for item in findings], [BOOT_INERT])

    def test_a_bootable_floppy_reports_what_it_starts(self) -> None:
        codes = [item["code"] for item in boot_findings(boot_sector())]

        self.assertEqual(codes, [BOOT_EXECUTABLE, BOOT_LOADS_FILE])


class AutoFolderTests(unittest.TestCase):
    def test_programs_are_reported_in_the_order_the_directory_holds_them(self) -> None:
        rows = [row("FIRST.PRG"), row("SECOND.PRG"), row("THIRD.PRG")]
        headers = {name: describe_program(program_header(), 0x400)
                   for name in ("FIRST.PRG", "SECOND.PRG", "THIRD.PRG")}

        findings = auto_folder_findings(rows, headers)

        self.assertEqual(
            [item["title"] for item in findings],
            ["1. FIRST.PRG", "2. SECOND.PRG", "3. THIRD.PRG"],
        )
        self.assertTrue(all(item["code"] == AUTO_ORDER for item in findings))

    def test_a_prg_without_a_program_header_is_reported(self) -> None:
        findings = auto_folder_findings(
            [row("BROKEN.PRG")], {"BROKEN.PRG": None}
        )

        self.assertEqual(findings[0]["code"], AUTO_NOT_A_PROGRAM)
        self.assertIn("&601A", findings[0]["detail"])

    def test_anything_tos_will_not_run_from_auto_is_named(self) -> None:
        findings = auto_folder_findings(
            [row("NOTES.TXT"), row("TOOLS", type="dir"), row("RUN.PRG")],
            {"RUN.PRG": describe_program(program_header(), 0x400)},
        )

        self.assertEqual(
            [item["code"] for item in findings],
            [AUTO_IGNORED, AUTO_IGNORED, AUTO_ORDER],
        )
        self.assertEqual(findings[2]["title"], "1. RUN.PRG")


class DesktopTests(unittest.TestCase):
    DESKTOP = (
        "#a000000\r\n"
        "#b000000\r\n"
        "#E 18 11\r\n"
        "#M 00 01 00 FF C HARD DISK@ @ \r\n"
        "#M 00 00 00 FF A FLOPPY DISK@ @ \r\n"
        "#G 03 04 *.APP@ @ \r\n"
        "#F 03 04 *.TOS@ @ \r\n"
        "#P 03 04 *.TTP@ @ \r\n"
        "#W 00 00 02 06 26 11 00 @\r\n"
    )

    def test_drive_icons_give_the_drive_letters_the_desktop_shows(self) -> None:
        desktop = parse_desktop_inf(self.DESKTOP)

        self.assertEqual(
            [item["letter"] for item in desktop["drives"]], ["C", "A"]
        )
        self.assertEqual(desktop["drives"][0]["label"], "HARD DISK")

    def test_installed_applications_are_read_from_their_line_types(self) -> None:
        desktop = parse_desktop_inf(self.DESKTOP)

        self.assertEqual(
            [(item["line"], item["mask"]) for item in desktop["applications"]],
            [("#G", "*.APP"), ("#F", "*.TOS"), ("#P", "*.TTP")],
        )
        self.assertEqual(desktop["applications"][2]["role"], "TOS program that takes parameters")

    def test_findings_carry_the_file_the_desktop_came_from(self) -> None:
        findings = desktop_findings("NEWDESK.INF", self.DESKTOP)

        self.assertEqual(
            [item["code"] for item in findings],
            [DESKTOP_DRIVE, DESKTOP_DRIVE, DESKTOP_APPLICATION,
             DESKTOP_APPLICATION, DESKTOP_APPLICATION],
        )
        self.assertEqual(findings[0]["title"], "NEWDESK.INF: drive C:")


class NameAndAttributeTests(unittest.TestCase):
    def test_two_names_that_share_an_8_3_form_are_reported_together(self) -> None:
        entries = [
            ("GAMES/LONGNAMEONE.TXT", row("LONGNAMEONE.TXT")),
            ("GAMES/LONGNAMETWO.TXT", row("LONGNAMETWO.TXT")),
        ]

        codes = [item["code"] for item in name_findings(entries)]

        self.assertEqual(codes.count(NAME_TOO_LONG), 2)
        self.assertEqual(codes.count(NAME_CONFLICT), 1)

    def test_a_lower_case_name_is_reported_as_the_name_tos_stores(self) -> None:
        findings = name_findings([("readme.txt", row("readme.txt"))])

        lower = next(item for item in findings if item["code"] == NAME_LOWER_CASE)
        self.assertIn("README.TXT", lower["detail"])

    def test_a_clean_8_3_catalogue_reports_nothing(self) -> None:
        self.assertEqual(name_findings([("AUTO/START.PRG", row("START.PRG"))]), [])

    def test_a_datestamp_outside_the_fat_range_is_reported(self) -> None:
        entries = [
            ("OLD.TXT", row("OLD.TXT", datestamp="1970-01-01T00:00:00")),
            ("NOW.TXT", row("NOW.TXT", datestamp="1992-06-01T09:00:00")),
        ]

        findings = datestamp_findings(entries)

        self.assertEqual([item["code"] for item in findings], [DATESTAMP_OUT_OF_RANGE])
        self.assertIn("1980 to 2107", findings[0]["detail"])

    def test_hidden_and_system_entries_are_named(self) -> None:
        entries = [
            ("HIDDEN.DAT", row("HIDDEN.DAT", attributes="-h---a")),
            ("SYSTEM.SYS", row("SYSTEM.SYS", attributes="--s--a")),
            ("PLAIN.TXT", row("PLAIN.TXT")),
        ]

        codes = [item["code"] for item in attribute_findings(entries)]

        self.assertEqual(codes, [HIDDEN_ATTRIBUTE, SYSTEM_ATTRIBUTE])


class CapacityTests(unittest.TestCase):
    def test_a_720k_floppy_root_holds_112_entries(self) -> None:
        findings = capacity_findings({"directoryEntryLimit": 112}, 112, 720 * 1024)

        full = next(item for item in findings if item["code"] == ROOT_DIRECTORY_FULL)
        self.assertEqual(full["title"], "112 of 112 root entries used")
        self.assertIn("It is full", full["detail"])

    def test_room_left_in_the_root_is_counted(self) -> None:
        findings = capacity_findings({"directoryEntryLimit": 112}, 40, 720 * 1024)

        self.assertIn("72 entries remain", findings[0]["detail"])

    def test_a_partition_beyond_a_tos_limit_is_reported(self) -> None:
        findings = capacity_findings({}, 0, 300 * 1024 * 1024)

        self.assertTrue(all(item["code"] == TOS_MOUNT_LIMIT for item in findings))
        self.assertTrue(any("256 MiB" in item["detail"] for item in findings))


class BasicDependencyTests(unittest.TestCase):
    def test_gfa_and_stos_statements_that_name_a_file_are_found(self) -> None:
        listing = (
            'CHAIN "PART2.GFA"\n'
            'BLOAD "TITLE.PI1",6\n'
            'LOAD "MUSIC.MOD"\n'
            'OPEN "I",#1,"SCORES.DAT"\n'
            'INLINE "SPRITES.INL"\n'
            'PRINT "nothing here"\n'
        )

        commands = basic_commands(listing)

        self.assertIn({"action": "CHAIN", "target": "PART2.GFA"}, commands)
        self.assertIn({"action": "BLOAD", "target": "TITLE.PI1"}, commands)
        self.assertIn({"action": "LOAD", "target": "MUSIC.MOD"}, commands)
        self.assertIn({"action": "INLINE", "target": "SPRITES.INL"}, commands)
        self.assertIn({"action": "OPEN", "target": "SCORES.DAT"}, commands)

    def test_a_dependency_report_resolves_names_beside_the_launcher(self) -> None:
        service = FakeService(
            tree={"": [row("MENU.BAS"), row("PART2.GFA")]},
            contents={"MENU.BAS": b'CHAIN "PART2.GFA"\r\nCHAIN "MISSING.GFA"\r\n'},
        )
        try:
            report = dependency_report(service, make_session(), "MENU.BAS", None)
        finally:
            service.cleanup()

        resolved = {item["target"]: item["resolved"] for item in report["dependencies"]}
        self.assertEqual(resolved, {"PART2.GFA": True, "MISSING.GFA": False})
        self.assertFalse(report["safeForSubdirectory"])
        self.assertIn("not present in the image", report["warnings"][0])

    def test_a_name_written_from_the_drive_root_is_reported(self) -> None:
        service = FakeService(
            tree={"": [row("MENU.BAS"), row("GAME.PRG")]},
            contents={"MENU.BAS": b'RUN "C:\\GAME.PRG"\r\n'},
        )
        try:
            report = dependency_report(service, make_session(), "MENU.BAS", None)
        finally:
            service.cleanup()

        self.assertTrue(report["dependencies"][0]["rootRelative"])
        self.assertIn("named from the drive root", report["warnings"][0])

    def test_the_inspector_reads_a_plain_text_launcher(self) -> None:
        service = FakeService(contents={"START.BAT": b'CHAIN "MENU.BAS"\r\n'})
        try:
            report = inspect_file(service, make_session(), "START.BAT", None)
        finally:
            service.cleanup()

        self.assertEqual(report["view"], "text")
        self.assertTrue(report["editable"])
        self.assertEqual([item["action"] for item in report["commands"]], ["CHAIN"])

    def test_the_inspector_recognises_a_program_rather_than_editing_it(self) -> None:
        service = FakeService(contents={"GAME.PRG": program_header() + bytes(0x200)})
        try:
            report = inspect_file(service, make_session(), "GAME.PRG", None)
        finally:
            service.cleanup()

        self.assertEqual(report["view"], "hex")
        self.assertFalse(report["editable"])
        self.assertEqual(report["program"]["text"], 0x100)


class ManifestTests(unittest.TestCase):
    def test_a_manifest_records_attributes_datestamps_and_checksums(self) -> None:
        service = FakeService(
            tree={
                "": [row("AUTO", type="dir", length=1), row("GAME.PRG", datestamp="1992-06-01T09:00:00")],
                "AUTO": [row("START.PRG")],
            },
            contents={"GAME.PRG": b"game", "AUTO/START.PRG": b"start"},
        )
        try:
            manifest = build_manifest(service, make_session())
        finally:
            service.cleanup()

        paths = [record["path"] for record in manifest["records"]]
        self.assertEqual(paths, ["AUTO", "GAME.PRG", "AUTO/START.PRG"])
        game = manifest["records"][1]
        self.assertEqual(game["attributes"], "-----a")
        self.assertEqual(game["datestamp"], "1992-06-01T09:00:00")
        self.assertTrue(game["sha256"])
        # The manifest columns are exactly the GEMDOS facts a directory entry
        # records, so a column from another filing system cannot creep back in.
        self.assertEqual(
            manifest_csv(manifest).splitlines()[0].split(","),
            [
                "attributes", "contentKind", "datestamp", "filetype", "partition",
                "path", "recordType", "sha256", "side", "size",
            ],
        )

    def test_identical_files_are_grouped_by_checksum(self) -> None:
        service = FakeService(
            tree={"": [row("ONE.PRG"), row("TWO.PRG"), row("OTHER.TXT")]},
            contents={"ONE.PRG": b"same", "TWO.PRG": b"same", "OTHER.TXT": b"different"},
        )
        try:
            duplicates = duplicate_report(service, make_session())
        finally:
            service.cleanup()

        self.assertEqual(len(duplicates["exact"]), 1)
        self.assertEqual(
            sorted(record["path"] for record in duplicates["exact"][0]),
            ["ONE.PRG", "TWO.PRG"],
        )

    @patch("app.analysis_service.build_manifest")
    def test_the_duplicate_finder_forwards_progress_to_the_manifest(self, manifest) -> None:
        manifest.return_value = {"records": [], "menus": []}
        progress = Mock()

        duplicate_report(Mock(), make_session(), progress)

        self.assertIs(manifest.call_args.args[2], progress)

    def test_a_checksum_does_not_swallow_a_cancellation(self) -> None:
        service = FakeService(tree={"": [row("GAME.PRG")]}, contents={"GAME.PRG": b"x"})

        def progress(message, _current, _total):
            if message.startswith("Checksumming"):
                raise OperationCancelled("Stopped safely")

        try:
            with self.assertRaises(OperationCancelled):
                build_manifest(service, make_session(), progress)
        finally:
            service.cleanup()

    def test_a_catalogue_walk_stops_when_the_operator_aborts(self) -> None:
        service = FakeService(tree={"": []}, contents={"MENU.BAS": b'CHAIN "X"\r'})

        def abort(message, _current, _total):
            if message.startswith("Reading directory"):
                raise OperationCancelled("Stopped safely")

        try:
            with self.assertRaises(OperationCancelled):
                dependency_report(service, make_session(), "MENU.BAS", None, abort)
        finally:
            service.cleanup()


class HealthReportTests(unittest.TestCase):
    def build(self, **overrides):
        service = FakeService(
            tree={
                "": [
                    row("AUTO", type="dir", length=2),
                    row("NEWDESK.INF", length=64),
                    row("readme.txt"),
                ],
                "AUTO": [row("START.PRG"), row("NOTES.TXT")],
            },
            contents={
                "AUTO/START.PRG": program_header(flags=0x0006),
                "NEWDESK.INF": b"#M 00 01 00 FF C HARD DISK@ @ \r\n#G 03 04 *.APP@ @ \r\n",
                "$boot": boot_sector(),
            },
            summary={"revision": "1", "label": "GAMES", "sizeBytes": 720 * 1024},
        )
        session = make_session(
            ffs_capabilities={
                "format": "FAT12", "nameLimit": 12, "labelLimit": 11,
                "directoryEntryLimit": 112, "caseInsensitive": True, "bootable": True,
            },
            hardware_profile={"name": "Plain ST", "machine": "st", "addons": ["tos-104"]},
            **overrides,
        )
        try:
            return health_report(service, session)
        finally:
            service.cleanup()

    def test_every_check_carries_one_of_the_four_categories(self) -> None:
        report = self.build()

        categories = {check["category"] for check in report["checks"]}
        self.assertTrue(categories <= {"structural", "capacity", "naming", "launch"})
        self.assertEqual(
            categories, {"structural", "capacity", "naming", "launch"}
        )

    def test_the_auto_folder_boot_sector_and_desktop_are_all_reported(self) -> None:
        report = self.build()
        checks = {check["name"]: check for check in report["checks"]}

        auto = checks["AUTO folder"]
        self.assertEqual(
            [item["title"] for item in auto["findings"]],
            ["1. START.PRG", "NOTES.TXT"],
        )
        self.assertIn("TOSBOOT.PRG", checks["Boot sector"]["detail"])
        self.assertEqual(
            [item["code"] for item in checks["Saved desktop"]["findings"]],
            [DESKTOP_DRIVE, DESKTOP_APPLICATION],
        )

    def test_a_tt_ram_program_on_an_st_profile_is_a_launch_warning(self) -> None:
        report = self.build()
        programs = next(check for check in report["checks"] if check["name"] == "Programs")

        self.assertEqual(programs["status"], "warn")
        self.assertTrue(
            any(item["code"] == PROGRAM_TT_RAM_ON_ST for item in programs["findings"])
        )

    def test_a_lower_case_name_lands_in_the_naming_category(self) -> None:
        report = self.build()
        naming = next(check for check in report["checks"] if check["category"] == "naming")

        self.assertEqual(naming["status"], "warn")
        self.assertTrue(
            any(item["code"] == NAME_LOWER_CASE for item in naming["findings"])
        )

    def test_a_drive_with_no_partition_open_reports_its_table_and_stops(self) -> None:
        service = FakeService(
            partitions=[
                {"device": "C:", "id": "GEM", "sizeBytes": 16 * 1024 * 1024},
                {"device": "D:", "id": "BGM", "sizeBytes": 300 * 1024 * 1024},
            ],
            summary={"revision": "1", "scheme": "ahdi", "byteSwapped": True},
        )

        report = health_report(service, make_session("hd"))
        checks = {check["name"]: check for check in report["checks"]}

        self.assertIn("2 partition(s) declared under the AHDI scheme", checks["Partition table"]["detail"])
        self.assertEqual(checks["TOS partition limits"]["status"], "warn")
        self.assertTrue(
            any(item["code"] == TOS_MOUNT_LIMIT for item in checks["TOS partition limits"]["findings"])
        )
        self.assertEqual(checks["Byte order"]["status"], "warn")
        self.assertIn("Open a partition", checks["Volume checks"]["detail"])

    def test_the_report_can_be_aborted_at_a_safe_boundary(self) -> None:
        service = FakeService()

        def abort(_message, _current, _total):
            raise OperationCancelled("Stopped safely")

        with self.assertRaises(OperationCancelled):
            health_report(service, make_session(), abort)


class PreflightTests(unittest.TestCase):
    def session(self, **overrides):
        return make_session(
            ffs_capabilities={"nameLimit": 12},
            **overrides,
        )

    def test_a_name_the_target_cannot_hold_is_reported_as_a_conversion(self) -> None:
        report = preflight_report(None, self.session(), {
            "operation": "copy",
            "targetKind": "gemdos",
            "changes": [{"name": "LONGNAMEONE.TXT"}],
        })

        self.assertEqual(report["format"], "atari-file-forge-compatibility-report")
        self.assertTrue(report["items"][0]["conversions"])
        self.assertTrue(any("becomes" in item["message"] for item in report["issues"]))
        self.assertIn("# Atari File Forge compatibility report", report["markdown"])

    def test_two_names_that_differ_only_in_case_clash_on_a_gemdos_volume(self) -> None:
        report = preflight_report(None, self.session(), {
            "operation": "copy",
            "targetKind": "gemdos",
            "changes": [{"name": "GAME.PRG"}, {"name": "game.prg"}],
        })

        self.assertFalse(report["canProceed"])
        self.assertTrue(any("clashes" in item["message"] for item in report["issues"]))

    def test_a_conversion_that_changes_the_extension_says_so(self) -> None:
        # The base and the extension are both longer than 8.3 allows, so the
        # extension changes whichever way the target name policy trims it.
        report = preflight_report(None, self.session(), {
            "targetKind": "gemdos",
            "changes": [{"name": "LONGPROGRAM.PROGRAM"}],
        })

        conversions = " ".join(report["items"][0]["conversions"])
        self.assertIn("extension", conversions)

    def test_a_datestamp_a_fat_entry_cannot_hold_is_reported_as_a_loss(self) -> None:
        report = preflight_report(None, self.session(), {
            "targetKind": "gemdos",
            "changes": [{"name": "OLD.TXT", "datestamp": "1970-01-01T00:00:00"}],
        })

        self.assertEqual(len(report["items"][0]["losses"]), 1)
        self.assertIn("1980 to 2107", report["items"][0]["losses"][0])

    def test_hidden_bits_are_reported_lost_on_a_host_directory(self) -> None:
        report = preflight_report(None, self.session(), {
            "targetKind": "gemdos-folder",
            "changes": [{"name": "HIDDEN.DAT", "attributes": "-h---a"}],
        })

        self.assertIn("attribute byte", report["items"][0]["losses"][0])

    def test_a_directory_copied_between_gemdos_volumes_loses_nothing(self) -> None:
        report = preflight_report(None, self.session(), {
            "operation": "copy",
            "sourceKind": "gemdos",
            "targetKind": "gemdos",
            "changes": [{"name": "GAMES", "type": "directory"}],
        })

        self.assertTrue(report["canProceed"])
        self.assertEqual(report["items"][0]["losses"], [])

    def test_distinct_slots_may_share_a_destination_name(self) -> None:
        report = preflight_report(None, self.session(), {
            "operation": "library-install",
            "targetKind": "gemdos",
            "changes": [
                {"name": "SAME.PRG", "sourceName": "Game One", "allowDuplicateName": True},
                {"name": "SAME.PRG", "sourceName": "Game Two", "allowDuplicateName": True},
            ],
        })

        self.assertTrue(report["canProceed"])
        self.assertEqual(report["items"][1]["sourceName"], "Game Two")

    def test_collisions_are_only_reported_inside_one_parent(self) -> None:
        report = preflight_report(None, self.session(), {
            "targetKind": "gemdos",
            "changes": [
                {"name": "READ.ME", "nameIsLeaf": True, "parent": "ONE"},
                {"name": "READ.ME", "nameIsLeaf": True, "parent": "TWO"},
            ],
        })

        self.assertTrue(report["canProceed"])


class AcceptedReportTests(unittest.TestCase):
    def test_a_reviewed_report_is_retained_with_its_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "GAMES.ST"
            path.write_bytes(b"image")
            session = make_session(path=path, name=path.name)
            report = preflight_report(None, session, {
                "operation": "copy", "targetKind": "gemdos",
                "changes": [{"name": "GAME.PRG"}],
            })

            accepted = accept_compatibility_report(None, session, report)

            self.assertEqual(session.compatibility_reports, [accepted])
            self.assertIn("acceptedAt", accepted)
            self.assertEqual(accepted["acceptedImage"]["name"], "GAMES.ST")
            self.assertIn("# Atari File Forge compatibility report", accepted["markdown"])

    def test_a_blocking_report_cannot_be_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "GAMES.ST"
            path.write_bytes(b"image")
            session = make_session(path=path, name=path.name)
            report = preflight_report(None, session, {
                "operation": "copy", "targetKind": "gemdos",
                "changes": [{"name": "GAME.PRG"}, {"name": "game.prg"}],
            })

            self.assertFalse(report["canProceed"])
            with self.assertRaisesRegex(DiskError, "blocking findings"):
                accept_compatibility_report(None, session, report)


class WorkspaceMetadataTests(unittest.TestCase):
    def test_partitions_and_saved_project_notes_reach_workspace_search(self) -> None:
        service = FakeService(partitions=[
            {"device": "C:", "id": "GEM", "sizeBytes": 16 * 1024 * 1024, "bootable": True},
        ])
        session = make_session("hd", editor_projects={
            "-|GAME.PRG": {"notes": "Where the loader starts", "symbols": {"&8010": "dispatch"}},
        })

        records = workspace_metadata_records(service, session)

        kinds = [record["resultType"] for record in records]
        self.assertIn("partition", kinds)
        self.assertIn("project-notes", kinds)
        symbol = next(item for item in records if item["resultType"] == "project-symbol")
        self.assertEqual(symbol["offset"], 0x8010)

    def test_a_rom_project_exposes_its_symbols_and_regions(self) -> None:
        session = make_session("tosrom", rom_project={
            "identity": {"title": "TOS 1.04"},
            "symbols": {"57344": "reset"},
            "regions": [{"start": "&E00000", "end": "&E00100", "name": "Header"}],
        })

        records = workspace_metadata_records(FakeService(), session)

        kinds = {record["resultType"] for record in records}
        self.assertEqual(kinds, {"rom-project", "rom-symbol", "rom-region"})


if __name__ == "__main__":
    unittest.main()
